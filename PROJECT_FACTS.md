# PROJECT_FACTS — AI-Based Energy Demand Forecasting for Military Facilities

Evidence-based inventory of the prototype in this folder (gathered 2026-11-14, read-only).
Status labels: **IMPLEMENTED** = working code that is called · **PARTIAL** = stub/unused/legacy · **PLANNED** = mentioned only in docs · **NOT FOUND** = no evidence.
Paths are relative to the `prototype/` folder.

---

## 1. Repository map

```
prototype/
├── README.md, run.ps1, run.bat          # docs + one-command launcher (build UI, start uvicorn)
├── requirements.txt, requirements-dev.txt
├── src/          # ML/data pipeline scripts (v1 legacy + v2_*.py current)
├── backend/      # FastAPI service: app.py, store.py, reports.py, narrate.py
├── frontend/     # React + TypeScript + Vite dashboard ("AMAKA")
│   ├── src/components/   (20 .tsx components)
│   ├── src/fleet/        (FleetMap, FleetView, RoleGate, RoleSwitcher, roles.ts, zambia.ts …)
│   ├── src/lib/          (alerts.ts, vocabulary …)
│   └── public/           (favicon, fonts)
├── config/       # trained models, scalers, metrics (v1 at root, v2 in config/v2/, smoke runs in config/v2_*)
├── data/         # raw weather, v1 processed, synthetic_v2, v2 replay/SHAP/midterm files (≈98 MB)
├── docs/         # model cards, results chapter, contracts, diagrams/, figures/, screenshots/
├── tests/        # smoke_api.py, smoke_narrate.py
├── scripts/      # colab.ps1/.cmd (run training on Google Colab)
├── notebooks/    # learning.ipynb
└── graphify-out/ # generated code knowledge graph (tooling, not part of the system)
```

| Folder | Purpose | Evidence |
|---|---|---|
| `src/` | v2 pipeline: weather fetch → synthetic load → features → validation → training → mid-term → replay/report builders. v1 scripts are kept but frozen | `README.md` "Pipeline" table; `src/v2_config.py:1-7` |
| `backend/` | REST API serving precomputed forecasts, alerts, SHAP, exports, LLM narrative | `backend/app.py`, `backend/store.py:1-11` |
| `frontend/` | Single-page dashboard served by the backend from `frontend/dist` | `frontend/package.json`, `backend/app.py:432-472` |
| `config/` | Model binaries + metric CSVs + `v2_sites.json` (dashboard config incl. cost assumptions) | `config/v2/`, `config/v2_sites.json` |
| `data/` | `raw/` weather CSVs, `synthetic_v2/` simulated load + features, `v2/` replay, SHAP and mid-term files | listed below |

---

## 2. Technologies and versions

Declared versions come from requirement files; "installed" versions come from the local environment (`pip show`, `frontend/node_modules/*/package.json`).

