/**
 * Was the close REJECTED, or did we just stop listening?
 *
 * Dependency-free on purpose so it can be unit-tested with no DOM, no
 * zustand store and no frappe-js-sdk — same reasoning as
 * connectivity-rule.ts. `pos-closing-api.ts` re-exports it.
 *
 * URY consolidates POS Invoices INLINE during the close, deliberately
 * (CLAUDE.md 2026-06-11: an enqueued close reported success while
 * silently marking the entry Failed). The price of that honesty is
 * wall-clock, and on landing.erpxpand.com the first ceiling is
 * CLOUDFLARE at 100s — below gunicorn's own 120s.
 *
 * When Cloudflare gives up it returns 504 to the browser and drops its
 * connection. gunicorn does NOT abort a request because the client went
 * away: the close keeps running and, if it finishes inside gunicorn's
 * timeout, commits normally. So a 504 means "we stopped listening", not
 * "it failed" — and treating it as failure is precisely what makes a
 * cashier retry a close that already succeeded.
 */

/** Statuses an edge/proxy returns when the ORIGIN ran out of time. */
export const IN_TRANSIT_STATUSES = [502, 503, 504, 524] as const;

export interface MaybeTransitError {
  httpStatus?: number;
  isOffline?: boolean;
  message?: string;
  /** Present only when FRAPPE itself answered — i.e. a real verdict. */
  _server_messages?: string;
}

/**
 * True when the request died in transit rather than being rejected by
 * the server, so the caller MUST verify the real outcome before
 * reporting failure.
 *
 * A genuine Frappe rejection (ValidationError, PermissionError, the
 * desk-close guard, "transfer required", …) always arrives with
 * `_server_messages`. Those are verdicts and must surface as errors, so
 * `_server_messages` short-circuits to false even on a 5xx — otherwise
 * a real refusal would be masked as "still running" and the cashier
 * would watch a spinner for four minutes for nothing.
 */
export function closeMayStillBeRunning(err: unknown): boolean {
  if (!err || typeof err !== 'object') return false;
  const e = err as MaybeTransitError;

  // The server told us why it refused. That is an answer, not a drop.
  if (e._server_messages) return false;

  // Connection died mid-request (normalized in frappe-sdk.ts).
  if (e.isOffline === true) return true;

  if (IN_TRANSIT_STATUSES.includes(Number(e.httpStatus) as never)) return true;

  // Last resort: some proxies surface only a message string.
  return /gateway time-?out|gateway timeout|timed out|\b(?:502|503|504|524)\b|network error/i.test(
    String(e.message || '')
  );
}
