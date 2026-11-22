"""
Sprint 2 residual LSTM (proposal 3.2.2 Stage 2).

Hybrid XGBoost-LSTM:
  Stage 1: XGBoost predicts baseline load from tabular features.
  Stage 2: 2-layer LSTM learns XGBoost residuals from 168h sequences,
           capturing temporal variation gradient-boosted trees miss.

Input : data/processed/features_arakan.csv + config/xgb_baseline_arakan.pkl
Output: config/lstm_residual_arakan.pt + scaler, metrics on test split

Splits match notebooks/learning.ipynb:
  train 2024-01-01..2024-12-31, val 2025-01-01..2025-06-30, test 2025-07-01..
Scaling fit on train only (no leakage).
"""
import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from pathlib import Path
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error

try:
    from sklearn.metrics import root_mean_squared_error
except ImportError:  # sklearn < 1.6
    from sklearn.metrics import mean_squared_error

    def root_mean_squared_error(y, p):
        return float(np.sqrt(mean_squared_error(y, p)))

BASE = Path(__file__).resolve().parents[1]
FEAT = BASE / "data" / "processed" / "features_arakan.csv"
XGB_PATH = BASE / "config" / "xgb_baseline_arakan.pkl"
OUT_MODEL = BASE / "config" / "lstm_residual_arakan.pt"

SEQ_LEN = 168  # 1-week lookback
HIDDEN = 64
LAYERS = 2
DROPOUT = 0.2  # per risk register R02
BATCH = 128
EPOCHS = 50
PATIENCE = 7
LR = 1e-3
SEED = 42

DROP = ["load_kw", "readiness_label"]


class ResidualLSTM(nn.Module):
    def __init__(self, n_features, hidden=HIDDEN, layers=LAYERS, dropout=DROPOUT):
        super().__init__()
        self.lstm = nn.LSTM(
            n_features, hidden, num_layers=layers,
            batch_first=True, dropout=dropout if layers > 1 else 0.0,
        )
        self.head = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(hidden, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
        )

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.head(out[:, -1, :]).squeeze(-1)


def make_sequences(X: np.ndarray, resid: np.ndarray, seq_len: int = SEQ_LEN):
    """X: (N, F) scaled features, resid: (N,) residuals. Target = resid[t]."""
    Xs, ys = [], []
    for t in range(seq_len, len(X)):
        Xs.append(X[t - seq_len:t])
        ys.append(resid[t])
    return np.stack(Xs).astype(np.float32), np.array(ys, dtype=np.float32)


