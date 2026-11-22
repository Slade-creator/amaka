/**
 * WGSL for the background tower scene: ray-marched steel lattice pylons and
 * sagging conductors over a moonlit night, lit like a photo studio.
 * Scene dimensions and camera come from config/visuals.ts (GRID_SCENE).
 */

import { GRID_SCENE as S } from "../config/visuals";

const f = (n: number): string => (Number.isInteger(n) ? `${n}.0` : String(n));

/** 4 scalars (time, aspect, glow, risk) + 5 vec4 (accent, warm, base, deep, camera = speed, offset, energize, 0). */
export const GRID_UNIFORM_FLOATS = 24;

export const GRID_WGSL = /* wgsl */ `
struct Uniforms {
  time: f32,
  aspect: f32,
  glow: f32,
  risk: f32,
  accent: vec4f,
  warm: vec4f,
  base: vec4f,
  deep: vec4f,
  cam: vec4f,
};
@group(0) @binding(0) var<uniform> u: Uniforms;

struct VSOut {
  @builtin(position) pos: vec4f,
  @location(0) uv: vec2f,
};

@vertex
fn vs(@builtin(vertex_index) vi: u32) -> VSOut {
  var positions = array<vec2f, 3>(
    vec2f(-1.0, -1.0),
    vec2f( 3.0, -1.0),
    vec2f(-1.0,  3.0)
  );
  var out: VSOut;
  let p = positions[vi];
  out.pos = vec4f(p, 0.0, 1.0);
  out.uv = p * 0.5 + vec2f(0.5);
  return out;
}

const PI: f32 = 3.14159265;
const SPAN: f32 = ${f(S.span)};
const ROW: f32 = ${f(S.rowOffset)};
const SAG: f32 = ${f(S.sag)};
const FOG: f32 = ${f(S.fog)};
const MAX_DIST: f32 = ${f(S.maxDistance)};

fn hash21(p: vec2f) -> f32 {
  var p3 = fract(vec3f(p.x, p.y, p.x) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}

fn lin(c: vec3f) -> vec3f { return pow(c, vec3f(2.2)); }

fn sdSeg(p: vec3f, a: vec3f, b: vec3f) -> f32 {
  let pa = p - a;
  let ba = b - a;
  let h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
  return length(pa - ba * h);
}

// Tower half-width at height y: tapers from the base to the waist, then the head.
fn halfW(y: f32) -> f32 {
  return select(0.6 - 0.2 * (y - 19.0) / 10.0, 3.0 - 2.4 * y / 19.0, y < 19.0);
}

// Lattice pylon in local coordinates (x across the line, y up, z along it).
fn pylon(q0: vec3f, r: f32) -> f32 {
  let q = vec3f(abs(q0.x), q0.y, abs(q0.z));
  // Fold into one octant so the four faces share one set of braces.
  let fq = select(q, vec3f(q.z, q.y, q.x), q.z > q.x);
  var d = 1.0e9;
  // Legs.
  d = min(d, sdSeg(fq, vec3f(3.0, 0.0, 3.0), vec3f(0.6, 19.0, 0.6)));
  d = min(d, sdSeg(fq, vec3f(0.6, 19.0, 0.6), vec3f(0.4, 29.0, 0.4)));
  // Six panels: horizontal bar + X bracing (folded to a V).
  for (var k = 0; k < 6; k++) {
    let y0 = f32(k) * 3.8;
    let y1 = y0 + 3.8;
    let w0 = halfW(y0);
    let w1 = halfW(y1);
    let ym = y0 + (y1 - y0) * w0 / (w0 + w1);
    let wm = halfW(ym);
    d = min(d, sdSeg(fq, vec3f(w0, y0, w0), vec3f(wm, ym, 0.0)));
    d = min(d, sdSeg(fq, vec3f(wm, ym, 0.0), vec3f(w1, y1, w1)));
    d = min(d, sdSeg(fq, vec3f(w0, y0, 0.0), vec3f(w0, y0, w0)));
  }
  // Cross arms, their struts, and the peak.
  d = min(d, sdSeg(q, vec3f(0.6, 20.4, 0.0), vec3f(4.6, 20.4, 0.0)));
  d = min(d, sdSeg(q, vec3f(0.5, 24.2, 0.0), vec3f(3.7, 24.2, 0.0)));
  d = min(d, sdSeg(q, vec3f(0.6, 18.6, 0.0), vec3f(4.6, 20.4, 0.0)));
  d = min(d, sdSeg(q, vec3f(0.5, 21.6, 0.0), vec3f(3.7, 24.2, 0.0)));
  d = min(d, sdSeg(q, vec3f(0.0, 29.0, 0.0), vec3f(0.0, 31.2, 0.0)));
  let members = d - (0.09 + r);
  // Insulator strings hang from the arm tips (thicker than the lattice).
  let ins = min(
    sdSeg(q, vec3f(4.6, 20.4, 0.0), vec3f(4.6, 18.7, 0.0)),
    sdSeg(q, vec3f(3.7, 24.2, 0.0), vec3f(3.7, 22.5, 0.0))
  ) - (0.15 + r);
  return min(members, ins);
}

// Conductors: three families (two phase wires per side, one shield wire), sagging between towers.
fn wires(q: vec3f, r: f32) -> f32 {
  let s = abs(q.z) / SPAN;
  let sag = 4.0 * SAG * s * (1.0 - s);
  let ax = abs(q.x);
  let d1 = length(vec2f(ax - 4.6, q.y - (18.7 - sag)));
  let d2 = length(vec2f(ax - 3.7, q.y - (22.5 - sag)));
  let d3 = length(vec2f(ax, q.y - (28.6 - sag * 0.7)));
  return min(d1, min(d2, d3)) - r;
}

// x = distance, y = material (0 ground, 1 steel, 2 conductor), z = distance to the nearest conductor.
fn map(p: vec3f, r: f32) -> vec3f {
  let right = p.x >= 0.0;
  let zs = p.z + select(0.0, SPAN * 0.5, right);   // the two rows are offset by half a span
  let zq = zs - SPAN * floor(zs / SPAN + 0.5);
  let q = vec3f(abs(p.x) - ROW, p.y, zq);

  let dw = wires(q, 0.10 + r);
  var dt = max(length(vec2f(q.x, q.z)) - 5.2, p.y - 31.5);
  if (dt < 1.2) {
    dt = pylon(q, r);
  }
  var res = vec3f(p.y, 0.0, dw);
  if (dt < res.x) { res = vec3f(dt, 1.0, dw); }
  if (dw < res.x) { res = vec3f(dw, 2.0, dw); }
  return res;
}

// Power arrives from the far end of the line and sweeps toward the viewer as
// cam.z (energize) goes 0 -> 1. At 1 everything ahead of the camera is live.
fn lit(z: f32, camZ: f32) -> f32 {
  let reach = camZ + (1.0 - u.cam.z) * 130.0;
  return smoothstep(reach - 10.0, reach + 10.0, z);
}

fn pulse(z: f32, phase: f32) -> f32 {
  return pow(0.5 + 0.5 * sin(z * 0.34 - u.time * (1.5 + u.glow * 1.5) + phase), 16.0);
}

fn studio(rd: vec3f) -> vec3f {
  var c = mix(lin(u.deep.rgb), lin(u.base.rgb) * 1.8, smoothstep(-0.3, 0.9, rd.y));
  let top = smoothstep(0.36, 0.68, rd.y) * smoothstep(1.10, 0.10, abs(rd.x + 0.10));
  c += vec3f(0.60, 0.68, 0.64) * top * 1.1;
  let strip = smoothstep(0.22, 0.0, abs(rd.x + 0.78)) * smoothstep(-0.05, 0.30, rd.y) * smoothstep(0.95, 0.55, rd.y);
  c += vec3f(0.85, 0.95, 0.90) * strip * 0.9;
  return c;
}

fn sky(rd: vec3f, glowCol: vec3f) -> vec3f {
  let deep = lin(u.deep.rgb);
  var c = mix(deep * 4.5, deep * 0.7, smoothstep(0.0, 0.55, rd.y));
  // Stars.
  let cellp = floor(vec2f(atan2(rd.x, rd.z) * 160.0, rd.y * 160.0));
  let star = step(0.996, hash21(cellp)) * smoothstep(0.08, 0.3, rd.y);
  c += vec3f(0.8, 0.9, 0.85) * star * (0.4 + 0.6 * hash21(cellp + 3.0));
  // Moon and its halo (the key light).
  let md = max(dot(rd, normalize(vec3f(${S.moon.map(f).join(", ")}))), 0.0);
  c += vec3f(0.75, 0.85, 0.9) * (pow(md, 600.0) * 2.0 + pow(md, 30.0) * 0.07);
  // Glow of the lines on the horizon.
  c += glowCol * exp(-abs(rd.y) * 10.0) * 0.05 * u.glow;
  return c;
}

fn aces(x: vec3f) -> vec3f {
  return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), vec3f(0.0), vec3f(1.0));
}

@fragment
fn fs(in: VSOut) -> @location(0) vec4f {
  let uv = in.uv;
  let t = u.time;
  let p = vec2f((uv.x - 0.5) * u.aspect, uv.y - 0.5) * 2.0;

  // Camera drifts down the line between the two rows.
  let pitch = ${f(S.camera.pitch)};
  let d0 = normalize(vec3f(p.x * ${f(S.camera.lens)}, p.y * ${f(S.camera.lens)}, 1.0));
  let rd = vec3f(
    d0.x,
    d0.y * cos(pitch) - d0.z * sin(pitch),
    d0.y * sin(pitch) + d0.z * cos(pitch)
  );
  let ro = vec3f(sin(t * 0.05) * 1.2, ${f(S.camera.height)} + sin(t * 0.07) * 0.25, u.cam.y + t * u.cam.x);

  let glowCol = mix(lin(u.accent.rgb), lin(u.warm.rgb), clamp(u.risk, 0.0, 1.0));

  // Ray march.
  var tm = 0.0;
  var halo = 0.0;
  var matId = -1.0;
  for (var i = 0; i < ${S.maxMarchSteps}; i++) {
    let pos = ro + rd * tm;
    let h = map(pos, tm * 0.0016);
    let phase = select(0.0, 2.4, pos.x >= 0.0);
    halo += exp(-h.z * 1.2) * pulse(pos.z, phase) * clamp(h.x, 0.05, 1.0) * 0.22 * lit(pos.z, ro.z);
    if (h.x < 0.0012 * tm + 0.0008) {
      matId = h.y;
      break;
    }
    tm += h.x * 0.85;
    if (tm > MAX_DIST) { break; }
  }

  var col: vec3f;
  let horizon = lin(u.deep.rgb) * 4.5 + glowCol * 0.03 * u.glow;
  if (matId < 0.0) {
    col = sky(rd, glowCol);
  } else {
    let pos = ro + rd * tm;
    let e = 0.004 + tm * 0.0012;
    let n = normalize(
      vec3f(1.0, -1.0, -1.0) * map(pos + vec3f(e, -e, -e), 0.0).x +
      vec3f(-1.0, -1.0, 1.0) * map(pos + vec3f(-e, -e, e), 0.0).x +
      vec3f(-1.0, 1.0, -1.0) * map(pos + vec3f(-e, e, -e), 0.0).x +
      vec3f(1.0, 1.0, 1.0) * map(pos + vec3f(e, e, e), 0.0).x
    );
    let v = -rd;
    let l = normalize(vec3f(${S.moon.map(f).join(", ")}));
    let hv = normalize(l + v);
    let noh = max(dot(n, hv), 0.0);
    let nol = max(dot(n, l), 0.0);
    let nov = max(dot(n, v), 0.001);

    let rough = select(0.38, 0.3, matId > 1.5);
    let a2 = rough * rough * rough * rough;
    let dd = noh * noh * (a2 - 1.0) + 1.0;
    let ggx = min(a2 / (PI * dd * dd), 40.0);
    let f0 = vec3f(0.56, 0.60, 0.58);
    let fres = f0 + (vec3f(1.0) - f0) * pow(1.0 - nov, 5.0);

    var albedo = vec3f(0.035, 0.04, 0.038);
    if (matId < 0.5) { albedo = lin(u.base.rgb) * 1.2; }
    // Steel: mostly reflection of the studio, a moonlit highlight, a cool rim.
    var metal = select(1.0, 0.0, matId < 0.5);
    col = albedo * (0.5 + 1.0 * nol);
    col += studio(reflect(rd, n)) * fres * metal * 3.4;
    col += vec3f(0.9, 0.97, 1.0) * ggx * nol * 0.9 * fres * metal;
    col += vec3f(0.35, 0.5, 0.45) * pow(1.0 - nov, 3.0) * 0.45 * metal;
    // Darker near the ground, brighter up high.
    col *= mix(0.45, 1.0, smoothstep(0.0, 14.0, pos.y));

    if (matId > 1.5) {
      // The conductor itself carries the travelling light.
      let ph = select(0.0, 2.4, pos.x >= 0.0);
      col += glowCol * (0.25 + pulse(pos.z, ph) * 3.2) * u.glow * lit(pos.z, ro.z);
    }
    if (matId < 0.5) {
      // Ground: faint ops grid in the glow colour.
      let g = abs(fract(pos.xz / 4.0 + 0.5) - 0.5) * 4.0;
      let line = 1.0 - smoothstep(0.0, 0.05 + tm * 0.004, min(g.x, g.y));
      col += glowCol * line * 0.05 * u.glow * exp(-tm * 0.03) * lit(pos.z, ro.z);
    }
    col = mix(col, horizon, 1.0 - exp(-tm * FOG));
  }

  // Volumetric halo around the travelling pulses.
  col += glowCol * halo * u.glow;

  // Vignette, tone-map, gamma, dither.
  let vig = 1.0 - smoothstep(0.55, 1.45, length(p * vec2f(0.8, 1.0)));
  col *= mix(0.55, 1.0, vig);
  col = pow(aces(col * 1.9), vec3f(1.0 / 2.2));
  col += (hash21(uv * vec2f(1920.0, 1080.0) + fract(t)) - 0.5) / 255.0;
  return vec4f(col, 1.0);
}
`;
