/*
 * Pure retry policy — which failures are worth retrying, and how long to
 * wait between attempts.
 *
 * Deliberately dependency-free so it can be unit-tested with no DOM, no
 * SDK and no network. Mirrored in URYMosaic/src/lib/retry-rule.js; a test
 * pins the two together.
 *
 * ── Why this exists (2026-09-24) ────────────────────────────────────────
 * The customer's branches run on Starlink. Every Starlink dish loses
 * packets **every 15 seconds** when the satellites hand the connection
 * over, on top of a 1–2 % background drop rate unrelated to congestion.
 * Published measurements call it "an unusually hostile link environment
 * for TCP".
 *
 * YouTube is unaffected because it buffers tens of seconds ahead. A POS is
 * the opposite shape: dozens of short request/response round trips a
 * minute, each of which has to complete *now*. With no retry anywhere in
 * the app, a request that happened to land in a handover window simply
 * failed — which is why the POS looked broken on a link that was, by any
 * other measure, working.
 *
 * A handover disturbance is sub-second, so retrying two or three times
 * over ~2.3 s absorbs it completely and invisibly.
 */

/**
 * Backoff before attempts 2, 3 and 4. Deliberately short and front-loaded:
 * we are stepping over a sub-second blip, not waiting out an outage. The
 * total (~2.3 s) stays well inside a user's patience for an order to land.
 */
export const RETRY_DELAYS_MS: readonly number[] = [200, 600, 1500];

/** HTTP statuses worth retrying. All mean "try again", never "you're wrong". */
const RETRYABLE_STATUS = new Set([408, 429, 500, 502, 503, 504]);

/** Dig a status code out of whatever shape the SDK/axios handed us. */
function statusOf(err: unknown): number | undefined {
  if (!err || typeof err !== 'object') return undefined;
  const e = err as Record<string, unknown>;
  const candidates = [
    e.httpStatus,
    e.status,
    e.statusCode,
    (e.response as Record<string, unknown> | undefined)?.status,
  ];
  for (const c of candidates) {
    if (typeof c === 'number' && c >= 100 && c < 600) return c;
  }
  return undefined;
}

/**
 * Is this failure transient — i.e. the same request might well succeed a
 * moment later?
 *
 * Deliberately CONSERVATIVE. A 4xx (403 permission, 417 Frappe validation,
 * 400 bad request) is the server telling us we are wrong; retrying it just
 * wastes a connection on an already-degraded link and delays the real
 * error reaching the cashier. Only response-less failures and explicit
 * "try again" statuses qualify.
 */
export function isTransientNetworkError(err: unknown): boolean {
  if (!err || typeof err !== 'object') return false;
  const e = err as { isOffline?: boolean; message?: string };

  // Flagged by the SDK hardening in frappe-sdk.ts.
  if (e.isOffline === true) return true;

  const status = statusOf(err);
  if (status !== undefined) return RETRYABLE_STATUS.has(status);

  // frappe-js-sdk's own crash on a response-less network error: its axios
  // interceptor reads error.response.data unconditionally, so a dropped
  // request surfaces as a bare TypeError with no status at all. That is
  // precisely the Starlink-handover case.
  if (err instanceof TypeError) {
    return /reading '(data|response|status)'/.test(e.message || '');
  }

  // A fetch() that never got a response.
  if (e.message && /network|failed to fetch|load failed/i.test(e.message)) {
    return true;
  }

  return false;
}

/**
 * How long to wait before the given attempt, or `null` when we're done.
 * `attempt` is 1-based: attempt 1 has already failed when this is called.
 */
export function retryDelayFor(
  attempt: number,
  delays: readonly number[] = RETRY_DELAYS_MS
): number | null {
  if (attempt < 1) return null;
  return attempt <= delays.length ? delays[attempt - 1] : null;
}