| Group | Technology | Declared / installed | Status | Evidence |
|---|---|---|---|---|
| Languages | Python | backend comment says 3.14; installed 3.13.9 | IMPLEMENTED | `backend/requirements.txt:1` |
| | TypeScript | ^5.8.0 / 5.9.3 | IMPLEMENTED | `frontend/package.json` |
| | PowerShell (launcher) | — | IMPLEMENTED | `run.ps1` |
| ML/XAI | XGBoost | >=2.0,<4 / 3.4.1 | IMPLEMENTED (Stage 1) | `src/v2_train.py:43,157` |
| | scikit-learn (HistGradientBoosting, Ridge, scalers) | >=1.5,<2 / 1.7.2 | IMPLEMENTED | `src/v2_train.py:40,380`; `src/v2_midterm.py:44-45` |
| | PyTorch (LSTM) | >=2.4 / 2.14.1+cpu | IMPLEMENTED | `src/v2_train.py:57-71` |
| | SHAP library (`shap` package) | — | **NOT FOUND**. SHAP values come from XGBoost's built-in TreeSHAP (`pred_contribs=True`) | `src/build_v2_replay.py:188-200` |
| | statsmodels / ARIMA | — | **NOT FOUND**. The "SARIMAX" baseline is actually a Ridge harmonic regression | `src/v2_midterm.py:351-367` |
| | pandas / numpy / joblib | pandas>=2.2 (2.3.3), numpy (2.3.5) | IMPLEMENTED | `requirements.txt` |
| Backend/API | FastAPI | >=0.115 / 0.140.0 | IMPLEMENTED | `backend/app.py` |
| | Uvicorn | >=0.34 / 0.51.0 | IMPLEMENTED | `run.ps1` |
| | httpx (LLM calls) | >=0.27 | IMPLEMENTED | `backend/narrate.py:696` |
| Database/cache | PostgreSQL / TimescaleDB | — | **NOT FOUND**. Data is stored in flat CSV/NPZ/JSON files | `backend/store.py:1-11` |
| | Redis | — | **NOT FOUND** | — |
| | In-process cache (`functools.lru_cache`, LLM answer cache) | stdlib | IMPLEMENTED | `backend/store.py:17`; `backend/narrate.py:851-870` |
| Frontend/charting | React | ^19.1.0 / 19.3.1 | IMPLEMENTED | `frontend/package.json` |
| | Next.js | — | **NOT FOUND** (Vite is used) | `frontend/vite.config.ts` |
| | Vite | ^6.3.0 / 6.4.5 | IMPLEMENTED | `frontend/vite.config.ts` |
| | Tailwind CSS | ^4.1.0 / 4.3.3 | IMPLEMENTED (`@import "tailwindcss"` + Vite plugin; most styling is custom CSS) | `frontend/src/styles.css:1` |
| | Recharts | ^2.15.4 / 2.15.4 | IMPLEMENTED | `frontend/src/components/LoadTrace.tsx:14` |
| | lucide-react (icons) | ^0.468.0 | IMPLEMENTED | `frontend/package.json` |
| | WebGPU hex animation | — | IMPLEMENTED (decorative) | `frontend/src/components/WebGPUHex.tsx` |
| Auth/security | Login / JWT / passwords | — | **NOT FOUND** | grep of `backend/`, `frontend/src` |
| | Role selection (client-side, no auth) | — | IMPLEMENTED | `frontend/src/fleet/roles.ts`, `RoleGate.tsx` |
| | CORS middleware | — | IMPLEMENTED | `backend/app.py:20,85` |
| Reporting | CSV export | pandas | IMPLEMENTED | `backend/reports.py:39-48` |
| | PDF export | reportlab >=4.2 (5.0.1) + matplotlib >=3.9 | IMPLEMENTED | `backend/reports.py:113-` |
| | Word results chapter | python-docx script | IMPLEMENTED (offline tool) | `src/v2_make_results_docx.py` |
| Notifications | Email / SMTP / webhook | — | **NOT FOUND**. Alerts are shown in the dashboard only | grep |
| AI narrative | LLM via OpenRouter / OpenAI / Ollama + rule-based fallback | env-configured | IMPLEMENTED (optional) | `backend/narrate.py:10-25` |
| Testing | pytest | >=8.0 (dev) | PARTIAL: declared, but the tests are scripts run with `python`, and only `smoke_narrate.py` has `test_` functions | `requirements-dev.txt`; `tests/` |
| | Vitest | — | **NOT FOUND** | `frontend/package.json` |
| DevOps | Docker / docker-compose | — | **NOT FOUND** | no Dockerfile/compose |
| | CI/CD (GitHub Actions etc.) | — | **NOT FOUND** | no `.github/` |
| | Google Colab GPU training helper | — | IMPLEMENTED | `scripts/colab.ps1`, `docs/colab-cli.md` |
| Other | Open-Meteo archive API (weather) | requests | IMPLEMENTED | `src/fetch_weather.py:35` |
| | Mermaid diagrams | — | IMPLEMENTED | `docs/diagrams/*.mmd`, `src/v2_make_mermaid.py` |

---

## 3. Data

### 3.1 Synthetic load generation: IMPLEMENTED
- Script: `src/v2_generate_load.py`; parameters in `src/v2_config.py`.
- **Sites (6):** Kohima (Lusaka, HQ + logistics), Arakan (Lusaka, admin + residential), Peter Zuze AFB (Ndola), Tug Argan (Ndola), Mikango (Chongwe, training depot), ZNS Makeni (Lusaka). See `src/v2_config.py:19,49-188`.
- **Per-site parameters:** base load 1,030–2,720 kW, PV 250–800 kWp, headcount 900–2,500, floor area 8,000–26,000 m², HVAC W/m²·°C, lighting W/m², weekend factor (0.80–0.82), holiday factor (0.90–0.92), fault, maintenance and comms-dropout probabilities. See `src/v2_config.py:49-188`.
- **Date range:** 2024-01-01 00:00 to 2025-12-31 23:00, hourly. That gives **17,544 rows per site** and about 105k rows in total (`data/synthetic_v2/facility_load_arakan.csv`).
- **Load components** (`src/v2_generate_load.py:39-102`):
  - base load
  - headcount occupancy with a double-hump daily profile
  - HVAC: cooling above 24 °C, heating below 16 °C (`v2_config.py:203-207`)
  - humidity term above 60 %
  - irradiance-driven lighting
  - noise: 1.5 % Gaussian plus AR(1) drift (φ = 0.98) (`v2_generate_load.py:89-94`)