def main():
    torch.manual_seed(SEED)
    np.random.seed(SEED)

    df = pd.read_csv(FEAT, parse_dates=["timestamp"]).dropna()
    df = df.set_index("timestamp").sort_index()
    train = df.loc["2024-01-01":"2024-12-31"]
    val = df.loc["2025-01-01":"2025-06-30"]
    test = df.loc["2025-07-01":]
    print(f"rows train={len(train)} val={len(val)} test={len(test)}")

    xgb = joblib.load(XGB_PATH)
    feat_cols = [c for c in df.columns if c not in DROP]
    print(f"features ({len(feat_cols)}): {feat_cols}")

    # Stage-1 residuals (XGBoost baseline)
    r_train = train["load_kw"].to_numpy() - xgb.predict(train[feat_cols])
    r_val = val["load_kw"].to_numpy() - xgb.predict(val[feat_cols])
    r_test = test["load_kw"].to_numpy() - xgb.predict(test[feat_cols])
    print(f"resid std train={r_train.std():.1f} val={r_val.std():.1f} test={r_test.std():.1f}")

    # Scale features on train only
    scaler = MinMaxScaler()
    scaler.fit(train[feat_cols])
    X_all = scaler.transform(df[feat_cols]).astype(np.float32)
    resid_all = (
        df["load_kw"].to_numpy() - xgb.predict(df[feat_cols])
    ).astype(np.float32)

    # Scale residuals on train only (stabilises LSTM training)
    r_scaler = MinMaxScaler()
    r_scaler.fit(r_train.reshape(-1, 1))

    n_train, n_val = len(train), len(val)
    idx = np.arange(len(df))
    # sequence target positions split by timestamp
    train_mask = (idx >= SEQ_LEN) & (idx < n_train)
    val_mask = (idx >= n_train) & (idx < n_train + n_val)
    test_mask = idx >= n_train + n_val

    X_seq, y_seq = make_sequences(X_all, resid_all)
    # make_sequences drops first SEQ_LEN rows -> offset by SEQ_LEN
    off = SEQ_LEN
    pos = np.arange(off, len(df))
    tr = np.isin(pos, np.where(train_mask)[0])
    va = np.isin(pos, np.where(val_mask)[0])
    te = np.isin(pos, np.where(test_mask)[0])

    y_scaler = r_scaler
    def rs(y):
        return y_scaler.transform(y.reshape(-1, 1)).ravel().astype(np.float32)

    Xtr, ytr, Xva, yva, Xte, yte = (
        X_seq[tr], rs(y_seq[tr]), X_seq[va], rs(y_seq[va]), X_seq[te], rs(y_seq[te]),
    )
    print(f"seq train={Xtr.shape} val={Xva.shape} test={Xte.shape}")

    dev = torch.device("cpu")
    model = ResidualLSTM(Xtr.shape[2]).to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    loss_fn = nn.MSELoss()

    def loader(X, y, shuffle):
        ds = torch.utils.data.TensorDataset(
            torch.from_numpy(X), torch.from_numpy(y))
        return torch.utils.data.DataLoader(ds, batch_size=BATCH, shuffle=shuffle)

    tr_loader, va_loader = loader(Xtr, ytr, True), loader(Xva, yva, False)
    best, best_state, bad = float("inf"), None, 0
    for ep in range(1, EPOCHS + 1):
        model.train()
        tot = 0.0
        for xb, yb in tr_loader:
            xb, yb = xb.to(dev), yb.to(dev)
            opt.zero_grad()
            loss = loss_fn(model(xb), yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tot += loss.item() * len(xb)
        model.eval()
        with torch.no_grad():
            vl = np.mean([loss_fn(
                model(xb.to(dev)), yb.to(dev)).item()
                for xb, yb in va_loader])
        print(f"ep {ep:02d} train_mse={tot/len(Xtr):.5f} val_mse={vl:.5f}")
        if vl < best - 1e-6:
            best, best_state, bad = vl, {k: v.cpu().clone() for k, v in model.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= PATIENCE:
                print(f"early stop at ep {ep}")
                break
    model.load_state_dict(best_state)

    # Evaluate: final = xgb baseline + lstm residual correction
    model.eval()
    with torch.no_grad():
        pred_r_scaled = model(torch.from_numpy(Xte).to(dev)).cpu().numpy()
    pred_r = y_scaler.inverse_transform(pred_r_scaled.reshape(-1, 1)).ravel()

    test_idx = test.index[SEQ_LEN:] if len(test) > SEQ_LEN else test.index
    # Align: Xte corresponds to last len(Xte) rows of test split
    y_true = test["load_kw"].to_numpy()[-len(Xte):]
    xgb_pred = xgb.predict(test[feat_cols].iloc[-len(Xte):])
    hybrid = xgb_pred + pred_r

    rmse = root_mean_squared_error(y_true, hybrid)
    mae = mean_absolute_error(y_true, hybrid)
    mape = mean_absolute_percentage_error(y_true, hybrid) * 100
    xb_rmse = root_mean_squared_error(y_true, xgb_pred)
    xb_mae = mean_absolute_error(y_true, xgb_pred)
    print(f"\nXGB-only  on same window: RMSE {xb_rmse:.1f} MAE {xb_mae:.1f}")
    print(f"Hybrid XGB+LSTM test: RMSE {rmse:.1f} MAE {mae:.1f} MAPE {mape:.2f}%")

    codes = test["readiness_code"].to_numpy()[-len(Xte):]
    for c in (1, 2, 3, 4):
        m = codes == c
        if m.sum():
            print(f"  readiness {c}: n={m.sum()} hybrid_MAE={mean_absolute_error(y_true[m], hybrid[m]):.1f} "
                  f"xgb_MAE={mean_absolute_error(y_true[m], xgb_pred[m]):.1f}")

    torch.save({
        "state_dict": model.state_dict(),
        "feat_cols": feat_cols,
        "seq_len": SEQ_LEN, "hidden": HIDDEN, "layers": LAYERS,
    }, OUT_MODEL)
    joblib.dump(scaler, BASE / "config" / "lstm_scaler_arakan.pkl")
    joblib.dump(y_scaler, BASE / "config" / "lstm_resid_scaler_arakan.pkl")
    print(f"saved -> {OUT_MODEL.name}")


if __name__ == "__main__":
    main()
