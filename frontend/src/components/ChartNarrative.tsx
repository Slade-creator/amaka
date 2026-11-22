import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
} from "react";
import { askNarrative, errMessage, fetchNarrative, isAbort } from "../api";
import { getRoleConfig, type Role } from "../fleet/roles";
import type { NarrativeAnswerResponse, NarrativeResponse, Site } from "../types";
import { Panel } from "./ui";

type Props = {
  site: Site;
  role: Role;
  horizon: number;
  at: string;
  from?: string;
  to?: string;
  playing: boolean;
  hasRows: boolean;
};

type Status = "idle" | "loading" | "ok" | "error";

const SUGGESTIONS = ["Why the peak?", "Top drivers?", "Headroom?"];
const MODEL_RETRY_MS = 5 * 60 * 1000;

/**
 * Sleek, compact Window Summary & Ask bar under the Load Trace.
 * Header row holds the title, quick-ask pills, and inline question input so
 * the entire card stays compact and fits cleanly above the fold.
 */
export default function ChartNarrative({
  site,
  role,
  horizon,
  at,
  from,
  to,
  playing,
  hasRows,
}: Props) {
  const [narrative, setNarrative] = useState<NarrativeResponse | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [refining, setRefining] = useState(false);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<NarrativeAnswerResponse | null>(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);

  const cacheRef = useRef<Map<string, NarrativeResponse>>(new Map());
  const modelDownUntilRef = useRef(0);
  const askCtrlRef = useRef<AbortController | null>(null);
  const askTicketRef = useRef(0);
  const mountedRef = useRef(true);

  useEffect(
    () => () => {
      mountedRef.current = false;
      askCtrlRef.current?.abort();
    },
    [],
  );

  const canAsk = role !== "commander";
  const roleCfg = getRoleConfig(role);

  const fresh = useMemo(() => {
    if (!narrative) return null;
    if (narrative.site !== site.id) return null;
    if (narrative.horizon !== horizon) return null;
    if (narrative.role !== role) return null;
    if (from && narrative.window.from !== from) return null;
    if (to && narrative.window.to !== to) return null;
    return narrative;
  }, [narrative, site.id, horizon, role, from, to]);

  /* phase 1: rules, fast */
  useEffect(() => {
    if (!site.id || !at || !hasRows) return;
    const key = `${site.id}|${horizon}|${role}|${at}|${from ?? ""}|${to ?? ""}|fast`;
    const cached = cacheRef.current.get(key);
    if (cached) {
      setNarrative(cached);
      setStatus("ok");
      setError(null);
      return;
    }

    const ctrl = new AbortController();
    setStatus((prev) => (prev === "ok" ? "ok" : "loading"));
    const timer = window.setTimeout(() => {
      fetchNarrative(
        site.id,
        { at, from, to, role, horizon, mode: "fast" },
        ctrl.signal,
      )
        .then((data) => {
          if (!mountedRef.current) return;
          cacheRef.current.set(key, data);
          if (cacheRef.current.size > 200) {
            const oldest = cacheRef.current.keys().next().value;
            if (oldest !== undefined) cacheRef.current.delete(oldest);
          }
          setNarrative(data);
          setStatus("ok");
          setError(null);
        })
        .catch((e) => {
          if (!mountedRef.current || isAbort(e)) return;
          setStatus((prev) => (prev === "ok" ? "ok" : "error"));
          setError(errMessage(e));
        });
    }, 200);

    return () => {
      ctrl.abort();
      window.clearTimeout(timer);
    };
  }, [site.id, horizon, role, at, from, to, hasRows]);

  /* phase 2: model refine */
  useEffect(() => {
    if (!site.id || !at || !hasRows || playing) return;
    if (Date.now() < modelDownUntilRef.current) return;

    const key = `${site.id}|${horizon}|${role}|${at}|${from ?? ""}|${to ?? ""}|auto`;
    const cached = cacheRef.current.get(key);
    if (cached) {
      if (cached.source === "model") setNarrative(cached);
      return;
    }

    const ctrl = new AbortController();
    const timer = window.setTimeout(() => {
      setRefining(true);
      fetchNarrative(
        site.id,
        { at, from, to, role, horizon, mode: "auto" },
        ctrl.signal,
      )
        .then((data) => {
          if (!mountedRef.current) return;
          cacheRef.current.set(key, data);
          if (data.source === "model") {
            setNarrative(data);
            modelDownUntilRef.current = 0;
          } else if (
            data.fallback_reason === "not_configured" ||
            data.fallback_reason === "breaker" ||
            data.fallback_reason === "provider"
          ) {
            modelDownUntilRef.current = Date.now() + MODEL_RETRY_MS;
          }
          setRefining(false);
        })
        .catch((e) => {
          if (!mountedRef.current || isAbort(e)) return;
          setRefining(false);
        });
    }, 1100);

    return () => {
      ctrl.abort();
      window.clearTimeout(timer);
    };
  }, [site.id, horizon, role, at, from, to, hasRows, playing]);

  useEffect(() => {
    setAnswer(null);
    setAskError(null);
  }, [site.id, at, from, to, role, horizon]);

  const ask = useCallback(
    async (text: string) => {
      const q = text.trim();
      if (!q || asking || !site.id || !at) return;
      askCtrlRef.current?.abort();
      const ctrl = new AbortController();
      askCtrlRef.current = ctrl;
      const ticket = ++askTicketRef.current;
      setAsking(true);
      setAskError(null);
      setAnswer(null);
      try {
        const data = await askNarrative(
          site.id,
          { question: q, at, from, to, role, horizon },
          ctrl.signal,
        );
        if (!mountedRef.current || ticket !== askTicketRef.current) return;
        setAnswer(data);
      } catch (e) {
        if (!mountedRef.current || ticket !== askTicketRef.current || isAbort(e)) return;
        setAskError(errMessage(e));
      } finally {
        if (mountedRef.current && ticket === askTicketRef.current) setAsking(false);
      }
    },
    [asking, site.id, at, from, to, role, horizon],
  );

  const onSubmit = useCallback(
    (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      const q = question.trim();
      if (!q) return;
      setQuestion("");
      void ask(q);
    },
    [ask, question],
  );

  const summaryText = useMemo(
    () =>
      (fresh?.text ?? "")
        .split(/\n{2,}/)
        .map((p) => p.trim())
        .filter(Boolean)
        .join(" "),
    [fresh],
  );

  const showEmpty = !fresh && (status === "loading" || status === "idle");
  const showError = !fresh && status === "error";

  return (
    <Panel id="narrative" className="section-anchor">
      <div
        className="chart-narrative"
        style={{ "--role": roleCfg.accent } as CSSProperties}
        aria-live={playing ? "off" : "polite"}
      >
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
          <span className="text-[11.5px] font-semibold text-fg">
            Window Summary
            {refining ? (
              <span className="text-[10.5px] font-normal text-[color:var(--color-amber)] ml-1.5">
                · refining…
              </span>
            ) : fresh?.source === "model" ? (
              <span className="text-[10.5px] font-normal text-lime ml-1.5">· AI grounded</span>
            ) : null}
          </span>

          {canAsk && fresh ? (
            <div className="flex flex-wrap items-center gap-1.5">
              {SUGGESTIONS.map((chip) => (
                <button
                  key={chip}
                  type="button"
                  className="driver-chip"
                  disabled={asking}
                  onClick={() => void ask(chip)}
                >
                  {chip}
                </button>
              ))}
              <form className="narrative-form" onSubmit={onSubmit}>
                <input
                  type="text"
                  value={question}
                  maxLength={280}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="Ask about this window…"
                  aria-label="Ask about this chart window"
                  disabled={asking}
                />
                <button
                  type="submit"
                  className="btn btn-lime btn-compact"
                  disabled={asking || !question.trim()}
                >
                  {asking ? "…" : "Ask"}
                </button>
              </form>
            </div>
          ) : null}
        </div>

        {showEmpty ? (
          <div className="narrative-skeleton" role="status">
            <span className="narrative-skel-line" />
            <span className="narrative-skel-line is-short" />
          </div>
        ) : null}

        {showError ? (
          <p className="text-[11.5px] text-[color:var(--color-red)]">
            Summary unavailable ({error})
          </p>
        ) : null}

        {fresh ? (
          <>
            <p className="chart-narrative-text">{summaryText}</p>

            {answer ? (
              <div className="narrative-answer" aria-live="polite">
                <p>{answer.answer}</p>
                <div className="narrative-answer-meta">
                  <span className="text-[10px] text-dim">
                    {answer.source === "model" ? "Grounded AI answer" : "Rule-based answer"}
                  </span>
                  <button
                    type="button"
                    className="narrative-dismiss"
                    onClick={() => setAnswer(null)}
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            ) : null}

            {askError ? <p className="narrative-error">{askError}</p> : null}
          </>
        ) : null}
      </div>
    </Panel>
  );
}