- **Readiness states** (`v2_config.py:227-237`):
  - 4 routine ×1.00, 3 elevated ×1.08, 2 high readiness ×1.25, 1 exercise surge ×1.50
  - Applied to **gross** load before PV netting (`v2_generate_load.py:222`)
  - Event start probabilities per hour: 0.0019, 0.00083 and 0.00042; events are anchored to 04:00–06:00
- **Rooftop PV:** irradiance/1000 × kWp × 0.85 performance ratio, capped at kWp (`v2_generate_load.py:98-102`).
- **Holidays:** Zambian public holidays, including Easter and observed Mondays (`src/v2_holidays.py`).
- **Disruptions:**
  - Telemetry gaps: fault trips, planned maintenance and comms dropouts (`v2_generate_load.py:142`)
  - Unscheduled ZESCO grid faults: p = 0.0005/h, 1–6 h (10 % long, up to 12 h), generator +6 % restart surge then +2 % (`v2_config.py:215-225`)
  - No scheduled load-shedding, citing the July 2024 ministerial exemption
- Seeds and summary: `data/synthetic_v2/generation_manifest.json`.

### 3.2 Weather: IMPLEMENTED
- Source: **Open-Meteo historical archive** (`https://archive-api.open-meteo.com/v1/archive`), 2024–2025, Africa/Lusaka timezone (`src/fetch_weather.py:35,81`). Stored in `data/raw/weather_<site>.csv`.
- Tug Argan reuses Peter Zuze's grid cell (`README.md`, Sites).
- **Short-term forecast-error proxy:** AR(1) noise with φ = 0.70 and σ(h) = base + slope·h per variable, e.g. temperature 0.40 + 0.03·h °C (`v2_config.py:193-201`; `src/v2_horizons.py:62-101`).
- **Mid-term proxy:** target weather is blended into a Fourier climatology fitted on 2024 with weight γ = e^(−D/7), plus AR(1) anomaly noise (`src/v2_midterm.py:254`, docstring lines 12-14).

### 3.3 Features (short-term, 22 model features): `src/v2_horizons.py:32-48`

| Group | Features | How computed | Taken at |
|---|---|---|---|
| Load history (6) | `load_lag_1h`, `load_lag_2h`, `load_lag_24h`, `load_lag_168h`, `load_roll_mean_24h`, `load_roll_std_24h` | shifts/rolling over gap-filled `load_kw_feature` (`src/v2_preprocess.py:45-49`) | origin |
| Calendar (8) | `hour_sin/cos`, `dow_sin/cos`, `month_sin/cos`, `is_holiday`, `is_weekend` | cyclic encodings, holiday calendar (`v2_preprocess.py:30-40`) | target time |
| Weather (6) | `temperature_2m`, `relative_humidity_2m`, `precipitation`, `cloud_cover`, `shortwave_radiation`, `wind_speed_10m` | Open-Meteo plus forecast-error proxy | target time |
| Operations (2) | `readiness_code`, `disruption_maintenance` | simulated schedule | target time |

- **Diagnostic columns** (not features): `net_load_kw`, `gross_load_kw`, `pv_kw`, `grid_fault`, `generator_backup`, `disruption_type`, `is_target_imputed`.
- **Gap handling:**
  - Short gaps (6 h or less) are interpolated for features only.
  - Longer gaps are carried forward for features only.
  - The target keeps its NaNs and is excluded from training and metrics (`v2_preprocess.py:2-14,57-60`).
- **Mid-term features:**
  - Daily lags `lag_1d`, `lag_7d`, `lag_14d`, `lag_28d` and others
  - Day-of-year Fourier terms
  - Day-of-week, weekend and holiday flags
  - A day is valid only if 6 or fewer hours were missing (`src/v2_midterm.py:10-11,58`)

### 3.4 Data volume and storage (all CSV/NPZ/JSON files; no database)

