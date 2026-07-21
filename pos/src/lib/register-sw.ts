/*
 * Service-worker registration (Phase A offline support).
 *
 * Registers the POS service worker at `/sw-min.js`. The built SW is
 * copied to `ury/www/sw-min.js` and served by Frappe at `/sw-min.js`
 * with a `text/javascript` content-type — Frappe's TemplatePage serves
 * any `*.min.js` file as raw static source (a plain `www/*.js` is refused
 * by the StaticPage renderer). See ury/www/sw_min.py for the full
 * rationale. `/sw-min.js` has default scope `/`, which covers the `/pos`
 * navigation even though the app's assets live under `/assets/ury/pos/` —
 * no `Service-Worker-Allowed` header / nginx edit needed. See sw.ts for
 * the scope rationale + route whitelist.
 *
 * `updateViaCache: 'none'` makes the browser bypass the HTTP cache when
 * checking the SW script for updates, so a redeploy propagates promptly.
 *
 * Registration only runs in a production build (never in `vite dev`) and
 * only over a secure context (HTTPS or localhost) — browsers refuse to
 * register a SW otherwise, which is expected on plain-http dev sites.
 */
export function registerServiceWorker(): void {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return;
  // Vite strips this branch out of the production bundle.
  if (import.meta.env.DEV) return;
  // SW registration requires a secure context. `isSecureContext` is true
  // on HTTPS and on http://localhost, false on a plain-http LAN address.
  if (typeof window !== 'undefined' && !window.isSecureContext) return;

  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw-min.js', { scope: '/', updateViaCache: 'none' })
      .catch((err) => {
        // Non-fatal: the app still works online without the SW.
        console.warn('[ury-pos] service worker registration failed', err);
      });
  });
}
