// Fails the build if a colour literal appears in src/ outside src/theme/.
// Colours belong in theme/palette.json; use var(--token), tint() or color().
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "src");
const literal = /#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b(?![\w-])|\brgba?\(\s*\d/;
const bad = [];

function walk(dir) {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) {
      if (name !== "theme") walk(full);
    } else if (/\.(css|ts|tsx)$/.test(name)) {
      readFileSync(full, "utf8").split("\n").forEach((line, i) => {
        if (literal.test(line)) bad.push(`${path.relative(root, full)}:${i + 1}: ${line.trim().slice(0, 100)}`);
      });
    }
  }
}
walk(root);
if (bad.length) {
  console.error(`Hardcoded colours found (use theme tokens; see docs/THEMING_AND_CONFIG.md):\n  ${bad.join("\n  ")}`);
  process.exit(1);
}
console.log("check-theme: no hardcoded colours");