| Location | Content |
|---|---|
| `data/raw/` | 6 weather CSVs + `zambia.geojson` |
| `data/synthetic_v2/` | `facility_load_<site>.csv` (17,544 × 16), `features_<site>.csv` (17,544 × 32), `generation_manifest.json` |
| `data/v2/` | 24 `replay_<site>_h<h>.csv`, 24 `shap_<site>_h<h>.npz`, 30 `midterm_<site>_d<D>.csv` |
| `data/processed/` | **legacy v1** data |
| Total `data/` | ≈98 MB |

---

## 4. Model pipeline

### 4.1 Short-term hybrid (`src/v2_train.py`): IMPLEMENTED
- **Stage 1: XGBoost** with 300 trees, max_depth 6, learning rate 0.05, subsample 0.8, colsample 0.8 (`v2_train.py:298-306,676-677`).
- **Stage 2 candidates:**
  - **Residual LSTM:** 2 layers, 32 hidden units, dropout 0.2, then Linear 32→16→1. Trained with Adam (learning rate 1e-3) for 20 epochs with early stopping (patience 5) and batch size 128, on 168-hour sequences (`v2_train.py:57-71,173-185`; `SEQ_LEN` in `v2_config.py:26`).
  - **HistGradientBoosting:** max_iter 150, max_depth 3, learning rate 0.05, L2 regularization 1.0 (`v2_train.py:380-383`).
- **Out-of-fold residuals:** expanding folds inside 2024. Each fold predicts the next quarter: Apr–Jun, Jul–Sep, Oct–Dec (`v2_config.py:39-43`; `oof_residuals` at `v2_train.py:236`).
- **Combination:** `hybrid = xgb + α·residual`.
  - α ∈ [0, 1] is a least-squares shrinkage fitted on Jan–Mar 2025 (`v2_train.py:385-397,456-462`).
- **Selection:**
  - The best candidate on Apr–Jun 2025 is chosen only if it beats XGBoost's validation RMSE by at least 0.5 % (`SELECTION_MARGIN = 0.005`, `v2_train.py:131,559-578`).
  - Otherwise plain XGBoost is served.
- **Splits on target timestamp** (`v2_config.py:29-34`):

| Period | Use |
|---|---|
| 2024 | train |
| Jan–Mar 2025 | α calibration |
| Apr–Jun 2025 | model selection |
| Jul–Dec 2025 | test, never used for fitting or selection |

- **Horizons implemented:** **1, 6, 24, 48 h**, direct (not recursive) (`v2_config.py:23`). The target is the load at origin + h (`README.md` "Forecast horizons").
- **Baselines:**
  - persistence
  - seasonal naive 24 h and 168 h
  - XGBoost
  - XGBoost + OOF mean bias (`xgb_bias_oof`)
  - `hybrid_lstm`, `hybrid_hgb`, selected `hybrid`
  - standalone LSTM (`--standalone-lstm`; also `src/v2_standalone.py`)
- **Ablations:** `xgb_no_readiness`, `xgb_no_weather`, `xgb_core` (history + calendar only) (`v2_train.py:312-330`).
- ARIMA is **NOT FOUND** for short-term.

### 4.2 Mid- to long-term (`src/v2_midterm.py`): IMPLEMENTED
- Horizons **7, 14, 30, 60, 90 days**, daily resolution, direct (`v2_midterm.py:53`).
- Targets: `daily_mean_kw` (energy budgeting / diesel) and `daily_peak_kw` (ZESCO demand charge at 120 ZMW/kW/month) (`v2_midterm.py:54-55`).
- **Stage 1: XGBoost** with 120 trees, depth 4, learning rate 0.05, λ 2, min_child_weight 5 (`v2_midterm.py:370-383`).
- **Stage 2:** OOF HGB and OOF Ridge (α 25). Selection uses the 0.5 % margin **plus** a residual-correlation gate of at least 0.05 (`v2_midterm.py:56-57,473-523`).
- **Baselines:**
  - persistence
  - 7-day rolling persistence
  - seasonal naive 7 d
  - `sarimax_harmonic`: Ridge on Fourier + AR lag terms. It is **not** a true SARIMAX (`v2_midterm.py:351-367`).
- Ablations as for short-term.
- Extra metrics:
  - WAPE
  - cumulative energy bias
  - 30-day window MAPE
  - monthly peak MAE in kW and ZMW
  - PICP 95 %
  - skill vs persistence and vs seasonal naive (`v2_midterm.py:98-170`)

### 4.3 Prediction intervals: IMPLEMENTED
- Method: **±1.96σ**, where σ is the standard deviation of validation residuals. This is a normal-approximation 95 % band, not quantile regression.
  - Short-term: `src/build_v2_replay.py:174-175,206`
  - Mid-term: `src/v2_midterm.py:143,632-633`
