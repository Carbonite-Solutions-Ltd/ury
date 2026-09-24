/*
 * Unit tests for the connectivity hysteresis rule.
 *
 * The POS has no frontend test harness (see CLAUDE.md "Testing"), so this
 * runs on node's built-in test runner and transpiles the single
 * dependency-free source module with esbuild in-process — no vitest/jest
 * dependency added, nothing to keep in sync, and no temp files.
 *
 *   node --test test/connectivity-rule.test.mjs
 *   (or: yarn test:unit)
 *
 * This rule is why the POS no longer alarms on a momentary blip, so it is
 * worth pinning down properly rather than eyeballing it on a tablet.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { transform } from 'esbuild';

const src = readFileSync(new URL('../src/lib/connectivity-rule.ts', import.meta.url), 'utf8');
const { code } = await transform(src, { loader: 'ts', format: 'esm' });
const { nextConnectivity, FAILURES_BEFORE_OFFLINE } = await import(
  `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
);

const ONLINE = { online: true, failures: 0 };

test('default threshold is two consecutive failures', () => {
  assert.equal(FAILURES_BEFORE_OFFLINE, 2);
});

test('a successful probe while online holds online and clears the streak', () => {
  assert.deepEqual(nextConnectivity(ONLINE, true), { online: true, failures: 0 });
});

test('a successful probe recovers immediately from offline (no hysteresis up)', () => {
  assert.deepEqual(
    nextConnectivity({ online: false, failures: 5 }, true),
    { online: true, failures: 0 }
  );
});

test('THE FIX: a single failure does NOT declare offline', () => {
  // This is the regression that caused the flapping on the floor.
  assert.deepEqual(nextConnectivity(ONLINE, false), { online: true, failures: 1 });
});

test('a second consecutive failure declares offline', () => {
  const first = nextConnectivity(ONLINE, false);
  assert.deepEqual(nextConnectivity(first, false), { online: false, failures: 2 });
});

test('further failures keep it offline and keep counting', () => {
  let s = { online: false, failures: 2 };
  s = nextConnectivity(s, false);
  assert.deepEqual(s, { online: false, failures: 3 });
  s = nextConnectivity(s, false);
  assert.deepEqual(s, { online: false, failures: 4 });
});

test('isolated blips never accumulate into an outage', () => {
  // fail, recover, fail, recover... must stay online the whole way through.
  let s = ONLINE;
  for (let i = 0; i < 10; i++) {
    s = nextConnectivity(s, false);
    assert.equal(s.online, true, `blip ${i} must not trip offline`);
    s = nextConnectivity(s, true);
    assert.deepEqual(s, { online: true, failures: 0 });
  }
});

test('a real outage is caught on the second probe, then reported once', () => {
  const seen = [];
  let s = ONLINE;
  for (const ok of [false, false, false, false]) {
    s = nextConnectivity(s, ok);
    seen.push(s.online);
  }
  assert.deepEqual(seen, [true, false, false, false]);
});

test('threshold 1 restores the old trigger-happy behaviour', () => {
  assert.deepEqual(
    nextConnectivity(ONLINE, false, 1),
    { online: false, failures: 1 }
  );
});

test('threshold 3 requires three consecutive failures', () => {
  let s = ONLINE;
  s = nextConnectivity(s, false, 3);
  assert.equal(s.online, true);
  s = nextConnectivity(s, false, 3);
  assert.equal(s.online, true);
  s = nextConnectivity(s, false, 3);
  assert.equal(s.online, false);
});

test('a recovery mid-streak resets the streak, so the next failure is forgiven', () => {
  let s = nextConnectivity(ONLINE, false);      // failures 1
  s = nextConnectivity(s, true);                 // reset
  s = nextConnectivity(s, false);                // failures 1 again, still online
  assert.deepEqual(s, { online: true, failures: 1 });
});

test('the rule is pure — it does not mutate its input', () => {
  const input = { online: true, failures: 0 };
  const frozen = Object.freeze({ ...input });
  const out = nextConnectivity(frozen, false);
  assert.deepEqual(input, { online: true, failures: 0 });
  assert.notEqual(out, frozen);
});

test('offline + failing probe is stable (idempotent once down)', () => {
  const down = { online: false, failures: 2 };
  const out = nextConnectivity(down, false);
  assert.equal(out.online, false);
});
