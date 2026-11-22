import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { readFileSync } from "node:fs";

/** Browser theme-color comes from the palette, not a literal in index.html. */
const palette = JSON.parse(readFileSync(new URL("./theme/palette.json", import.meta.url), "utf8"));
const flat: Record<string, string> = Object.assign({}, ...Object.values(palette.groups as Record<string, Record<string, string>>));
const themeColorPlugin = () => ({
  name: "amaka-theme-color",
  transformIndexHtml: (html: string) => html.replace("%THEME_COLOR%", flat[palette.native.themeColor]),
});

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  // A native bundle has no same-origin API, so fail loudly instead of shipping
  // an APK that calls https://localhost/api and shows "data service unreachable".
  if (mode === "mobile" && !env.VITE_API_BASE_URL) {
    throw new Error(
      "VITE_API_BASE_URL is required for mobile builds. Copy frontend/.env.mobile.example " +
        "to frontend/.env.mobile.local and set the API origin (for example " +
        "http://192.168.1.20:8000 or your HTTPS deployment URL).",
    );
  }

  return {
    plugins: [react(), tailwindcss(), themeColorPlugin()],
    server: {
      port: 5173,
      proxy: {
        "/api": "http://127.0.0.1:8000",
      },
      // Gradle rewrites android/ during APK builds; don't reload the dev page.
      watch: {
        ignored: ["**/android/**"],
      },
    },
    build: {
      outDir: "dist",
      sourcemap: false,
    },
  };
});
