# AMAKA — Design Direction (locked)

This is the UI/UX designer's direction. Apply it to the React dashboard. It overrides the
looser layout notes in `BUILD_CONTRACT.md` where they conflict.

## 1. First screen is one instrument band

At 1920×1080, fit the command view above the fold:

```
header            56px
page padding      24px
site header       68px
gap               16px
KPI row          116px
gap               16px
hero row         448px   (chart 1312px | alert rail 300px, 24px gap)
page padding      24px
```

Total ≈ 792px, leaving ~288px of the explainability panel visible to signal scroll. Make
the hero chart and alert feed equal height; the alert feed scrolls internally (44px rows)
and must never grow the row.

At 1366×768, keep the same order but let the hero row shrink to 360px and the KPI row to
96px. Do not let the chart collapse below 300px.

## 2. KPI row is readouts, not cards

- No card fill, no radius, no shadow.
- Each KPI: `1px` top rule `#24312a`; label `10px / 600 / 0.14em` uppercase `#7d8d84`;
  number `40px` JetBrains Mono `600`, tracking `-0.02em`, `#eaf2ec`; unit `12px`
  `#6b7a71`; delta on one `11px` mono line (`+120 kW · 4.6%`).
- The delta is the only place the accent color appears; never color the big number
  unless it is a critical alert state.
- At 1366px, numbers drop to 34px.

## 3. Left rail is a facility roster

- Rows 44px tall, no fills, name `12px / 500`, location and kW on one baseline (kW
  right-aligned, `12px` mono).
- Active row: `2px` lime left border + `#0e1712` tint + lime dot — not a lime background.
- Region headers: `9px / 0.18em / #5c6a62`, 20px top space.
- Pin the model info to the rail footer with `border-top: 1px #1e2b24`.

## 4. Hex field stays peripheral

- Pass `intensity={0.22}` (not 0.45) to `WebGPUHex`.
- Mask the canvas to the top third with a radial gradient
  (`ellipse 70% 55% at 50% 22%, black, transparent 78%`) so it never sits behind a chart.
- Scanline overlay opacity `0.25`; outer vignette stop `0.96`.
- Panels: `rgba(8,12,10,0.94)` with `1px #1e2b24` borders, no backdrop blur. Chart plot
  area `#080c0a`.
- The grid should be visible in gutters, header and rail edges only.

## 5. The signature idea: one shared time gate

One `1px` lime vertical cursor at the replay hour runs through the hero chart, the
readiness strip and the SHAP panel, each topped with the same `HH:MM` JetBrains Mono pill
(`10px`, `#b7f34a` on `#0b120e`). The four panels read as one plotting table.

Implementation:
- Recharts `ReferenceLine` at the cursor x, stroke `#b7f34a`, opacity 0.65, width 1.
- Readiness strip: highlight the segment under the cursor with a 1px lime outline and
  place the `HH:MM` pill above it.
- SHAP panel: same pill in its header, updated from the same cursor state.
- Do not animate the cursor line; it moves in discrete 1.2s steps with the replay.

## Chart styling

- Actual: `2.5px #ffffff`.
- Hybrid: `2px #b7f34a`, dash `6 4`.
- Interval fill: `#b7f34a` at `0.14`.
- Peak threshold: `1.5px #ffb020` dashed, with a `12px` mono label at the right edge.
- Readiness ≤ 2 shading: `#ffb020` at `0.10`.
- Grid: `rgba(255,255,255,0.05)`, horizontal lines only.
- Tooltip: `#0b120e` fill, `1px #2a3a30` border, no shadow, mono values.
- No chart entry animation; replay must be smooth.

## Copy / severity

- Use a non-color cue for severity: a `2px` left bar plus a short mono code
  (`CRIT`, `WARN`, `INFO`) so the feed works for color-blind viewers and on a washed-out
  projector.
- Keep the model-performance caveat: "Residual stage adds a marginal 1h correction;
  longer-horizon ablation is Sprint 4."