- Quantile models: **NOT FOUND**.
- Coverage is measured only for mid-term (PICP). For `daily_mean_kw` the hybrid's PICP is 93.5–95.0 %; for `daily_peak_kw` it is 87.7–91.5 % (`config/v2/metrics_midterm_summary.csv`).

### 4.4 SHAP: IMPLEMENTED (via XGBoost TreeSHAP)
- Explains the **Stage 1 XGBoost** model only, not the residual learner. Computed on the test rows with `booster.predict(..., pred_contribs=True)` (`src/build_v2_replay.py:188-200`).
- Stored as `data/v2/shap_<site>_h<h>.npz` (values, feature values, bias, feature names, timestamps).
- Served by `GET /api/sites/{site}/explain` and shown in `frontend/src/components/ExplainPanel.tsx`.

### 4.5 Metrics and headline results
Metrics are computed in `eval_metrics`, `src/v2_train.py:88-114`:
- RMSE, MAE, MAPE, bias
- top-decile peak bias and peak MAE
- grid-fault MAE, and RMSE/MAE excluding grid faults
- per-readiness MAE (`metrics_readiness.csv`)

**Short-term, mean over 6 sites, 2025 H2 test** (`config/v2/metrics_horizons_combined.csv`):

| Model | RMSE h1 | h6 | h24 | h48 | MAE h1 | h6 | h24 | h48 | MAPE h1 | h6 | h24 | h48 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Persistence | 114.5 | 352.5 | 252.8 | 334.6 | 87.9 | 294.8 | 164.5 | 255.3 | 5.0 | 17.0 | 9.5 | 15.0 |
| Seasonal naive 168 h | 215.3 | 215.3 | 215.3 | 215.2 | 121.4 | 121.4 | 121.4 | 121.8 | 6.7 | 6.7 | 6.7 | 6.7 |
| XGBoost | 53.3 | 68.6 | 74.2 | 78.8 | 35.6 | 42.6 | 47.4 | 51.8 | 2.0 | 2.3 | 2.6 | 2.9 |
| Hybrid (selected) | **50.8** | **62.2** | **70.1** | **75.3** | 35.4 | 42.0 | 47.2 | 51.9 | 2.0 | 2.3 | 2.6 | 2.9 |
| Hybrid-HGB | 50.3 | 61.8 | 69.4 | 75.0 | 35.3 | 42.1 | 47.2 | 51.8 | 2.0 | 2.4 | 2.6 | 2.9 |
| Hybrid-LSTM | 52.0 | 67.6 | 75.3 | 81.0 | 35.5 | 43.9 | 49.7 | 55.6 | 2.0 | 2.4 | 2.8 | 3.1 |
| Standalone LSTM | 92.6 | 95.2 | 97.8 | 98.5 | 61.0 | 63.4 | 65.9 | 67.1 | 3.4 | 3.6 | 3.7 | 3.8 |
| XGB no readiness | 68.0 | 115.0 | 141.3 | 151.7 | 40.0 | 58.4 | 72.3 | 78.8 | 2.2 | 3.2 | 3.9 | 4.3 |
| XGB no weather | 61.0 | 90.8 | 86.5 | 92.3 | 41.3 | 60.3 | 58.1 | 63.0 | 2.3 | 3.4 | 3.3 | 3.5 |
| XGB core | 72.4 | 127.3 | 149.1 | 159.6 | 44.4 | 73.3 | 81.1 | 88.1 | 2.5 | 4.0 | 4.4 | 4.8 |

RMSE and MAE are in kW; MAPE is in %.

**Selected Stage 2 per site and horizon** (`config/v2/metrics/run_<site>_h<h>.json` → `selection.selected`). Totals: XGB 11, HGB 10, LSTM 3.

| Site | h1 | h6 | h24 | h48 |
|---|---|---|---|---|
| arakan | hgb | hgb | hgb | xgb |
| kohima | hgb | hgb | hgb | hgb |
| makeni | xgb | xgb | xgb | xgb |
| mikango | xgb | xgb | lstm | lstm |
| peter_zuze | hgb | hgb | hgb | xgb |
| tug_argan | xgb | xgb | lstm | xgb |

**Mid-term mean RMSE in kW** (`config/v2/metrics_midterm_summary.csv`):

