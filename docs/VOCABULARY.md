# AMAKA — Dashboard Vocabulary

The words the dashboard uses, and the rules for choosing them. Plain
operational English: a commander, energy manager or analyst should understand
the screen without knowing machine-learning jargon.

The code source of truth is:

- `frontend/src/lib/vocabulary.ts` — readiness, status, alert and shared terms.
- `backend/store.py` — `READINESS_NAMES` and `FEATURE_LABELS`.

This document and those files must stay in step.

## Core terms

| Use | Meaning | Do not use |
|---|---|---|
| **Site** | One facility (barracks, base, camp). | facility, installation, node |
| **Fleet** | All six sites together. | estate, network |
| **Load** | Electrical demand at a site, in kW. | consumption, usage, power (when you mean load) |
| **Actual load** | Measured load for the hour. | actual, observed, meter reading |
| **Forecast** | AMAKA's predicted load for the hour. | prediction, predicted value, output |
| **Hybrid forecast** | The served forecast: XGBoost plus residual correction. Only use when contrasting with XGBoost-only. | hybrid, hybrid model |
| **Peak threshold** | The site's demand limit, in kW. | limit, cap, max |
| **Headroom** | Peak threshold minus forecast peak (positive). | margin, spare capacity |
| **Shortfall** | The amount by which the forecast exceeds the peak threshold. | deficit, need, negative headroom |
| **Over threshold** | Prose form for a negative headroom. | breaching, over limit |
| **95% forecast range** | The lower–upper band around the forecast. | interval, confidence band, 95% band |
| **Readiness level** | R1–R4 operational state. | readiness code, alert level |
| **Test period** | The held-out evaluation window, July–December 2025. | held-out set, test set, H2 |
| **Replay** | Historical playback of the 2025 H2 test period. | simulation, live mode |
| **Selected hour** | The hour the replay cursor is on. | cursor hour, current time |
| **Data link** | Connection to the local data service. | backend, API, uplink |

Sentence case for prose. Uppercase only for micro-labels (`PEAK THRESHOLD`).
Use `kW` for site load, `MW` for fleet totals, and `ZMW` for money.

## Readiness levels

Higher readiness means more activity and higher load. R1 is the highest level,
not the lowest.

| Code | Name | Compact tag | Meaning |
|---:|---|---|---|
| 1 | **Exercise surge** | `R1 EXERCISE SURGE` | Major exercise; load is well above normal. |
| 2 | **High readiness** | `R2 HIGH READINESS` | Heightened operations; load is above normal. |
| 3 | **Elevated** | `R3 ELEVATED` | Increased activity; load is slightly above normal. |
| 4 | **Routine** | `R4 ROUTINE` | Normal day-to-day activity. |

**High readiness** covers R1–R2. Do not call R1 alone "readiness" or call the
R1–R2 total "surge": that is what caused the old label drift.

## Site status

Status describes the forecast against the peak threshold, not readiness.

| Status | Meaning |
|---|---|
| **Critical** | Forecast is at or above the peak threshold. |
| **Warning** | Forecast is within 3% of the peak threshold. |
| **Nominal** | Forecast is below the warning band. |

Compact HUD codes `CRIT`, `WARN`, `NOM` are allowed only where space is tight
and a legend is visible. Everywhere else spell the status out.

## Alerts

Severity: **Critical**, **Warning**, **Info**.

| Alert kind | Display name | Rule |
|---|---|---|
| `peak` | Peak threshold | Forecast above the threshold (critical) or within 3% (warning). |
| `surge` | Readiness | R1 (warning) or R2 (info) in effect. |
| `variance` | Forecast range | Actual load outside the 95% forecast range. |

Alert titles are sentences: "Peak threshold exceeded", "High readiness in
effect", "Actual load outside forecast range".

## Roles and views

| Role | View name | Purpose |
|---|---|---|
| **Commander** | Strategic view | Fleet status, peak risk and cost exposure. |
| **Energy Manager** | Operations view | Generator dispatch, peak shaving and site weather. |
| **Analyst** | Analysis view | Model accuracy, data quality and fleet comparison. |

Use "Energy Manager", never "operator", in user-facing copy. The internal role
key stays `operator` for URL and storage stability.

## Forecast horizons

The pipeline serves direct forecasts 1, 6, 24 and 48 hours ahead.

- Compact control: `H1`, `H6`, `H24`, `H48`.
- Prose: "24-hour forecast", "forecast 24 hours ahead".
- The chart's `24H / 72H / 7D / 30D` tabs are the **visible time window**, not
  the forecast horizon. Keep the two controls visually separate.

## Metrics and model terms

These are analyst terms, so keep the acronym but say what it means the first
time it appears in a panel:

| Term | Plain gloss |
|---|---|
| **MAPE** | Mean absolute percentage error; the headline forecast error. |
| **MAE** | Mean absolute error, in kW; the typical miss. |
| **RMSE** | Root-mean-square error, in kW; penalises large misses. |
| **XGBoost** | The stage-1 tree model. |
| **Residual correction** | The stage-2 model that adjusts the XGBoost forecast. |
| **SHAP** | How much each input moved this forecast up or down. |

Baselines are named by what they assume, not by their statistical name:

- **Last hour** — assumes load repeats the last hour (persistence).
- **Same hour last week** — assumes load repeats last week (seasonal naive).

## Wording rules

1. **One idea, one word.** Do not alternate load/demand/consumption in the UI.
2. **No `Δ` in prose.** Write "63 kW above forecast", not "Δ +63 kW".
3. **No "predicted" or "prediction".** Use "forecast".
4. **No "hybrid" as a primary label.** The lime line is "Forecast"; the analyst
   table may say "Hybrid forecast".
5. **No "cursor".** Say "selected hour".
6. **No "facility".** Say "site".
7. **Do not call R1–R2 "surge".** Say "high readiness".
8. **Do not use "elevated" for a peak warning.** It is reserved for R3.
9. **Keep API keys stable.** `surge_sites`, `surge_hours` and
   `variance_hours` are data-contract names. Display them as "high readiness"
   and "outside forecast range".
10. **Technical detail belongs in a tooltip or footnote**, not the primary
    label.

## Deliberate exceptions

- **"Demand charge"** — the utility billing term, not a synonym for load.
- **"Energy-demand forecasting"** — the project title and thesis scope.
- **"MAPE", "RMSE", "MAE", "SHAP", "XGBoost"** — analyst vocabulary, glossed in
  the panel rather than renamed.
- **`readiness_code`, `hybrid_kw`, `surge_sites`, `surge_hours`,
  `variance_hours`** — API/data names. The UI derives display words from the
  code so old CSV labels cannot leak into the screen.
