# AMAKA — Dashboard Design Justification (ICD322 Unit 10)

This document maps the AMAKA prototype onto the Unit 3 and Unit 10 principles:
Gestalt grouping, dashboard purpose, F/Z layout, progressive disclosure,
Nielsen's heuristics, the 5-second test and the seven deadly sins. It is the design
rationale to cite in the capstone report.

## 1. Purpose: three roles, three dashboard types

AMAKA is not one dashboard. The same data serves three users with different
decisions. The role gate exists because a dashboard that tries to serve all three
becomes a chart dump.

| Role | Purpose | Primary user | Time horizon | Default view | Chart budget |
|---|---|---|---|---|---|
| **Commander** | **Strategic** | Facility commander / executive | Weekly–monthly, plus current risk | Fleet map + readiness + cost | 3–4 |
| **Energy Manager** | **Operational** | Facility energy manager / watch officer | Hourly, next 24 h | Site console + live trace + alerts | 4–5 |
| **Analyst** | **Analytical** | Data analyst / model engineer | Historical / model evaluation | Site console + SHAP + model table | 5–7 |

**5-second test (the one thing each role must know):**

- Commander: `4 SITES AT PEAK RISK · PETER ZUZE 4,202 kW · ZMW 373k/MO SAVING`
- Energy Manager: `PETER ZUZE 4,202 kW · 702 kW OVER THRESHOLD · PRE-START 1,000 kW`
- Analyst: `H24 MAPE 2.54% · PETER ZUZE · 4,189 TEST HOURS`

Every role's first screen carries its version of this line in the **narrative strip**
directly under the header, in 14–16px text, not in a tooltip.

## 2. Layout: Z for the fleet, F for the console

### Fleet map — Z-pattern (visual-heavy, strategic)

```
top-left: AMAKA + FLEET COMMAND     top-right: role + replay time
        ╲                                        ╱
         ╲            ZAMBIA MAP                ╱
          ╲                                    ╱
bottom-left: fleet totals/legend     bottom-right: site roster + ENTER SITE
```

- Top-left is the fleet status headline, not the logo (the logo is in the header).
- Top-right is the role switcher and the replay cursor time.
- The diagonal is the map: site nodes and the Lusaka–Ndola corridor.
- Bottom-left is the fleet total/risk legend; bottom-right is the site roster and the
  primary action (`OPEN CONSOLE`). This is where the eye ends and where the click lives.

### Site console — F-pattern (data-dense, analytical/operational)

```
top row:    ACTUAL LOAD | PEAK 24H | FORECAST ERROR | SAVING/MO
left rail:  site roster + facility profile (navigation and category labels)
main:       LOAD TRACE (hero) with shared time gate
right:      ACTIVE ALERTS + DISPATCH (operator) / READINESS (commander)
below:      SHAP drivers (analyst/operator) + model table (analyst)
```

- Top row is the KPI strip. Left column is navigation and site context.
- The main chart is the first content block the eye reaches after the KPIs.
- The right rail is alerts; it is not equal-weight with the chart.
- SHAP and model detail sit below the fold — progressive disclosure, not the first screen.

**Prime real estate rule:** the top-left content cell of the console is `ACTUAL LOAD`
(site name immediately above it). Filters, role controls and export buttons live top-right.

## 3. Progressive disclosure: three levels

| Level | Content | Interaction |
|---|---|---|
| **1 — Overview** | Fleet map, role headline, fleet totals, risk count, site nodes | Visible by default |
| **2 — Details on demand** | Site console: load trace, peak alerts, dispatch/readiness, weather, shared time gate | One click on a site |
| **3 — Raw / analytical** | SHAP drivers, model performance, data quality, CSV/PDF export, API docs | One scroll or `ANALYSIS` tab |

Rules:
- No more than **two clicks** to any data. Map → site → SHAP section.
- A persistent `← FLEET` control returns to Level 1 from every console state.
- A visible affordance on each site card (`OPEN CONSOLE →`) and on the map
  (`SELECT A SITE TO OPEN ITS CONSOLE`), so users do not have to guess that nodes click.
- Filters and range controls show their current value; no hidden state.
- CSV/PDF exports are Level 3 and live behind `EXPORT` buttons, not on the first screen.

## 4. Nielsen's 10 heuristics — AMAKA checklist

