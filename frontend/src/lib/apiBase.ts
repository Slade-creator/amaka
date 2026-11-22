/**
 * Backend origin configuration.
 *
 * Web (Vite dev server + the FastAPI static build): no base URL, so every call
 * stays root-relative ("/api/...") and works on the same origin.
 *
 * Capacitor (Android/iOS): the bundled UI runs from https://localhost, so the
 * requests must target the real API origin. VITE_API_BASE_URL sets the default
 * at build time (see .env.mobile.example); the sign-in screen can override it
 * at runtime ("Server" field) so a demo APK keeps working when the laptop's
 * LAN address changes. The override is restored by lib/session.ts on start-up.
 */

const raw = import.meta.env.VITE_API_BASE_URL;
const configured = typeof raw === "string" ? raw.trim() : "";

/** Build-time API origin with no trailing slash. Empty string = same origin. */
export const DEFAULT_API_BASE: string = normalizeBase(configured);

let current = DEFAULT_API_BASE;

/** "http://10.0.0.5:8000/" → "http://10.0.0.5:8000". Empty stays empty. */
export function normalizeBase(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

/** True for an absolute http(s) origin (or empty = same origin). */
export function isValidBase(value: string): boolean {
  const v = normalizeBase(value);
  if (!v) return true;
  try {
    const u = new URL(v);
    return (u.protocol === "http:" || u.protocol === "https:") && !!u.host;
  } catch {
    return false;
  }
}

/** Active API origin (runtime override, else the build-time default). */
export function getApiBase(): string {
  return current;
}

/** Set the runtime API origin; empty resets to the build-time default. */
export function setApiBase(value: string | null | undefined): void {
  const v = normalizeBase(value ?? "");
  current = v || DEFAULT_API_BASE;
}

/** Prefix a root-relative API path with the configured backend origin. */
export function apiUrl(path: string): string {
  return `${current}${path}`;
}

/** One connection-error message for web and native builds. */
export function unreachableMessage(): string {
  if (current) {
    return `Data service unreachable — check that ${current} is running and reachable`;
  }
  return "Data service unreachable — start the API on 127.0.0.1:8000";
}
