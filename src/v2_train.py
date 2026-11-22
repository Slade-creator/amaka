"""
Train and evaluate direct multi-horizon XGBoost + residual-LSTM models.

Stage 1: XGBoost on tabular origin/target features.
Stage 2: LSTM on OUT-OF-FOLD Stage-1 residuals from expanding-window folds
         inside 2024, then evaluated once on the held-out 2025 H2 period.

The target is load_kw. Rows where the target is missing or was imputed are
excluded from training loss and from all accuracy metrics.

Usage examples
--------------
    python src/v2_train.py --horizons 1 6 24 48
    python src/v2_train.py --sites arakan --horizons 1 24 --quick
    python src/v2_train.py --standalone-lstm --horizons 1 24

Outputs
-------
    config/v2/xgb_<site>_h<h>.pkl
    config/v2/lstm_<site>_h<h>.pt
    config/v2/feature_scaler_<site>_h<h>.pkl
    config/v2/residual_scaler_<site>_h<h>.pkl
    config/v2/standalone_lstm_<site>_h<h>.pt (optional)
    config/v2/metrics/*.csv, *.json
"""
from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import MinMaxScaler, StandardScaler
from torch.utils.data import DataLoader, TensorDataset
from xgboost import XGBRegressor

from v2_config import (
    HORIZONS, MODELS, OOF_FOLDS, SEQ_LEN, SITES, TEST_END, TEST_START,
    TRAIN_END, TRAIN_START, VAL_END, VAL_START, stable_site_seed,
)
from v2_horizons import FEATURE_COLS, TARGET_WEATHER_COLS, build_horizon, load_base

BASELINES = ["persistence", "seasonal_naive_24", "seasonal_naive_168"]


# --------------------------------------------------------------------------- #
# Models / metrics
# --------------------------------------------------------------------------- #
class ResLSTM(nn.Module):
    def __init__(self, n_features: int, hidden: int = 32, layers: int = 2, dropout: float = 0.2):
        super().__init__()
        self.lstm = nn.LSTM(
            n_features, hidden, num_layers=layers,
            batch_first=True, dropout=dropout if layers > 1 else 0.0,
        )
        self.head = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(hidden, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
        )

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.head(out[:, -1, :]).squeeze(-1)


def rmse(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y - p) ** 2)))


def mae(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean(np.abs(y - p)))


def mape(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean(np.abs((y - p) / np.clip(np.abs(y), 1e-6, None))) * 100.0)


def eval_metrics(y: np.ndarray, p: np.ndarray, readiness: np.ndarray, grid_fault: np.ndarray) -> dict:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    err = y - p
    out = {
        "n": int(len(y)),
        "rmse": round(rmse(y, p), 2),
        "mae": round(mae(y, p), 2),
        "mape": round(mape(y, p), 2),
        "bias": round(float(np.mean(err)), 2),
    }
    if len(y):
        peak = y >= np.quantile(y, 0.90)
        out["peak_n"] = int(peak.sum())
        out["peak_bias"] = round(float(np.mean(err[peak])), 2) if peak.any() else None
        out["peak_mae"] = round(float(np.mean(np.abs(err[peak]))), 2) if peak.any() else None
    gf = np.asarray(grid_fault, dtype=bool)
    out["grid_fault_n"] = int(gf.sum())
    out["grid_fault_mae"] = round(float(np.mean(np.abs(err[gf]))), 2) if gf.any() else None
    ng = ~gf
    out["n_ex_grid_fault"] = int(ng.sum())
    out["mae_ex_grid_fault"] = round(float(np.mean(np.abs(err[ng]))), 2) if ng.any() else None
    out["rmse_ex_grid_fault"] = round(rmse(y[ng], p[ng]), 2) if ng.any() else None
    return out


# --------------------------------------------------------------------------- #
# Data plumbing
# --------------------------------------------------------------------------- #
def _ns(value: str) -> int:
    return int(pd.Timestamp(value).value)