| Target / model | 7 d | 14 d | 30 d | 60 d | 90 d |
|---|---|---|---|---|---|
| daily_mean: hybrid | 59.4 | 61.3 | 67.2 | 71.3 | 69.7 |
| daily_mean: XGB | 65.5 | 67.0 | 72.8 | 74.2 | 75.4 |
| daily_mean: harmonic "SARIMAX" | 126.4 | 125.6 | 125.2 | 125.1 | 125.2 |
| daily_peak: hybrid | 89.6 | 93.9 | 105.9 | 108.2 | 107.4 |
| daily_peak: XGB | 93.1 | 97.4 | 106.8 | 110.4 | 109.7 |

The hybrid's mid-term MAPE is 2.2–2.6 % for daily mean and 2.9–3.5 % for daily peak.

---

## 5. Backend and dashboard

### 5.1 API endpoints (`backend/app.py`)

| Method | Path | Purpose | Line |
|---|---|---|---|
| GET | `/api/health` | health check | 168 |
| GET | `/api/overview?horizon=` | fleet config, metrics, cost per site | 182 |
| GET | `/api/fleet?at=` | fleet status at a timestamp | 207 |
| GET | `/api/sites/{site}/series` | replay series (actual, XGB, hybrid, 95 % band, context) | 220 |
| GET | `/api/sites/{site}/explain` | SHAP contributions for an hour | 249 |
| GET | `/api/sites/{site}/narrative` | chart explanation (rules or LLM, grounded) | 267 |
| POST | `/api/sites/{site}/narrative/ask` | question about the chart | 312 |
| GET | `/api/sites/{site}/alerts` | peak / variance alerts | 330 |
| GET | `/api/midterm/overview` | mid-term fleet summary | 344 |
| GET | `/api/sites/{site}/midterm` | mid-term series per site | 354 |
| GET | `/api/sites/{site}/report.csv` | CSV export | 366 |
| GET | `/api/sites/{site}/report.pdf` | PDF export | 393 |
| GET | `/`, `/{path}` | serves the built SPA | 438, 471 |

- **Inference:** none happens live. The API serves **precomputed** replays from `data/v2/` (`backend/store.py:1-11`). It is a historical "replay" of the 2025 H2 test period, not a real-time feed.
- **Database:** **NOT FOUND**. Storage is files plus `config/v2_sites.json`.
- **Cache:** in-process `lru_cache` for replay/SHAP data and an in-memory LLM answer cache. There is no Redis.

### 5.2 Frontend views (`frontend/src/App.tsx`)
- **Role gate:** pick one of three roles (`fleet/RoleGate.tsx`).
- **Fleet view:** Zambia map with the 6 sites (`FleetMap.tsx`, `zambia.ts`), a fleet table, and a right column of panels that depend on the role.
- **Site console** (tabs; `SiteHeader.tsx`):
  - KPI row (`KpiRow.tsx`)
  - load trace of actual vs forecast with the 95 % band (`LoadTrace.tsx`, Recharts)
  - horizon switcher H1/H6/H24/H48 (`HorizonSwitcher.tsx`)
  - chart explanation (`ChartNarrative.tsx`) and role narrative (`RoleNarrative.tsx`)
  - SHAP explanation (`ExplainPanel.tsx`) and model performance (`ModelPerf.tsx`)
  - alert feed (`AlertFeed.tsx`), dispatch card (`DispatchCard.tsx`) and facility facts (`FacilityFacts.tsx`)
  - **mid-term panel** (`MidtermPanel.tsx`)
- **Extras:** boot screen, "iris" scene transition (`SceneWipe.tsx`) and WebGPU hex background (`WebGPUHex.tsx`).

### 5.3 Alerts: IMPLEMENTED, dashboard only
- **Rules:**
  - forecast above the site's peak threshold → critical
  - forecast within 3 % of the threshold → warning
  - readiness R1/R2 surge → warning/info (client side)
  - |actual − forecast| > 95 % band → variance warning
- **Threshold:** the 97th percentile of load, rounded up to 50 kW (`src/build_v2_replay.py:205`).
- At most 8 alerts, deduplicated by kind.
- **Code:** `backend/store.py:363-475`; `frontend/src/lib/alerts.ts:1-12`.
- **Channels:** dashboard only. Email and webhook are **NOT FOUND**.

### 5.4 Report export: IMPLEMENTED
- **CSV:** the replay rows for the selected horizon and time range (`backend/reports.py:39-48`).
- **PDF:** a one-page A4 executive report built with reportlab (`backend/reports.py:113-390`). It contains:
  - a matplotlib chart of actual vs hybrid
  - metrics and alert counts
  - a cost table: baseline bill, monthly/annual saving, demand-charge and fuel savings
  - the cost assumptions

