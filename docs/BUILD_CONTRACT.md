# AMAKA Prototype — Build Contract

This file is the single source of truth for the 8-hour prototype build. Read it fully
before writing code. Do not modify files outside your assigned ownership.

## Product

AMAKA is an AI energy-demand forecasting and visual-analytics command dashboard for
six Zambian military facilities. It is a final-year capstone prototype. The demo is live
in front of a supervisor, so reliability, speed and a convincing "operations room" feel
matter more than exhaustive features.

- Backend: FastAPI, Python 3.14, pandas/numpy, reportlab. Data is precomputed; no model
  inference at request time except TreeSHAP (cheap, from a saved `.npz`).
- Frontend: React 19 + TypeScript + Vite + Tailwind CSS v4 + Recharts + lucide-react.
- Data period: 2025-07-01 .. 2025-12-31 (held-out test set). A "live replay" simulates
  telemetry by advancing a cursor through this period.
- All data is synthetic / demo. Show `UNCLASSIFIED // SYNTHETIC DEMO DATA` in the header.

## Files already generated (do not edit)

- `data/processed/replay_<site>.csv` — one row per hour. Columns:
  `timestamp, actual_kw, xgb_kw, hybrid_kw, lower_kw, upper_kw, readiness_code,
  readiness_label, temperature_c, humidity_pct, radiation_wm2, cloud_cover_pct`
- `data/processed/shap_<site>.npz` — arrays: `values` (N×23 float32 SHAP),
  `feature_values` (N×23 float32), `bias` (N,), `features` (23 strings),
  `timestamps` (N int64 nanoseconds)
- `config/sites.json` — overview payload (see below)
- Sites: `arakan, kohima, makeni, mikango, peter_zuze, tug_argan`

`config/sites.json` shape:

```json
{
  "generated_at": "ISO-8601",
  "test_period": {"start": "2025-07-01", "end": "2025-12-31T23:00:00"},
  "model": {
    "name": "Hybrid XGBoost + Residual LSTM",
    "stage1": "XGBoost Regressor (300 trees, depth 6)",
    "stage2": "2-layer LSTM, 32 hidden, 168h lookback",
    "horizon": "1 hour ahead (operational replay)",
    "features": 23
  },
  "cost_assumptions": { "...": 0 },
  "sites": [
    {
      "id": "arakan", "label": "Arakan Barracks", "location": "Lusaka",
      "type": "Admin + residential barracks", "base_load_kw": 1800,
      "pv_kwp": 400, "headcount": 2000, "floor_area_m2": 15000,
      "lat": -15.435, "lon": 28.321,
      "test_start": "...", "test_end": "...", "rows": 4416,
      "demo_anchor": "ISO local time", "demo_start": "ISO local time",
      "metrics": {
        "xgb_rmse": 87.7, "xgb_mae": 52.4, "hyb_rmse": 87.7, "hyb_mae": 52.3,
        "hyb_mape": 2.78, "persistence_mae": 134.0, "seasonal_naive_mae": 150.0,
        "band_kw": 210.0
      },
      "load": {
        "avg_kw": 2100.0, "peak_kw": 2800.0, "threshold_kw": 2750.0,
        "latest_actual_kw": 2400.0, "latest_hybrid_kw": 2390.0
      },
      "alerts": {"peak_hours": 34, "surge_hours": 120, "variance_hours": 80},
      "cost": {
        "energy_month_kwh": 1533000, "baseline_monthly_zmw": 3050000,
        "monthly_saving_zmw": 51000, "annual_saving_zmw": 612000,
        "demand_saving_zmw": 18000, "fuel_saving_zmw": 33000, "saving_pct": 1.67
      }
    }
  ]
}
```

## API contract (backend owns)

Base: `http://127.0.0.1:8000`. All responses JSON unless noted. Dates are ISO strings
without timezone (local Africa/Lusaka time) to match the CSVs.

| Method | Path | Response |
|---|---|---|
| GET | `/api/health` | `{status:"ok", sites:6, generated_at}` |
| GET | `/api/overview` | full `config/sites.json` payload + `served_at` |
| GET | `/api/sites/{site}/series?from=&to=` | `{site, rows:[ReplayRow...]}`; default full test period; `from`/`to` inclusive ISO |
| GET | `/api/sites/{site}/explain?at=` | `{site, at, base_kw, top:[ShapRow...], all:[ShapRow...]}` |
| GET | `/api/sites/{site}/alerts?at=&hours=24` | `{site, at, alerts:[Alert...]}` |
| GET | `/api/sites/{site}/report.csv?from=&to=` | CSV download, filename `amaka_<site>_report.csv` |
| GET | `/api/sites/{site}/report.pdf?from=&to=` | PDF download, filename `amaka_<site>_report.pdf` |

Types:

