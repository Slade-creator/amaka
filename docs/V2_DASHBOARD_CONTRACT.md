# V2 Dashboard Integration Contract

The dashboard is switching from the v1 replay to the **v2 research pipeline**. V2 is a
direct multi-horizon model (1, 6, 24, 48 hours ahead) with XGBoost Stage 1 and a
validation-selected residual learner (HGB or LSTM). The v1 pipeline remains frozen; v2
writes to `data/v2/` and `config/v2_sites.json`.

## Generated artifacts (do not edit)

`src/build_v2_replay.py` writes:

- `data/v2/replay_<site>_h<h>.csv` for `h ∈ {1,6,24,48}`
- `data/v2/shap_<site>_h<h>.npz`
- `config/v2_sites.json`

### Replay CSV columns

`timestamp, actual_kw, xgb_kw, hybrid_kw, lower_kw, upper_kw, selected_model,
readiness_code, readiness_label, temperature_c, humidity_pct, radiation_wm2,
cloud_cover_pct, is_holiday, is_weekend`

`timestamp` is the **target** hour (the hour being forecast), so actual and forecast are
compared at the same time. Rows cover the held-out test period 2025-07-01..2025-12-31
(~4,340 rows per site/horizon).

### SHAP NPZ

`values` (N×22 float32), `feature_values` (N×22), `bias` (N), `features` (22 strings),
`timestamps` (N int64 ns). Features are v2's 22 model inputs (`FEATURE_COLS` in
`src/v2_horizons.py`).

### `config/v2_sites.json` shape

```json
{
  "version": "v2",
  "default_horizon": 24,
  "available_horizons": [1, 6, 24, 48],
  "test_period": {"start": "...", "end": "..."},
  "fleet_anchor": "2025-09-08T18:00:00",
  "fleet_anchor_by_horizon": {"1": "...", "6": "...", "24": "...", "48": "..."},
  "model": {
    "name": "Hybrid XGBoost + validation-selected residual learner",
    "stage1": "XGBoost direct multi-horizon regressor",
    "stage2": "Residual HGB or LSTM, selected on Apr-Jun 2025 validation",
    "horizon": "Direct 1 / 6 / 24 / 48 hours ahead",
    "features": 22
  },
  "cost_assumptions": { "...": 0 },
  "sites": [
    {
      "id": "arakan", "label": "...", "location": "...", "type": "...",
      "base_load_kw": 1700, "pv_kwp": 400, "headcount": 2000, "floor_area_m2": 15000,
      "lat": -15.435, "lon": 28.321, "horizon": 1, "selected_model": "hgb",
      "test_start": "...", "test_end": "...", "rows": 4340,
      "demo_anchor": "...", "demo_start": "...",
      "metrics": { "xgb_rmse": 0, "xgb_mae": 0, "hyb_rmse": 0, "hyb_mae": 0,
                   "hyb_mape": 0, "band_kw": 0, "selected_model": "hgb",
                   "persistence_mae": 0, "seasonal_naive_24_mae": 0,
                   "seasonal_naive_168_mae": 0, "standalone_lstm_mae": 0 },
      "load": { "avg_kw": 0, "peak_kw": 0, "threshold_kw": 0,
                "latest_actual_kw": 0, "latest_hybrid_kw": 0 },
      "alerts": { "peak_hours": 0, "surge_hours": 0, "variance_hours": 0 },
      "cost": { "energy_month_kwh": 0, "baseline_monthly_zmw": 0,
                "monthly_saving_zmw": 0, "annual_saving_zmw": 0,
                "demand_saving_zmw": 0, "fuel_saving_zmw": 0, "saving_pct": 0 },
      "horizons": {
        "1": { same shape as the top-level site, plus "horizon": 1 },
        "6": { ... }, "24": { ... }, "48": { ... }
      }
    }
  ]
}
```

The top-level site fields mirror the `default_horizon`; `horizons` carries all four.

## Backend changes (backend/ only)

Default to v2. Keep the same endpoint names but add a `horizon` query parameter
(`1|6|24|48`, default `config.default_horizon` = 24). This keeps the frontend contract
simple and makes the horizon switch a query change.

| Endpoint | New behaviour |
|---|---|
| `GET /api/health` | add `version:"v2"`, `horizons:[1,6,24,48]` |
| `GET /api/overview?horizon=24` | load `config/v2_sites.json`; return the selected horizon's metrics/load/cost/alerts at the top level of each site, and keep `available_horizons`, `default_horizon`, `fleet_anchor_by_horizon`, `version` |
| `GET /api/sites/{site}/series?horizon=24&from=&to=` | load `data/v2/replay_<site>_h24.csv`, cache by `(site,horizon)`; include `selected_model` in rows |
| `GET /api/sites/{site}/explain?horizon=24&at=` | load `data/v2/shap_<site>_h24.npz`; map v2 feature labels (add `is_holiday`, `is_weekend`; remove v1-only names) |
| `GET /api/sites/{site}/narrative?horizon=24&at=&from=&to=&role=&mode=` | grounded chart explanation: `mode=fast` is deterministic rules only; `mode=auto` adds model prose with a grounding check and fallback. See `docs/AI_NARRATIVE.md`. |
| `POST /api/sites/{site}/narrative/ask` | free-text question answered from the same fact pack |
| `GET /api/sites/{site}/alerts?horizon=24&at=&hours=24` | use the horizon's replay/threshold/band |
| `GET /api/fleet?horizon=24&at=` | each site's row at the target hour from that horizon's replay; totals/status/headroom as before; include `horizon` |
| `GET /api/sites/{site}/report.csv?horizon=24&from=&to=` | CSV column set is the replay CSV; add `horizon` to the filename or content? Keep filename `amaka_<site>_h24_report.csv` |
| `GET /api/sites/{site}/report.pdf?horizon=24&from=&to=` | PDF title/period includes `H24`; KPI table uses that horizon's metrics; chart uses that horizon's replay |

