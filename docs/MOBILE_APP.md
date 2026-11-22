# Android app (Capacitor)

AMAKA ships as an Android app built with **Capacitor 8**. The phone gets its
own UI (`frontend/src/mobile/`), not a squeezed desktop dashboard: sign-in,
bottom tabs, pushed site screens, bottom sheets, pull-to-refresh, haptics and
the Android back button. It talks to the FastAPI backend over HTTPS (or plain
HTTP on a demo LAN) with a bearer token.

## Phone UI

| Tab | What it shows |
|---|---|
| **Fleet** | Fleet load, sites at risk, high-readiness count, a role card (below), status map of Zambia, sites sorted by risk |
| **Alerts** | Every site's server-evaluated alerts for the 24 h up to the selected hour, filterable by severity; tap to open the site |
| **Sites** | Search and filter (all / at risk / nominal), grouped by city |
| **More** | Profile and role access, default forecast horizon, data-link status, model info, about, sign out |

Tapping a site opens a pushed screen with **Monitor** (KPIs, touch load trace
with replay, generator dispatch for energy managers, alerts, chart
explanation), **Drivers** (SHAP for the selected hour; not shown to
commanders), **Outlook** (7–90 day forecasts) and **Details** (site profile,
model accuracy). The share button exports the visible window as PDF or CSV
through the Android share sheet.

The horizon chip (H1 / H6 / H24 / H48) on every screen opens a bottom sheet;
the default horizon is saved on the device.

### Roles

The role comes from the signed-in account, not a picker:

| Account role | Fleet card | Site extras |
|---|---|---|
| Commander | Fleet risk: sites over threshold, peak shortfall, monthly saving | — |
| Energy Manager (`operator`) | Generator dispatch actions per site | Drivers tab, dispatch card, chart questions |
| Analyst | Fleet forecast accuracy, best and worst site | Drivers tab, chart questions |

Browsers on screens narrower than 760 px get the same phone UI. Force either
UI with `?ui=mobile` or `?ui=desktop`.

## Accounts and sign-in

Every `/api` data endpoint needs `Authorization: Bearer <token>`
(`/api/health` and `/api/auth/login` are open).

- `POST /api/auth/login` `{username, password}` → token (12 h, HS256 JWT) and
  the account `{username, name, role}`.
- `GET /api/auth/me` → the account for a saved token.
- Five failed sign-ins per username or address within 5 minutes → HTTP 429.
- Passwords are stored as PBKDF2-SHA256 hashes in `config/users.json`
  (gitignored). The token signing key comes from `SENTINEL_JWT_SECRET`, or is
  generated once into `config/.jwt_secret` (gitignored).
- The chart-question endpoint is limited to Energy Manager and Analyst, and the
  narrative voice always follows the account role.

On first start the API creates three demo accounts (commander, manager,
analyst) from `config/users.seed.json`; their passwords are in that file.
Disable this with `SENTINEL_DEMO_USERS=0` and manage real accounts with:

```powershell
python -m backend.users add jbanda --role operator --name "J. Banda"
python -m backend.users list
python -m backend.users passwd jbanda
python -m backend.users disable jbanda
```

`SENTINEL_AUTH=off` turns authentication off for local research runs only.