### 5.5 Authentication and roles
- Login: **NOT FOUND**.
- Roles: three **UI roles with no authentication** (`frontend/src/fleet/roles.ts`):

| Role | Code | View | Panels shown |
|---|---|---|---|
| Commander | CMD | Strategic view | readiness, cost exposure |
| Energy Manager | `operator` | Operations view | — |
| Analyst | — | Analysis view | — |

- The narrative question box is offered to Energy Manager and Analyst only (`README.md`).

### 5.6 Cost-impact simulation: IMPLEMENTED (simple and illustrative)
Assumptions in `config/v2_sites.json` → `cost_assumptions` (built in `src/build_v2_replay.py:230-268`):

| Assumption | Value |
|---|---|
| Energy tariff | 1.78 ZMW/kWh |
| Demand charge | 120 ZMW/kW/month |
| Diesel price | 30 ZMW/L |
| Generator fuel use | 0.28 L/kWh |
| Generator share of energy | 3 % |
| Peak shaving | 8 % |
| Fuel-efficiency gain | 10 % |
| Hours per month | 730 |
| Exchange rate | 28.5 ZMW/USD |

- Saving = peak × 8 % × demand charge + energy × 3 % × fuel-efficiency gain × diesel cost.
- These are assumed parameters, not measured savings.

### 5.7 Beyond the list
- **Grounded LLM chart explanation** (`backend/narrate.py`):
  - The numbers in the answer are checked against a server-computed fact pack.
  - Answers are rejected if they invent numbers, use banned words or make causal claims.
  - A rule-based fallback is used when the LLM is unavailable or rejected.
- Map-to-console transition animation, and a vocabulary/terminology contract (`docs/VOCABULARY.md`).

---

## 6. Engineering quality

### 6.1 Tests
| File | Lines | Covers |
|---|---|---|
| `tests/smoke_api.py` | 545 | Starts uvicorn and calls every endpoint across horizons, including CSV/PDF exports and validation errors |
| `tests/smoke_narrate.py` | 239 | LLM provider config, fact pack, rule fallback, grounding (13 `test_*`/check functions) |

- Framework: plain Python scripts with assertions; `pytest` is listed in `requirements-dev.txt`.
- There are **no frontend tests**.
- Pass/fail: **no recorded result or CI badge found.** Tests were not run, as instructed.

### 6.2 CI/CD, containers, environment variables, run instructions
- CI/CD, Dockerfile and docker-compose: **NOT FOUND**.
- Environment variables (names only): `SENTINEL_LLM_PROVIDER`, `SENTINEL_LLM_MODEL`, `SENTINEL_LLM_BASE_URL`, `SENTINEL_LLM_API_KEY` (falls back to `OPENAI_API_KEY`), `SENTINEL_LLM_TIMEOUT`, `SENTINEL_LLM_MAX_TOKENS` (`backend/narrate.py:16-21`). No `.env` file was found in the project.
- **To run:** `.\run.ps1` builds the UI with `npm run build` and starts `uvicorn backend.app:app` on http://127.0.0.1:8000. `.\run.ps1 -Dev` runs the Vite dev server on :5173 with a proxy to the API.
- **Pipeline order:** `fetch_weather` → `v2_generate_load` → `v2_preprocess` → `v2_validate` → `v2_train` → `v2_midterm` → `v2_report` (`README.md` "v2 quick start").

### 6.3 Lines of code
Counted with `wc -l`; cloc was not available, so blank and comment lines are included. Data, `node_modules`, `dist`, notebooks and generated files are excluded.

| Language / area | Files | Lines |
|---|---|---|
| Python: v2 pipeline (`src/v2_*.py`, `fetch_weather.py`, `build_v2_replay.py`) | 18 | 4,459 |
| Python: backend | 5 | 2,685 |
| Python: tests | 2 | 784 |
| TypeScript/TSX: frontend | ~35 | 6,836 |
| CSS | — | 2,485 |
| PowerShell/batch | 4 | 82 |
| **Total current system** | | **≈17,300 LOC (≈17.3 KLOC)** |
| Python: legacy v1 (excluded from the total) | 6 | 1,133 |
| Markdown docs (not code) | — | 2,508 |

### 6.4 Git history
- **No usable project history.** The git repository root is the user's home folder (`C:/Users/TMB COMPUTERS`), not `prototype/`.
- That repository has one commit ("first demo"), and **0 commits touch this folder**: `git log -- .` returns nothing.
- File dates suggest work ran from **about 2026-11-01** (v1 and dashboard QA) to **2026-11-13** (v2, mid-term, final results). This is based on file timestamps, not commits.

