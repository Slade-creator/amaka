# Model Card — AMAKA v2 Multi-Horizon Forecaster

## Overview

| Item | Detail |
|---|---|
| Version | `v2` (research pipeline), served by the AMAKA prototype |
| Model | Two-stage **direct multi-horizon** forecaster: XGBoost + validation-selected residual learner (HGB or LSTM) |
| Horizons | Short-term: 1, 6, 24 and 48 hours ahead (`src/v2_train.py`)<br>Mid/Long-term: 7, 14, 30, 60 and 90 days ahead (`src/v2_midterm.py`) |
| Output | Hourly point forecast (kW) + 95% interval (short-term); Daily Mean/Energy (kW / kWh) & Daily Peak (kW) + 95% interval (mid/long-term) |
| Explainability | TreeSHAP contributions from the Stage-1 XGBoost model |
| Sites | 6 Zambian military facilities (synthetic v2 load) |
| Training | 2024; validation 2025 H1; test 2025 H2 (never used for fitting/selection) |

## What changed from v1

- **Direct horizons** instead of a single 1-hour model: each horizon has its own XGBoost
  and residual learner.
- **Target-time features**: calendar, weather and readiness at the target hour; load
  history up to the forecast origin.
- **Weather forecast proxy**: target weather is perturbed with a reproducible AR(1)
  error that grows with horizon, so the model does not see the archived future weather.
- **Out-of-fold Stage-2 residuals** from expanding-window folds inside 2024 (no leakage).
- **Residual learner selection**: HGB and LSTM are both fit; the better Apr–Jun 2025
  validation model is selected per site/horizon. If neither beats XGBoost by the 0.5%
  selection margin, XGBoost is used.
- **v2 synthetic data**: grid faults, generator backup, planned maintenance, holidays,
  humidity/HVAC and site-specific parameters; gap-aware targets.

## Held-out performance (2025 H2, common test rows n≈4,189)

| Site | H | XGB RMSE | Hybrid RMSE | Hybrid MAE | MAPE | Persistence MAE | Standalone LSTM MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Arakan | 1 | 51.0 | 50.2 | 35.9 | 2.01% | 89.8 | 64.4 |
| Arakan | 24 | 82.2 | 76.8 | 50.6 | 2.77% | 178.0 | 73.1 |
| Arakan | 48 | 85.2 | 85.2 | 54.4 | 2.97% | 279.9 | 68.7 |
| Kohima | 1 | 88.8 | 74.4 | 47.7 | 2.15% | 108.1 | 80.3 |
| Kohima | 24 | 117.0 | 98.0 | 64.2 | 2.87% | 226.0 | 85.7 |
| Kohima | 48 | 126.3 | 105.5 | 71.8 | 3.23% | 343.6 | 92.7 |
| Makeni | 1 | 38.1 | 38.1 | 22.3 | 2.05% | 50.6 | 35.5 |
| Makeni | 24 | 47.5 | 47.5 | 28.3 | 2.60% | 94.1 | 38.0 |
| Makeni | 48 | 48.4 | 48.4 | 30.6 | 2.87% | 148.3 | 39.1 |
| Mikango | 1 | 32.0 | 32.0 | 23.9 | 1.93% | 60.8 | 41.6 |
| Mikango | 24 | 45.7 | 45.8 | 31.8 | 2.51% | 113.5 | 46.6 |
| Mikango | 48 | 49.3 | 49.5 | 35.3 | 2.84% | 178.2 | 46.8 |
| Peter Zuze | 1 | 70.7 | 70.9 | 54.0 | 1.94% | 145.8 | 93.2 |
| Peter Zuze | 24 | 97.5 | 97.1 | 69.9 | 2.51% | 236.4 | 96.0 |
| Peter Zuze | 48 | 106.4 | 106.4 | 77.8 | 2.79% | 362.5 | 97.2 |
| Tug Argan | 1 | 39.2 | 39.2 | 28.6 | 1.88% | 72.1 | 51.0 |
| Tug Argan | 24 | 55.2 | 55.3 | 38.4 | 2.50% | 139.3 | 55.9 |
| Tug Argan | 48 | 57.0 | 57.0 | 41.8 | 2.72% | 219.2 | 57.7 |

**Interpretation.** The hybrid gives a clear gain at the medium horizons for the larger
sites (Kohima h1: 88.8 → 74.4 RMSE; h24: 117.0 → 98.0) and a marginal or no gain where
the validation selection chooses XGBoost. All sites remain under 3.3% MAPE at 48 hours,
and every model beats persistence by a wide margin. The dashboard names the selected
residual learner per site/horizon rather than claiming HGB or LSTM everywhere.

## Design protocol

- Stage 1: XGBoost, 300 trees, depth 6, lr 0.05, subsample/colsample 0.8.
- Stage 2: residual HGB (150 iterations, depth 3) and residual LSTM (168h window,
  32 hidden, 2 layers, dropout 0.2).
- Alpha blending for each residual learner is fit on Jan–Mar 2025 and selected on
  Apr–Jun 2025; the test period is untouched.
- If the best residual learner does not beat XGBoost by 0.5% validation RMSE, the
  system selects XGBoost.
- The 95% band is `±1.96σ` of held-out hybrid residuals per site/horizon.

## Ablations and baselines

The v2 metrics include `xgb_no_readiness`, `xgb_no_weather`, `xgb_core`,
`seasonal_naive_24`, `seasonal_naive_168`, persistence and standalone LSTM. See
`config/v2/metrics_horizons_combined.csv`, `metrics_standalone.csv` and
`metrics_readiness.csv`. These support the Sprint 4 ablation narrative.

## Intended use and non-use

**Intended:** research/demo decision support, horizon comparison, SHAP explanation and
operational planning in a synthetic/prototype context.

**Not intended:** safety-critical dispatch, automated generator/breaker control,
settlement, or real-installation operation without retraining and validation.

## Caveats

- Load is synthetic; weather is real Open-Meteo but the target weather is a forecast
  proxy, not observed future weather.
- Grid faults and some telemetry gaps are simulated; real SCADA behavior may differ.
- MAPE is unstable near zero load; RMSE/MAE are primary.
- The interval is constant within a site/horizon, not horizon- or quantile-aware.
- The dashboard shows the selected residual learner honestly; some site/horizons fall
  back to XGBoost.

## Reproduction

```powershell
python src/v2_generate_load.py
python src/v2_preprocess.py
python src/v2_validate.py
python src/v2_train.py --horizons 1 6 24 48
python src/v2_report.py --dir config/v2 --write
python src/build_v2_replay.py   # dashboard replay + SHAP + v2_sites.json
```

Artifacts: `config/v2/`, `data/synthetic_v2/`, `data/v2/`, `config/v2_sites.json`.
