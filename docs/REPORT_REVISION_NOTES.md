# Report revision notes for the v2 prototype

These are the paragraphs/sections in `ICT431_202308647_EltonChiwala_revised.docx`
that need to change so the report matches the implemented v2 pipeline. Replace
the bracketed results with the final `config/v2/metrics_horizons.csv` numbers.

## 1. Abstract

Current wording implies public proxy load datasets. Replace with:

> The prototype uses a synthetic hourly facility-load simulation for six Zambian
> military sites, driven by real Open-Meteo weather, Zambian public holidays, a
> parameterised operational-readiness schedule, rooftop PV, and documented
> telemetry disruptions. Because real defence telemetry is restricted, the
> results demonstrate the methodology and the value of weather/activity features
> rather than validate accuracy on real Zambian defence loads.

Also narrow the horizon claim until medium-term models are implemented:

> short-term direct forecasts from 1 to 48 hours ahead

and note that medium-term (1 week–3 months) forecasting is future work.

## 2. Section 1.5.2 — Technical and data scope

Replace the ASHRAE/BDG2 sentence with:

> Because operational data from military installations are restricted, the
> prototype uses a synthetic hourly load simulator for six Zambian security-wing
> sites. Real historical weather is obtained from the Open-Meteo archive for
> 2024–2025 at each site's coordinates. The simulator combines facility base
> load, headcount-driven occupancy, floor-area-sized HVAC and lighting, humidity,
> rooftop PV, Zambian public holidays, and a synthetic operational-readiness
> schedule. No classified or real installation data are used.

## 3. Section 1.5.4 — Assumptions and limitations

Update to:

> The readiness signal is synthetic and is a direct driver of the simulated
> load, so the reported accuracy is partly circular. The evaluation therefore
> reports the model with and without readiness features. The demand series is
> also synthetic; results demonstrate the methodology rather than validate
> accuracy on real Zambian defence loads. Weather forecasts are represented by
> archived observations with an explicit, horizon-growing forecast-error proxy,
> not by an operational numerical weather prediction product.

## 4. New subsection — Zambian load-shedding context

Add after the site description:

> Public statements by the Minister of Energy in July 2024 list security wings
> among the strategic institutions exempt from scheduled ZESCO load management
> and supplied on a 24-hour basis. All six sites are therefore modelled as
> exempt from scheduled load shedding. They are not immune to unscheduled
> ZESCO-side faults, vandalism, or restoration failures; the simulator includes a
> small number of such grid faults, during which backup generators carry the
> load with a short restart surge and a small sustained efficiency penalty. The
> `grid_fault` and `generator_backup` columns record these events. Scheduled
> load-shedding blocks are deliberately out of scope.

## 5. Section 3.2.1 — Data acquisition and preprocessing

Replace the gap-handling sentence with:

> Short telemetry gaps of up to six hours are linearly interpolated for feature
> construction. Longer gaps are carried forward only for lag/rolling features;
> the observed target remains missing and is marked by `is_target_imputed`.
> Imputed targets are excluded from training loss and from all accuracy metrics.
> A separate validation script checks hourly coverage, missingness, lag
> alignment, holiday flags, and horizon alignment.

Remove the claim that extended gaps are excluded entirely; they are excluded
from the target, not from feature continuity.

## 6. Section 3.2.2 — Hybrid model

Replace the Stage 2 description with:

> Stage 2 is trained on out-of-fold Stage-1 residuals from expanding-window
> folds inside 2024 (April–June, July–September, October–December). This avoids
> the artificially small in-sample residuals of a boosted model. Two residual
> learners are compared: a two-layer LSTM on 168-hour sequences and a tabular
> HistGradientBoosting regressor on the same residual target. A one-parameter
> shrinkage factor is fitted on January–March 2025, and the better residual
> learner is selected on April–June 2025; the July–December 2025 test period is
> untouched. If neither candidate beats plain XGBoost by at least 0.5% RMSE on
> the selection window, the pipeline serves plain XGBoost.

