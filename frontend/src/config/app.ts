/**
 * App-wide constants: storage keys, polling intervals, breakpoints.
 * One place to change them; nothing in components should hardcode these.
 */

/** localStorage / Preferences / sessionStorage keys. */
export const STORAGE = {
  session: "amaka.session",
  server: "amaka.server",
  horizon: "amaka.horizon",
  /** sessionStorage: which UI shell was forced with ?ui=. */
  ui: "amaka.ui",
  /** sessionStorage: the intro already played in this browser session. */
  introSeen: "amaka.introSeen",
} as const;

/** Keys from before the SENTINEL -> AMAKA rename, migrated once on start-up. */
export const LEGACY_STORAGE: Record<string, string> = {
  [STORAGE.session]: "sentinel.session",
  [STORAGE.server]: "sentinel.server",
  [STORAGE.horizon]: "sentinel.horizon",
};

/** How often live views refresh, in milliseconds. */
export const POLL_MS = {
  /** API health dot. */
  health: 30_000,
  /** Meter-kit list and hourly readings on Data sources. */
  liveData: 15_000,
  /** Live forecast card. */
  liveForecast: 5 * 60_000,
} as const;

/** Replay cursor: milliseconds per simulated hour while playing. */
export const REPLAY_TICK_MS = {
  desktop: 1200,
  mobile: 900,
} as const;

/** Layout breakpoints (px). */
export const BREAKPOINT = {
  /** At or below this width a browser gets the phone UI. */
  phoneMaxWidth: 760,
} as const;

/** The app asks the server again after being in the background this long. */
export const RESUME_REFRESH_MS = 5 * 60_000;
