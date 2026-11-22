/**
 * Procedural power-grid night scene for the AMAKA intro (Canvas 2D).
 *
 * A camera dollies along two lines of lattice transmission pylons. Conductors
 * sag between towers (parabolic catenary), energise span by span, and carry
 * glowing pulses of power toward the viewer. Sparks crackle off insulators,
 * city lights glow on the horizon and a faint ops grid covers the ground.
 * Everything is real 3D projected to the screen, so it stays crisp at any
 * resolution and costs nothing in APK size.
 */

type V3 = { x: number; y: number; z: number };
import { color, rgba, type ColorToken } from "../theme/theme";

type P2 = { x: number; y: number; s: number };

const SPACING = 70; // world units between pylons
const CAM_H = 9; // camera height
const SPEED = 15; // dolly speed (units / s)
const ROWS = [
  { x: -16, towers: 12, alpha: 1 },
  { x: 34, towers: 10, alpha: 0.45 },
];
// Conductor attachment points on a tower (x offset, y), insulators hang below arms.
const ATTACH = [
  { x: -7.5, y: 18.6 },
  { x: 7.5, y: 18.6 },
  { x: -5.8, y: 24.6 },
  { x: 5.8, y: 24.6 },
  { x: 0, y: 30.5 },
];
const SAG = 4.2;

type Pulse = { row: number; wire: number; z: number; speed: number; hue: "lime" | "amber" };
type Spark = { x: number; y: number; vx: number; vy: number; life: number };

export type GridScene = {
  resize: (w: number, h: number, dpr: number) => void;
  frame: (tMs: number) => void;
};

