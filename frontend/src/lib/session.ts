/**
 * Signed-in session: bearer token, account and persistence.
 *
 * The token is kept in Capacitor Preferences on native builds (Android
 * SharedPreferences, private to the app) and in localStorage on the web. Every
 * API call goes through `apiFetch`, which attaches the token and signs the
 * user out when the server answers 401 (expired, revoked or disabled account).
 */

import { Capacitor } from "@capacitor/core";
import { Preferences } from "@capacitor/preferences";
import { isRole, type Role } from "../fleet/roles";
import { apiUrl, getApiBase, setApiBase, unreachableMessage } from "./apiBase";
import { STORAGE, LEGACY_STORAGE } from "../config/app";

export type SessionUser = {
  username: string;
  name: string;
  role: Role;
};

export type Session = {
  token: string;
  /** Epoch seconds. */
  expiresAt: number;
  user: SessionUser;
};

const KEY_SESSION = STORAGE.session;
const KEY_SERVER = STORAGE.server;
const LEGACY_KEYS = LEGACY_STORAGE;

let session: Session | null = null;
const listeners = new Set<(s: Session | null) => void>();

/* ------------------------------------------------------------------ */
/* storage                                                             */
/* ------------------------------------------------------------------ */

export async function readPref(key: string): Promise<string | null> {
  const value = await readRaw(key);
  if (value !== null || !LEGACY_KEYS[key]) return value;
  // Move a pre-rename value across so existing sign-ins keep working.
  const legacy = await readRaw(LEGACY_KEYS[key]);
  if (legacy !== null) {
    await writePref(key, legacy);
    await writePref(LEGACY_KEYS[key], null);
  }
  return legacy;
}

async function readRaw(key: string): Promise<string | null> {
  try {
    if (Capacitor.isNativePlatform()) return (await Preferences.get({ key })).value;
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export async function writePref(key: string, value: string | null): Promise<void> {
  try {
    if (Capacitor.isNativePlatform()) {
      if (value === null) await Preferences.remove({ key });
      else await Preferences.set({ key, value });
      return;
    }
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable (private mode) — the session lives in memory only */
  }
}

function parseSession(raw: string | null): Session | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as Partial<Session>;
    const u = v.user as Partial<SessionUser> | undefined;
    if (
      typeof v.token === "string" &&
      typeof v.expiresAt === "number" &&
      u &&
      typeof u.username === "string" &&
      isRole(u.role)
    ) {
      return {
        token: v.token,
        expiresAt: v.expiresAt,
        user: { username: u.username, name: String(u.name ?? u.username), role: u.role },
      };
    }
  } catch {
    /* corrupt entry */
  }
  return null;
}

/* ------------------------------------------------------------------ */
/* state                                                               */
/* ------------------------------------------------------------------ */

export function getSession(): Session | null {
  return session;
}

export function subscribeSession(fn: (s: Session | null) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function setSession(next: Session | null): void {
  session = next;
  void writePref(KEY_SESSION, next ? JSON.stringify(next) : null);
  for (const fn of listeners) fn(next);
}

/** Why the last session ended (shown once on the sign-in screen). */
let endReason: string | null = null;
export function takeEndReason(): string | null {
  const r = endReason;
  endReason = null;
  return r;
}

export function signOut(reason?: string): void {
  endReason = reason ?? null;
  setSession(null);
}

/* ------------------------------------------------------------------ */
/* server override                                                     */
/* ------------------------------------------------------------------ */

export async function saveServer(base: string): Promise<void> {
  setApiBase(base);
  await writePref(KEY_SERVER, base.trim() ? base.trim() : null);
}

/* ------------------------------------------------------------------ */
/* HTTP                                                                */
/* ------------------------------------------------------------------ */

export class HttpError extends Error {
  status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.name = "HttpError";
    this.status = status;
  }
}

/**
 * fetch() against the API with the bearer token attached. A 401 on a signed-in
 * request ends the session; the caller still receives the response.
 * Network failures throw HttpError with the "unreachable" message; aborts rethrow.
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  const token = session?.token;
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res: Response;
  try {
    res = await fetch(apiUrl(path), { ...init, headers });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new HttpError(unreachableMessage());
  }
  if (res.status === 401 && token && session?.token === token) {
    signOut("Your session has expired. Sign in again.");
  }
  return res;
}

async function detail(res: Response): Promise<string | null> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : null;
  } catch {
    return null;
  }
}

/** POST /api/auth/login → stores and returns the new session. */
export async function signIn(username: string, password: string): Promise<Session> {
  const res = await apiFetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: username.trim(), password }),
  });
  if (!res.ok) {
    const msg = await detail(res);
    if (res.status === 401) throw new HttpError(msg ?? "Incorrect username or password", 401);
    if (res.status === 429) throw new HttpError(msg ?? "Too many attempts. Try again later.", 429);
    if (res.status === 404)
      throw new HttpError(
        `${getApiBase() || "This server"} does not support sign-in. Update the AMAKA API.`,
        404,
      );
    throw new HttpError(msg ?? `Sign-in failed (HTTP ${res.status})`, res.status);
  }
  const body = (await res.json()) as {
    access_token?: string;
    expires_at?: number;
    user?: { username?: string; name?: string; role?: string };
  };
  const role = body.user?.role;
  if (!body.access_token || !body.user?.username || !isRole(role)) {
    throw new HttpError("Malformed sign-in response");
  }
  const next: Session = {
    token: body.access_token,
    expiresAt: typeof body.expires_at === "number" ? body.expires_at : Date.now() / 1000 + 3600,
    user: { username: body.user.username, name: body.user.name ?? body.user.username, role },
  };
  endReason = null;
  setSession(next);
  return next;
}

/**
 * Restore the saved server + session on start-up and confirm the token with
 * /api/auth/me. An offline server keeps the saved session (the app shows the
 * data-link error instead of forcing a sign-in); a rejected token clears it.
 */
export async function restoreSession(): Promise<Session | null> {
  const server = await readPref(KEY_SERVER);
  if (server) setApiBase(server);
  const saved = parseSession(await readPref(KEY_SESSION));
  if (!saved) return null;
  if (saved.expiresAt * 1000 <= Date.now()) {
    await writePref(KEY_SESSION, null);
    endReason = "Your session has expired. Sign in again.";
    return null;
  }
  session = saved;
  try {
    const res = await apiFetch("/api/auth/me");
    if (res.status === 401) return null; // apiFetch already signed out
    if (res.ok) {
      const body = (await res.json()) as { user?: { name?: string; role?: string } };
      const role = body.user?.role;
      if (isRole(role) && role !== saved.user.role) {
        // Role changed on the server: adopt it.
        setSession({ ...saved, user: { ...saved.user, role, name: body.user?.name ?? saved.user.name } });
      }
    }
  } catch {
    /* offline — keep the saved session */
  }
  return session;
}
