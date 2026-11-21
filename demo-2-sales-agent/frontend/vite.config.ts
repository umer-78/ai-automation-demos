import { readFileSync } from "node:fs";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/** Ships src/seo/routes.json next to index.html so the API server can write per-page meta tags. */
function seoRoutes(): Plugin {
  return {
    name: "seo-routes",
    apply: "build",
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "seo-routes.json", source: readFileSync(new URL("./src/seo/routes.json", import.meta.url), "utf8") });
    },
  };
}

const api = process.env.VITE_DEV_API ?? "http://localhost:8001";

export default defineConfig({
  plugins: [react(), tailwindcss(), seoRoutes()],
  server: {
    port: 5174,
    proxy: { "/api": api },
  },
  build: {
    outDir: "../backend/app/static",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
});
