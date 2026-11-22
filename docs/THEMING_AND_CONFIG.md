# Theming and configuration

Nothing in AMAKA's code should hardcode a colour, a storage key, a polling
interval or a server setting. Each has one home.

## Colours: `frontend/theme/palette.json`

The single source of truth for every colour, grouped by role (brand, status,
surface, text, line, scene). Edit a value there, run `npm run theme` (the build
and dev server do it automatically), and the whole app follows.

`scripts/gen-theme.mjs` generates, from that one file:

| Output | Use |
|---|---|
| `src/theme/theme.css` | `:root { --accent: #b7f34a; --accent-rgb: 183 243 74; … }` |
| `src/theme/tokens.ts` | typed `TOKENS` / `ColorToken` for canvas, WebGPU and the map |
| Android `res/values/colors.xml` | native colours listed under `"native"` |
| browser `theme-color`, Capacitor background | read from the palette by `vite.config.ts` and `capacitor.config.ts` |

How to use a colour:

| Where | Write |
|---|---|
| CSS / inline styles / SVG attributes | `var(--accent)` |
| Transparency | `rgb(var(--accent-rgb)/0.3)` |
| JSX helpers | `cssVar("accent")`, `tint("accent", 0.3)` from `theme/theme.ts` |
| Canvas, WebGPU uniforms, MapLibre | `color("accent")`, `rgba("accent", 0.3)`, `rgb01("accent")` |

`npm run check:theme` (run by every build) fails if a hex or `rgb()` literal
appears anywhere in `src/` outside `src/theme/`, so literals cannot creep back.

To re-skin the app (for example a new brand palette), change the values in
`palette.json`. Status colours (`warn`, `crit`) are separate tokens from the
brand `accent` on purpose, so a new brand colour never collides with
"peak threshold" or "critical".

## Visual tunables: `frontend/src/config/visuals.ts`

Everything that shapes the animated scenes, with comments:

- `GRID_BG`: background render resolution, frame rate, glow range, the scrim
  that keeps data legible.
- `GRID_SCENE`: tower spacing, row offset, conductor sag, camera height, pitch
  and speed, fog, moon direction. These are compiled into the shader.
- `INTRO`: duration, flythrough speed, how long the power takes to light up.
- `MAP_SWITCH`: the satellite "character switch" camera moves.

## App constants: `frontend/src/config/app.ts`

Storage keys (and the legacy `sentinel.*` keys migrated on start-up), polling
intervals, replay tick speeds, the phone/desktop breakpoint.

## Backend: `backend/settings.py`

All environment variables and tunables, read once: authentication (token
lifetime, rate limit, password policy, demo accounts), live forecasting
(minimum history, gap filling, weather source and timeouts, forecast length),
and CORS origins. Other modules import `settings` and never touch
`os.environ`. Variable names are unchanged (`SENTINEL_*`), so existing setups
keep working.

## The background and the intro

`GridCanvas` renders the lit transmission-tower scene with WebGPU (ray-marched
lattice pylons, sagging conductors, steel shading, moonlit sky, light pulses
travelling along the lines). It is used twice: `GridBackground` (slow drift
under the app, with legibility scrims; the glow turns warm as more sites are at
risk) and `PowerIntro` (fast flythrough while the power lights up from the far
end). Without WebGPU it falls back to a Canvas2D drawing of the same scene.
