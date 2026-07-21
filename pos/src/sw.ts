/// <reference lib="webworker" />
/*
 * URY POS service worker — Phase A (offline app-shell + connectivity).
 *
 * WHY A SERVICE WORKER: waiters run the POS as an installed PWA on
 * Android tablets. When the venue's internet drops, a reload/cold-open
 * used to show a blank screen because nothing was cached. This SW caches
 * the built app + the last-known boot data so the POS still loads and is
 * usable read-only while offline. It does NOT let orders be placed
 * offline — that's Phase B (an outbox + an idempotent backend endpoint).
 *
 * SCOPE (the crux): the app HTML is served at `/pos` but its assets live
 * at `/assets/ury/pos/`. Their only common prefix is `/`, so this SW is
 * served from `/sw-min.js` (the built SW is copied to `ury/www/sw-min.js`
 * at build time; Frappe serves any `*.min.js` www file as raw static JS —
 * see ury/www/sw_min.py) whose default scope `/` covers `/pos`. Because
 * that scope also covers the
 * Frappe Desk (`/app`), login, and any other app on the origin, this SW
 * only registers routes for `/pos*` navigations and `/assets/ury/pos/*`
 * + `/api/method/*` GETs. Everything else falls through to the network
 * untouched (workbox-routing does nothing when no route matches).
 *
 * CSRF: the `/pos` shell embeds a server-rendered CSRF token. We never
 * PREcache the shell HTML (a stale token would break POSTs). It's cached
 * NetworkFirst at runtime, so an online load always gets the freshest
 * token and offline only ever serves read-only.
 */
import { precacheAndRoute, cleanupOutdatedCaches } from 'workbox-precaching';
import { clientsClaim } from 'workbox-core';
import { registerRoute, NavigationRoute } from 'workbox-routing';
import { NetworkFirst } from 'workbox-strategies';
import { CacheableResponsePlugin } from 'workbox-cacheable-response';
import { ExpirationPlugin } from 'workbox-expiration';

declare const self: ServiceWorkerGlobalScope & {
  __WB_MANIFEST: Array<{ url: string; revision: string | null }>;
};

const SHELL_CACHE = 'ury-pos-shell-v1';
const API_CACHE = 'ury-pos-api-v1';
const ASSET_CACHE = 'ury-pos-assets-v1';
// Normalized fallback key so a hard reload at any /pos sub-route (e.g.
// /pos/orders) still resolves to a cached shell when offline.
const SHELL_KEY = '/pos';
const NAV_TIMEOUT_MS = 4000; // fail over to cache fast on a weak connection

// --- Precache the hashed build assets (JS/CSS). Injected by
// vite-plugin-pwa's injectManifest. URLs are absolute (/assets/ury/pos/*)
// so they resolve regardless of where this SW file itself is served. ---
precacheAndRoute(self.__WB_MANIFEST);
cleanupOutdatedCaches();

// A freshly-activated SW takes control of already-open clients. We do
// NOT call skipWaiting(): an UPDATED sw waits and activates on the next
// natural load so a cashier is never yanked mid-order. (A SKIP_WAITING
// message hook is wired below for when we want an explicit "reload to
// update" flow.)
clientsClaim();

self.addEventListener('message', (event) => {
  if ((event as ExtendableMessageEvent).data?.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

async function fetchWithTimeout(request: Request, ms: number): Promise<Response> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), ms);
  try {
    return await fetch(request, { signal: controller.signal });
  } finally {
    clearTimeout(id);
  }
}

// --- Navigation: the server-rendered /pos shell. NetworkFirst by hand so
// we can cache under BOTH the exact URL and a normalized shell key. ---
async function handlePosNavigation(request: Request): Promise<Response> {
  const cache = await caches.open(SHELL_CACHE);
  try {
    const response = await fetchWithTimeout(request, NAV_TIMEOUT_MS);
    if (response && response.status === 200) {
      await cache.put(request, response.clone());
      await cache.put(SHELL_KEY, response.clone());
    }
    return response;
  } catch (err) {
    const cached =
      (await cache.match(request, { ignoreSearch: true })) ||
      (await cache.match(SHELL_KEY));
    if (cached) return cached;
    throw err;
  }
}

registerRoute(
  new NavigationRoute((options) => handlePosNavigation(options.request as Request), {
    // Only take over /pos* navigations. Desk/login/other-app navigations
    // don't match → the browser handles them normally.
    allowlist: [/^\/pos(\/|$|\?)/],
  })
);

// --- POS API GETs (the boot data: auth, terminal, POS profile, menu,
// courses, payment modes, opening entry). NetworkFirst so an online load
// is always fresh and offline falls back to the last cached response. A
// short network timeout means a WEAK connection fails over to cache
// quickly instead of hanging. `?__ping=` is excluded so the connectivity
// heartbeat can probe true reachability without hitting this cache.
//
// Scoped to the POS's OWN surface only — every URY whitelisted method
// (/api/method/ury.*) plus the one session check the boot needs. This SW
// is root-scoped, so it deliberately does NOT cache general Frappe Desk
// (/api/method/frappe.*) calls — the Desk is left completely untouched. ---
registerRoute(
  ({ url, request }) =>
    url.origin === self.location.origin &&
    request.method === 'GET' &&
    !url.searchParams.has('__ping') &&
    (url.pathname.startsWith('/api/method/ury.') ||
      url.pathname === '/api/method/frappe.auth.get_logged_user'),
  new NetworkFirst({
    cacheName: API_CACHE,
    networkTimeoutSeconds: 5,
    plugins: [
      // Never cache a 403/417/500 — only successful JSON responses.
      new CacheableResponsePlugin({ statuses: [200] }),
      new ExpirationPlugin({ maxEntries: 200, maxAgeSeconds: 60 * 60 * 24 * 7 }),
    ],
  }),
  'GET'
);

// --- Built POS assets not covered by precache (runtime chunks, icons,
// sounds, manifest). NetworkFirst keeps them fresh online, cached offline.
// `?__ping=` excluded so the heartbeat probe isn't served from cache. ---
registerRoute(
  ({ url }) =>
    url.origin === self.location.origin &&
    url.pathname.startsWith('/assets/ury/pos/') &&
    !url.searchParams.has('__ping'),
  new NetworkFirst({
    cacheName: ASSET_CACHE,
    plugins: [
      new CacheableResponsePlugin({ statuses: [200] }),
      new ExpirationPlugin({ maxEntries: 300, maxAgeSeconds: 60 * 60 * 24 * 30 }),
    ],
  })
);
