# AMAKA — 5-minute live demo script (v2 / H24 default)

**Before the panel arrives**

```powershell
cd "C:\Users\TMB COMPUTERS\Documents\school\4th year\final year project\prototype"
.\run.ps1
```

Open `http://127.0.0.1:8000` in Chrome or Edge. The role gate is the first screen.
Second tab: `http://127.0.0.1:8000/docs` for API questions.

If anything fails: `.\run.ps1 -Dev` and use `http://127.0.0.1:5173`. The WebGPU
background falls back to Canvas2D; the dashboard works without it.

---

## 0:00 — Frame the problem (30 sec)

> "Military facilities have volatile, activity-driven loads. Without foresight, managers
> pay maximum-demand charges, keep too much diesel spinning, and react to peaks instead of
> planning for them. AMAKA forecasts demand at four direct horizons and turns it into a
> decision surface for three roles."

Point at **UNCLASSIFIED // SYNTHETIC DEMO DATA**.
> "All facility load is synthetic; weather is real Open-Meteo. No classified data."

---

## 0:30 — Role gate (30 sec)

Three cards:

- **Commander — Strategic view.** Fleet status, peak risk, cost exposure.
- **Energy Manager — Operations view.** Load trace, next 24 h peak, dispatch, alerts.
- **Analyst — Analysis view.** SHAP, model comparison, data quality, exports.

Press **COMMANDER → OPEN FLEET**.

> "Purpose first. One dashboard cannot serve a commander, an energy manager and an analyst
> without becoming a chart dump."

**5-second test** after the map loads:
> "What is the main message, and what would you do next?"
Intended answer: **"Four sites are at risk; I'd open Peter Zuze."**

---

## 1:00 — Fleet map, H24 (45 sec)

The map opens at **09 Sep 2025 · 18:00 CAT**, default horizon **H24** (24-hour direct
forecast).

- **Mikango** — critical, R1 exercise surge, 2,122 kW forecast.
- **Peter Zuze** — critical, R2 high readiness, 4,202 kW forecast.
- **Arakan** and **Tug Argan** — warning, approaching threshold.
- **Kohima / Makeni** — nominal.
- Bottom strip: **6 sites · 14.5 MW · 4 at risk · 2 high readiness · ZMW 373k/month saving**.

> "This is a Z-pattern: fleet status top-left, map centre, action bottom-right. The map is
> the overview. The H24 chip is the forecast horizon — not the chart window."

Gestalt notes:
- **Proximity:** horizon + time + role controls sit with the map.
- **Similarity:** red critical, amber warning, lime nominal everywhere.
- **Figure/ground:** the map is the figure; the hex field stays at the edges.

Click **Peter Zuze** (or `OPEN SITE →`). The map zooms; the hex iris opens the console.

---

## 1:45 — Site console, H24 (60 sec)

KPIs:

- **Actual load** — 4,521 kW.
- **Peak · next 24 h** — forecast peak vs the 3,500 kW site threshold; headroom negative.
- **Forecast error** — **2.54% MAPE**, 97.8 kW RMSE, 70.7 kW MAE at **H24**.
- **Est. saving / mo** — **ZMW 94.6k**.

> "F-pattern: the top row is the decision numbers; the left column is the site roster and
> facility profile; the chart is the hero; the right rail is alerts."

Press **RUN REPLAY**.
> "White is actual, lime is the H24 forecast, the band is 95%, amber is the peak threshold.
> The cursor, readiness strip and SHAP panel move together — one time gate."

Pause replay. Point at **CHART EXPLANATION** directly under the trace.

> "This is a grounded explanation layer, not a chatbot over the CSV. Python computes the
> fact pack from this exact window; the model only turns it into prose. Every number in
> the answer is checked against the fact pack, and if the model is offline or invents a
> value the rule-based text stays. The demo never depends on the network."

Ask the box: **"How accurate was the forecast?"** The answer names MAPE, MAE, bias and
the largest miss from this window, not from the whole test period.

> "The chip says LLM or RULES, so the reader always knows which generated the sentence."

Commander sees **no SHAP or model table** — progressive disclosure for the strategic role.

---

## 2:30 — Multi-horizon story (60 sec)

Switch to **H1** using the horizon buttons.

- Forecast error drops to **1.95% MAPE**, RMSE 71.1, selected residual **HGB**.
- The same site, same hour, one hour ahead instead of 24.

Switch to **H48**.

