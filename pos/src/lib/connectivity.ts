/*
 * Connectivity store + watcher (Phase A offline support).
 *
 * `navigator.onLine` is a reliable "definitely offline" signal (the
 * offline event fires when the tablet's Wi-Fi drops) but it can report a
 * false "online" when the interface is up but there's no real internet —
 * exactly the "internet is messing up" case at the venue. So on top of
 * the online/offline events we run a light heartbeat that actually
 * probes the server. The probe uses `?__ping=` which the service worker
 * deliberately does NOT serve from cache (see sw.ts), so it measures
 * TRUE reachability, not a cached 200.
 */
import { create } from 'zustand';

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
const PROBE_TIMEOUT_MS = 5000;
const HEARTBEAT_MS = 20000;

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

/**
 * Wire the online/offline events + start the heartbeat. Idempotent —
 * safe to call once from main.tsx. In non-browser contexts it no-ops.
 */
export function initConnectivityWatch(): void {
  if (started || typeof window === 'undefined') return;
  started = true;

  const apply = (online: boolean) => useConnectivity.getState().setOnline(online);

  // Browser interface events. "offline" is trustworthy → apply directly.
  // "online" only means the interface came up → verify with a probe.
  window.addEventListener('offline', () => apply(false));
  window.addEventListener('online', () => {
    probeReachability().then(apply);
  });

  const tick = async () => apply(await probeReachability());
  // First check on boot, then poll to catch "connected but no internet".
  tick();
  heartbeat = window.setInterval(tick, HEARTBEAT_MS);
}

/** Test/teardown helper — not used in production. */
export function stopConnectivityWatch(): void {
  if (heartbeat !== null) {
    clearInterval(heartbeat);
    heartbeat = null;
  }
  started = false;
}
