"""
Train hybrid XGB+LSTM for all 6 sites (Sprint 2 completion).
Per-site models: base loads differ 1000-3000 kW, so separate models.
Reuses Arakan pipeline: SEQ 168, StandardScaler residuals, 20 epochs max, early stop 5.
Saves: config/xgb_<site>.pkl, config/lstm_<site>.pt, scalers, metrics csv.
"""
import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from pathlib import Path
from sklearn.preprocessing import MinMaxScaler, StandardScaler
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error
try:
    from sklearn.metrics import root_mean_squared_error
except ImportError:
    from sklearn.metrics import mean_squared_error
    def root_mean_squared_error(y, p):
        return float(np.sqrt(mean_squared_error(y, p)))
from xgboost import XGBRegressor

BASE = Path(__file__).resolve().parents[1]
PROC = BASE / "data" / "processed"
CFG = BASE / "config"
SITES = ["arakan", "kohima", "makeni", "mikango", "peter_zuze", "tug_argan"]
DROP = ["load_kw", "readiness_label"]
SEQ = 168

class ResLSTM(nn.Module):
    def __init__(self, f):
        super().__init__()
        self.lstm = nn.LSTM(f, 32, num_layers=2, batch_first=True, dropout=0.2)
        self.head = nn.Sequential(nn.Linear(32, 16), nn.ReLU(), nn.Linear(16, 1))
    def forward(self, x):
        o, _ = self.lstm(x)
        return self.head(o[:, -1, :]).squeeze(-1)

def train_site(site):
    torch.manual_seed(42); np.random.seed(42)
    df = pd.read_csv(PROC / f"features_{site}.csv", parse_dates=["timestamp"]).dropna().set_index("timestamp").sort_index()
    train = df.loc["2024-01-01":"2024-12-31"]; val = df.loc["2025-01-01":"2025-06-30"]; test = df.loc["2025-07-01":]
    feat_cols = [c for c in df.columns if c not in DROP]
    x_train, y_train = train[feat_cols], train["load_kw"]
    # Stage 1 XGBoost
    xgb = XGBRegressor(n_estimators=300, max_depth=6, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8, n_jobs=-1, random_state=42)
    xgb.fit(x_train, y_train)
    # Sequences
    scaler = MinMaxScaler().fit(x_train)
    X_all = scaler.transform(df[feat_cols]).astype("float32")
    resid_all = (df["load_kw"].values - xgb.predict(df[feat_cols])).astype("float32")
    X_seq = np.stack([X_all[i-SEQ:i] for i in range(SEQ, len(X_all))]).astype("float32")
    y_seq = resid_all[SEQ:]
    n_tr, n_va = len(train), len(val)
    pos = np.arange(SEQ, len(df))
    tr = pos < n_tr; va = (pos >= n_tr) & (pos < n_tr+n_va); te = pos >= n_tr+n_va
    r_scaler = StandardScaler().fit(y_seq[tr].reshape(-1, 1))
    y_s = r_scaler.transform(y_seq.reshape(-1, 1)).ravel().astype("float32")
    Xtr, Xva, Xte = X_seq[tr], X_seq[va], X_seq[te]
    ytr, yva = y_s[tr], y_s[va]
    # Stage 2 LSTM
    from torch.utils.data import TensorDataset, DataLoader
    trL = DataLoader(TensorDataset(torch.from_numpy(Xtr), torch.from_numpy(ytr)), batch_size=128, shuffle=True)
    vaL = DataLoader(TensorDataset(torch.from_numpy(Xva), torch.from_numpy(yva)), batch_size=256)
    model = ResLSTM(Xtr.shape[2])
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    lossf = nn.MSELoss()
    best, bs, bad = float("inf"), None, 0
    for ep in range(20):
        model.train()
        for xb, yb in trL:
            opt.zero_grad(); lossf(model(xb), yb).backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step()
        model.eval()
        with torch.no_grad():
            vl = sum(lossf(model(xb), yb).item()*len(xb) for xb, yb in vaL)/len(Xva)
        if vl < best-1e-6: best, bs, bad = vl, {k: v.cpu().clone() for k, v in model.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= 5: break
    model.load_state_dict(bs)
    # Eval
    model.eval()
    with torch.no_grad():
        pr = r_scaler.inverse_transform(model(torch.from_numpy(Xte)).numpy().reshape(-1, 1)).ravel()
    y_true = test["load_kw"].values[-len(Xte):]
    xp = xgb.predict(test[feat_cols].iloc[-len(Xte):])
    hyb = xp + pr
    m = {"site": site,
         "xgb_rmse": round(float(root_mean_squared_error(y_true, xp)), 1),
         "xgb_mae": round(float(mean_absolute_error(y_true, xp)), 1),
         "hyb_rmse": round(float(root_mean_squared_error(y_true, hyb)), 1),
         "hyb_mae": round(float(mean_absolute_error(y_true, hyb)), 1),
         "hyb_mape": round(float(mean_absolute_percentage_error(y_true, hyb)*100), 2)}
    joblib.dump(xgb, CFG / f"xgb_{site}.pkl")
    torch.save({"state_dict": model.state_dict(), "feat_cols": feat_cols}, CFG / f"lstm_{site}.pt")
    joblib.dump(scaler, CFG / f"scaler_{site}.pkl")
    joblib.dump(r_scaler, CFG / f"rscaler_{site}.pkl")
    print(f"{site}: XGB {m['xgb_rmse']}/{m['xgb_mae']} -> HYB {m['hyb_rmse']}/{m['hyb_mae']} MAPE {m['hyb_mape']}%", flush=True)
    return m

if __name__ == "__main__":
    import csv
    rows = [train_site(s) for s in SITES]
    with open(CFG / "metrics_all_sites.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    print("saved metrics_all_sites.csv")
