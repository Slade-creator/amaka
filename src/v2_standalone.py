"""
Standalone LSTM baseline for the v2 direct-horizon task.

This is a pure sequence model on the same features and targets as the hybrid,
trained and evaluated on the same chronological splits. It is deliberately a
separate entry point so it can run on Colab without retraining the XGB/hybrid
models.

Usage:
    python src/v2_standalone.py --horizons 1 6 24 48
    python src/v2_standalone.py --sites arakan --horizons 1 --quick
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
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from v2_config import HORIZONS, MODELS, SEQ_LEN, SITES, stable_site_seed
from v2_horizons import FEATURE_COLS, build_horizon, load_base
from v2_train import (
    BASELINES, eval_metrics, fit_lstm, make_sequences, predict_lstm,
    rmse, split_mask,
)


def run_one(
    site: str, horizon: int, args: argparse.Namespace,
    out_dir: Path, metrics_dir: Path, device: torch.device,
) -> dict:
    t0 = time.time()
    frame = build_horizon(load_base(site), site, horizon)
    tt_ns = (
        pd.to_datetime(frame["target_time"])
        .astype("datetime64[ns]").astype("int64").to_numpy()
    )
    valid = frame["target_valid"].to_numpy().astype(bool)
    tr = split_mask(tt_ns, "train")
    va = split_mask(tt_ns, "val")
    te = split_mask(tt_ns, "test")

    x_raw = frame[FEATURE_COLS].to_numpy(np.float32)
    y = frame["target"].to_numpy(np.float32)

    # Feature scaling fitted on train only.
    feature_scaler = MinMaxScaler().fit(x_raw[tr])
    x_scaled = feature_scaler.transform(x_raw).astype(np.float32)

    # Load target scaling fitted on train valid targets only.
    load_scaler = StandardScaler().fit(y[tr & valid].reshape(-1, 1))
    y_scaled = np.full(len(frame), np.nan, dtype=np.float32)
    y_scaled[valid] = load_scaler.transform(
        y[valid].reshape(-1, 1)
    ).ravel().astype(np.float32)

    x_seq, y_seq, v_seq, t_seq, idx_seq = make_sequences(
        x_scaled, y_scaled, valid, tt_ns, args.seq_len
    )
    tr_l = split_mask(t_seq, "train") & v_seq
    va_l = split_mask(t_seq, "val") & v_seq
    baseline_ok = frame[BASELINES].notna().all(axis=1).to_numpy()
    te_l = split_mask(t_seq, "test") & v_seq & baseline_ok[idx_seq]
    test_idx = idx_seq[te_l]

    seed = stable_site_seed(site) + horizon * 10007 + 1
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)

    model, history = fit_lstm(
        x_seq[tr_l], y_seq[tr_l],
        x_seq[va_l], y_seq[va_l],
        seed=seed, device=device, epochs=args.epochs, patience=args.patience,
    )
    pred_scaled = predict_lstm(model, x_seq[te_l], device)
    pred = load_scaler.inverse_transform(pred_scaled.reshape(-1, 1)).ravel()

    y_true = y[test_idx]
    m = eval_metrics(
        y_true, pred,
        frame["readiness_code"].to_numpy()[test_idx],
        frame["grid_fault"].to_numpy()[test_idx],
    )
    m.update({"site": site, "horizon": horizon, "split": "test", "model": "standalone_lstm"})

    pd.DataFrame([m]).to_csv(
        metrics_dir / f"standalone_{site}_h{horizon}.csv", index=False
    )
    joblib.dump(feature_scaler, out_dir / f"feature_scaler_{site}_h{horizon}.pkl")
    joblib.dump(load_scaler, out_dir / f"load_scaler_{site}_h{horizon}.pkl")
    torch.save({
        "state_dict": model.state_dict(),
        "feat_cols": FEATURE_COLS,
        "seq_len": args.seq_len,
        "hidden": 32,
        "layers": 2,
        "dropout": 0.2,
        "site": site,
        "horizon": horizon,
    }, out_dir / f"standalone_lstm_{site}_h{horizon}.pt")

    run = {
        **m,
        "rows": len(frame),
        "train_rows": int(tr_l.sum()),
        "val_rows": int(va_l.sum()),
        "test_rows_common": int(te_l.sum()),
        "features": FEATURE_COLS,
        "seq_len": args.seq_len,
        "history": history,
        "seconds": round(time.time() - t0, 1),
    }
    with open(metrics_dir / f"standalone_run_{site}_h{horizon}.json", "w", encoding="utf-8") as f:
        json.dump(run, f, indent=2)

    print(
        f"{site:11s} h={horizon:2d} n={len(y_true):5d} "
        f"LSTM {m['rmse']:6.1f}/{m['mae']:5.1f} MAPE {m['mape']:4.2f}% "
        f"peak_bias {m['peak_bias']:+6.1f} time {run['seconds']:5.0f}s",
        flush=True,
    )
    return run


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sites", nargs="+", default=None)
    p.add_argument("--horizons", nargs="+", type=int, default=None)
    p.add_argument("--seq-len", type=int, default=SEQ_LEN)
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--patience", type=int, default=5)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--out-dir", type=Path, default=MODELS)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.sites is None:
        args.sites = SITES
    if args.horizons is None:
        args.horizons = HORIZONS
    if args.quick:
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
        f"Standalone LSTM | sites={args.sites} horizons={args.horizons} "
        f"seq={args.seq_len} epochs={args.epochs} device={device}",
        flush=True,
    )

    rows = []
    for site in args.sites:
        for h in args.horizons:
            rows.append(run_one(site, h, args, args.out_dir, metrics_dir, device))

    pd.DataFrame(rows).drop(columns=["history"], errors="ignore").to_csv(
        args.out_dir / "metrics_standalone.csv", index=False
    )
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "args": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        "features": FEATURE_COLS,
        "runs": [{k: r[k] for k in ("site", "horizon", "rmse", "mae", "mape", "seconds")}
                 for r in rows],
    }
    with open(args.out_dir / "standalone_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nWrote {args.out_dir / 'metrics_standalone.csv'}")


if __name__ == "__main__":
    main()
