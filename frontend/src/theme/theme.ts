/**
 * Colour access for code that cannot use CSS variables: <canvas>, WebGPU,
 * MapLibre paint properties. Values come from the generated TOKENS (itself
 * generated from theme/palette.json), so there is still one source of truth.
 *
 * In CSS and JSX prefer the variables directly:
 *   var(--accent)                 solid colour
 *   rgb(var(--accent-rgb)/0.3)    with transparency
 */

import { TOKENS, type ColorToken } from "./tokens";

export type { ColorToken };

/** "#rrggbb" for a token. */
export const color = (t: ColorToken): string => TOKENS[t];

/** [r, g, b] in 0–255. */
export function rgb255(t: ColorToken): [number, number, number] {
  const h = TOKENS[t];
  return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
}

/** [r, g, b] in 0–1 (sRGB, not linearised) — for shader uniforms. */
export function rgb01(t: ColorToken): [number, number, number] {
  const [r, g, b] = rgb255(t);
  return [r / 255, g / 255, b / 255];
}

/** "rgba(r,g,b,a)" for canvas fillStyle / strokeStyle / gradient stops. */
export function rgba(t: ColorToken, alpha: number): string {
  const [r, g, b] = rgb255(t);
  return `rgba(${r},${g},${b},${alpha})`;
}

/** `var(--token)` for inline styles and SVG attributes. */
export const cssVar = (t: ColorToken): string => `var(--${t})`;

/** `rgb(var(--token-rgb)/alpha)` for inline styles and SVG attributes. */
export const tint = (t: ColorToken, alpha: number): string => `rgb(var(--${t}-rgb)/${alpha})`;
