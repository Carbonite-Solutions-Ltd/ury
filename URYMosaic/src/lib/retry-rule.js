/*
 * Pure retry policy (KDS) — which failures are worth retrying, and how
 * long to wait between attempts.
 *
 * Dependency-free so it can be unit-tested with no DOM and no SDK.
 *
 * An intentional MIRROR of pos/src/lib/retry-rule.ts. The frontends share
 * no code by design (CLAUDE.md "Repository layout"), and the two copies
 * must agree — a till and a kitchen screen on the same Starlink link
 * disagreeing about what counts as a transient failure would be a
 * miserable bug to chase. A test pins them together; change one, change
 * both.
 *
 * Why it exists: these branches run on Starlink, which loses packets every
 * ~15 s at satellite handover plus a 1–2 % background drop rate unrelated
 * to congestion — "an unusually hostile link environment for TCP".
 * Buffered video shrugs that off; a request/response app with no retries
 * anywhere does not. (2026-09-24)
 */

/** Backoff before attempts 2, 3 and 4 — stepping over a sub-second blip. */
export const RETRY_DELAYS_MS = [200, 600, 1500];

const RETRYABLE_STATUS = new Set([408, 429, 500, 502, 503, 504]);

function statusOf(err) {
  if (!err || typeof err !== 'object') return undefined;
  const candidates = [
    err.httpStatus,
    err.status,
    err.statusCode,
    err.response && err.response.status,
  ];
  for (const c of candidates) {
    if (typeof c === 'number' && c >= 100 && c < 600) return c;
  }
  return undefined;
}

/**
 * Is this failure transient — might the same request succeed a moment later?
 *
 * Conservative on purpose: a 4xx is the server saying we are wrong, and
 * retrying it wastes a connection on an already-degraded link while
 * delaying the real error.
 */
export function isTransientNetworkError(err) {
  if (!err || typeof err !== 'object') return false;

  if (err.isOffline === true) return true;

  const status = statusOf(err);
  if (status !== undefined) return RETRYABLE_STATUS.has(status);

  // frappe-js-sdk's axios interceptor reads error.response.data
  // unconditionally, so a dropped request surfaces as a bare TypeError
  // with no status — exactly the Starlink-handover case.
  if (err instanceof TypeError) {
    return /reading '(data|response|status)'/.test(err.message || '');
  }

  if (err.message && /network|failed to fetch|load failed/i.test(err.message)) {
    return true;
  }

  return false;
}

/**
 * Delay before the given 1-based attempt, or null when retries are done.
 */
export function retryDelayFor(attempt, delays = RETRY_DELAYS_MS) {
  if (attempt < 1) return null;
  return attempt <= delays.length ? delays[attempt - 1] : null;
}

/**
 * Wrap a frappe-js-sdk `call` object so its READ method (`get`) retries
 * through a handover blip. Writes are never retried here — the KDS's
 * posts (serve, reinstate, cancel-accept) are not idempotent.
 */
export function hardenCall(call) {
  const rawGet = call.get.bind(call);
  call.get = async (...args) => {
    let attempt = 0;
    for (;;) {
      try {
        return await rawGet(...args);
      } catch (e) {
        attempt += 1;
        const delay = isTransientNetworkError(e) ? retryDelayFor(attempt) : null;
        if (delay === null) throw e;
        await new Promise((r) => setTimeout(r, delay));
      }
    }
  };
  return call;
}