/** `speed`: dolly speed in world units per second (the intro uses the default; backgrounds go slower). */
export function createGridScene(ctx: CanvasRenderingContext2D, speed: number = SPEED): GridScene {
  let W = 0;
  let H = 0;
  let f = 0; // focal length (px)
  let horizon = 0;
  let cx = 0;
  let stars: Array<{ x: number; y: number; r: number; p: number }> = [];
  let city: Array<{ x: number; r: number; a: number }> = [];
  const pulses: Pulse[] = [];
  const sparks: Spark[] = [];
  let lastT = 0;
  let nextSpark = 900;
  let rand = mulberry(7);

  for (let i = 0; i < 26; i++) {
    pulses.push({
      row: i % 5 === 0 ? 1 : 0,
      wire: i % ATTACH.length,
      z: 40 + rand() * SPACING * 9,
      speed: 55 + rand() * 60,
      hue: rand() < 0.22 ? "amber" : "lime",
    });
  }

  function resize(w: number, h: number, dpr: number) {
    W = w;
    H = h;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    f = Math.max(w, h * 0.75) * 0.9;
    horizon = h * 0.6;
    cx = w * 0.42;
    rand = mulberry(11);
    stars = Array.from({ length: Math.round((w * h) / 5200) }, () => ({
      x: rand() * w,
      y: rand() * horizon * 0.92,
      r: rand() * 1.1 + 0.2,
      p: rand() * Math.PI * 2,
    }));
    city = Array.from({ length: 70 }, () => ({
      x: w * (0.5 + rand() * 0.5),
      r: rand() * 2.2 + 0.6,
      a: rand() * 0.6 + 0.2,
    }));
  }

  function project(p: V3, camZ: number): P2 | null {
    const z = p.z - camZ;
    if (z < 2) return null;
    const s = f / z;
    return { x: cx + p.x * s, y: horizon - (p.y - CAM_H) * s, s };
  }

  function wirePoint(rowX: number, wire: number, z: number): V3 {
    const a = ATTACH[wire];
    const i = Math.floor(z / SPACING);
    const t = z / SPACING - i;
    const sag = SAG * 4 * t * (1 - t);
    return { x: rowX + a.x, y: a.y - 2.2 - sag, z };
  }

  /* ----------------------------- drawing ----------------------------- */

  function sky(t: number) {
    const g = ctx.createLinearGradient(0, 0, 0, horizon);
    g.addColorStop(0, color("bg-void"));
    g.addColorStop(0.55, color("bg-lift"));
    g.addColorStop(1, color("scene-horizon"));
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, horizon + 1);
    for (const s of stars) {
      const tw = 0.45 + 0.55 * Math.sin(t / 900 + s.p);
      ctx.fillStyle = rgba("fg", 0.15 + tw * 0.45);
      ctx.fillRect(s.x, s.y, s.r, s.r);
    }
    // Horizon glow + distant city lights.
    const hg = ctx.createRadialGradient(W * 0.78, horizon, 0, W * 0.78, horizon, W * 0.7);
    hg.addColorStop(0, rgba("accent", 0.16));
    hg.addColorStop(0.4, rgba("teal", 0.05));
    hg.addColorStop(1, rgba("black", 0));
    ctx.fillStyle = hg;
    ctx.fillRect(0, 0, W, horizon + 2);
    for (const c of city) {
      ctx.fillStyle = rgba("warn-soft", c.a * (0.7 + 0.3 * Math.sin(t / 400 + c.x)));
      ctx.beginPath();
      ctx.arc(c.x, horizon - 1.5, c.r * 0.6, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function ground(camZ: number) {
    const g = ctx.createLinearGradient(0, horizon, 0, H);
    g.addColorStop(0, color("bg-lift"));
    g.addColorStop(1, color("bg-void"));
    ctx.fillStyle = g;
    ctx.fillRect(0, horizon, W, H - horizon);
    // Hills silhouette on the horizon.
    ctx.fillStyle = color("bg-void");
    ctx.beginPath();
    ctx.moveTo(0, horizon + 2);
    for (let x = 0; x <= W; x += 24) {
      const y = horizon - 6 - 10 * Math.sin(x / 140) - 6 * Math.sin(x / 47 + 1.3);
      ctx.lineTo(x, Math.min(horizon + 2, y));
    }
    ctx.lineTo(W, horizon + 2);
    ctx.closePath();
    ctx.fill();
    // Ops grid on the ground plane (scrolls with the dolly).
    ctx.lineWidth = 1;
    const step = 20;
    const off = camZ % step;
    for (let i = 1; i < 40; i++) {
      const z = i * step - off;
      const p = project({ x: 0, y: 0, z: camZ + z }, camZ);
      if (!p || p.y > H) continue;
      ctx.strokeStyle = rgba("accent", Math.min(0.09, 0.9 / z));
      ctx.beginPath();
      ctx.moveTo(0, p.y);
      ctx.lineTo(W, p.y);
      ctx.stroke();
    }
    for (let x = -200; x <= 200; x += 20) {
      const a = project({ x, y: 0, z: camZ + 4 }, camZ);
      const b = project({ x, y: 0, z: camZ + 900 }, camZ);
      if (!a || !b) continue;
      ctx.strokeStyle = rgba("accent", 0.05);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }
  }

  function tower(rowX: number, z: number, camZ: number, alpha: number) {
    const P = (x: number, y: number) => project({ x: rowX + x, y, z }, camZ);
    const legsL: Array<[number, number]> = [
      [-4.2, 0],
      [-1.6, 17],
      [-1.0, 30],
    ];
    const pts = legsL.map(([x, y]) => [P(x, y), P(-x, y)] as const);
    if (pts.some(([a, b]) => !a || !b)) return;
    const s = pts[0][0]!.s;
    ctx.globalAlpha = alpha * Math.min(1, s * 0.9);
    ctx.strokeStyle = rgba("fg-3", 0.55);
    ctx.lineWidth = Math.max(0.6, s * 0.22);
    ctx.beginPath();
    for (const side of [0, 1] as const) {
      ctx.moveTo(pts[0][side]!.x, pts[0][side]!.y);
      for (let k = 1; k < pts.length; k++) ctx.lineTo(pts[k][side]!.x, pts[k][side]!.y);
    }
    // Lattice bracing.
    const levels = [0, 4, 8, 12, 17, 21, 25, 30];
    for (let k = 0; k < levels.length - 1; k++) {
      const y0 = levels[k];
      const y1 = levels[k + 1];
      const w0 = halfWidth(y0);
      const w1 = halfWidth(y1);
      const a = P(-w0, y0);
      const b = P(w1, y1);
      const c = P(w0, y0);
      const d = P(-w1, y1);
      if (a && b && c && d) {
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.moveTo(c.x, c.y);
        ctx.lineTo(d.x, d.y);
        ctx.moveTo(d.x, d.y);
        ctx.lineTo(b.x, b.y);
      }
    }
    // Cross arms + insulators.
    for (const [y, span] of [
      [18.6, 7.5],
      [24.6, 5.8],
    ] as const) {
      const l = P(-span, y);
      const r = P(span, y);
      const ml = P(-halfWidth(y), y - 1.8);
      const mr = P(halfWidth(y), y - 1.8);
      if (l && r && ml && mr) {
        ctx.moveTo(l.x, l.y);
        ctx.lineTo(r.x, r.y);
        ctx.moveTo(l.x, l.y);
        ctx.lineTo(ml.x, ml.y);
        ctx.moveTo(r.x, r.y);
        ctx.lineTo(mr.x, mr.y);
        for (const sx of [-span, span]) {
          const top = P(sx, y);
          const bot = P(sx, y - 2.2);
          if (top && bot) {
            ctx.moveTo(top.x, top.y);
            ctx.lineTo(bot.x, bot.y);
          }
        }
      }
    }
    ctx.stroke();
    // Aircraft warning light on the peak.
    const peak = P(0, 30.8);
    if (peak) {
      ctx.fillStyle = rgba("crit", 0.9);
      ctx.beginPath();
      ctx.arc(peak.x, peak.y, Math.max(0.8, s * 0.35), 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  function wires(rowX: number, z0: number, z1: number, camZ: number, energy: number, alpha: number) {
    for (let w = 0; w < ATTACH.length; w++) {
      ctx.beginPath();
      let started = false;
      for (let k = 0; k <= 14; k++) {
        const z = z0 + ((z1 - z0) * k) / 14;
        const p = project(wirePoint(rowX, w, z), camZ);
        if (!p) {
          started = false;
          continue;
        }
        if (!started) {
          ctx.moveTo(p.x, p.y);
          started = true;
        } else ctx.lineTo(p.x, p.y);
      }
      const near = project({ x: rowX, y: 20, z: z0 }, camZ);
      const s = near?.s ?? 0.1;
      ctx.lineWidth = Math.max(0.5, s * 0.16);
      ctx.strokeStyle = rgba("accent", alpha * (0.12 + 0.5 * energy));
      ctx.shadowColor = rgba("accent", 0.8);
      ctx.shadowBlur = energy > 0.5 ? 6 * energy : 0;
      ctx.stroke();
    }
    ctx.shadowBlur = 0;
  }

  function drawPulses(camZ: number, dt: number, reach: number) {
    ctx.globalCompositeOperation = "lighter";
    for (const p of pulses) {
      p.z -= p.speed * dt;
      if (p.z < camZ + 4) p.z = camZ + SPACING * (6 + Math.random() * 5);
      if (p.z > camZ + reach) continue;
      const row = ROWS[p.row];
      const col: ColorToken = p.hue === "amber" ? "warn" : "accent";
      for (let k = 0; k < 6; k++) {
        const pt = project(wirePoint(row.x, p.wire, p.z + k * 2.2), camZ);
        if (!pt) continue;
        const r = Math.max(0.8, pt.s * (0.9 - k * 0.12));
        ctx.fillStyle = rgba(col, (0.95 - k * 0.15) * row.alpha);
        ctx.shadowColor = rgba(col, 1);
        ctx.shadowBlur = k === 0 ? 14 : 0;
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, r, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.shadowBlur = 0;
    ctx.globalCompositeOperation = "source-over";
  }

  function drawSparks(camZ: number, dt: number, tMs: number) {
    if (tMs > nextSpark) {
      nextSpark = tMs + 700 + Math.random() * 1300;
      const zi = Math.ceil((camZ + 30) / SPACING) * SPACING + SPACING * Math.floor(Math.random() * 2);
      const w = Math.floor(Math.random() * 4);
      const a = ATTACH[w];
      const p = project({ x: ROWS[0].x + a.x, y: a.y - 2.2, z: zi }, camZ);
      if (p) {
        for (let i = 0; i < 16; i++) {
          const ang = Math.random() * Math.PI * 2;
          const v = (40 + Math.random() * 120) * Math.min(2.2, p.s);
          sparks.push({ x: p.x, y: p.y, vx: Math.cos(ang) * v, vy: Math.sin(ang) * v - 40, life: 1 });
        }
      }
    }
    ctx.globalCompositeOperation = "lighter";
    for (let i = sparks.length - 1; i >= 0; i--) {
      const s = sparks[i];
      s.life -= dt * 1.8;
      if (s.life <= 0) {
        sparks.splice(i, 1);
        continue;
      }
      s.vy += 260 * dt;
      s.x += s.vx * dt;
      s.y += s.vy * dt;
      ctx.strokeStyle = rgba("accent-soft", s.life);
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      ctx.lineTo(s.x - s.vx * 0.02, s.y - s.vy * 0.02);
      ctx.stroke();
    }
    ctx.globalCompositeOperation = "source-over";
  }

  function frame(tMs: number) {
    const dt = lastT ? Math.min(0.05, (tMs - lastT) / 1000) : 0;
    lastT = tMs;
    const camZ = (tMs / 1000) * speed;
    // Power arrives from the far end: spans light up from 0.5 s to 2.2 s.
    const energize = clamp((tMs - 500) / 1700, 0, 1);

    sky(tMs);
    ground(camZ);

    const first = Math.floor(camZ / SPACING) * SPACING;
    for (let ri = ROWS.length - 1; ri >= 0; ri--) {
      const row = ROWS[ri];
      for (let i = row.towers; i >= 0; i--) {
        const z = first + i * SPACING;
        const spanFromFar = (row.towers - i) / row.towers;
        const e = clamp((energize - spanFromFar * 0.75) * 4, 0, 1);
        wires(row.x, z, z + SPACING, camZ, e, row.alpha);
        tower(row.x, z, camZ, row.alpha);
      }
    }
    drawPulses(camZ, dt, SPACING * 11 * energize);
    if (energize > 0.6) drawSparks(camZ, dt, tMs);

    // Vignette.
    const v = ctx.createRadialGradient(W / 2, H * 0.45, Math.min(W, H) * 0.3, W / 2, H * 0.5, Math.max(W, H) * 0.8);
    v.addColorStop(0, rgba("black", 0));
    v.addColorStop(1, rgba("black", 0.7));
    ctx.fillStyle = v;
    ctx.fillRect(0, 0, W, H);
  }

  return { resize, frame };
}

function halfWidth(y: number): number {
  if (y <= 17) return 4.2 - (2.6 * y) / 17;
  return 1.6 - (0.6 * (y - 17)) / 13;
}

function clamp(v: number, a: number, b: number): number {
  return Math.max(a, Math.min(b, v));
}

function mulberry(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