The app keeps the session in Capacitor Preferences (app-private storage) and
signs out automatically when the server rejects the token. On the sign-in
screen, **Server → Change** points the APK at a different API address without
rebuilding (useful when the laptop's LAN IP changes).

## Native plugins

| Plugin | Used for |
|---|---|
| `@capacitor/app` | Android back button, refresh after returning to the app |
| `@capacitor/preferences` | Session token, server address, default horizon |
| `@capacitor/haptics` | Tap feedback |
| `@capacitor/filesystem` + `@capacitor/share` | Saving PDF/CSV reports and opening the share sheet |

After adding or upgrading a plugin run `npm run cap:sync` so the Android
project picks it up.

```
frontend/
  capacitor.config.ts        app id, name, WebView scheme
  assets/icon.svg            launcher/splash source (AMAKA hex)
  android/                   generated native project (commit this)
  .env.mobile.example        template for the API origin
  .env.mobile.local          your machine's API origin (gitignored)
```

| Item | Value |
|---|---|
| App name | AMAKA |
| App id | `zm.amaka.energy` |
| Min Android | 7.0 (API 24) |
| Target / compile SDK | 36 (Android 16) |
| WebView origin | `https://localhost` |
| API calls | `VITE_API_BASE_URL` + `/api/...` |

## Prerequisites

- Node 20+ (this machine has Node 23).
- **JDK 21** — Capacitor 8 requires Java 21, and the system JDK here is 25.
  Android Studio's bundled JDK works:
  `C:\Program Files\Android\Android Studio\jbr`.
- Android SDK with platform 36 and build-tools (already installed here).

The Gradle build needs `JAVA_HOME` on JDK 21. `npm run apk` picks a JDK 21
automatically (your `JAVA_HOME` if it is 21, otherwise Android Studio's bundled
`jbr`), writes `android/local.properties` with the SDK path, and passes the SDK
`aapt2.exe` to Gradle. No manual environment setup is required for the CLI
build. When building from Android Studio, set `JAVA_HOME` yourself if the IDE
points at Java 25:

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
```

## Build a debug APK

```powershell
cd frontend

# 1. Point the app at the backend (no trailing slash).
#    LAN demo: http://<laptop-lan-ip>:8000
#    Cloud:    https://<api-id>.execute-api.<region>.amazonaws.com
Copy-Item .env.mobile.example .env.mobile.local
notepad .env.mobile.local

# 2. Build the web bundle, copy it into Android, and assemble the APK.
npm run apk
```

Output:

```
frontend/android/app/build/outputs/apk/debug/app-debug.apk
```

Install it on a connected phone:

```powershell
adb install -r frontend/android/app/build/outputs/apk/debug/app-debug.apk
```

The debug APK is self-signed with the Android debug key, which is fine for a
demo and for sideloading. A Play Store release needs your own keystore and
`gradlew assembleRelease` with signing config.

## Testing against the laptop (LAN demo)

1. Start the API on all interfaces:

   ```powershell
   .\run.ps1 -Lan
   ```

   It prints every LAN address. Allow Python through Windows Firewall on
   private networks if prompted.

2. Put the Wi-Fi address in `frontend/.env.mobile.local`:

   ```
   VITE_API_BASE_URL=http://10.15.130.150:8000
   ```

3. Rebuild the APK (`npm run apk`). The phone must be on the same Wi-Fi.

The API must be reachable from the phone's browser first — open
`http://<laptop-ip>:8000/api/health` on the phone. If that fails, the APK cannot
work either (firewall, router client isolation, or wrong IP).

`vite.config.ts` refuses to produce a mobile bundle when
`VITE_API_BASE_URL` is empty, so a misconfigured APK fails at build time instead
of showing "data service unreachable".

## Development workflow

```powershell
cd frontend
npm run dev            # normal browser development, Vite proxies /api
npm run build:mobile   # production web bundle for the app (mode=mobile)
npm run cap:sync       # build:mobile + copy into android/
npm run cap:open       # open the native project in Android Studio
npm run apk            # cap:sync + gradlew assembleDebug
```

After changing web code, `npm run apk` is the only command needed. After
changing `capacitor.config.ts` or adding a Capacitor plugin, run `npm run
cap:sync` (then rebuild).

Live reload on a device (optional, development only):

```powershell
cd frontend
npm run dev
npx cap run android -l --external
```

This loads the UI from the Vite dev server instead of the bundled `dist`.
It is not used in the APK build.

## Networking and CORS

- Native WebView origin is `https://localhost` on Android
  (`capacitor://localhost` on iOS). The backend allows both, plus the Vite dev
  origins; see `DEFAULT_ALLOWED_ORIGINS` in `backend/app.py`.
- Add more origins without editing code:

  ```powershell
  $env:SENTINEL_ALLOWED_ORIGINS = "https://amaka.example.com"
  ```

- `android:usesCleartextTraffic="true"` and `allowMixedContent` are enabled for
  the HTTP LAN demo. **Turn them off once the API is served over HTTPS**: remove
  the manifest attribute and set `cleartext` / `allowMixedContent` to `false` in
  `capacitor.config.ts`.

## Safe areas

Android 15+ draws apps edge-to-edge. `index.html` uses `viewport-fit=cover`,
and `styles.css` maps `env(safe-area-inset-*)` into `--safe-top` /
`--safe-bottom`, so the header, rail and bottom of the console stay clear of
the status and navigation bars.

## Icons and splash screen

`frontend/assets/icon.svg` is the source. Regenerate the Android mipmaps and
splash images with:

```powershell
cd frontend
npx @capacitor/assets generate --android `
  --iconBackgroundColor "#070a09" --iconBackgroundColorDark "#070a09" `
  --splashBackgroundColor "#070a09" --splashBackgroundColorDark "#070a09"
```

## Backend hosting for the app

The APK only needs one thing: an **HTTPS origin** that serves the FastAPI
routes. The dashboard itself is already bundled in the APK, so the server does
not need to serve `frontend/dist`.

The current backend is a stateful, file-backed FastAPI app (`backend/store.py`
reads `config/v2_sites.json`, `data/v2/*.csv`, `data/v2/*.npz`). Two practical
options:

| Option | Fit | Notes |
|---|---|---|
| **AWS Lambda + API Gateway** (container image, Mangum) | Works, cheapest at low traffic | Needs a container build, 10 GB image limit, and cold starts while numpy/pandas/reportlab import. API Gateway has a 30 s limit. |
| **AWS App Runner** (container) | Better fit for this backend | Persistent HTTPS URL, no request timeout surprises, simple deploy. Scales down when idle, but not to zero on all plans. |
| **EC2 / Lightsail** | Simplest to reason about | Always-on small instance, HTTPS via Caddy/ALB. |

If the goal is "free/cheap and serverless", Lambda is viable. If the goal is a
demo that starts quickly and never times out while generating a PDF, App Runner
is the lower-risk choice. Either way, set `SENTINEL_ALLOWED_ORIGINS` only if a
separate web frontend is added; the Android app's `https://localhost` origin is
already allowed.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "Data service unreachable" | Wrong `VITE_API_BASE_URL`, phone off Wi-Fi, backend bound to 127.0.0.1, or firewall. Open `/api/health` in the phone browser. |
| `net::ERR_CLEARTEXT_NOT_PERMITTED` | HTTP API without the manifest cleartext flag; rebuild after checking `AndroidManifest.xml`. |
| Blank screen after launch | Run `npm run cap:sync`; confirm `dist/index.html` exists; check `adb logcat` for WebView errors. |
| `Unsupported class file major version 69` | Gradle is using Java 25. Set `JAVA_HOME` to the Android Studio JDK 21. |
| Build cannot find SDK 36 | Install SDK Platform 36 in Android Studio, or set `ANDROID_HOME`. |
| App still shows the old build | Reinstall: `adb install -r ...` (or uninstall first). |
| Gradle hangs at `Downloading .../aapt2-8.13.0-...-windows.jar` | `dl.google.com` is slow/blocked on this connection. `npm run apk` passes the SDK `aapt2.exe` instead. For Android Studio builds, keep the `android.aapt2FromMavenOverride=.../build-tools/36.0.0/aapt2.exe` line in `%USERPROFILE%\.gradle\gradle.properties`. |
| `Could not move temporary workspace` or `daemon disappeared` | Windows file lock (usually antivirus) during dex merging. Close Android Studio/Gradle javas, delete `frontend/android/app/build`, and rerun. `npm run apk` uses `--max-workers=1 --no-daemon`, which avoids most of these collisions. Adding the project and `%USERPROFILE%\.gradle` to Windows Defender exclusions also helps. |


## Satellite map and intro

- **Satellite map** (`frontend/src/mobile/map/`): MapLibre GL with Esri World
  Imagery (no API key; keep the attribution visible), the real Zambia
  boundary from `public/zambia.geojson`, and live status pins at each site's
  configured coordinates. Tap **Explore** or a pin for the full-screen map.
  Choosing a site runs the "switch": the camera pulls up into the sky in
  stepped jumps, sweeps across the country, then drops in stages onto the
  real base and slowly orbits it. Needs internet; offline it falls back to
  the vector map.
- **Intro** (`frontend/src/intro/`): a canvas power-grid scene (pylons,
  energising conductors, travelling power pulses, sparks) followed by the
  AMAKA mark and tagline. Plays on every cold start of the app and once per
  browser session (`?intro` forces it). Tap to skip; skipped entirely when the
  OS asks for reduced motion.

## Rename to AMAKA (November 2026)

The product was renamed from SENTINEL to **AMAKA** (Bemba for "power").

- The Android app ID is now `zm.amaka.energy`. Android treats it as a new
  app, so uninstall the old `zm.sentinel.energy` SENTINEL app from demo phones.
- Environment variables keep their `SENTINEL_*` names (for example
  `SENTINEL_LLM_API_KEY`, `SENTINEL_JWT_SECRET`) so existing setups keep working.
- Tokens issued before the rename are still accepted until they expire, and
  saved sessions under the old `sentinel.*` storage keys are migrated on start-up.
- Brand files: `frontend/assets/brand/` (mark and wordmark), launcher source
  `frontend/assets/icon.svg`.

## Data sources (analyst)

**More → Data sources** shows live meter kits and measured load
(backend: `backend/ingest_api.py`, design: `docs/DATA_INGESTION.md`).
Analysts can add a meter kit (pick or create a site, then read the one-time
enrolment code off the screen), upload a meter CSV, and revoke a kit after a
confirmation. Other roles get a read-only kit status view. The hourly chart
shades quality flags red and missing hours grey, with a completeness figure
and per-flag counts. The **Live forecast** card runs the trained models on the
site's readings (with a readiness selector); see
[`SCADA_AND_LIVE_FORECAST.md`](SCADA_AND_LIVE_FORECAST.md).

Demo data: issue a code in the app, then run
`python scripts/device_sim.py --code <CODE> --device-id kit-0042 --base-kw 1400 --backfill-hours 48 --interval 10`
(add `--fault flatline` to show quality flags).