---

## 7. Gaps and mismatches

1. **README contradicts itself on mid-term.** The "Known limitations" section says "Only short-term hourly horizons (1–48 h) are implemented", but `src/v2_midterm.py` (7–90 d) and its results exist. `docs/REPORT_REVISION_NOTES.md` §1 and §10 also still say to drop 1 week–3 months. Both are now **outdated**.
2. **"SARIMAX" baseline is not SARIMAX.** `sarimax_harmonic` is a Ridge harmonic regression with AR lag features, and statsmodels is not installed (`src/v2_midterm.py:351-367`). README says "SARIMAX / Harmonic Regression" in one place and "ARIMA baseline is not implemented" in another.
3. README "Known limitations" says "a v2 replay builder is a later migration", but `src/build_v2_replay.py` exists and the dashboard serves v2 data (`backend/store.py`).
4. `v2_config.py:21-22` comment says medium-term "is a later extension". This is stale.
5. Python version: `backend/requirements.txt` says 3.14, while 3.13.9 is installed.
6. Results files report **HGB as the strongest Stage 2 model and the LSTM as weakest**. Any proposal text that claims an LSTM advantage would be wrong. The 3 LSTM selections were slightly worse on test (`docs/REPORT_REVISION_NOTES.md` §9, §11).
7. `pytest` is listed but the tests are standalone scripts. There is no CI and no frontend tests.
8. The proposal-style stack items (TimescaleDB, PostgreSQL, Redis, Next.js, Docker, email/webhook alerts, login/RBAC, `shap` package, Vitest) are **not in the code**.
9. `.gitignore` excludes the models and data, and the project folder itself has no commits. Results are not version-controlled.
10. `docs/screenshots/` is referenced by README; the folder exists. README's `docs/RESULTS_V2.txt` and `docs/RESULTS_CHAPTER.*` exist. `docs/figures/` holds only methodology figures (fig_3_*), so verify the results figures before citing them.

---

## Top 10 facts the proposal must state accurately

1. Demand data is a **synthetic simulation** of 6 Zambian military sites:
   - hourly, **2024-01-01 to 2025-12-31**, 17,544 rows per site
   - driven by **real Open-Meteo weather**, Zambian holidays, rooftop PV, a synthetic 4-level readiness schedule and simulated disruptions
   - no real defence data
2. The model is a **two-stage hybrid**: XGBoost (Stage 1), plus an out-of-fold residual learner chosen on validation between an **LSTM and HistGradientBoosting**. It falls back to XGBoost unless the gain is at least 0.5 %.
3. Short-term horizons are **1, 6, 24 and 48 h**, as direct models. **Mid-term 7–90 days** (daily mean and peak) is also implemented with XGBoost + HGB/Ridge.
4. Splits are by target time:

   | Period | Use |
   |---|---|
   | 2024 | train |
   | Jan–Mar 2025 | α calibration |
   | Apr–Jun 2025 | model selection |
   | Jul–Dec 2025 | untouched test |

5. Headline short-term test RMSE (6-site mean): **hybrid 50.8 / 62.2 / 70.1 / 75.3 kW** vs XGBoost 53.3 / 68.6 / 74.2 / 78.8 at h = 1/6/24/48. MAPE is about **2.0–2.9 %**.
6. **HGB beats the LSTM** as the residual learner. The standalone LSTM is the weakest learned model (92.6–98.5 kW RMSE). Do not claim an LSTM advantage.
7. Removing the readiness feature roughly **doubles** RMSE at 24–48 h, which shows the circularity of the synthetic readiness signal.
8. Uncertainty is a **±1.96σ (95 %) band** from validation residuals. Explainability is **TreeSHAP on the XGBoost stage** via XGBoost `pred_contribs`, not the `shap` library.
9. The stack is **FastAPI + React 19/Vite/TypeScript + Recharts + Tailwind**, with flat-file storage. There is **no database, Redis, Docker, CI, login or email/webhook alerts**. Roles (Commander, Energy Manager, Analyst) are UI views without authentication.
10. Features are:
    - alerts in the dashboard
    - CSV and PDF reports
    - an illustrative cost model (1.78 ZMW/kWh, 120 ZMW/kW/month demand charge, diesel 30 ZMW/L)
    - an optional grounded LLM chart explanation

    Size is about **17.3 KLOC** across Python, TypeScript and CSS, with legacy v1 excluded.
