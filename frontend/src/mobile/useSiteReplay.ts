/**
 * Replay state for one site on the phone: the hourly series at the current
 * horizon, the selected hour (cursor), the visible window and playback.
 * Mirrors the desktop App logic in a self-contained hook.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { errMessage, fetchExplain, fetchSeries, isAbort } from "../api";
import { anchorIndex, deriveBounds, projectedPeak, type Bounds } from "../lib/replay";
import { normTs } from "../lib/format";
import { REPLAY_TICK_MS } from "../config/app";
import type { ExplainResponse, ReplayRow } from "../types";

const seriesCache = new Map<string, ReplayRow[]>();
const explainCache = new Map<string, ExplainResponse>();

export type ExplainState = {
  data: ExplainResponse | null;
  status: "idle" | "loading" | "ok" | "error";
  error: string | null;
};

export function useSiteReplay(siteId: string, horizon: number, anchor: string) {
  const [rows, setRows] = useState<ReplayRow[]>(() => seriesCache.get(`${siteId}|${horizon}`) ?? []);
  const [loading, setLoading] = useState(rows.length === 0);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [cursor, setCursor] = useState(() => anchorIndex(rows, anchor));
  const [rangeHours, setRangeHours] = useState(72);
  const [frozen, setFrozen] = useState<Bounds | null>(null);
  const [playing, setPlaying] = useState(false);
  const boundsRef = useRef<Bounds>({ ws: 0, we: 0 });
  const cursorTsRef = useRef<string>("");

  /* series */
  useEffect(() => {
    const key = `${siteId}|${horizon}`;
    const keepTs = cursorTsRef.current || anchor;
    const apply = (data: ReplayRow[]) => {
      const idx = anchorIndex(data, keepTs);
      setRows(data);
      setCursor(idx);
      setFrozen(deriveBounds(idx, data.length, 72));
      setRangeHours(72);
      setError(null);
      setLoading(false);
    };
    const cached = seriesCache.get(key);
    if (cached) {
      apply(cached);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    fetchSeries(siteId, ctrl.signal, horizon)
      .then((data) => {
        seriesCache.set(key, data);
        apply(data);
      })
      .catch((e) => {
        if (isAbort(e)) return;
        setError(errMessage(e));
        setLoading(false);
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [siteId, horizon, attempt]);

  const len = rows.length;
  const bounds = useMemo<Bounds>(() => {
    if (len <= 0) return { ws: 0, we: 0 };
    if (frozen && frozen.we > frozen.ws && frozen.we <= len) return frozen;
    return deriveBounds(cursor, len, rangeHours);
  }, [frozen, cursor, len, rangeHours]);
  boundsRef.current = bounds;

  const cursorRow = cursor >= 0 && cursor < len ? rows[cursor] : undefined;
  cursorTsRef.current = cursorRow ? normTs(cursorRow.timestamp) : "";

  /* playback */
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      const b = boundsRef.current;
      if (b.we <= b.ws) return;
      setCursor((prev) => (prev + 1 >= b.we ? b.ws : prev + 1));
    }, REPLAY_TICK_MS.mobile);
    return () => window.clearInterval(id);
  }, [playing]);

  const scrub = useCallback(
    (idx: number) => {
      if (len === 0) return;
      const v = Math.max(0, Math.min(idx, len - 1));
      setCursor(v);
      const b = boundsRef.current;
      if (!(v >= b.ws && v < b.we)) setFrozen(deriveBounds(v, len, rangeHours));
    },
    [len, rangeHours],
  );

  const step = useCallback(
    (delta: number) => {
      setPlaying(false);
      scrub(cursor + delta);
    },
    [cursor, scrub],
  );

  const changeRange = useCallback(
    (h: number) => {
      setRangeHours(h);
      setFrozen(deriveBounds(cursor, len, h));
    },
    [cursor, len],
  );

  const resetToAnchor = useCallback(() => {
    if (len === 0) return;
    const idx = anchorIndex(rows, anchor);
    setPlaying(false);
    setCursor(idx);
    setFrozen(deriveBounds(idx, len, rangeHours));
  }, [rows, len, anchor, rangeHours]);

  const peak24 = useMemo(() => (len > 0 ? projectedPeak(rows, cursor, 24) : null), [rows, cursor, len]);

  return {
    rows,
    loading,
    error,
    retry: () => setAttempt((n) => n + 1),
    cursor,
    cursorRow,
    bounds,
    rangeHours,
    playing,
    peak24,
    scrub,
    step,
    changeRange,
    resetToAnchor,
    togglePlay: () => setPlaying((p) => !p),
    pause: () => setPlaying(false),
  };
}

/** SHAP drivers for the selected hour (fetched only while `enabled`). */
export function useExplain(siteId: string, horizon: number, at: string, enabled: boolean): ExplainState {
  const [state, setState] = useState<ExplainState>({ data: null, status: "idle", error: null });

  useEffect(() => {
    if (!enabled || !at) return;
    const key = `${siteId}|${at}|${horizon}`;
    const hit = explainCache.get(key);
    if (hit) {
      setState({ data: hit, status: "ok", error: null });
      return;
    }
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => {
      setState((s) => ({ ...s, status: "loading", error: null }));
      fetchExplain(siteId, at, ctrl.signal, horizon)
        .then((data) => {
          explainCache.set(key, data);
          if (explainCache.size > 200) {
            const first = explainCache.keys().next().value;
            if (first !== undefined) explainCache.delete(first);
          }
          setState({ data, status: "ok", error: null });
        })
        .catch((e) => {
          if (isAbort(e)) return;
          setState((s) => ({ ...s, status: s.data ? "ok" : "error", error: errMessage(e) }));
        });
    }, 350);
    return () => {
      ctrl.abort();
      window.clearTimeout(timer);
    };
  }, [siteId, horizon, at, enabled]);

  return state;
}

/** Drop cached series/explain data (pull-to-refresh). */
export function clearReplayCaches(): void {
  seriesCache.clear();
  explainCache.clear();
}
