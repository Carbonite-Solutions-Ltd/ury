/*
 * Unit tests for "was the close rejected, or did we just stop listening?"
 *
 * This predicate decides whether the POS tells a cashier the close
 * FAILED or goes and checks what actually happened. Getting it wrong is
 * expensive in both directions:
 *
 *   - too narrow  -> a Cloudflare 504 reads as failure, the cashier
 *                    retries a close that already committed;
 *   - too broad   -> a real refusal (unpaid drafts, permission, the
 *                    desk-close guard) is swallowed as "still running"
 *                    and they stare at a spinner for four minutes.
 *
 * Same harness as connectivity-rule.test.mjs: node's built-in runner,
 * esbuild transpiling the one dependency-free module in process.
 *
 *   node --test test/close-timeout-rule.test.mjs   (or: yarn test:unit)
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { transform } from 'esbuild';

const src = readFileSync(new URL('../src/lib/close-timeout-rule.ts', import.meta.url), 'utf8');
const { code } = await transform(src, { loader: 'ts', format: 'esm' });
const { closeMayStillBeRunning, IN_TRANSIT_STATUSES } = await import(
  `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
);

/* --- the reported incident -------------------------------------- */

test('the Cloudflare 504 that broke the 31 Oct close is treated as in-transit', () => {
  // Shape taken from the real DevTools capture: Cloudflare answers with
  // its own JSON body, so there is NO _server_messages.
  assert.equal(
    closeMayStillBeRunning({
      httpStatus: 504,
      message: 'Request failed with status code 504',
    }),
    true
  );
});

test('Cloudflare 524 (origin took too long) is in-transit', () => {
  assert.equal(closeMayStillBeRunning({ httpStatus: 524 }), true);
});

test('502 and 503 from nginx are in-transit', () => {
  assert.equal(closeMayStillBeRunning({ httpStatus: 502 }), true);
  assert.equal(closeMayStillBeRunning({ httpStatus: 503 }), true);
});

test('every declared in-transit status matches', () => {
  for (const status of IN_TRANSIT_STATUSES) {
    assert.equal(closeMayStillBeRunning({ httpStatus: status }), true, `status ${status}`);
  }
});

test('a dropped connection (frappe-sdk isOffline) is in-transit', () => {
  assert.equal(closeMayStillBeRunning({ isOffline: true, message: "You're offline" }), true);
});

test('a proxy that only gives a message string still matches', () => {
  assert.equal(closeMayStillBeRunning({ message: '504 Gateway Timeout' }), true);
  assert.equal(closeMayStillBeRunning({ message: 'The request timed out' }), true);
  assert.equal(closeMayStillBeRunning({ message: 'Network Error' }), true);
});

/* --- real verdicts must NOT be mistaken for a drop ---------------- */

test('a Frappe rejection is a verdict, never in-transit', () => {
  assert.equal(
    closeMayStillBeRunning({
      httpStatus: 417,
      _server_messages: JSON.stringify([
        JSON.stringify({ message: 'You have unpaid orders on this shift.', raise_exception: 1 }),
      ]),
    }),
    false
  );
});

test('_server_messages wins even on a 5xx - the server DID answer', () => {
  // Frappe returns 500 with _server_messages for an unhandled throw.
  // Masking that as "still running" would hide the real error behind a
  // four-minute spinner, which is worse than showing it.
  assert.equal(
    closeMayStillBeRunning({
      httpStatus: 503,
      _server_messages: JSON.stringify([JSON.stringify({ message: 'Mode of Payment misconfigured' })]),
    }),
    false
  );
});

test('the desk-close guard refusal is a verdict', () => {
  assert.equal(
    closeMayStillBeRunning({
      httpStatus: 417,
      _server_messages: JSON.stringify([
        JSON.stringify({ title: 'Close From The POS, Not The Desk', message: '151 invoices', raise_exception: 1 }),
      ]),
    }),
    false
  );
});

test('403 and 404 are verdicts', () => {
  assert.equal(closeMayStillBeRunning({ httpStatus: 403, message: 'Forbidden' }), false);
  assert.equal(closeMayStillBeRunning({ httpStatus: 404, message: 'Not Found' }), false);
});

test('an ordinary validation message is not in-transit', () => {
  assert.equal(
    closeMayStillBeRunning({ httpStatus: 417, message: 'Item Fanta has no stock in warehouse' }),
    false
  );
});

test('a 200-shaped error object is not in-transit', () => {
  assert.equal(closeMayStillBeRunning({ httpStatus: 200, message: 'ok' }), false);
});

/* --- degenerate inputs ------------------------------------------- */

test('null, undefined, strings and numbers are not in-transit', () => {
  assert.equal(closeMayStillBeRunning(null), false);
  assert.equal(closeMayStillBeRunning(undefined), false);
  assert.equal(closeMayStillBeRunning('504 Gateway Timeout'), false);
  assert.equal(closeMayStillBeRunning(504), false);
});

test('an empty object is not in-transit', () => {
  assert.equal(closeMayStillBeRunning({}), false);
});

test('a bare Error with no status is not in-transit', () => {
  assert.equal(closeMayStillBeRunning(new Error('Something went wrong')), false);
});

test('isOffline false does not force a match', () => {
  assert.equal(closeMayStillBeRunning({ isOffline: false, httpStatus: 417 }), false);
});

test('a status that merely CONTAINS 504 does not match', () => {
  // 5040 is not 504 — the word boundary in the message regex matters,
  // and the status check is an equality test, not a substring one.
  assert.equal(closeMayStillBeRunning({ httpStatus: 5040 }), false);
  assert.equal(closeMayStillBeRunning({ message: 'order 15042 failed' }), false);
});

test('the predicate does not mutate its input', () => {
  const err = { httpStatus: 504, message: 'Request failed with status code 504' };
  const before = JSON.stringify(err);
  closeMayStillBeRunning(err);
  assert.equal(JSON.stringify(err), before);
});
