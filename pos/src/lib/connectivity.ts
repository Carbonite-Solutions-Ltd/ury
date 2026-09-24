/*
 * Connectivity store + watcher (Phase A offline support).
 *
 * `navigator.onLine` is NOT trustworthy on the tablets this POS runs on.
 * It reports a false "online" when the interface is up but there's no
 * real internet, and it reports a false "offline" when Android roams
 * between APs or parks the Wi-Fi radio for power saving (which happens
 * whenever the screen sleeps). So the arbiter of truth here is a light
 * heartbeat that actually probes the server. The probe uses `?__ping=`
 * which the service worker deliberately does NOT serve from cache (see
 * sw.ts), so it measures TRUE reachability, not a cached 200.
 *
 * ── Why there is hysteresis (2026-09-24) ────────────────────────────────
 * The first version flipped to offline on a SINGLE failed probe. That is
 * too trigger-happy to survive a real venue: one slow response, one
 * dropped packet, or one moment of connection-pool starvation produced a
 * full "You're offline" alarm, and the next tick 20s later produced
 * "Back online" — the flapping the client reported, on an internet
 * connection that was genuinely fine.
 *
 * Two changes fix it without making a genuine outage slow to notice:
 *
 *   1. A failed probe no longer means offline. It takes
 *      `FAILURES_BEFORE_OFFLINE` CONSECUTIVE failures. One blip is
 *      absorbed silently — no banner, no toast.
 *   2. A failure schedules a fast re-probe (`RECHECK_DELAY_MS`) instead
 *      of waiting a full heartbeat. So a REAL outage is still caught in
 *      ~2s, not ~20s, while an isolated blip costs nothing.
 *
 * Recovery is deliberately NOT hysteretic: a single successful probe is
 * positive proof of reachability, so we go back online immediately.
 */
import { create } from 'zustand';
import { nextConnectivity } from './connectivity-rule';

// Re-exported so existing importers (and tests) can reach the rule from
// either module.
export { nextConnectivity, FAILURES_BEFORE_OFFLINE } from './connectivity-rule';

interface ConnectivityState {
  online: boolean;
  setOnline: (online: boolean) => void;
}

export const useConnectivity = create<ConnectivityState>((set) => ({
  online: typeof navigator !== 'undefined' ? navigator.onLine : true,
  // No-op when unchanged so the heartbeat doesn't spam re-renders.
  setOnline: (online) =>
    set((state) => (state.online === online ? state : { online })),
}));

const PROBE_URL = '/assets/ury/pos/manifest.json';
/* Kept comfortably inside HEARTBEAT_MS even with one re-probe:
 * 6000 + 1500 + 6000 = 13.5s < 20s, so ticks can never overlap. */
const PROBE_TIMEOUT_MS = 6000;
const HEARTBEAT_MS = 20000;
const RECHECK_DELAY_MS = 1500;

/**
 * Real reachability probe. A tiny same-origin static file with a
 * cache-busting `__ping` param that the SW passes straight to the
 * network. Resolves true only on an actual 2xx response.
 */
async function probeReachability(): Promise<boolean> {
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

let started = false;
let heartbeat: number | null = null;
let recheck: number | null = null;
let probing = false;
/** Consecutive-failure streak. Module-local, not in the store, so the
 * counter can't cause a re-render in any consumer. */
let failures = 0;

/**
 * Wire the online/offline events + start the heartbeat. Idempotent —
 * safe to call once from main.tsx. In non-browser contexts it no-ops.
 */
export function initConnectivityWatch(): void {
  if (started || typeof window === 'undefined') return;
  started = true;

  const clearRecheck = () => {
    if (recheck !== null) {
      clearTimeout(recheck);
      recheck = null;
    }
  };

  /**
   * One probe, folded through the hysteresis rule. A failure that hasn't
   * yet crossed the threshold queues a fast re-probe so a genuine outage
   * is confirmed in ~2s rather than on the next 20s tick.
   *
   * `probing` prevents a queued re-probe and a heartbeat tick from
   * running concurrently — two in-flight probes would both count against
   * the streak and could trip the threshold off a single real failure,
   * defeating the hysteresis.
   */
  const check = async (): Promise<void> => {
    // Skipped entirely while the page is hidden. A backgrounded tab has
    // its timers throttled and its fetches deferred, so a probe there
    // measures BROWSER THROTTLING rather than the network — and counting
    // that as a failure is what makes the POS appear to "go offline"
    // while the tablet is locked, then announce "back online" the moment
    // the waiter wakes it. A hidden page isn't being used, so its
    // connectivity doesn't matter until it's visible; the
    // visibilitychange listener below probes the instant it is.
    // (2026-09-24, found while auditing the KDS for the same bug.)
    if (typeof document !== 'undefined' && document.hidden) return;
    if (probing) return;
    probing = true;
    let ok = false;
    try {
      ok = await probeReachability();
    } finally {
      probing = false;
    }

    const store = useConnectivity.getState();
    const decided = nextConnectivity({ online: store.online, failures }, ok);
    failures = decided.failures;
    store.setOnline(decided.online);

    clearRecheck();
    // Still nominally online but a probe just failed → confirm quickly
    // instead of leaving a real outage unreported for a full heartbeat.
    if (!ok && decided.online) {
      recheck = window.setTimeout(() => {
        recheck = null;
        void check();
      }, RECHECK_DELAY_MS);
    }
  };

  // Interface events are treated as HINTS, never as verdicts — both of
  // them lie on Android tablets. Each one just asks for a fresh probe and
  // lets the hysteresis above decide.
  window.addEventListener('offline', () => void check());
  window.addEventListener('online', () => void check());
  // Waking the tablet is the moment we most need a fresh verdict, and the
  // moment the throttled-probe skip above has left us without one.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) void check();
  });

  // First check on boot, then poll to catch "connected but no internet".
  void check();
  heartbeat = window.setInterval(() => void check(), HEARTBEAT_MS);
}

/** Test/teardown helper — not used in production. */
export function stopConnectivityWatch(): void {
  if (heartbeat !== null) {
    clearInterval(heartbeat);
    heartbeat = null;
  }
  if (recheck !== null) {
    clearTimeout(recheck);
    recheck = null;
  }
  failures = 0;
  probing = false;
  started = false;
}
