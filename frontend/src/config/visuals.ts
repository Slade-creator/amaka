/**
 * Tunables for the animated visuals (background scene, intro, map switch).
 * Colours are NOT here: they live in theme/palette.json.
 */

/** Persistent app background (components/GridBackground.tsx). */
export const GRID_BG = {
  /** Cap on devicePixelRatio for the ray-marched canvas. */
  maxDpr: 1,
  /** Fraction of that resolution actually rendered (soft background, big saving). */
  renderScale: 0.8,
  /** Minimum ms between frames (33 ≈ 30 fps). */
  frameIntervalMs: 33,
  initialEnergy: 0.35,
  /** Per-frame easing toward the target energy / risk (0..1). */
  energyEase: 0.12,
  riskEase: 0.05,
  /** Glow strength = floor + energy * range. */
  glowFloor: 0.22,
  glowRange: 0.78,
  /** Time (s) shown when the OS asks for reduced motion: one still frame. */
  reducedMotionTime: 8,
  /** Opacity of the dark centre scrim that keeps data legible. */
  scrim: { center: 0.7, mid: 0.56, edge: 0.22 },
  headerScrimPx: 240,
  /** Canvas2D fallback: dolly speed (world units/s) and start offset. */
  fallbackSpeed: 3.5,
  fallbackStartMs: 4000,
} as const;

/** The lit tower scene (components/gridShader.ts). World units ≈ metres. */
export const GRID_SCENE = {
  /** Distance between towers along the line. */
  span: 26,
  /** Distance from the camera path to each row of towers. */
  rowOffset: 11,
  /** Conductor sag at mid-span. */
  sag: 3.2,
  camera: {
    height: 3.0,
    /** Radians; negative looks up so the towers loom. */
    pitch: -0.1,
    /** Forward drift, metres per second. */
    speed: 0.9,
    /** Horizontal field of view scale (lower = tighter). */
    lens: 0.6,
  },
  /** Exponential fog density per metre. */
  fog: 0.016,
  /** Direction toward the moon / key light. */
  moon: [-0.45, 0.55, 0.7],
  maxMarchSteps: 80,
  maxDistance: 150,
} as const;

/** Intro sequence (intro/PowerIntro.tsx). Times in ms. */
export const INTRO = {
  total: 5200,
  leaveFade: 480,
  /** Flythrough speed, metres per second (the background drifts at ~1). */
  cameraSpeed: 14,
  /** The line lights up from the far end to the viewer over this long. */
  energizeMs: 2300,
  /** Scene energy (glow strength) during the intro. */
  intensity: 1,
  /** Render sharper than the background: it is the focus for five seconds. */
  renderScale: 1,
  maxDpr: 1.25,
  /** Canvas2D fallback dolly speed. */
  fallbackSpeed: 15,
} as const;

/** Satellite map camera moves (mobile/map/satMap.ts). */
export const MAP_SWITCH = {
  skyZoom: 4.6,
  dropZooms: [8.2, 11.6],
  landZoom: 15,
  landPitch: 52,
  landBearing: -28,
  upMs: 340,
  sweepMs: 900,
  dropMs: 360,
  landMs: 1500,
} as const;
