import { FrappeApp } from "frappe-js-sdk";
import { isTransientNetworkError, retryDelayFor } from "./retry-rule";

const frappe = new FrappeApp(import.meta.env.VITE_FRAPPE_BASE_URL);

const rawCall = frappe.call();
const rawDb = frappe.db();

/**
 * Offline hardening (Phase A PWA).
 *
 * frappe-js-sdk's axios error interceptor reads `error.response.data`
 * unconditionally. On a true network failure (offline / dropped
 * connection) an axios error has NO `.response`, so the SDK itself throws
 * a bare `TypeError: Cannot read properties of undefined (reading 'data')`
 * — which surfaced to users on the Reports tab as exactly that cryptic
 * string. We wrap every `call`/`db` method so a network failure becomes a
 * clean, catchable Error ("you're offline") that every feature can show
 * sensibly. Real server errors (403/500 with a response body) are left
 * untouched, so `_server_messages` parsing keeps working.
 */
const OFFLINE_MESSAGE =
  "You're offline — this needs an internet connection. Reconnect and try again.";

function toFriendlyError(e: unknown): unknown {
  const offline = typeof navigator !== "undefined" && !navigator.onLine;
  // The SDK's own crash on a response-less network error.
  const isSdkNetworkCrash =
    e instanceof TypeError &&
    /reading '(data|response|status)'/.test((e as TypeError).message || "");
  if (offline || isSdkNetworkCrash) {
    const err = new Error(OFFLINE_MESSAGE) as Error & { isOffline?: boolean };
    err.isOffline = true;
    return err;
  }
  return e;
}

/*
 * Methods that are SAFE TO RETRY — reads only.
 *
 * This list is deliberately an allowlist rather than a denylist. A retried
 * read costs one extra request; a retried WRITE can create a second
 * invoice, a second payment or a second kitchen ticket. `sync_order` is
 * the one write that is genuinely safe to retry because it carries an
 * idempotency key, and it is retried explicitly at its own call site in
 * order-api.ts rather than by widening this list.
 */
const RETRYABLE_METHODS = new Set([
  "get",            // call.get
  "getDoc",
  "getDocList",
  "getCount",
  "getSingleValue",
  "getLastDoc",
]);

const sleep = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Retry a read through the Starlink handover window.
 *
 * The branches run on Starlink, which loses packets every ~15 s at
 * satellite handover (see retry-rule.ts). A read that lands in one of
 * those windows used to fail outright, because nothing in this app ever
 * retried anything. Absorbing it here fixes every poller and every boot
 * fetch at once.
 */
async function callWithRetry(
  fn: (...a: unknown[]) => Promise<unknown>,
  args: unknown[]
): Promise<unknown> {
  let attempt = 0;
  for (;;) {
    try {
      return await fn(...args);
    } catch (e) {
      attempt += 1;
      const delay = isTransientNetworkError(e) ? retryDelayFor(attempt) : null;
      if (delay === null) throw e;
      await sleep(delay);
    }
  }
}

// Proxy that wraps every method so its rejected promise is normalized via
// toFriendlyError, and retries the read methods above through a transient
// network blip. Covers all current + future methods without enumerating
// them, and preserves the original typed shape. Non-promise return values
// and non-function/symbol props pass straight through.
function harden<T extends object>(target: T): T {
  return new Proxy(target, {
    get(obj, prop, receiver) {
      const value = Reflect.get(obj, prop, receiver);
      if (typeof value === "function" && typeof prop === "string") {
        const bound = value.bind(obj) as (...a: unknown[]) => unknown;
        const retryable = RETRYABLE_METHODS.has(prop);
        return (...args: unknown[]) => {
          if (retryable) {
            // Normalize only after the retries are exhausted, so the
            // policy sees the SDK's original error shape.
            return callWithRetry(
              bound as (...a: unknown[]) => Promise<unknown>,
              args
            ).catch((e: unknown) => {
              throw toFriendlyError(e);
            });
          }
          const result = bound(...args);
          if (result && typeof (result as Promise<unknown>).then === "function") {
            return (result as Promise<unknown>).catch((e: unknown) => {
              throw toFriendlyError(e);
            });
          }
          return result;
        };
      }
      return value;
    },
  });
}

export const call = harden(rawCall);
export const db = harden(rawDb);
export const auth = frappe.auth();
