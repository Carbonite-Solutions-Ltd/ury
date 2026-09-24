/*
 * Offline order outbox (Phase B).
 *
 * When a waiter places an order with no internet (or the submit drops
 * mid-flight), the order is queued here instead of failing. On reconnect
 * the queue drains — each order is (re)sent to `sync_order` carrying its
 * client-generated `idempotency_key`, so a flaky reconnect that replays
 * the same order never creates a duplicate (the backend returns the
 * already-created invoice). See ury_order.sync_order.
 *
 * Storage: localStorage (survives an app close; Android-only per the
 * agreed scope, so iOS eviction isn't a concern). The queue is small
 * (a handful of orders at most), so a JSON array is plenty — no IndexedDB.
 *
 * A pending order is NOT in the kitchen yet — it only reaches the kitchen
 * once it drains successfully on reconnect. The UI (OutboxIndicator) makes
 * that explicit.
 */
import { create } from 'zustand';
import { v4 as uuidv4 } from 'uuid';
import { syncOrder, type SyncOrderRequest } from './order-api';
import { useConnectivity } from './connectivity';
import { extractFrappeServerError, parseFrappeServerMessages } from './utils';
import { showToast } from '../components/ui/toast';
import { kickKotCheck } from './kot-listener';

export type OutboxStatus = 'pending' | 'sending' | 'failed';

export interface OutboxEntry {
  id: string;
  /** Reused on every retry so the backend de-dupes replays. */
  idempotencyKey: string;
  payload: SyncOrderRequest;
  /** Human label for the UI, e.g. "Take Away · 3 items". */
  label: string;
  status: OutboxStatus;
  createdAt: number;
  attempts: number;
  error?: string;
}

const STORAGE_KEY = 'ury_order_outbox';

function load(): OutboxEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

function persist(entries: OutboxEntry[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    /* localStorage full/unavailable — the in-memory queue still works */
  }
}

/** Is this error a network failure (vs a real server rejection)? The
 * hardened SDK marks offline/response-less errors with `isOffline`. */
function isNetworkError(err: unknown): boolean {
  if (err && typeof err === 'object' && (err as { isOffline?: boolean }).isOffline) {
    return true;
  }
  // Fallback: no Frappe server message + we're offline right now.
  return (
    parseFrappeServerMessages(err).length === 0 &&
    !useConnectivity.getState().online
  );
}

interface OutboxState {
  entries: OutboxEntry[];
  draining: boolean;
  /** Queue a new order. Returns the created entry. */
  enqueue: (payload: SyncOrderRequest, label: string) => OutboxEntry;
  /** Try to send every pending entry (sequentially). No-op when offline. */
  drain: () => Promise<void>;
  /** Move a failed entry back to pending and drain. */
  retry: (id: string) => Promise<void>;
  /** Drop an entry from the queue (give up on it). */
  discard: (id: string) => void;
}

