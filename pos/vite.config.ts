import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { fileURLToPath } from 'url'
import { dirname, resolve } from 'path'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // Offline PWA (Phase A). injectManifest (not generateSW) because the
    // /pos shell is rendered by Frappe (ury/www/pos.py), not emitted by
    // Vite — so we hand-write the SW (src/sw.ts) with our own navigation
    // handling. We register it manually (injectRegister: null) from
    // src/lib/register-sw.ts so we control the /sw.js URL + root scope,
    // and keep the committed public/manifest.json (manifest: false).
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      injectRegister: null,
      manifest: false,
      injectManifest: {
        // Precache the hashed app bundle only. NOT the HTML shell — it
        // carries a server-rendered CSRF token and is handled
        // NetworkFirst at runtime instead (see sw.ts).
        globPatterns: ['**/*.{js,css}'],
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
        // The SW is served from the origin root (/sw.js) so its default
        // scope covers /pos. Workbox resolves precache URLs relative to
        // the SW's location, so the default RELATIVE urls ("assets/...")
        // would wrongly resolve to /assets/... instead of the real
        // /assets/ury/pos/assets/... . Make them ABSOLUTE (base-prefixed)
        // so they resolve correctly no matter where the SW is served.
        manifestTransforms: [
          // Param type is inferred from workbox's ManifestTransform so the
          // spread preserves `size` (required by ManifestTransformResult).
          (entries) => ({
            manifest: entries.map((e) => ({
              ...e,
              url: e.url.startsWith('/') ? e.url : `/assets/ury/pos/${e.url}`,
            })),
            warnings: [],
          }),
        ],
      },
      devOptions: { enabled: false },
    }),
  ],
  resolve: {
    alias: {
      "@": resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: "../ury/public/pos",
    emptyOutDir: true,
  },
})