```ts
type ReplayRow = {
  timestamp: string; actual_kw: number; xgb_kw: number; hybrid_kw: number;
  lower_kw: number; upper_kw: number; readiness_code: 1|2|3|4;
  readiness_label: string; temperature_c: number; humidity_pct: number;
  radiation_wm2: number; cloud_cover_pct: number;
};
type ShapRow = { feature: string; label: string; value: number; contribution_kw: number; direction: "up"|"down" };
type Alert = { id: string; severity: "critical"|"warning"|"info"; kind: "peak"|"surge"|"variance"|"readiness"|"model"; title: string; detail: string; timestamp: string };
```

- `explain` computes TreeSHAP from the `.npz` row matching `at` (nearest hour). `top` is
  the 10 largest absolute contributions. `label` is a human label: map feature names
  (e.g. `load_lag_1h` → "Load · 1h lag", `temperature_2m` → "Temperature",
  `readiness_code` → "Readiness code", `shortwave_radiation` → "Solar radiation",
  `hour_sin` → "Hour of day", etc.). `base_kw` is the XGBoost bias value.
- `alerts` evaluates the window ending at `at` (default latest) over the prior `hours`:
  - `peak` critical when `hybrid_kw > threshold_kw`; warning when within 3% of it.
    Detail includes predicted kW and threshold.
  - `surge` info/warning when `readiness_code <= 2`; title from readiness_label.
  - `variance` warning when `abs(actual_kw - hybrid_kw) > band_kw`.
  - Return at most 8, newest first, de-duplicated by kind over the window.
- CSV: the replay columns for the selected range + a `model` column? Keep it simple:
  selected rows as-is.
- PDF: one-page executive report with AMAKA header, classification strip, site
  metadata, KPI table (`MAPE`, `RMSE`, `MAE`, peak, average, threshold), a line chart of
  actual vs hybrid for the selected period, alert counts, cost estimate, assumptions
  footer, generated timestamp. Use reportlab platypus; matplotlib is available if useful.
  Must return a valid PDF even if the chart fails.
- Serve `frontend/dist` at `/` when it exists (StaticFiles html=True) so the demo runs
  from one URL. API routes must take precedence. Add SPA fallback for unknown non-API
  paths if practical.
- CORS: allow `http://localhost:5173`, `http://127.0.0.1:5173`.
- Lazy-load per-site CSV/NPZ; cache. Handle unknown site with 404 JSON.
- No database, no auth. Keep startup under 2 seconds.

## Frontend design contract

### Look

A defense operations room, not a generic SaaS dashboard. Near-black green-tinted
background (`#070a09`), thin technical borders, monospaced numerals, restrained lime
signal accent (`#b7f34a`), amber warnings (`#ffb020`), red critical (`#ff5d5d`).
No purple gradients, no glassmorphism overload, no rounded-everything. Corners 2–6px.
Dense but breathable. Labels uppercase, 10–11px, letter-spacing 0.12–0.16em.

Fonts: `Space Grotesk` for UI, `JetBrains Mono` for numbers/labels. Both loaded in
`index.html`; include `ui-sans-serif`/`ui-monospace` fallbacks.

Use CSS variables for tokens. Tailwind v4 is installed; `src/styles.css` should start
with `@import "tailwindcss";` and define tokens in `@theme` / `:root`. Custom utility
classes are fine for repeated technical details (`.panel`, `.label`, `.num`).

### Layout

- Fixed top header 56px: hexagon mark + `AMAKA` / `ENERGY COMMAND`; centered chip
  `UNCLASSIFIED // SYNTHETIC DEMO DATA`; right: UTC clock (ticking), backend status dot,
  `v0.1 PROTOTYPE`.
- Left rail 236px (desktop), fixed under header: nav (`OVERVIEW`, `FORECAST`,
  `EXPLAINABILITY`, `FLEET`), then site list grouped by region (Lusaka / Ndola). Each
  site row: status dot, name, location, current load in kW. Active row has lime left
  border and subtle tint. Footer of rail: model info + link/status.
- Main content: max-width 1560px, padding 24px.
- Responsive: under 1100px rail becomes a horizontal site selector; KPI grid 2×2;
  under 720px single column.

### Sections (single scrolling page, nav scrolls to anchors)

1. **Site header**: breadcrumb `FACILITY / <REGION> / <SITE>`, H1 site name, type +
   coordinates; right: `REPLAY 2025-H2` chip, `Export CSV` and `Export PDF` buttons.
2. **KPI row (4 cards)**:
   - `CURRENT LOAD` — actual kW at cursor, delta vs hybrid forecast.
   - `PROJECTED PEAK · 24H` — max hybrid in next 24 rows, delta vs threshold, amber
     if above 97% of threshold.
   - `FORECAST ACCURACY` — MAPE, plus RMSE/MAE small.
   - `EST. MONTHLY SAVING` — ZMW value, `% of baseline bill`, annual figure small.
   Each card has a top hairline, label, big mono number, unit, and a small contextual
   line. No icons unless they add meaning.