| # | Heuristic | How AMAKA satisfies it |
|---|---|---|
| 1 | Visibility of system status | Persistent replay cursor date/time in the header; `H2 2025 REPLAY`; API status dot + `API NOMINAL/OFFLINE`; role badge; current range tab; loading line on site change. |
| 2 | Match with real world | `ACTUAL LOAD`, `PEAK`, `HEADROOM`, `READINESS`, `DISPATCH`, `SURGE`; Zambia geography and real site names; kW and ZMW, not abstract scores. |
| 3 | User control and freedom | `← FLEET` back; pause/play; scrubber; range tabs; role switcher; `RESET VIEW`; no destructive actions. |
| 4 | Consistency and standards | Every site node opens a console; every chart hover shows a tooltip; every export is a download; same colors mean the same thing in every role (lime = model, amber = caution, red = breach). |
| 5 | Error prevention | Dates clamped; invalid ranges rejected with a clear message; role switch preserves context; no destructive actions; scrubber constrained to the visible window. |
| 6 | Recognition rather than recall | Persistent KPI labels and units; legends on chart, readiness strip and SHAP; site names on map cards; no hover-only values for the demo's key numbers. |
| 7 | Flexibility and efficiency | Keyboard: `Space` play/pause, `←/→` step, `F` fleet, `1/2/3` roles, `Esc` close; range tabs; persistent readout; cached series for instant site switches. |
| 8 | Aesthetic and minimalist design | Role-specific chart budget; one hero chart; no gauges, donuts, sparkline cards or 3D; grid 4 lines; no decorative icons; one accent per semantic role. |
| 9 | Error recovery | `FLEET DATA UNREACHABLE · RETRY`; `ATTRIBUTION UNAVAILABLE · SCRUB TO ANOTHER HOUR`; `NO ACTIVE ALERTS` with explanation; no raw 500 text. |
| 10 | Help and documentation | `?` opens a "How to read this console" panel; chart and SHAP info tooltips; README + `/docs` API; demo script. |

## 5. The seven deadly sins — audit

| Sin | AMAKA response |
|---|---|
| 1. Chart dump | Commander sees 3–4 views; operator 4–5; analyst 5–7. SHAP/model hidden from Commander. One hero chart. |
| 2. Missing context | Every KPI has a comparison: forecast vs actual, peak vs threshold, saving vs baseline bill, MAPE vs target. |
| 3. No narrative | The narrative strip states the current risk and recommended action in one sentence; section titles are takeaways, not labels (`PEAK RISK CONCENTRATED AT KOHIMA`, not `Chart 3`). |
| 4. Inconsistent interaction | One rule: click a site = open console; click a range = change chart; hover = tooltip; export = download. Documented in the help panel. |
| 5. Poor performance | Precomputed replay + SHAP, cached series, <300ms API, no chart animation, max 720 points plotted, readiness runs merged. |
| 6. Mobile-unfriendly | Rail becomes a horizontal roster; KPIs 2×2; map cards collapse to a list; 44px touch targets; no horizontal scroll. |
| 7. No user testing | Plan: 5-second test + think-aloud with 3 classmates; record confusion points; iterate. The demo script includes a 5-second prompt. |

## 6. Interaction standards

| Action | Result | Everywhere |
|---|---|---|
| Click site node / card | Zoom map, open site console | Map, roster |
| Click `← FLEET` | Zoom out, return to map | Console header |
| Click range tab | Change visible window, keep cursor at same relative position | Console chart |
| Drag scrubber | Pause replay, move cursor, update all panels | Console |
| `Space` | Play/pause replay | Console |
| `←/→` | Step one hour | Console |
| `1/2/3` | Switch role | Global |
| `F` | Toggle fleet/console | Global |
| `Esc` | Close help / role menu | Global |
| Hover chart | Tooltip with actual, hybrid, band, readiness | Console |
| Click `EXPORT` | Download CSV/PDF for the visible range | Console |

**Time gate:** one cursor and one `HH:MM` pill across the chart, readiness strip and SHAP
panel. It is the single interaction the demo is built around.

## 7. Role-specific content

### Commander (Strategic)
- Fleet map with risk nodes and readiness.
- Narrative: sites at risk, surge sites, total load, saving/month.
- Panels: `FLEET READINESS`, `RISK SITES` (top 3), `COST EXPOSURE`, `ALERTS SUMMARY`.
- Site console: KPIs, load trace, alerts, cost. **No SHAP, no model table.**
- Primary action: `OPEN SITE CONSOLE` / `EXPORT PDF`.

