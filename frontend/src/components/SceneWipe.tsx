import type { CSSProperties } from "react";

type Props = {
  active: boolean;
  label: string;
  accent?: string;
  /** Entering a site or returning to the fleet map. */
  mode?: "enter" | "fleet";
  /** Screen-space origin of the iris (the clicked site marker). */
  x?: number;
  y?: number;
};

/**
 * Full-screen hex iris used between the fleet map and the site view.
 * The map zooms first; this field closes over it, the route swaps underneath,
 * then the iris opens onto the site view. It is decorative only (aria-hidden).
 */
export default function SceneWipe({
  active,
  label,
  accent = "var(--accent)",
  mode = "enter",
  x,
  y,
}: Props) {
  return (
    <div
      className={`scene-wipe${active ? " is-on" : ""} is-${mode}`}
      style={
        {
          "--wipe-acc": accent,
          "--wipe-x": x !== undefined ? `${x}px` : "50%",
          "--wipe-y": y !== undefined ? `${y}px` : "50%",
        } as CSSProperties
      }
      aria-hidden="true"
    >
      <div className="scene-wipe-field">
        <div className="scene-wipe-ring" />
      </div>
      <div className="scene-wipe-center">
        <span className="scene-wipe-kicker">
          {mode === "enter" ? "OPENING SITE VIEW" : "RETURNING TO FLEET"}
        </span>
        <span className="scene-wipe-label">{label}</span>
      </div>
    </div>
  );
}
