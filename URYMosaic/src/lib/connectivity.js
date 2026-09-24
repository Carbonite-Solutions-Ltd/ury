/*
 * Connectivity watcher for the KDS.
 *
 * The kitchen screen previously drove its online/offline toast straight
 * off `navigator.onLine`, with no verification of any kind. That signal
 * is not trustworthy on the hardware this runs on: it reports a false
 * "offline" when Android roams between access points or sleeps the Wi-Fi
 * radio, and a false "online" when the interface is up but nothing is
 * actually reachable. The result was a red "You are Offline" toast
 * followed by a green "You are online", repeatedly, on a healthy
 * connection — while a genuine loss of the server (socket dropped,
 * Frappe down) showed a reassuring green dot.
 *
 * So the arbiter here is an actual reachability probe, with the same
 * two-strike hysteresis the POS uses (connectivity-rule.js).
 *
 * Unlike the POS there is no service worker on the KDS, so the probe only
 * has to defeat the HTTP cache — hence `cache: 'no-store'` plus a
 * cache-busting param. The `__ping` name is kept for symmetry with the
 * POS, where it additionally tells the service worker to bypass its
 * cache. (2026-09-24)
 */
import { nextConnectivity } from './connectivity-rule';

/** Small static asset served from the KDS's own build output. */
const PROBE_URL = '/assets/ury/URYMosaic/ury.ico';
const PROBE_TIMEOUT_MS = 6000;
const HEARTBEAT_MS = 20000;
const RECHECK_DELAY_MS = 1500;

let heartbeat = null;
let recheck = null;
let probing = false;
let started = false;
let failures = 0;
let online = typeof navigator !== 'undefined' ? navigator.onLine : true;
let notify = null;

async function probeReachability() {
  try {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
    const res = await fetch(`${PROBE_URL}?__ping=${Date.now()}`, {
      method: 'GET',
      cache: 'no-store',
      signal: controller.signal,
    });
    clearTimeout(id);
    return res.ok;
  } catch {
    return false;
  }
}

function clearRecheck() {
  if (recheck !== null) {
    clearTimeout(recheck);
    recheck = null;
  }
}

/**
 * One probe, folded through the hysteresis rule.
 *
 * Skipped entirely while the page is hidden. A backgrounded tab has its
 * timers throttled and its fetches deferred, so a probe there measures
 * browser throttling rather than the network — and counting that as a
 * failure is what makes a screen appear to "go offline" while nobody is
 * looking at it, then announce "back online" the moment it is woken. A
 * hidden screen is not being used, so its connectivity does not matter
 * until it is visible again; `visibilitychange` probes immediately.
 */
async function check() {
  if (typeof document !== 'undefined' && document.hidden) return;
  if (probing) return;
  probing = true;
  let ok = false;
  try {
    ok = await probeReachability();
  } finally {
    probing = false;
  }

  const decided = nextConnectivity({ online, failures }, ok);
  failures = decided.failures;
  if (decided.online !== online) {
    online = decided.online;
    if (notify) notify(online);
  }

  clearRecheck();
  // Still nominally online but a probe just failed → confirm quickly
  // rather than leaving a real outage unreported for a full heartbeat.
  if (!ok && decided.online) {
    recheck = setTimeout(() => {
      recheck = null;
      void check();
    }, RECHECK_DELAY_MS);
  }
}

/**
 * Start watching. `onChange(online)` fires only on a settled CHANGE, so
 * the caller never has to de-duplicate toasts. Idempotent.
 *
 * @param {(online: boolean) => void} onChange
 */
export function startConnectivityWatch(onChange) {
  notify = onChange;
  if (started || typeof window === 'undefined') return;
  started = true;

  // Interface events are HINTS, never verdicts — both of them lie on
  // Android. Each just asks for a fresh probe and lets the rule decide.
  window.addEventListener('online', () => void check());
  window.addEventListener('offline', () => void check());
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) void check();
  });

  void check();
  heartbeat = setInterval(() => void check(), HEARTBEAT_MS);
}

/** Current settled state. */
export function isOnline() {
  return online;
}

export function stopConnectivityWatch() {
  if (heartbeat !== null) {
    clearInterval(heartbeat);
    heartbeat = null;
  }
  clearRecheck();
  failures = 0;
  probing = false;
  started = false;
  notify = null;
}
