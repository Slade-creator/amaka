/** Phone UI primitives for the AMAKA mobile shell. */

import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type TouchEvent as ReactTouchEvent,
} from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, ArrowDown, ChevronLeft, Loader2, RotateCcw, X } from "lucide-react";
import { Haptics, ImpactStyle } from "@capacitor/haptics";
import { isNative } from "../lib/platform";
import type { FleetStatus } from "../fleet/fleetApi";

/* ------------------------------------------------------------------ */
/* haptics                                                             */
/* ------------------------------------------------------------------ */

export function tap(style: "light" | "medium" = "light"): void {
  if (!isNative()) return;
  void Haptics.impact({ style: style === "light" ? ImpactStyle.Light : ImpactStyle.Medium }).catch(
    () => {},
  );
}

/* ------------------------------------------------------------------ */
/* top bar                                                             */
/* ------------------------------------------------------------------ */

export function TopBar({
  title,
  subtitle,
  onBack,
  right,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  onBack?: () => void;
  right?: ReactNode;
}) {
  return (
    <header className="m-topbar">
      {onBack ? (
        <button type="button" className="m-icon-btn m-back" onClick={onBack} aria-label="Back">
          <ChevronLeft size={24} aria-hidden="true" />
        </button>
      ) : null}
      <div className="m-topbar-text">
        <h1 className="m-topbar-title">{title}</h1>
        {subtitle ? <p className="m-topbar-sub">{subtitle}</p> : null}
      </div>
      {right ? <div className="m-topbar-right">{right}</div> : null}
    </header>
  );
}

/* ------------------------------------------------------------------ */
/* segmented control                                                   */
/* ------------------------------------------------------------------ */

