/**
 * Which shell to render.
 *
 * The Android/iOS app always uses the phone UI. In a browser the phone UI is
 * used on narrow screens; `?ui=mobile` / `?ui=desktop` force either one (the
 * choice is remembered for the tab so a demo can switch without resizing).
 */

import { Capacitor } from "@capacitor/core";
import { BREAKPOINT, STORAGE } from "../config/app";

export const isNative = (): boolean => Capacitor.isNativePlatform();

const KEY = STORAGE.ui;

export function prefersMobileShell(): boolean {
  if (isNative()) return true;
  let forced: string | null = null;
  try {
    forced = new URLSearchParams(window.location.search).get("ui");
    if (forced === "mobile" || forced === "desktop") window.sessionStorage.setItem(KEY, forced);
    else forced = window.sessionStorage.getItem(KEY);
  } catch {
    /* storage blocked */
  }
  if (forced === "mobile") return true;
  if (forced === "desktop") return false;
  return window.matchMedia(`(max-width: ${BREAKPOINT.phoneMaxWidth}px)`).matches;
}
