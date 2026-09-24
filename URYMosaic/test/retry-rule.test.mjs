/*
 * Unit tests for the KDS retry policy, plus a parity check against the POS
 * copy.
 *
 * The parity test is the important one. The two retry rules are deliberate
 * duplicates (the frontends share no code by design), and a till and a
 * kitchen screen on the same Starlink link disagreeing about what counts
 * as a transient failure would be a miserable bug to chase.
 *
 *   node --test test/retry-rule.test.mjs     (or: yarn test:unit)
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
  isTransientNetworkError,
  retryDelayFor,
  RETRY_DELAYS_MS,
  hardenCall,
} from '../src/lib/retry-rule.js';

test('the SDK offline flag and the response-less TypeError are transient', () => {
  assert.equal(isTransientNetworkError({ isOffline: true }), true);
  assert.equal(
    isTransientNetworkError(
      new TypeError("Cannot read properties of undefined (reading 'data')")
    ),
    true
  );
});

test('"try again" statuses retry, client errors do not', () => {
  for (const s of [408, 429, 500, 502, 503, 504]) {
    assert.equal(isTransientNetworkError({ status: s }), true, `status ${s}`);
  }
  for (const s of [400, 403, 404, 417, 422]) {
    assert.equal(isTransientNetworkError({ status: s }), false, `status ${s}`);
  }
});

test('three front-loaded retries, then exhausted', () => {
  assert.deepEqual([...RETRY_DELAYS_MS], [200, 600, 1500]);
  assert.equal(retryDelayFor(3), 1500);
  assert.equal(retryDelayFor(4), null);
  assert.equal(retryDelayFor(0), null);
});

// ── hardenCall: the actual wrapper the KDS uses ─────────────────────────

test('hardenCall retries a transient read and eventually succeeds', async () => {
  let calls = 0;
  const call = {
    get: async () => {
      calls += 1;
      if (calls < 3) throw { isOffline: true };
      return { message: 'ok' };
    },
  };
  hardenCall(call);
  const res = await call.get('some.method');
  assert.deepEqual(res, { message: 'ok' });
  assert.equal(calls, 3, 'should have taken three attempts');
});

test('hardenCall does NOT retry a real server rejection', async () => {
  let calls = 0;
  const call = {
    get: async () => {
      calls += 1;
      throw { status: 417, message: 'Price Not Set' };
    },
  };
  hardenCall(call);
  await assert.rejects(() => call.get('x'), (e) => e.status === 417);
  assert.equal(calls, 1, 'a 417 must fail on the first attempt');
});

test('hardenCall gives up after the schedule and rethrows the last error', async () => {
  let calls = 0;
  const call = {
    get: async () => {
      calls += 1;
      throw { isOffline: true, marker: calls };
    },
  };
  hardenCall(call);
  await assert.rejects(() => call.get('x'), (e) => e.marker === 4);
  assert.equal(calls, 4, '1 initial attempt + 3 retries');
});

test('hardenCall leaves writes alone', () => {
  const post = async () => 'untouched';
  const call = { get: async () => 'g', post };
  hardenCall(call);
  assert.equal(call.post, post, 'post must not be wrapped — writes are not idempotent');
});

// ── parity with the POS copy ────────────────────────────────────────────

test('KDS and POS retry rules agree on every error shape and attempt', async () => {
  const posSrc = fileURLToPath(
    new URL('../../pos/src/lib/retry-rule.ts', import.meta.url)
  );
  if (!existsSync(posSrc)) {
    console.log('  (skipped: pos/ copy not present)');
    return;
  }
  const { transform } = await import('esbuild');
  const { code } = await transform(readFileSync(posSrc, 'utf8'), {
    loader: 'ts',
    format: 'esm',
  });
  const pos = await import(
    `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
  );

  assert.deepEqual(
    [...pos.RETRY_DELAYS_MS],
    [...RETRY_DELAYS_MS],
    'backoff schedules drifted between the POS and the KDS'
  );

  const shapes = [
    null, undefined, 'boom', 42,
    {}, { isOffline: true }, { isOffline: false },
    new Error('Failed to fetch'), new Error('Price Not Set'),
    new TypeError("Cannot read properties of undefined (reading 'data')"),
    new TypeError("Cannot read properties of undefined (reading 'status')"),
    new TypeError('x is not a function'),
    ...[400, 401, 403, 404, 408, 409, 417, 422, 429, 500, 502, 503, 504].flatMap(
      (status) => [{ status }, { httpStatus: status }, { response: { status } }]
    ),
    { status: 403, message: 'network policy denied' },
  ];

  for (const shape of shapes) {
    assert.equal(
      isTransientNetworkError(shape),
      pos.isTransientNetworkError(shape),
      `drift on ${JSON.stringify(shape) || String(shape)}`
    );
  }
  for (let attempt = -1; attempt <= 6; attempt++) {
    assert.equal(
      retryDelayFor(attempt),
      pos.retryDelayFor(attempt),
      `drift at attempt ${attempt}`
    );
  }
});