export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  label,
  stretch,
}: {
  value: T;
  options: Array<{ value: T; label: ReactNode; badge?: number }>;
  onChange: (v: T) => void;
  label: string;
  stretch?: boolean;
}) {
  return (
    <div className={`m-seg${stretch ? " is-stretch" : ""}`} role="tablist" aria-label={label}>
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="tab"
          aria-selected={o.value === value}
          className={`m-seg-btn${o.value === value ? " is-active" : ""}`}
          onClick={() => {
            if (o.value !== value) {
              tap();
              onChange(o.value);
            }
          }}
        >
          {o.label}
          {o.badge ? <span className="m-seg-badge">{o.badge}</span> : null}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* status                                                              */
/* ------------------------------------------------------------------ */

const STATUS_LABEL: Record<FleetStatus, string> = {
  critical: "Critical",
  warning: "Warning",
  nominal: "Nominal",
};

export function StatusPill({ status }: { status: FleetStatus }) {
  return <span className={`m-pill is-${status}`}>{STATUS_LABEL[status]}</span>;
}

export function StatusDot({ status }: { status: FleetStatus | "info" }) {
  return <span className={`m-dot is-${status}`} aria-hidden="true" />;
}

/* ------------------------------------------------------------------ */
/* states                                                              */
/* ------------------------------------------------------------------ */

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="m-state is-error" role="alert">
      <AlertTriangle size={22} aria-hidden="true" />
      <p>{message}</p>
      {onRetry ? (
        <button type="button" className="m-btn" onClick={onRetry}>
          <RotateCcw size={15} aria-hidden="true" />
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({ icon, title, body }: { icon?: ReactNode; title: string; body?: string }) {
  return (
    <div className="m-state">
      {icon}
      <p className="m-state-title">{title}</p>
      {body ? <p>{body}</p> : null}
    </div>
  );
}

export function Skeleton({ h = 64, w = "100%" }: { h?: number; w?: string }) {
  return <div className="skeleton m-skel" style={{ height: h, width: w }} aria-hidden="true" />;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="m-spinner" role="status">
      <Loader2 size={20} className="m-spin" aria-hidden="true" />
      {label ? <span>{label}</span> : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* bottom sheet                                                        */
/* ------------------------------------------------------------------ */

export function Sheet({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const [mounted, setMounted] = useState(open);
  useEffect(() => {
    if (open) setMounted(true);
    else {
      const t = window.setTimeout(() => setMounted(false), 220);
      return () => window.clearTimeout(t);
    }
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!mounted) return null;
  // Portal to <body>: pushed screens create their own stacking context, which
  // would otherwise put the sheet underneath the tab bar.
  return createPortal(
    <div className={`m-sheet-root${open ? " is-open" : ""}`}>
      <button type="button" className="m-sheet-scrim" aria-label="Close" onClick={onClose} />
      <div className="m-sheet" role="dialog" aria-modal="true" aria-label={title}>
        <div className="m-sheet-grip" aria-hidden="true" />
        <div className="m-sheet-head">
          <h2>{title}</h2>
          <button type="button" className="m-icon-btn" onClick={onClose} aria-label="Close">
            <X size={20} aria-hidden="true" />
          </button>
        </div>
        <div className="m-sheet-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}

/* ------------------------------------------------------------------ */
/* scroll view with pull-to-refresh                                    */
/* ------------------------------------------------------------------ */

const PULL_TRIGGER = 72;

export function ScrollView({
  children,
  onRefresh,
  className = "",
  resetKey,
}: {
  children: ReactNode;
  onRefresh?: () => Promise<unknown> | void;
  className?: string;
  /** Scroll back to the top whenever this value changes (e.g. a sub-tab). */
  resetKey?: string | number;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    ref.current?.scrollTo({ top: 0 });
  }, [resetKey]);
  const startY = useRef<number | null>(null);
  const [pull, setPull] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  const onStart = (e: ReactTouchEvent) => {
    if (!onRefresh || refreshing) return;
    if ((ref.current?.scrollTop ?? 0) <= 0) startY.current = e.touches[0].clientY;
  };
  const onMove = (e: ReactTouchEvent) => {
    if (startY.current === null) return;
    const dy = e.touches[0].clientY - startY.current;
    if (dy <= 0) {
      setPull(0);
      return;
    }
    setPull(Math.min(110, dy * 0.5));
  };
  const onEnd = () => {
    if (startY.current === null) return;
    startY.current = null;
    if (pull >= PULL_TRIGGER * 0.75 && onRefresh) {
      tap("medium");
      setRefreshing(true);
      setPull(PULL_TRIGGER * 0.75);
      Promise.resolve(onRefresh()).finally(() => {
        setRefreshing(false);
        setPull(0);
      });
    } else {
      setPull(0);
    }
  };

  const ready = pull >= PULL_TRIGGER * 0.75;
  return (
    <div
      ref={ref}
      className={`m-scroll ${className}`}
      onTouchStart={onStart}
      onTouchMove={onMove}
      onTouchEnd={onEnd}
      onTouchCancel={onEnd}
    >
      {onRefresh ? (
        <div className="m-ptr" style={{ height: pull }} aria-hidden={!refreshing}>
          {refreshing ? (
            <Loader2 size={18} className="m-spin" aria-label="Refreshing" />
          ) : pull > 8 ? (
            <ArrowDown size={18} style={{ transform: ready ? "rotate(180deg)" : undefined }} />
          ) : null}
        </div>
      ) : null}
      <div className="m-scroll-inner">{children}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* cards                                                               */
/* ------------------------------------------------------------------ */

export function Card({
  title,
  right,
  children,
  className = "",
  flush,
}: {
  title?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  flush?: boolean;
}) {
  return (
    <section className={`m-card ${className}`}>
      {title || right ? (
        <div className="m-card-head">
          {title ? <h2>{title}</h2> : <span />}
          {right}
        </div>
      ) : null}
      <div className={flush ? "" : "m-card-body"}>{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  unit,
  note,
  tone,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  note?: ReactNode;
  tone?: "critical" | "warning" | "good";
}) {
  return (
    <div className="m-stat">
      <span className="m-stat-label">{label}</span>
      <span className={`m-stat-value${tone ? ` is-${tone}` : ""}`}>
        {value}
        {unit ? <small>{unit}</small> : null}
      </span>
      {note ? <span className="m-stat-note">{note}</span> : null}
    </div>
  );
}