export const useOutbox = create<OutboxState>((set, get) => {
  const patch = (id: string, changes: Partial<OutboxEntry>) => {
    const entries = get().entries.map((e) =>
      e.id === id ? { ...e, ...changes } : e
    );
    persist(entries);
    set({ entries });
  };
  const remove = (id: string) => {
    const entries = get().entries.filter((e) => e.id !== id);
    persist(entries);
    set({ entries });
  };

  return {
    entries: load(),
    draining: false,

    enqueue: (payload, label) => {
      const idempotencyKey = payload.idempotency_key || uuidv4();
      const entry: OutboxEntry = {
        id: uuidv4(),
        idempotencyKey,
        payload: { ...payload, idempotency_key: idempotencyKey },
        label,
        status: 'pending',
        createdAt: Date.now(),
        attempts: 0,
      };
      const entries = [...get().entries, entry];
      persist(entries);
      set({ entries });
      return entry;
    },

    drain: async () => {
      if (get().draining) return;
      if (!useConnectivity.getState().online) return;
      set({ draining: true });
      try {
        // Snapshot the pending ids up front; only auto-send 'pending'
        // (a 'failed' entry was rejected by the server and waits for a
        // manual retry so we don't hammer a genuinely-bad order).
        const pendingIds = get()
          .entries.filter((e) => e.status === 'pending')
          .map((e) => e.id);

        for (const id of pendingIds) {
          const entry = get().entries.find((e) => e.id === id);
          if (!entry) continue;
          // Bail out fast if we went offline again mid-drain.
          if (!useConnectivity.getState().online) break;

          patch(id, { status: 'sending', attempts: entry.attempts + 1 });
          try {
            await syncOrder(entry.payload);
            remove(id);
            // A drained order has already waited; don't make it wait for
            // the next poll tick to reach the kitchen printer too.
            kickKotCheck();
            showToast.success(`Order sent to the kitchen — ${entry.label}.`);
          } catch (err) {
            if (isNetworkError(err)) {
              // Transient — put it back to pending, stop; retry next reconnect.
              patch(id, { status: 'pending' });
              break;
            }
            // Real server rejection (price/stock/validation). Keep it as
            // failed for the waiter to fix + retry or discard.
            const parsed = extractFrappeServerError(
              err,
              'The order was rejected when sending.'
            );
            patch(id, { status: 'failed', error: parsed.message });
            showToast.error({
              title: "A queued order couldn't be sent",
              description: `${entry.label}: ${parsed.message}`,
            });
          }
        }
      } finally {
        set({ draining: false });
      }
    },

    retry: async (id) => {
      const entry = get().entries.find((e) => e.id === id);
      if (!entry) return;
      patch(id, { status: 'pending', error: undefined });
      await get().drain();
    },

    discard: (id) => remove(id),
  };
});

// ── Drain wiring ────────────────────────────────────────────
let started = false;
let sweeper: number | null = null;

/*
 * Why there is a timer as well as a transition (2026-09-24).
 *
 * The transition subscription below only fires on offline -> online. That
 * covers an order queued while the POS KNEW it was offline. It does NOT
 * cover the other way an order gets queued: OrderPanel also enqueues when
 * a submit drops mid-flight while the app still believes it is online
 * (see the `networkFailure` branch there). In that case there is no
 * transition to ride, so the drain was never triggered - the order sat in
 * localStorage indefinitely while the waiter had been told, in writing,
 * that it would be sent automatically. Orders really were lost this way.
 *
 * The sweeper closes that hole: while online, retry pending entries on a
 * slow timer regardless of how they got queued. `drain()` is already
 * guarded (it no-ops when offline or already draining) and only touches
 * `pending` entries, so a tick with an empty queue costs nothing and a
 * server-rejected `failed` entry is still left alone for a manual retry.
 */
const SWEEP_MS = 30000;

/** Wire the outbox to drain when connectivity returns, on a slow timer
 * while online, and once on load if we're already online with a backlog.
 * Call once from main.tsx. */
export function initOutbox(): void {
  if (started || typeof window === 'undefined') return;
  started = true;

  useConnectivity.subscribe((state, prev) => {
    if (state.online && !prev.online) {
      // Small delay so the network is actually usable before we fire.
      window.setTimeout(() => useOutbox.getState().drain(), 800);
    }
  });

  sweeper = window.setInterval(() => {
    const { online } = useConnectivity.getState();
    const { entries, draining } = useOutbox.getState();
    if (!online || draining) return;
    if (!entries.some((e) => e.status === 'pending')) return;
    void useOutbox.getState().drain();
  }, SWEEP_MS);

  if (useConnectivity.getState().online && useOutbox.getState().entries.length) {
    window.setTimeout(() => useOutbox.getState().drain(), 1500);
  }
}

/** Test/teardown helper - not used in production. */
export function stopOutbox(): void {
  if (sweeper !== null) {
    clearInterval(sweeper);
    sweeper = null;
  }
  started = false;
}