Add the horizon definition:

> A forecast origin is the last observed hour. For horizon h, the target is
> load at origin + h. Load-history features come from the origin; calendar,
> weather, readiness and scheduled-maintenance features come from the target
> time. The model is direct, not recursive.

Add the weather proxy:

> Target-time weather is the archived observation plus AR(1) forecast error with
> horizon-growing variance. This stands in for an operational weather forecast;
> it is not a claim that future weather is known.

## 7. Section 3.2.4 — Evaluation

Replace the baseline paragraph with:

> The evaluation reports persistence, seasonal-naive 24-hour and 168-hour
> forecasts, standalone XGBoost, standalone LSTM, XGBoost + residual LSTM,
> XGBoost + residual HGB, and the validation-selected hybrid. ARIMA remains
> future work. Metrics are RMSE, MAE, MAPE, overall bias, top-decile peak
> bias/MAE, grid-fault MAE, and per-readiness MAE. Ablations remove readiness,
> weather, or both. The readiness ablation is essential because the synthetic
> readiness signal directly drives load.

## 8. Section 4.2.2 — Validation protocol

Replace the expanding-window CV paragraph with:

> Stage-1 residual generation uses expanding-window time-series folds inside the
> 2024 training period. Final model selection uses a chronological 2025 H1
> validation period split into January–March (correction calibration) and
> April–June (model selection). The 2025 H2 test period is evaluated once and is
> never used for scaling, early stopping, shrinkage, or model selection.

## 9. Results/discussion points to add

Use the final tables from `python src/v2_report.py --dir config/v2 --write`.
Expected discussion points:

- The OOF fix removes the v1 failure where the residual LSTM collapsed to a
  constant.
- The LSTM is not the strongest residual learner on this simulation. A tabular
  HGB on the same OOF residuals is stronger at most horizons. Report both;
  do not claim an unconditional LSTM advantage.
- The validation gate selects plain XGBoost at some site/horizon combinations
  (e.g. Arakan h=48), which is the correct outcome when Stage 2 does not
  generalise.
- The gate is not infallible: at Mikango h=24 and h=48 it selected the LSTM on
  small validation gains, but test RMSE was slightly worse (+0.1 and +0.2 kW).
  The LSTM correction was nearly constant in those runs. Report this as a
  validation–test shift and recommend adding a variance/correlation gate (the
  residual correction must be non-degenerate) in future work. Do not change the
  protocol after seeing the test set.
- Removing readiness increases RMSE substantially, confirming the circularity
  risk; the synthetic activity signal must be discussed explicitly.
- Peak/top-decile bias is much lower for the selected hybrid than for XGBoost,
  which matters for peak-demand charges and generator dispatch even when
  overall RMSE gains are modest.
- The standalone LSTM is substantially weaker than XGBoost; include it as the
  required baseline, not as the production model.

## 10. Scope wording

Change "1 to 48 hours and 1 week to 3 months" to "1 to 48 hours" in the
objectives and abstract until the medium-term daily/weekly models are built.
Keep medium-term as future work in Chapter 5.

## 11. Final v2 numbers

From `config/v2/metrics_horizons_combined.csv` (six sites, 2025 H2 test).
`hybrid` is the validation-selected model; `hybrid_hgb` and `hybrid_lstm` are
the two candidates.

### Mean RMSE (kW)

| Horizon | XGB | Hybrid | Hybrid-HGB | Hybrid-LSTM | Persistence | Seasonal naive 168 h |
|---:|---:|---:|---:|---:|---:|---:|
| 1 h | 53.3 | 50.8 | 50.3 | 52.0 | 114.5 | 215.3 |
| 6 h | 68.6 | 62.2 | 61.8 | 67.6 | 352.5 | 215.3 |
| 24 h | 74.2 | 70.1 | 69.4 | 75.3 | 252.8 | 215.3 |
| 48 h | 78.8 | 75.3 | 75.0 | 81.0 | 334.6 | 215.2 |

