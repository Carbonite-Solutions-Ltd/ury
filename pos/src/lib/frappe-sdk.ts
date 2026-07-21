import { FrappeApp } from "frappe-js-sdk";

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

// Proxy that wraps every method so its rejected promise is normalized via
// toFriendlyError. Covers all current + future methods without
// enumerating them, and preserves the original typed shape. Non-promise
// return values and non-function/symbol props pass straight through.
function harden<T extends object>(target: T): T {
  return new Proxy(target, {
    get(obj, prop, receiver) {
      const value = Reflect.get(obj, prop, receiver);
      if (typeof value === "function" && typeof prop === "string") {
        const bound = value.bind(obj);
        return (...args: unknown[]) => {
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
