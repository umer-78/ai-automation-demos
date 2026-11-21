import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Public address of the deployed agent, e.g. https://acme-sales-agent.onrender.com (set at build time).
const SITE_URL = (process.env.SITE_URL ?? "").replace(/\/+$/, "");

/** Absolute URLs for search engines and link previews, plus robots.txt and sitemap.xml. */
function seo(): Plugin {
  return {
    name: "seo",
    transformIndexHtml(html) {
      if (!SITE_URL) html = html.replace(/^.*data-site-url.*\n/gm, "").replace(/\s*"url": "%SITE_URL%\/",/g, "");
      return html.replaceAll("%SITE_URL%", SITE_URL);
    },
    generateBundle() {
      const sitemap = SITE_URL ? `\nSitemap: ${SITE_URL}/sitemap.xml\n` : "";
      this.emitFile({ type: "asset", fileName: "robots.txt", source: `User-agent: *\nAllow: /\nDisallow: /api/\n${sitemap}` });
      if (SITE_URL) {
        this.emitFile({
          type: "asset",
          fileName: "sitemap.xml",
          source: `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n  <url><loc>${SITE_URL}/</loc><lastmod>${new Date().toISOString().slice(0, 10)}</lastmod></url>\n</urlset>\n`,
        });
      }
    },
  };
}

// The FastAPI backend serves the built files from ./dist on the same origin.
// During development, /api is proxied to the backend on port 8000.
export default defineConfig({
  plugins: [react(), tailwindcss(), seo()],
  base: "./",
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  // three.js and the scene are lazy-loaded (see App.tsx), so they land in their own chunk.
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1800 },
});