### Energy Manager (Operational)
- Fleet map + site console.
- Narrative: next peak, headroom, recommended dispatch.
- Panels: `LOAD TRACE`, `ACTIVE ALERTS`, `DISPATCH BOARD`, `WEATHER`, `TOP DRIVER` (one
  SHAP line, not the full panel).
- Site console: full operational view. **No model-performance table.**
- Primary action: `RUN REPLAY` / `EXPORT CSV`.

### Analyst (Analytical)
- Fleet map + site console with analysis below.
- Narrative: fleet MAPE, worst site, test hours.
- Panels: `LOAD TRACE`, `SHAP DRIVERS`, `MODEL PERFORMANCE`, `DATA QUALITY`, `EXPORT`.
- Site console: full analytical view. **No dispatch recommendation.**
- Primary action: `EXPORT CSV` / `VIEW API`.

## 8. 5-second test script

Show the role screen for five seconds, hide it, ask:

1. "What is the main message?"
2. "What would you do next?"
3. "Where would you click?"

Success criteria:
- Commander: "Four sites are at peak risk; I'd open Peter Zuze."
- Energy Manager: "Peter Zuze is over threshold; I'd pre-start the generator."
- Analyst: "H24 MAPE is 2.54%; I'd inspect Peter Zuze."

If any role cannot answer, fix the narrative strip and top-left hierarchy before adding
more charts.

## 9. What changes in the build

1. Add the **narrative strip** under the header for every role.
2. Add explicit purpose labels: `STRATEGIC`, `OPERATIONAL`, `ANALYTICAL` next to the role.
3. Build the **fleet map** as Level 1 (Z-pattern) with `ENTER SITE →` affordances.
4. Keep the **console** as Level 2 (F-pattern) with `← FLEET`.
5. Hide role-inappropriate panels; enforce the chart budget.
6. Add `?` help panel and keyboard shortcuts.
7. Add comparison lines to every KPI.
8. Add a 5-second test to the demo script and record the result.

## 10. Gestalt grouping (Unit 3)

The six principles are applied deliberately, not left to chance.

| Principle | AMAKA application | Violation avoided |
|---|---|---|
| **Proximity** | Role/time controls sit with the fleet map; the site roster sits beside the map; range tabs and legend sit in the chart header; export buttons sit with the chart; SHAP sits directly below the chart. White space separates the fleet view, console and analysis view. | Scattered filters and controls; export buttons floating in the header. |
| **Similarity** | One status colour everywhere: red = critical, amber = warning, lime = nominal/model. The same readiness scale R1–R4 on the map, strip, tooltip and table. Same site name and load formatting in every panel. Role accents are chrome only (header rule, role badge, active nav) and never used for data marks. | Same site shown in different colours across map, chart and table; role colour competing with severity colour. |
| **Closure** | One board with thin internal dividers and open KPI cells; the map outline is a single continuous path; readiness strip uses segments without a heavy box. The brain completes the grouping from alignment and spacing. | A box around every cell, heavy borders, dashboard "cards inside cards". |
| **Continuity** | Identical time axis and tick format across ranges; the shared time gate is one continuous vertical path through chart, readiness strip and SHAP; fleet table uses one MAPE scale; no broken axes. | Different y-axis scales across small multiples; a cursor that stops at the chart edge. |
| **Figure/Ground** | Data is the figure: 2px actual line, 1.75px hybrid, solid `#080c0a` plot area. Grid lines are `rgba(255,255,255,0.05)`, horizontal only. The WebGPU hex field is masked behind panels and never behind the plot. Non-data chrome stays low-contrast. | Hex grid or dark grid lines competing with the data; gradient fills behind the chart. |
| **Common Fate** | Replay advances the cursor, KPI values, readiness strip, SHAP panel and alert feed in the same tick. Role switching updates the whole dashboard at once. Nothing animates independently of the time gate. | A pulsing map while the chart is static; panels updating at different rates. |

**The squint test:** at arm's length, the first things visible must be the actual/hybrid
lines, the KPI numbers and the status colours — not the hex field, grid lines, or panel
borders.

## 11. Reference

Mulungushi University, *ICD322: Data Visualization and Analytics*:
Unit 3, "Gestalt Principles of Visual Grouping"; Unit 10, "Principles of Dashboard
Design" (lecture notes, 2026). Principles adapted from Stephen Few,
*Information Dashboard Design*, and Jakob Nielsen's 10 usability heuristics.
