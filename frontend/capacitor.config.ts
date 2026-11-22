import type { CapacitorConfig } from "@capacitor/cli";
import { readFileSync } from "node:fs";

// Brand colours come from theme/palette.json (single source of truth).
const palette = JSON.parse(readFileSync(new URL("./theme/palette.json", import.meta.url), "utf8"));
const flat: Record<string, string> = Object.assign({}, ...Object.values(palette.groups as Record<string, Record<string, string>>));
const BG = flat[palette.native.colorPrimary];

/**
 * Capacitor shell for the AMAKA dashboard.
 *
 * The React app is built to `dist/` and copied into the Android project by
 * `npx cap sync android`. The app keeps its normal web API surface; only the
 * base URL changes (see `VITE_API_BASE_URL` in `.env.mobile`).
 *
 * `cleartext` + `allowMixedContent` are enabled so a phone can reach the
 * FastAPI server over plain HTTP on the demo LAN. Turn both off when the
 * backend is served over HTTPS (for example behind API Gateway).
 */
const config: CapacitorConfig = {
  appId: "zm.amaka.energy",
  appName: "AMAKA",
  webDir: "dist",
  backgroundColor: BG,
  server: {
    androidScheme: "https",
    cleartext: true,
  },
  android: {
    backgroundColor: BG,
    allowMixedContent: true,
  },
  plugins: {
    // AMAKA is always dark, so keep light status/nav bar icons regardless of
    // the device theme, and let the CSS safe-area variables handle insets.
    SystemBars: {
      style: "DARK",
      insetsHandling: "css",
      initialViewportFitValueHint: "cover",
    },
  },
};

export default config;
