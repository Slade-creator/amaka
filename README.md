# AI-Based Energy Demand Forecasting for Zambian Military Facilities

Prototype for the final-year project. The repository currently contains two
pipelines:

| Pipeline | Outputs | Status |
|---|---|---|
| **v1** (`src/generate_load.py`, `src/preprocess.py`, `src/train_all_sites.py`) | `data/processed/`, `config/*.pkl` | Frozen. Used by `src/build_forecasts.py` for the dashboard replay. Do not overwrite. |
| **v2** (`src/v2_*.py`) | `data/synthetic_v2/`, `config/v2/` | Current research pipeline: realistic Zambian synthetic data, direct 1–48 h horizons, out-of-fold Stage-2 residuals, ablations. |

## Dashboard prototype (AMAKA)

The visual prototype lives in `frontend/` (React + TypeScript) and `backend/` (FastAPI).
It serves the **v2** research artifacts (`data/v2/replay_<site>_h<h>.csv`,
`config/v2_sites.json`) at horizons **1, 6, 24 and 48 hours**, defaulting to **H24**.
The horizon selector is live in the fleet map and site console. The desktop top bar also opens the satellite map (with the site switch), the fleet-wide alerts inbox and Data sources (meter kits, SCADA, CSV upload, live forecast) — the same screens as the phone app. It does not modify the
v2 training pipeline.

```powershell
.\run.ps1          # builds the UI and serves it at http://127.0.0.1:8000
```