BOUNDS = {
    "train": (_ns(TRAIN_START), _ns(TRAIN_END)),
    "val": (_ns(VAL_START), _ns(VAL_END)),
    "test": (_ns(TEST_START), _ns(TEST_END)),
}
# Validation is split again: Jan-Mar is used to fit the residual correction
# scale (alpha), Apr-Jun is used to choose between XGB, LSTM and HGB. The test
# period is never used for either decision.
VA_FIT_END = _ns("2025-03-31 23:00:00")
VA_SELECT_START = _ns("2025-04-01 00:00:00")
SELECTION_MARGIN = 0.005  # require >=0.5% RMSE improvement over XGB


def split_mask(tt_ns: np.ndarray, split: str) -> np.ndarray:
    lo, hi = BOUNDS[split]
    return (tt_ns >= lo) & (tt_ns <= hi)


def make_sequences(
    x_scaled: np.ndarray,
    target: np.ndarray,
    valid: np.ndarray,
    tt_ns: np.ndarray,
    seq_len: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (N,seq,F), target, valid, target_time_ns, frame_row_index."""
    n = len(x_scaled)
    if n <= seq_len:
        raise ValueError(f"not enough rows ({n}) for seq_len={seq_len}")
    windows = np.lib.stride_tricks.sliding_window_view(x_scaled, seq_len, axis=0)
    # windows[j] covers rows j..j+seq_len-1; target row i uses start i-seq_len.
    x_seq = np.transpose(windows[: n - seq_len], (0, 2, 1)).astype(np.float32)
    idx = np.arange(seq_len, n)
    return x_seq, target[idx], valid[idx], tt_ns[idx], idx


def fit_xgb(x: np.ndarray, y: np.ndarray, mask: np.ndarray, params: dict) -> XGBRegressor:
    model = XGBRegressor(**params)
    model.fit(x[mask], y[mask])
    return model


def predict_lstm(model: nn.Module, x: np.ndarray, device: torch.device, batch: int = 512) -> np.ndarray:
    model.eval()
    out: list[np.ndarray] = []
    with torch.no_grad():
        for i in range(0, len(x), batch):
            xb = torch.from_numpy(x[i:i + batch]).to(device)
            out.append(model(xb).cpu().numpy())
    return np.concatenate(out) if out else np.empty(0, dtype=np.float32)


def fit_lstm(
    x_tr: np.ndarray, y_tr: np.ndarray,
    x_va: np.ndarray, y_va: np.ndarray,
    seed: int, device: torch.device, *,
    hidden: int = 32, layers: int = 2, dropout: float = 0.2,
    epochs: int = 20, patience: int = 5, batch: int = 128, lr: float = 1e-3,
) -> tuple[nn.Module, list[dict]]:
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)

    model = ResLSTM(x_tr.shape[2], hidden=hidden, layers=layers, dropout=dropout).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    lossf = nn.MSELoss()

    tr_loader = DataLoader(
        TensorDataset(torch.from_numpy(x_tr), torch.from_numpy(y_tr)),
        batch_size=batch, shuffle=True, num_workers=0,
    )
    va_x = torch.from_numpy(x_va).to(device)
    va_y = torch.from_numpy(y_va).to(device)

    best, best_state, bad = float("inf"), None, 0
    history: list[dict] = []
    for ep in range(1, epochs + 1):
        model.train()
        total = 0.0
        for xb, yb in tr_loader:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            loss = lossf(model(xb), yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            total += loss.item() * len(xb)

        model.eval()
        with torch.no_grad():
            vl = 0.0
            for i in range(0, len(va_x), 512):
                xb = va_x[i:i + 512]
                yb = va_y[i:i + 512]
                vl += lossf(model(xb), yb).item() * len(xb)
            vl /= len(va_x)

        history.append({
            "epoch": ep,
            "train_mse": round(total / len(x_tr), 8),
            "val_mse": round(float(vl), 8),
        })
        if vl < best - 1e-6:
            best, bad = vl, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    return model, history


def oof_residuals(
    x: np.ndarray, y: np.ndarray, valid: np.ndarray, tt_ns: np.ndarray,
    xgb_params: dict,
) -> tuple[np.ndarray, list[dict]]:
    """Expanding-window out-of-fold residuals on the training period."""
    resid = np.full(len(y), np.nan, dtype=np.float32)
    fold_info: list[dict] = []
    for k, (start, end) in enumerate(OOF_FOLDS):
        start_ns = _ns(f"{start} 00:00:00")
        end_ns = _ns(f"{end} 23:00:00")
        tr = (tt_ns < start_ns) & valid
        fold = (tt_ns >= start_ns) & (tt_ns <= end_ns)
        if tr.sum() < 200 or fold.sum() == 0:
            continue
        model = fit_xgb(x, y, tr, xgb_params)
        pred = model.predict(x[fold])
        ok = valid[fold]
        resid[np.where(fold)[0][ok]] = y[fold][ok] - pred[ok]
        fold_info.append({
            "fold": k,
            "train_start": start,
            "fold_end": end,
            "n_train": int(tr.sum()),
            "n_fold": int(fold.sum()),
            "rmse": round(rmse(y[fold][ok], pred[ok]), 2) if ok.any() else None,
            "mae": round(mae(y[fold][ok], pred[ok]), 2) if ok.any() else None,
        })
    return resid, fold_info


# --------------------------------------------------------------------------- #
# One site x horizon
# --------------------------------------------------------------------------- #
def train_one(
    site: str, horizon: int, args: argparse.Namespace,
    out_dir: Path, metrics_dir: Path, device: torch.device,
) -> dict:
    start_time = time.time()
    base = load_base(site)
    frame = build_horizon(base, site, horizon)

    # pandas 3 defaults to datetime64[us]; normalise to ns before comparing
    # against pd.Timestamp.value (which is always nanoseconds).
    tt_ns = (
        pd.to_datetime(frame["target_time"])
        .astype("datetime64[ns]")
        .astype("int64")
        .to_numpy()
    )
    valid = frame["target_valid"].to_numpy().astype(bool)
    tr = split_mask(tt_ns, "train")
    va = split_mask(tt_ns, "val")
    te = split_mask(tt_ns, "test")

    x_raw = frame[FEATURE_COLS].to_numpy(np.float32)
    y = frame["target"].to_numpy(np.float32)

    seed = stable_site_seed(site) + horizon * 10007
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)

    xgb_params = {
        "n_estimators": args.n_estimators,
        "max_depth": args.max_depth,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "n_jobs": -1,
        "random_state": 42,
    }

    # ---- Stage 1 ---------------------------------------------------------
    xgb = fit_xgb(x_raw, y, tr & valid, xgb_params)
    xgb_pred = xgb.predict(x_raw)

    # ---- Required ablations (cheap: XGB only) ----------------------------
    ablation_preds: dict[str, np.ndarray] = {}
    if not args.no_ablations:
        ablate_sets = {
            "xgb_no_readiness": [c for c in FEATURE_COLS if c != "readiness_code"],
            "xgb_no_weather": [c for c in FEATURE_COLS if c not in TARGET_WEATHER_COLS],
            "xgb_core": [
                c for c in FEATURE_COLS
                if c not in TARGET_WEATHER_COLS
                and c != "readiness_code"
                and not c.startswith("disruption_")
            ],
        }
        for name, cols in ablate_sets.items():
            xa = frame[cols].to_numpy(np.float32)
            ma = fit_xgb(xa, y, tr & valid, xgb_params)
            ablation_preds[name] = ma.predict(xa)

    # ---- OOF residuals ---------------------------------------------------
    oof, fold_info = oof_residuals(x_raw, y, valid, tt_ns, xgb_params)
    oof_mean = float(np.nanmean(oof[tr & valid])) if np.isfinite(oof[tr & valid]).any() else 0.0

    # ---- Common test rows for all models --------------------------------
    # Sequences lose the first seq_len rows of the test period; use the same
    # rows for XGB, hybrid and all baselines so the comparison is fair.
    feature_scaler = MinMaxScaler().fit(x_raw[tr])
    x_scaled = feature_scaler.transform(x_raw).astype(np.float32)

    resid_target = np.full(len(frame), np.nan, dtype=np.float32)
    resid_target[tr] = oof[tr]
    resid_target[va] = (y - xgb_pred)[va]
    resid_target[te] = (y - xgb_pred)[te]
    resid_valid = valid & np.isfinite(resid_target)

    x_seq, y_seq, v_seq, t_seq, idx_seq = make_sequences(
        x_scaled, resid_target, resid_valid, tt_ns, args.seq_len
    )
    tr_seq = split_mask(t_seq, "train") & v_seq
    va_seq = split_mask(t_seq, "val") & v_seq
    va_fit_seq = va_seq & (t_seq <= VA_FIT_END)
    va_sel_seq = va_seq & (t_seq >= VA_SELECT_START)
    te_seq = split_mask(t_seq, "test") & v_seq

    baseline_ok = frame[BASELINES].notna().all(axis=1).to_numpy()
    te_seq = te_seq & baseline_ok[idx_seq]
    test_idx = idx_seq[te_seq]

    y_true = y[test_idx]
    readiness = frame["readiness_code"].to_numpy()[test_idx]
    grid_fault = frame["grid_fault"].to_numpy()[test_idx]
    base_preds = {
        "xgb": xgb_pred[test_idx],
        "xgb_bias_oof": xgb_pred[test_idx] + oof_mean,
        **{name: frame[name].to_numpy()[test_idx] for name in BASELINES},
        **{name: pred[test_idx] for name, pred in ablation_preds.items()},
    }

    # ---- Robust residual-learner comparison ------------------------------
    # A single feature-vector HGB on the same OOF residuals. It is not the
    # proposed LSTM, but it is a useful check on whether Stage 2 is learning
    # real residual structure or just noise.
    hgb_metrics: dict | None = None
    hgb_bundle: dict | None = None
    if not args.no_resid_baselines:
        fit_mask = tr & valid & np.isfinite(oof)
        va_fit_h = va & valid & (tt_ns <= VA_FIT_END)
        va_sel_h = va & valid & (tt_ns >= VA_SELECT_START)
        if fit_mask.sum() >= 200 and va_fit_h.sum() >= 50 and va_sel_h.sum() >= 50:
            hgb = HistGradientBoostingRegressor(
                max_iter=150, max_depth=3, learning_rate=0.05,
                l2_regularization=1.0, random_state=42,
            )
            hgb.fit(x_raw[fit_mask], oof[fit_mask])
            hgb_pred_all = hgb.predict(x_raw)

            denom = float(np.dot(hgb_pred_all[va_fit_h], hgb_pred_all[va_fit_h]))
            alpha_h = (
                float(np.clip(
                    np.dot(
                        y[va_fit_h] - xgb_pred[va_fit_h],
                        hgb_pred_all[va_fit_h],
                    ) / denom,
                    0.0, 1.0,
                ))
                if denom > 0 else 0.0
            )
            hgb_val_select_rmse = rmse(
                y[va_sel_h], xgb_pred[va_sel_h] + alpha_h * hgb_pred_all[va_sel_h]
            )
            hgb_xgb_val_select_rmse = rmse(y[va_sel_h], xgb_pred[va_sel_h])
            base_preds["hybrid_hgb"] = (
                xgb_pred[test_idx] + alpha_h * hgb_pred_all[test_idx]
            )
            hgb_bundle = {
                "alpha": alpha_h,
                "test_pred": base_preds["hybrid_hgb"],
                "val_select_rmse": hgb_val_select_rmse,
            }
            hgb_metrics = {
                "alpha": round(alpha_h, 4),
                "val_fit_xgb_rmse": round(rmse(y[va_fit_h], xgb_pred[va_fit_h]), 2),
                "val_fit_hybrid_rmse": round(rmse(
                    y[va_fit_h], xgb_pred[va_fit_h] + alpha_h * hgb_pred_all[va_fit_h]
                ), 2),
                "val_select_xgb_rmse": round(hgb_xgb_val_select_rmse, 2),
                "val_select_hybrid_rmse": round(hgb_val_select_rmse, 2),
                "test_pred_std": round(float(np.std(hgb_pred_all[test_idx])), 3),
                "test_corr": (
                    round(float(np.corrcoef(
                        hgb_pred_all[test_idx], y_true - base_preds["xgb"]
                    )[0, 1]), 4)
                    if np.std(hgb_pred_all[test_idx]) > 0 else None
                ),
            }
            joblib.dump(hgb, out_dir / f"resid_hgb_{site}_h{horizon}.pkl")

    # ---- Stage 2 ---------------------------------------------------------
    lstm_metrics: dict | None = None
    lstm_bundle: dict | None = None
    history: list[dict] = []
    if (
        not args.no_lstm
        and tr_seq.sum() >= 100
        and va_fit_seq.sum() >= 50
        and va_sel_seq.sum() >= 50
        and te_seq.sum() >= 20
    ):
        r_scaler = StandardScaler().fit(y_seq[tr_seq].reshape(-1, 1))
        y_scaled = np.full_like(y_seq, np.nan, dtype=np.float32)
        tv = tr_seq | va_seq
        y_scaled[tv] = r_scaler.transform(y_seq[tv].reshape(-1, 1)).ravel().astype(np.float32)

        model, history = fit_lstm(
            x_seq[tr_seq], y_scaled[tr_seq],
            x_seq[va_seq], y_scaled[va_seq],
            seed=seed, device=device, epochs=args.epochs, patience=args.patience,
        )
        pred_scaled_va = predict_lstm(model, x_seq[va_seq], device)
        pred_resid_va = r_scaler.inverse_transform(
            pred_scaled_va.reshape(-1, 1)
        ).ravel()
        val_idx = idx_seq[va_seq]
        val_tt = tt_ns[val_idx]

        # Fit alpha on Jan-Mar 2025 only; select on Apr-Jun 2025.
        fit_m = val_tt <= VA_FIT_END
        sel_m = val_tt >= VA_SELECT_START
        denom = float(np.dot(pred_resid_va[fit_m], pred_resid_va[fit_m]))
        alpha = (
            float(np.clip(
                np.dot(
                    y[val_idx][fit_m] - xgb_pred[val_idx][fit_m],
                    pred_resid_va[fit_m],
                ) / denom,
                0.0, 1.0,
            ))
            if denom > 0 else 0.0
        )
        lstm_val_select_rmse = rmse(
            y[val_idx][sel_m],
            xgb_pred[val_idx][sel_m] + alpha * pred_resid_va[sel_m],
        )

        pred_scaled = predict_lstm(model, x_seq[te_seq], device)
        pred_resid = r_scaler.inverse_transform(pred_scaled.reshape(-1, 1)).ravel()
        base_preds["hybrid_lstm"] = base_preds["xgb"] + alpha * pred_resid
        lstm_bundle = {
            "alpha": alpha,
            "test_pred": base_preds["hybrid_lstm"],
            "val_select_rmse": lstm_val_select_rmse,
        }
        lstm_metrics = {
            "alpha": round(alpha, 4),
            "pred_resid_std": round(float(np.std(pred_resid)), 3),
            "actual_resid_std": round(float(np.std(y_true - base_preds["xgb"])), 3),
            "corr": round(float(np.corrcoef(pred_resid, y_true - base_preds["xgb"])[0, 1]), 4)
            if len(y_true) > 1 and np.std(pred_resid) > 0 else None,
            "r_scaler_mean": round(float(r_scaler.mean_[0]), 3),
            "r_scaler_scale": round(float(r_scaler.scale_[0]), 3),
            "val_fit_xgb_rmse": round(rmse(y[val_idx][fit_m], xgb_pred[val_idx][fit_m]), 2),
            "val_fit_hybrid_rmse": round(rmse(
                y[val_idx][fit_m],
                xgb_pred[val_idx][fit_m] + alpha * pred_resid_va[fit_m],
            ), 2),
            "val_select_xgb_rmse": round(rmse(y[val_idx][sel_m], xgb_pred[val_idx][sel_m]), 2),
            "val_select_hybrid_rmse": round(lstm_val_select_rmse, 2),
        }

        joblib.dump(r_scaler, out_dir / f"residual_scaler_{site}_h{horizon}.pkl")
        torch.save({
            "state_dict": model.state_dict(),
            "feat_cols": FEATURE_COLS,
            "seq_len": args.seq_len,
            "hidden": 32,
            "layers": 2,
            "dropout": 0.2,
            "site": site,
            "horizon": horizon,
        }, out_dir / f"lstm_{site}_h{horizon}.pt")

        # Optional standalone LSTM baseline on the load target.
        if args.standalone_lstm:
            load_scaler = StandardScaler().fit(y[tr & valid].reshape(-1, 1))
            y_load_scaled = np.full(len(frame), np.nan, dtype=np.float32)
            y_load_scaled[valid] = load_scaler.transform(
                y[valid].reshape(-1, 1)
            ).ravel().astype(np.float32)
            y_load_seq = y_load_scaled[idx_seq]
            lv_seq = valid[idx_seq] & np.isfinite(y_load_seq)
            tr_l = split_mask(t_seq, "train") & lv_seq
            va_l = split_mask(t_seq, "val") & lv_seq
            te_l = split_mask(t_seq, "test") & lv_seq & baseline_ok[idx_seq]
            if tr_l.sum() >= 100 and va_l.sum() >= 20 and te_l.sum() >= 20:
                standalone, _ = fit_lstm(
                    x_seq[tr_l], y_load_seq[tr_l],
                    x_seq[va_l], y_load_seq[va_l],
                    seed=seed + 1, device=device, epochs=args.epochs,
                    patience=args.patience,
                )
                p_load_scaled = predict_lstm(standalone, x_seq[te_l], device)
                p_load = load_scaler.inverse_transform(p_load_scaled.reshape(-1, 1)).ravel()
                te_l_idx = idx_seq[te_l]
                torch.save({
                    "state_dict": standalone.state_dict(),
                    "feat_cols": FEATURE_COLS,
                    "seq_len": args.seq_len,
                    "hidden": 32,
                    "layers": 2,
                    "dropout": 0.2,
                    "site": site,
                    "horizon": horizon,
                }, out_dir / f"standalone_lstm_{site}_h{horizon}.pt")
                joblib.dump(load_scaler, out_dir / f"load_scaler_{site}_h{horizon}.pkl")
                # The standalone model has its own target-valid mask. Add it to
                # the main table only when it matches the common test rows.
                m_stand = eval_metrics(
                    y[te_l_idx], p_load,
                    frame["readiness_code"].to_numpy()[te_l_idx],
                    frame["grid_fault"].to_numpy()[te_l_idx],
                )
                m_stand.update({"site": site, "horizon": horizon, "split": "test",
                                "model": "standalone_lstm",
                                "aligned_to_common_test": bool(np.array_equal(te_l_idx, test_idx))})
                lstm_metrics["standalone"] = m_stand
                if np.array_equal(te_l_idx, test_idx):
                    base_preds["standalone_lstm"] = p_load

    # ---- Validation-based model selection --------------------------------
    # Alpha is fitted on Jan-Mar; this comparison uses Apr-Jun only. The test
    # period is never used to choose between XGB, LSTM and HGB.
    va_sel_frame = va & valid & (tt_ns >= VA_SELECT_START)
    xgb_val_select_rmse = rmse(y[va_sel_frame], xgb_pred[va_sel_frame])
    candidates = {
        name: bundle
        for name, bundle in (("lstm", lstm_bundle), ("hgb", hgb_bundle))
        if bundle is not None
    }
    best_name = None
    best_bundle = None
    for name, bundle in candidates.items():
        if best_bundle is None or bundle["val_select_rmse"] < best_bundle["val_select_rmse"]:
            best_name, best_bundle = name, bundle

    if (
        best_bundle is not None
        and best_bundle["val_select_rmse"] < xgb_val_select_rmse * (1.0 - SELECTION_MARGIN)
    ):
        base_preds["hybrid"] = best_bundle["test_pred"]
        selected = best_name
    else:
        base_preds["hybrid"] = base_preds["xgb"]
        selected = "xgb"

    selection = {
        "xgb_val_select_rmse": round(xgb_val_select_rmse, 2),
        "lstm_val_select_rmse": (
            round(candidates["lstm"]["val_select_rmse"], 2) if "lstm" in candidates else None
        ),
        "hgb_val_select_rmse": (
            round(candidates["hgb"]["val_select_rmse"], 2) if "hgb" in candidates else None
        ),
        "selected": selected,
        "margin_pct": SELECTION_MARGIN * 100,
        "protocol": "alpha fit Jan-Mar 2025; select Apr-Jun 2025; test 2025 H2 untouched",
    }

    # ---- Metrics ---------------------------------------------------------
    rows = []
    for name, pred in base_preds.items():
        m = eval_metrics(y_true, pred, readiness, grid_fault)
        m.update({"site": site, "horizon": horizon, "split": "test", "model": name})
        rows.append(m)

    # Per-readiness metrics for the main models.
    readiness_rows = []
    for name, pred in base_preds.items():
        for c in (1, 2, 3, 4):
            mask = readiness == c
            if not mask.any():
                continue
            m = eval_metrics(y_true[mask], pred[mask], readiness[mask], grid_fault[mask])
            m.update({"site": site, "horizon": horizon, "model": name, "readiness_code": c})
            readiness_rows.append(m)

    joblib.dump(xgb, out_dir / f"xgb_{site}_h{horizon}.pkl")
    if not args.no_lstm:
        joblib.dump(feature_scaler, out_dir / f"feature_scaler_{site}_h{horizon}.pkl")

    metrics_df = pd.DataFrame(rows)
    metrics_df.to_csv(metrics_dir / f"metrics_{site}_h{horizon}.csv", index=False)
    pd.DataFrame(readiness_rows).to_csv(
        metrics_dir / f"readiness_{site}_h{horizon}.csv", index=False
    )

    run = {
        "site": site,
        "horizon": horizon,
        "rows": len(frame),
        "train_rows": int((tr & valid).sum()),
        "val_rows": int((va & valid).sum()),
        "test_rows": int((te & valid).sum()),
        "test_rows_common": int(len(test_idx)),
        "test_rows_excluded_imputed": int((te & ~valid).sum()),
        "target_start": str(frame["target_time"].min()),
        "target_end": str(frame["target_time"].max()),
        "features": FEATURE_COLS,
        "xgb_params": xgb_params,
        "seq_len": args.seq_len,
        "selection": selection,
        "lstm": lstm_metrics,
        "resid_hgb": hgb_metrics,
        "lstm_history": history,
        "oof_folds": fold_info,
        "oof_mean": round(oof_mean, 3),
        "seconds": round(time.time() - start_time, 1),
    }
    with open(metrics_dir / f"run_{site}_h{horizon}.json", "w", encoding="utf-8") as f:
        json.dump(run, f, indent=2)

    xgb_row = next(r for r in rows if r["model"] == "xgb")
    hyb_row = next((r for r in rows if r["model"] == "hybrid"), None)
    delta = (hyb_row["rmse"] - xgb_row["rmse"]) if hyb_row else 0.0
    print(
        f"{site:11s} h={horizon:2d} n={len(y_true):5d} "
        f"XGB {xgb_row['rmse']:6.1f}/{xgb_row['mae']:5.1f} "
        + (f"HYB {hyb_row['rmse']:6.1f}/{hyb_row['mae']:5.1f} (d {delta:+5.1f}) " if hyb_row else "HYB skipped ")
        + f"persist {next(r for r in rows if r['model']=='persistence')['rmse']:6.1f} "
        f"peak_bias {xgb_row['peak_bias']:+6.1f} "
        f"sel={selected:4s} time {run['seconds']:5.0f}s",
        flush=True,
    )
    return {"run": run, "metrics": rows, "readiness": readiness_rows}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sites", nargs="+", default=None)
    p.add_argument("--horizons", nargs="+", type=int, default=None)
    p.add_argument("--seq-len", type=int, default=SEQ_LEN)
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--patience", type=int, default=5)
    p.add_argument("--n-estimators", type=int, default=300)
    p.add_argument("--max-depth", type=int, default=6)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--no-lstm", action="store_true")
    p.add_argument("--no-ablations", action="store_true")
    p.add_argument("--no-resid-baselines", action="store_true")
    p.add_argument("--standalone-lstm", action="store_true")
    p.add_argument("--out-dir", type=Path, default=MODELS)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.sites is None:
        args.sites = SITES
    if args.horizons is None:
        args.horizons = HORIZONS
    if args.quick:
        args.n_estimators = min(args.n_estimators, 80)
        args.max_depth = min(args.max_depth, 4)
        args.epochs = min(args.epochs, 3)
        args.patience = min(args.patience, 2)
        if args.seq_len == SEQ_LEN:
            args.seq_len = 48
        if args.sites == SITES:
            args.sites = ["arakan"]
        if args.horizons == HORIZONS:
            args.horizons = [1, 24]

    args.out_dir = Path(args.out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    metrics_dir = args.out_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    print(
        f"v2 training | sites={args.sites} horizons={args.horizons} "
        f"seq={args.seq_len} trees={args.n_estimators} epochs={args.epochs} "
        f"device={device}",
        flush=True,
    )

    all_rows: list[dict] = []
    all_readiness: list[dict] = []
    all_runs: list[dict] = []
    for site in args.sites:
        for horizon in args.horizons:
            result = train_one(site, horizon, args, args.out_dir, metrics_dir, device)
            all_rows.extend(result["metrics"])
            all_readiness.extend(result["readiness"])
            all_runs.append(result["run"])

    pd.DataFrame(all_rows).to_csv(args.out_dir / "metrics_horizons.csv", index=False)
    pd.DataFrame(all_readiness).to_csv(args.out_dir / "metrics_readiness.csv", index=False)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "args": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        "features": FEATURE_COLS,
        "baselines": BASELINES,
        "runs": [
            {k: r[k] for k in ("site", "horizon", "rows", "train_rows", "val_rows",
                               "test_rows", "test_rows_common", "seconds")}
            for r in all_runs
        ],
        "package_versions": {
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "torch": torch.__version__,
            "xgboost": __import__("xgboost").__version__,
            "sklearn": __import__("sklearn").__version__,
        },
    }
    with open(args.out_dir / "training_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nWrote metrics to {args.out_dir / 'metrics_horizons.csv'}")
    print(f"Wrote models/scalers to {args.out_dir}")


if __name__ == "__main__":
    main()