3. **Load trace panel** (hero, full width, ~420px):
   - Title `LOAD TRACE` + `ACTUAL VS HYBRID FORECAST`.
   - Range tabs `24H 72H 7D 14D 30D`.
   - Legend: Actual (white line), Hybrid (lime dashed), 95% interval (lime area),
     Peak threshold (amber dashed).
   - Live replay control: `● LIVE REPLAY` / `❚❚ PAUSED`, cursor timestamp. When playing,
     advance one row every 1200ms and loop within the selected window. Pause on hover?
     No — keep it simple, but a manual scrub slider is required.
   - Recharts `ComposedChart`: area for interval, line actual, line hybrid, `ReferenceLine`
     for threshold, faint `ReferenceArea` for readiness<=2 windows, custom tooltip with
     all four values, `YAxis` domain padded, `XAxis` time labels, `CartesianGrid` very
     faint. Use `isAnimationActive={false}` for replay smoothness.
   - Below chart: readiness strip (small colored segments) + weather mini-stats for the
     cursor hour (temp, humidity, radiation, cloud).
4. **Right rail inside main** (next to chart, 300px, stacks under on small screens):
   - `ALERT FEED` with severity bars, counts, timestamps, details. At least peak,
     variance, surge examples. Empty state `ALL CLEAR`.
   - `FACILITY` facts: base load, PV, headcount, floor area, threshold.
5. **Explainability panel**: `WHY THIS FORECAST?` title; SHAP horizontal bar chart for
   the cursor hour (top 8), green positive / amber negative, `kW` labels, feature value
   annotation; selector chips for top drivers. Show base value and predicted value.
   Fetch `/explain?at=<cursor>` debounced. Cache.
6. **Model performance panel**: table comparing XGBoost vs Hybrid vs Persistence vs
   Seasonal-naive (MAE; RMSE for first two; MAPE for hybrid). Include a one-line honest
   note: "Hybrid residual stage currently delivers a marginal correction; ablation is
   part of Sprint 4." Show band width.
7. **Fleet panel**: table of all six sites with region, current load (from overview
   latest), MAPE, peak, monthly saving. Clicking a row selects that site. Highlight
   active. Maybe a small horizontal bar comparing MAPE.
8. **Footer**: data provenance, model version, generated timestamp, `Built for ICT431 ·
   Mulungushi University`.

### Interaction / reliability

- On boot, fetch `/api/overview`. Show a skeleton with the AMAKA mark and
  `ESTABLISHING UPLINK…`; fail gracefully with a retry button and clear message.
- On site change, fetch `/series`; cache per site in a `Map`. Keep previous chart visible
  with a subtle loading overlay rather than blanking.
- Initial cursor = index of `demo_anchor` (so the opening view shows a readiness surge).
  Range default `72H`; scrub slider spans the series.
- Replay starts **paused**; the presenter clicks play. Pulsing lime dot when playing.
  Ensure the clock/timestamp in the header of the chart updates.
- All numbers formatted with thousands separators; ZMW values compact (`ZMW 51k`).
- No external chart libraries beyond Recharts. No animation libraries.
- Keyboard accessible buttons, visible focus rings, aria-labels on icon buttons.
- Do not fetch SHAP on every replay tick; debounce 500ms and throttle to at most once
  per second. If replay is running, update SHAP only every 5 ticks.
- Prefer `useMemo` for sliced windows; series is 4,416 rows.

## File ownership

Backend agent: `backend/` only.
Frontend agent: `frontend/src/` except `frontend/src/components/WebGPUHex.tsx`,
`frontend/src/main.tsx` may be created, `frontend/index.html` already done.
Main agent: WebGPU component, favicon, integration, run scripts, README, tests.

Do not run `npm install` (already in progress). Do not edit `package.json` unless a
strictly necessary dependency is missing; report it instead.

## Addendum — map + roles pivot (post-review)

The product now opens with a **role gate** and a **fleet map** before the site console.

- Roles: `commander` (strategic, violet `#b9a7ff`), `operator` (operational, teal
  `#5ad1c8`), `analyst` (analytical, blue `#6fa8ff`).
- Default flow: RoleGate → FleetView (vector Zambia map, Z-pattern) → click a site →
  zoom animation → SiteConsole (F-pattern) → `← FLEET` returns.
- Shared time gate: one cursor/time pill across chart, readiness strip and SHAP.
- Fleet data: `GET /api/fleet?at=<ISO>` returns the six site snapshots and totals.
- Fleet anchor: `2025-09-08T18:00:00` (2 critical, 2 warning, 2 nominal).
- Role-specific visibility:
  - Commander: KPIs, load trace, alerts, cost, readiness; no SHAP/model table.
  - Operator: full operational console, dispatch board, one top SHAP driver; no model table.
  - Analyst: load trace, SHAP, model table, data quality, exports; no dispatch.
- Design rationale and heuristics: `docs/DASHBOARD_PRINCIPLES.md`.
- Visual direction: `docs/DESIGN_DIRECTION.md`.

## Demo acceptance

- One command starts the app; dashboard loads in <2s locally.
- Site switching, range switching, scrub, replay play/pause all work.
- Chart, KPIs, alerts, SHAP and fleet table update with the cursor.
- CSV and PDF downloads produce valid files.
- No console errors, no layout overflow at 1366×768 or 1920×1080.
- Looks credible on a projector: high contrast, large enough numbers, no tiny gray text.
