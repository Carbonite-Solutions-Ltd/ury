/*
 * Unit tests for the retry policy.
 *
 * These matter more than most: the policy decides what gets retried on a
 * link that loses packets every 15 seconds. Too narrow and Starlink
 * handovers still break orders; too broad and we retry genuine server
 * rejections, wasting connections on an already-degraded link and delaying
 * the real error reaching the cashier.
 *
 *   node --test test/retry-rule.test.mjs     (or: yarn test:unit)
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { transform } from 'esbuild';

const src = readFileSync(new URL('../src/lib/retry-rule.ts', import.meta.url), 'utf8');
const { code } = await transform(src, { loader: 'ts', format: 'esm' });
const { isTransientNetworkError, retryDelayFor, RETRY_DELAYS_MS } = await import(
  `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
);

// ── what counts as transient ───────────────────────────────────────────

test('the SDK offline flag is transient', () => {
  assert.equal(isTransientNetworkError({ isOffline: true }), true);
});

test("the SDK's response-less TypeError is transient (the Starlink case)", () => {
  const e = new TypeError("Cannot read properties of undefined (reading 'data')");
  assert.equal(isTransientNetworkError(e), true);
});

test('a TypeError from an unrelated bug is NOT retried', () => {
  // Retrying a genuine coding error would just repeat it three times.
  const e = new TypeError('x is not a function');
  assert.equal(isTransientNetworkError(e), false);
});

test('"try again" statuses are transient', () => {
  for (const status of [408, 429, 500, 502, 503, 504]) {
    assert.equal(isTransientNetworkError({ status }), true, `status ${status}`);
  }
});

test('client errors are NOT transient — the server is telling us we are wrong', () => {
  // 417 is Frappe's ValidationError status; 403 is a permission failure.
  for (const status of [400, 401, 403, 404, 409, 417, 422]) {
    assert.equal(isTransientNetworkError({ status }), false, `status ${status}`);
  }
});

test('a status is found wherever the SDK/axios hid it', () => {
  assert.equal(isTransientNetworkError({ httpStatus: 503 }), true);
  assert.equal(isTransientNetworkError({ statusCode: 502 }), true);
  assert.equal(isTransientNetworkError({ response: { status: 504 } }), true);
  assert.equal(isTransientNetworkError({ response: { status: 403 } }), false);
});

test('a status present and non-retryable wins over a message that looks network-ish', () => {
  // Otherwise a 403 whose body mentions "network" would be retried forever.
  assert.equal(
    isTransientNetworkError({ status: 403, message: 'network policy denied' }),
    false
  );
});

test('a bare fetch failure is transient', () => {
  assert.equal(isTransientNetworkError(new Error('Failed to fetch')), true);
  assert.equal(isTransientNetworkError(new Error('NetworkError: timed out')), true);
});

test('non-objects and unknown errors are NOT retried', () => {
  for (const v of [null, undefined, 'boom', 42, new Error('Price Not Set')]) {
    assert.equal(isTransientNetworkError(v), false);
  }
});

// ── backoff schedule ───────────────────────────────────────────────────

test('three retries, front-loaded', () => {
  assert.deepEqual([...RETRY_DELAYS_MS], [200, 600, 1500]);
  assert.equal(retryDelayFor(1), 200);
  assert.equal(retryDelayFor(2), 600);
  assert.equal(retryDelayFor(3), 1500);
});

test('retries are exhausted after the schedule', () => {
  assert.equal(retryDelayFor(4), null);
  assert.equal(retryDelayFor(99), null);
});

test('a nonsensical attempt number yields no delay', () => {
  assert.equal(retryDelayFor(0), null);
  assert.equal(retryDelayFor(-1), null);
});

test('the whole budget stays inside a cashier‘s patience', () => {
  const total = RETRY_DELAYS_MS.reduce((a, b) => a + b, 0);
  assert.ok(total <= 2500, `total backoff ${total}ms should stay under 2.5s`);
  // And comfortably longer than a sub-second handover disturbance.
  assert.ok(total >= 1500, `total backoff ${total}ms should exceed one blip`);
});

test('a custom schedule is honoured', () => {
  assert.equal(retryDelayFor(1, [50]), 50);
  assert.equal(retryDelayFor(2, [50]), null);
});