### Mean MAE (kW)

| Horizon | XGB | Hybrid | Hybrid-HGB | Hybrid-LSTM |
|---:|---:|---:|---:|---:|
| 1 h | 35.6 | 35.4 | 35.3 | 35.5 |
| 6 h | 42.6 | 42.0 | 42.1 | 43.9 |
| 24 h | 47.4 | 47.2 | 47.2 | 49.7 |
| 48 h | 51.8 | 51.9 | 51.8 | 55.6 |

### Top-decile peak bias (kW, positive = under-prediction)

| Horizon | XGB | Hybrid | Hybrid-HGB | Hybrid-LSTM |
|---:|---:|---:|---:|---:|
| 1 h | 49.1 | 29.1 | 26.6 | 36.9 |
| 6 h | 79.1 | 49.2 | 44.0 | 62.1 |
| 24 h | 84.0 | 62.7 | 59.7 | 68.2 |
| 48 h | 89.5 | 68.1 | 66.6 | 64.3 |

### Readiness/weather ablations (mean RMSE, kW)

| Horizon | XGB | No readiness | No weather | Core (history + calendar) |
|---:|---:|---:|---:|---:|
| 1 h | 53.3 | 68.0 | 61.0 | 72.4 |
| 6 h | 68.6 | 115.0 | 90.8 | 127.3 |
| 24 h | 74.2 | 141.3 | 86.5 | 149.1 |
| 48 h | 78.8 | 151.7 | 92.3 | 159.6 |

### Standalone LSTM baseline (Colab T4, 168 h / 20 epochs)

Mean RMSE across sites: **92.6 / 95.2 / 97.8 / 98.5 kW** at h=1/6/24/48.
This is much weaker than XGB (53.3/68.6/74.2/78.8) and the selected hybrid
(50.8/62.2/70.1/75.3). Report it as the required standalone sequence baseline,
not as a competitive production model. Its top-decile peak bias is
101.6/105.5/120.4/117.8 kW.

### Selection counts

- XGB: 11 of 24 site/horizon combinations.
- HGB: 10 of 24.
- LSTM: 3 of 24 (Mikango h=24/48, Tug Argan h=24), and test RMSE was
  +0.1/+0.2/+0.1 kW worse in those three cases.

### Key interpretation

- The selected hybrid improves mean RMSE by about 4.4–9.3% versus XGB, but the
  gain is concentrated at Kohima and Arakan; Makeni/Mikango/Tug mostly gate to
  plain XGB, and Peter Zuze is mixed.
- The HGB residual learner is the strongest overall: it is the best test model
  at **22 of 24** site/horizon combinations. The LSTM ties XGB at Peter Zuze
  h=1 (70.7 kW) and is never uniquely best; plain XGB is best at Tug Argan h=6.
- The pre-registered 0.5% validation gate selected HGB at only 10 of 24
  combinations; it is deliberately conservative and leaves some small HGB gains
  on the table. Do **not** lower the threshold after seeing the test set. For a
  future prospective design, consider HGB as the primary Stage 2, or a lower HGB
  margin (e.g. 0.1%) combined with a non-degenerate-variance/correlation gate
  for the LSTM.
- The LSTM residual learner is not reliable on this simulation. It was selected
  at Mikango h=24/48 and Tug Argan h=24, and test RMSE was slightly worse in all
  three cases; its correction was near-constant.
- Removing readiness almost doubles RMSE at 24–48 h, confirming that the
  synthetic activity signal is a major driver and that the ablation is essential.
- Peak bias improves substantially even where overall MAE changes little, which
  is relevant for peak-demand charges and generator dispatch.
- The standalone LSTM baseline is the weakest of the model families; report it
  as a required baseline, not as the production model.
