import { useEffect, useRef, useState } from "react";
import GridCanvas from "../components/GridCanvas";
import { INTRO } from "../config/visuals";
import { STORAGE } from "../config/app";
import "./intro.css";

type Props = {
  /** Called once the intro has finished or was skipped. */
  onDone: () => void;
};

/**
 * Should the intro play? Always on a cold start of the native app; once per
 * browser session on the web; never when the OS asks for reduced motion.
 */
export function shouldPlayIntro(native: boolean): boolean {
  try {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
    if (native) return true;
    if (new URLSearchParams(window.location.search).has("intro")) return true;
    if (window.sessionStorage.getItem(STORAGE.introSeen)) return false;
    window.sessionStorage.setItem(STORAGE.introSeen, "1");
  } catch {
    /* storage blocked — just play it */
  }
  return true;
}

/**
 * Opening sequence: a flythrough along a line of steel transmission towers
 * (lit WebGPU scene), the power lighting up from the far end, then the AMAKA
 * mark draws itself and the tagline lands. Tap anywhere to skip.
 */
export default function PowerIntro({ onDone }: Props) {
  const [leaving, setLeaving] = useState(false);
  const doneRef = useRef(false);

  const finish = () => {
    if (doneRef.current) return;
    doneRef.current = true;
    setLeaving(true);
    window.setTimeout(onDone, INTRO.leaveFade);
  };

  useEffect(() => {
    const end = window.setTimeout(finish, INTRO.total);
    return () => window.clearTimeout(end);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      className={`intro${leaving ? " is-leaving" : ""}`}
      onClick={finish}
      role="presentation"
      aria-label="AMAKA intro"
      style={{ ["--intro-total" as string]: `${INTRO.total}ms` }}
    >
      <GridCanvas
        className="intro-canvas"
        intensity={INTRO.intensity}
        cameraSpeed={INTRO.cameraSpeed}
        energizeMs={INTRO.energizeMs}
        fallbackSpeed={INTRO.fallbackSpeed}
        fallbackStartMs={0}
        renderScale={INTRO.renderScale}
        maxDpr={INTRO.maxDpr}
      />
      {/* Darkens the lower third so the brand reads over the scene. */}
      <div className="intro-shade" aria-hidden="true" />

      <div className="intro-brand">
        <svg className="intro-mark" viewBox="14 9 68 78" aria-hidden="true">
          <polygon className="im-hex" points="48,14 77,31 77,65 48,82 19,65 19,31" />
          <line className="im-thr" x1="27" y1="40" x2="69" y2="40" />
          <polyline className="im-spike" points="27,58 37,52 43,56 49,32 54,62 60,46 69,46" />
        </svg>
        <h1 className="intro-word" aria-label="AMAKA">
          {"AMAKA".split("").map((ch, i) => (
            <span key={i} style={{ animationDelay: `${2350 + i * 90}ms` }}>
              {ch}
            </span>
          ))}
        </h1>
        <p className="intro-sub">ENERGY COMMAND</p>
        <p className="intro-tag">See the peak before it hits.</p>
      </div>

      <button
        type="button"
        className="intro-skip"
        onClick={(e) => {
          e.stopPropagation();
          finish();
        }}
      >
        Skip
      </button>
      <div className="intro-progress" aria-hidden="true" />
    </div>
  );
}