Sign in with an account. On first start the API creates three demo accounts
(commander, manager, analyst) whose passwords are in `config/users.seed.json`;
create real ones with `python -m backend.users add <name> --role operator`.
The account's role (Commander, Energy Manager, Analyst) decides the views.
Every data endpoint needs a bearer token — see
[`docs/MOBILE_APP.md`](docs/MOBILE_APP.md#accounts-and-sign-in).

Design rationale: [`docs/DASHBOARD_PRINCIPLES.md`](docs/DASHBOARD_PRINCIPLES.md).
Model card: [`docs/MODEL_CARD_V2.md`](docs/MODEL_CARD_V2.md).
Chart explanation: [`docs/AI_NARRATIVE.md`](docs/AI_NARRATIVE.md).
Colours, config and the tower background: [`docs/THEMING_AND_CONFIG.md`](docs/THEMING_AND_CONFIG.md).
SCADA (OPC UA) integration and live forecasting: [`docs/SCADA_AND_LIVE_FORECAST.md`](docs/SCADA_AND_LIVE_FORECAST.md).
UI terminology: [`docs/VOCABULARY.md`](docs/VOCABULARY.md).
Screenshots: [`docs/screenshots/`](docs/screenshots/). Demo flow:
[`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).

| View | Screenshot |
|---|---|
| Intro animation (phone) | [`01-intro.png`](docs/screenshots/01-intro.png) |
| Sign-in | [`02-sign-in.png`](docs/screenshots/02-sign-in.png) |
| Fleet, Energy Manager | [`03-mobile-fleet.png`](docs/screenshots/03-mobile-fleet.png) |
| Alerts inbox | [`04-mobile-alerts.png`](docs/screenshots/04-mobile-alerts.png) |
| Site screen, Peter Zuze AFB | [`05-mobile-site.png`](docs/screenshots/05-mobile-site.png) |
| Satellite switch in flight | [`06-satellite-switch.png`](docs/screenshots/06-satellite-switch.png) |
| Satellite switch landed | [`07-satellite-landed.png`](docs/screenshots/07-satellite-landed.png) |
| Fleet, Commander | [`08-commander-fleet.png`](docs/screenshots/08-commander-fleet.png) |
| Data sources, Analyst | [`09-data-sources.png`](docs/screenshots/09-data-sources.png) |
| Desktop fleet map | [`10-desktop-fleet.png`](docs/screenshots/10-desktop-fleet.png) |
| Desktop site console | [`11-desktop-console.png`](docs/screenshots/11-desktop-console.png) |
| Intro: lit transmission-tower flythrough (WebGPU) | [`18-intro-towers.png`](docs/screenshots/18-intro-towers.png) |
| Live forecast from real readings | [`12-live-forecast.png`](docs/screenshots/12-live-forecast.png) |
| Desktop fleet with tools (Satellite · Alerts · Data sources) | [`13-desktop-fleet-tools.png`](docs/screenshots/13-desktop-fleet-tools.png) |
| Desktop alerts drawer | [`14-desktop-alerts.png`](docs/screenshots/14-desktop-alerts.png) |
| Desktop data sources + live forecast | [`15-desktop-data-sources.png`](docs/screenshots/15-desktop-data-sources.png) |
| Desktop satellite switch | [`16-desktop-satellite.png`](docs/screenshots/16-desktop-satellite.png) |
| Desktop site console with tools | [`17-desktop-console-tools.png`](docs/screenshots/17-desktop-console-tools.png) |

### Android app (Capacitor)

`frontend/` also builds as a **Capacitor 8** Android app (`frontend/android/`)
with a dedicated phone UI (`frontend/src/mobile/`: Fleet · Alerts · Sites ·
More tabs, pushed site screens, sign-in). It calls the FastAPI backend through
`VITE_API_BASE_URL`, which the sign-in screen can override at runtime. Debug APK:

```powershell
cd frontend
Copy-Item .env.mobile.example .env.mobile.local   # set the API origin
npm run apk
# → android/app/build/outputs/apk/debug/app-debug.apk
```

For a LAN demo, `.\run.ps1 -Lan` exposes the API on the laptop's Wi-Fi address.
The Gradle build needs JDK 21 (Android Studio's bundled JDK works). Full guide:
[`docs/MOBILE_APP.md`](docs/MOBILE_APP.md).

### Chart explanation (grounded LLM)

A **CHART EXPLANATION** panel sits directly under the load trace. It writes one short
paragraph about the selected hour and one about the visible window, and offers a
question box to the Energy Manager and Analyst roles.

The numbers are computed server-side in `backend/narrate.py`; the language model only
turns that fact pack into prose. Every number in the answer is checked against the fact
pack, and the answer is rejected if it invents a value, uses prohibited vocabulary
(*prediction*, *facility*) or makes a causal claim. A deterministic rule-based
narrative is always available and is what the panel shows while the model is thinking,
when no provider is configured, or after a grounding failure.

```powershell
# Optional: point at a provider. Without this, the panel runs rules-only.
$env:SENTINEL_LLM_PROVIDER = "openrouter"   # or openai / ollama / off
$env:SENTINEL_LLM_MODEL    = "google/gemini-2.5-flash"
$env:SENTINEL_LLM_API_KEY  = "sk-or-v1-..."
.\run.ps1
```

The same code works with a local Ollama model for an on-premises deployment. See
[`docs/AI_NARRATIVE.md`](docs/AI_NARRATIVE.md) for the fact-pack contract, provider
configuration, API shape and a thesis evaluation plan.

## v2 quick start

```bash
# 1. Optional: verify/refresh raw weather (Open-Meteo, Africa/Lusaka)
python src/fetch_weather.py

# 2. Generate realistic synthetic facility load
python src/v2_generate_load.py

# 3. Build features (gap-aware target, holidays, lags/rolling)
python src/v2_preprocess.py

# 4. Run the data contract checks
python src/v2_validate.py

# 5. Train/evaluate short-term (1–48 h) across all sites
python src/v2_train.py --horizons 1 6 24 48

# 6. Train/evaluate mid- to long-term (1 wk – 3 mo: 7, 14, 30, 60, 90 d)
python src/v2_midterm.py --horizons 7 14 30 60 90

# 7. Summarise results
python src/v2_report.py --dir config/v2 --write

# Optional required baseline: standalone LSTM
python src/v2_standalone.py --horizons 1 6 24 48
```

Smoke test (fast, one site/two horizons):

```bash
python src/v2_train.py --sites arakan --horizons 1 24 --quick --out-dir config/v2_smoke
```

## Synthetic simulation assumptions

The demand series is **synthetic** (the proposal's public-proxy dataset is not
used). Real Open-Meteo weather drives the simulation. This is a simulation
study, not a validation on real Zambian defence loads.

### Sites

| Site | Location | Type |
|---|---|---|
| Kohima Barracks | Lusaka | HQ + logistics barracks |
| Arakan Barracks | Lusaka | Admin + residential barracks |
| Peter Zuze AFB | Ndola | Air force base |
| Tug Argan Barracks | Ndola | Army garrison |
| Mikango Barracks | Chongwe | Training depot |
| ZNS Makeni | Lusaka | ZNS camp |

Peter Zuze and Tug Argan are ~3 km apart and share the same Open-Meteo grid
cell; `weather_tug_argan.csv` is derived from `weather_peter_zuze.csv`.

### Load components

For each site:

- fixed infrastructure base load;
- headcount-driven daily occupancy (double-hump profile);
- weekend and Zambian public-holiday reductions of administrative activity;
- per-site HVAC cooling/heating sized from floor area;
- a humidity/latent-load term;
- lighting driven by real solar irradiance;
- rooftop PV netting (real irradiance, per-site kWp);
- operational-readiness multipliers (4 routine → 1 exercise surge) applied to
  **gross** load before PV netting;
- 1.5% Gaussian noise plus a slow AR(1) drift;
- missing telemetry from internal feeder faults, planned maintenance and comms
  dropouts;
- unscheduled ZESCO-side grid faults with generator backup.

### Load-shedding assumption

All six sites are security-wing facilities. Public ministerial statements
(July 2024) say security wings are exempt from **scheduled** load shedding and
supplied 24/7. The simulation therefore does **not** create scheduled
load-shedding blocks. It does include a small number of unscheduled ZESCO-side
grid faults, because exempt institutions still experience faults, vandalism and
restoration failures. During a grid fault the backup generator carries the load:
a +6% restart surge in the first hour, then a +2% sustained efficiency penalty.
These are observed load events, not telemetry gaps, and are tracked by the
`grid_fault` / `generator_backup` columns.

### Zambian calendar

`src/v2_holidays.py` covers New Year, International Women's Day, Youth Day,
Kenneth Kaunda Day, Labour Day, Africa Freedom Day, National Day of Prayer,
Independence Day, Christmas, the four Easter days, Heroes' Day, Unity Day,
Farmers' Day, and observed Mondays when a holiday falls on Sunday. The same
calendar is used by the generator and the feature pipeline.

## Forecast horizons

A forecast origin is row `s`; the model knows load history through `s-1`. For
horizon `h`, the target is load at:

```text
t = s + h - 1
```

so `h=1` is one hour ahead and `h=48` is two days ahead.

- Load-history features (lags 1/2/24/168 h, 24 h rolling mean/std) come from the
  origin row.
- Calendar, weather, readiness and scheduled-maintenance features come from the
  **target** time.
- Weather is passed through a reproducible forecast-error proxy
  (`v2_config.WEATHER_ERROR`): AR(1) noise with horizon-growing variance. It
  stands in for a real numerical weather forecast; it is not the future observed
  weather.
- The model is a direct horizon model, not a recursive one.

### Mid- to long-term horizons (1 week – 3 months)

`src/v2_midterm.py` implements direct strategic forecasting at **7, 14, 30, 60 and 90 days ahead** (`1 week to 3 months`) at daily resolution for two operational targets:

1. **`daily_mean_kw`** (daily average power in kW; $\times 24$ = daily energy volume in $\text{kWh/day}$) for diesel fuel procurement and monthly ZESCO energy budgeting.
2. **`daily_peak_kw`** (daily maximum hourly demand in kW) for monthly ZESCO maximum-demand tariff planning (`120 ZMW/kW/month`) and generator capacity sizing.

To prevent future weather leakage at 1–3 months ahead, target weather blends exponentially into a 2024-fitted Fourier seasonal climatology ($\gamma(D) = e^{-D/7}$) plus stationary $\text{AR}(1)$ weather anomaly noise. Stage 1 is a regularized `XGBoost` regressor; Stage 2 compares out-of-fold `HistGradientBoosting` (`hybrid_hgb`) and L2-regularized `Ridge` (`hybrid_ridge`) residual learners alongside a statistical `SARIMAX / Harmonic Regression` baseline (`sarimax_harmonic`).

## Splits and evaluation protocol

Chronological split on the **target** timestamp:

| Split | Period |
|---|---|
| Train | 2024-01-01 – 2024-12-31 |
| Validation | 2025-01-01 – 2025-06-30 |
| Test | 2025-07-01 – 2025-12-31 |

- Rows where the target is missing or was imputed are excluded from training
  loss and from all accuracy metrics.
- Stage 2 is trained on **out-of-fold** Stage-1 residuals from expanding-window
  folds inside 2024 (Apr–Jun, Jul–Sep, Oct–Dec). This fixes the v1 failure where
  in-sample residuals were artificially small and the LSTM collapsed to a
  constant.
- The residual correction is shrunk by `alpha ∈ [0,1]`. Alpha is fitted on
  **Jan–Mar 2025**; the model choice is made on **Apr–Jun 2025**; the test set
  (2025 H2) is never used for either decision.
- Stage 2 candidates are the proposed residual LSTM and a tabular
  HistGradientBoosting residual learner. The validation-selected candidate
  becomes `hybrid`; `hybrid_lstm` and `hybrid_hgb` are always reported so the
  comparison is transparent.
- A candidate must beat XGBoost on the Apr–Jun validation window by at least
  0.5% RMSE to be selected; otherwise the pipeline serves plain XGBoost.
- Metrics: RMSE, MAE, MAPE, overall bias, top-decile peak bias/MAE, grid-fault
  MAE, and per-readiness MAE. `v2_report.py` produces the summary tables.

### Baselines and ablations

The evaluation includes:

- persistence (last observed load);
- seasonal naive 24 h and 168 h;
- standalone XGBoost;
- XGBoost + OOF residual LSTM (`hybrid_lstm`);
- XGBoost + OOF HistGradientBoosting residual learner (`hybrid_hgb`);
- validation-selected hybrid (`hybrid`; XGB, LSTM or HGB);
- XGBoost + OOF mean bias correction;
- XGBoost without readiness;
- XGBoost without weather;
- XGBoost core (load history + calendar only);
- optional standalone LSTM (`--standalone-lstm`).

## Outputs

```text
data/synthetic_v2/
  facility_load_<site>.csv        # observed target + diagnostics
  features_<site>.csv             # features for horizon building
  generation_manifest.json        # seeds, configs, disruption/holiday summary

config/v2/
  xgb_<site>_h<h>.pkl
  lstm_<site>_h<h>.pt
  resid_hgb_<site>_h<h>.pkl
  feature_scaler_<site>_h<h>.pkl
  residual_scaler_<site>_h<h>.pkl
  metrics_horizons.csv
  metrics_readiness.csv
  metrics_standalone.csv        # from v2_standalone.py
  metrics/
    metrics_<site>_h<h>.csv
    readiness_<site>_h<h>.csv
    run_<site>_h<h>.json          # OOF folds, alpha, LSTM diagnostics
  training_manifest.json
```

## Results snapshot

Final v2 results (six sites, 2025 H2 test) are in `docs/RESULTS_V2.txt`.
A report-ready draft is in `docs/RESULTS_CHAPTER.md` and
`docs/RESULTS_CHAPTER.docx`; the figures are in `docs/figures/`.
Regenerate them with:

```bash
python src/v2_make_figures.py
python src/v2_make_results_docx.py
```

Methodology diagrams are kept as Mermaid sources in `docs/diagrams/` and
rendered to `docs/figures/` with:

```bash
python src/v2_make_mermaid.py
```

Mean RMSE across sites:

| Horizon | XGB | Selected hybrid | Hybrid-HGB | Standalone LSTM |
|---:|---:|---:|---:|---:|
| 1 h | 53.3 | 50.8 | 50.3 | 92.6 |
| 6 h | 68.6 | 62.2 | 61.8 | 95.2 |
| 24 h | 74.2 | 70.1 | 69.4 | 97.8 |
| 48 h | 78.8 | 75.3 | 75.0 | 98.5 |

The validation gate selected XGB for 11 of 24 site/horizon combinations, HGB
for 10, and the LSTM for 3. The LSTM selections were all marginally worse on the
test set; this validation–test shift is documented in
`docs/REPORT_REVISION_NOTES.md`. The HGB residual learner is the strongest
overall. Peak-bias improvements are larger than the MAE improvements and are
reported in `docs/RESULTS_V2.txt`.

## Known limitations

- Demand is synthetic; results demonstrate methodology, not real defence-load
  accuracy.
- The synthetic readiness schedule is a direct driver of load. The required
  readiness ablation is implemented and must be reported: it shows how much of
  the apparent accuracy depends on that circular signal.
- With a strong 300-tree XGBoost, the LSTM residual correction is unstable at
  h=1 and is generally weaker than a tabular HGB residual learner. The pipeline
  reports both and selects on validation; the thesis should discuss this rather
  than claim an unconditional LSTM advantage.
- Weather forecast error is a proxy, not a real forecast product.
- Only short-term hourly horizons (1–48 h) are implemented.
- `statsmodels`/ARIMA baseline is not implemented yet.
- The v1 dashboard/replay (`build_forecasts.py`) still reads v1 artifacts; a v2
  replay builder is a later migration.
