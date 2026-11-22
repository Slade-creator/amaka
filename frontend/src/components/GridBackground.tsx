import { useEffect, useState } from "react";
import { cssVar, tint } from "../theme/theme";
import { GRID_BG } from "../config/visuals";
import GridCanvas from "./GridCanvas";

type Props = {
  /** 0..1 — overall energy (fleet load). Drives how strongly the lines glow. */
  intensity?: number;
  /** 0..1 — share of the fleet at risk. Turns the glow from accent to warm. */
  risk?: number;
  className?: string;
};

/**
 * Persistent full-screen background: the lit transmission-tower scene
 * (GridCanvas) under scrims that keep data legible. Fades in after first paint.
 */
export default function GridBackground({ intensity, risk, className }: Props) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setReady(true);
      return;
    }
    const frame = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <div
      className={className}
      aria-hidden="true"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 0,
        overflow: "hidden",
        pointerEvents: "none",
        opacity: ready ? 1 : 0,
        transition: "opacity 800ms ease-out",
        background: `linear-gradient(180deg, ${cssVar("bg-lift")} 0%, ${cssVar("bg")} 58%, ${cssVar("bg-deep")} 100%)`,
      }}
    >
      <GridCanvas intensity={intensity} risk={risk} />
      {/* Centre scrim: the towers stay visible in the gutters and softly behind data. */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(ellipse at 50% 45%, ${tint("bg", GRID_BG.scrim.center)} 0%, ${tint("bg", GRID_BG.scrim.mid)} 55%, ${tint("bg", GRID_BG.scrim.edge)} 100%)`,
        }}
      />
      {/* Header scrim so the wordmark and classification strip stay crisp. */}
      <div
        style={{
          position: "absolute",
          inset: "0 0 auto 0",
          height: GRID_BG.headerScrimPx,
          background: `linear-gradient(180deg, ${tint("bg", 0.96)} 0px, ${tint("bg", 0.72)} ${GRID_BG.headerScrimPx / 2}px, ${tint("bg", 0)} ${GRID_BG.headerScrimPx}px)`,
        }}
      />
    </div>
  );
}