Validation:
- Unknown horizon → 400 with detail.
- Missing v2 file → 404/500 with a clear message (do not silently fall back to v1).
- Dates clamp as before.
- `/api/overview?horizon=1` and `?horizon=48` must return 6 sites, correct metrics and
  `fleet_anchor` for that horizon (or top-level `fleet_anchor_by_horizon`).
- Keep `/docs` working; update the root JSON to mention `version v2` and `horizon`.
- Update `tests/smoke_api.py` to test h=1 and h=48, including fleet and a PDF.

## Frontend changes (frontend/src/ only)

Do not touch `components/WebGPUHex.tsx`, `components/SceneWipe.tsx`, or `styles.css`
token section without need. The main agent owns those.

1. **Types** (`types.ts`): add `version`, `default_horizon`, `available_horizons`,
   `fleet_anchor_by_horizon`; `Site` add `horizon`, `selected_model`, `horizons`.
2. **API** (`api.ts`): every site/fleet/explain/report call takes `horizon` and appends
   `&horizon=`; `fetchOverview(signal, horizon)`; cache key `${site}|${horizon}` for
   series prefetch.
3. **App state**: `horizon` initialized from `overview.default_horizon` (24).
   On horizon change:
   - update state,
   - fetch `/api/overview?horizon=<h>` (or use nested `site.horizons` to swap metrics),
   - fetch the active site's series for the new horizon (keep the cursor timestamp if it
     exists; otherwise use that horizon's `demo_anchor`),
   - prefetch other sites in the background for the new horizon,
   - keep map/console state; role unchanged.
4. **Horizon selector**: a new `components/HorizonSwitcher.tsx` with four buttons
   `1H 6H 24H 48H`, 10px mono, active accent. Place it:
   - console: in `SiteHeader` next to `H2 2025 REPLAY`;
   - fleet: in the top bar next to the replay time / role switcher, or in the narrative
     strip. It must be visible without scrolling.
   - Use `aria-pressed`; no dropdown.
5. **Labels**:
   - Chart sub: `ACTUAL vs H24 FORECAST` (not just "HYBRID FORECAST").
   - KPI "Forecast error" context: `H24 · hybrid`; add `H24` to model table title.
   - Fleet narrative/map title: `FLEET · H24 HORIZON`; `OPEN SITE`.
   - `ModelPerf` rows: XGBoost, Hybrid (selected residual model), Persistence,
     Seasonal-naive 24h, Seasonal-naive 168h, standalone LSTM if present. The hybrid row
     label should name the selected learner: `Hybrid · HGB` or `Hybrid · LSTM`.
   - `ExplainPanel` title: `WHY THIS H24 FORECAST?`
6. **Reports**: pass `horizon` to CSV/PDF URLs.
7. **Map**: `FleetView` takes `horizon` and passes it to `fetchFleet`; show `H24` in the
   map title and site cards (`H24 FCST`). The status colours remain based on hybrid vs
   threshold.
8. **Replay**: the series `timestamp` is the target hour. The chart now shows actual vs
   direct-horizon forecast at the same timestamp. Do not add the horizon to the x-axis;
   the label is enough.
9. **Compatibility**: if `/api/overview` has no `version`, fall back to current v1
   behaviour (this is only a safety net; v2 is the default).
10. **Build/verify**: `npx tsc --noEmit`, `npm run build`, and a live browser pass at
    1920×1080 and 1366×768:
    - gate → map → site console,
    - switch horizon 1/6/24/48 and confirm the chart, KPIs, narrative, SHAP, model table
      and fleet card values update,
    - export CSV/PDF for h=24,
    - no console errors, no horizontal overflow, no map card overlap.

## Acceptance numbers (for sanity; from config/v2/metrics_horizons_combined.csv)

- Arakan h=1 hybrid RMSE 50.2 / MAE 35.9 / MAPE 2.01%.
- Arakan h=24 hybrid RMSE 76.8 / MAE 50.6 / MAPE 2.77%.
- Arakan h=48 hybrid RMSE 85.2 / MAE 54.4 / MAPE 2.97%.
- Persistence and seasonal-naive must be clearly worse.
- The selected model per site/horizon comes from the run JSON; h=1 and h=24 are HGB for
  Arakan; Mikango/Tug h=24 select LSTM; some horizons select XGB. Do not hardcode HGB
  globally.

## Ownership

- Backend agent: `backend/` + `tests/smoke_api.py` only.
- Frontend agent: `frontend/src/` only (except the two files above).
- Main agent: data build, docs, final integration and verification.
