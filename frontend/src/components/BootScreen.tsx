import { RotateCcw } from "lucide-react";
import { AmakaMark } from "./ui";

type Props = {
  state: "loading" | "error";
  message?: string | null;
  onRetry?: () => void;
};

/**
 * Boot gate — AMAKA mark + skeleton while /api/overview loads,
 * or a clear failure card with retry when the backend is unreachable.
 */
export default function BootScreen({ state, message, onRetry }: Props) {
  const error = state === "error";

  return (
    <div className="boot" role={error ? "alert" : "status"} aria-live="polite">
      <div className="flex w-[min(430px,92vw)] flex-col items-center">
        <AmakaMark size={54} />
        <div
          className="mt-3 text-[22px] font-semibold text-fg"
          style={{ letterSpacing: "0.34em", paddingLeft: "0.34em" }}
        >
          AMAKA
        </div>
        <div className="label mt-1 text-[10.5px]" style={{ letterSpacing: "0.32em" }}>
          ENERGY COMMAND
        </div>

        {error ? (
          <div className="mt-7 w-full border border-[rgb(var(--crit-hot-rgb)/0.45)] bg-[rgb(var(--crit-hot-rgb)/0.07)] px-4 py-4 text-center">
            <div className="label text-[11px]" style={{ color: "var(--crit-hot)" }}>
              DATA LINK FAILED
            </div>
            <p className="num mt-2 text-[11px] leading-relaxed text-dim">
              {message || "Data service unreachable."}
            </p>
            <p className="num mt-1 text-[10.5px] text-dim">
              Start the local data service on 127.0.0.1:8000, then retry.
            </p>
            {onRetry ? (
              <button type="button" className="btn btn-lime mt-3.5" onClick={onRetry}>
                <RotateCcw size={13} aria-hidden="true" />
                Retry
              </button>
            ) : null}
          </div>
        ) : (
          <div className="mt-7 w-full">
            <div className="label mb-3 text-center text-[11px] tracking-[0.3em]">
              LOADING DASHBOARD DATA…
            </div>
            <div className="flex flex-col gap-2.5" aria-hidden="true">
              <div className="skeleton h-8 w-full" />
              <div className="skeleton h-8 w-[86%]" />
              <div className="skeleton h-8 w-[64%]" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