- Forecast error rises to **2.82% MAPE**, RMSE 107.0, selected model **XGB**.
- The point: the interface shows the horizon cost honestly; 48 hours ahead is harder.

Switch back to **H24**.

> "This is the v2 contribution: four direct models per site, not one model rolled forward.
> Each horizon has its own XGBoost Stage 1 and its own residual learner. The H24 and H48
> models see a weather-forecast proxy, never the archived future weather."

Point at the model table:
- XGB vs Hybrid (HGB or LSTM selected on validation), persistence and seasonal naive.
- At Peter H24, hybrid MAE is 69.9 vs persistence 236.4 — roughly 3.4× better.
- If a residual learner does not beat XGB by the validation margin, the system selects
  XGB; the table says so. We do not force HGB or LSTM everywhere.

---

## 3:30 — Energy Manager (45 sec)

Switch role to **ENERGY MANAGER**.

- Accent becomes teal; the **DISPATCH** card appears.
- Forecast 4,202 kW vs 3,500 kW threshold → **pre-start 1,000 kW generator**.
- Weather, alerts and the load trace stay.
- Model table is hidden.

> "Same data, different decision: the operator needs the next peak, headroom and a dispatch
> action, not a model comparison."

Press **RUN REPLAY**; show the alert feed and readiness strip.

---

## 4:15 — Analyst + reports (45 sec)

Switch to **ANALYST**.

- SHAP drivers for the H24 target hour: readiness, load history, temperature, calendar.
- Model performance: XGB, hybrid selected learner, persistence, seasonal naive,
  standalone LSTM.
- Data quality and exports.

Click **EXPORT PDF**; open `amaka_peter_zuze_h24_report.pdf`.

> "One page for management: site, horizon, KPIs, actual-vs-forecast chart, alert counts,
> savings, and the tariff/fuel assumptions. CSV is the analyst's copy."

Click **← FLEET** to return to the map.

Close:
> "Sprint 3 delivers the FastAPI service and the TypeScript visual analytics over the v2
> multi-horizon model. The map is strategic, the console operational, SHAP analytical.
> Next: real meter data, production inference and the full cost-benefit sensitivity."

---

## Likely questions

**Is the data real?**
Facility load is synthetic v2 (grid faults, generator backup, maintenance, holidays);
weather is real Open-Meteo. This is a simulation study, not validation on real Zambian
defence loads.

**What changed from v1?**
V1 was a single 1-hour-ahead model. V2 trains **direct 1/6/24/48-hour** models, uses
target-time weather forecast proxies, out-of-fold Stage-2 residuals, and selects HGB vs
LSTM on validation. The dashboard defaults to H24 and lets you switch horizons live.

**Why is the hybrid sometimes no better than XGBoost?**
At some site/horizons the residual signal is weak, so validation selection falls back to
XGBoost. The dashboard names the selected learner rather than pretending the hybrid always
wins. Kohima H1 is a clear gain (RMSE 88.8 → 74.4); Peter H1 is essentially flat.

**How is leakage prevented?**
Targets are shifted to the target hour; models only see load history through the origin,
target-time calendar/readiness schedules and a weather **forecast-error proxy**. Training
is 2024, alpha/selection use 2025 H1, and the test period 2025 H2 is untouched.

**Why a map?**
The fleet is geographically distributed. The map is Level 1 of progressive disclosure;
clicking a site opens Level 2; SHAP/model detail is Level 3.

**What about colour-blind users?**
Status is colour + 2px bar + a critical/warning/nominal word; readiness is colour +
`R1–R4` text + the timeline. Lime vs amber is never the only cue.

**What did you take from ICD322?**
Purpose first (strategic, operations and analysis views); Z-pattern map, F-pattern console;
progressive disclosure; Nielsen heuristics; Gestalt grouping (proximity, similarity,
figure/ground, common fate); and the 7 deadly sins audit. See
`docs/DASHBOARD_PRINCIPLES.md`.

**Does the WebGPU background matter?**
Presentation only. It is masked to the gutters/header, falls back to Canvas2D, and never
touches the forecast path.

**Is the explanation model inventing numbers?**
No. The backend builds a fact pack with pandas, sends only that pack to the model, and
then checks every number in the returned prose against it. A number outside the pack
(for example a hallucinated 99,999 kW) fails the check and the rule-based narrative is
shown instead. The same fallback covers an expired key, no network, or a local model that
is not running. See `docs/AI_NARRATIVE.md` and `tests/smoke_narrate.py`.
