/*
 * Unit tests for the KDS connectivity hysteresis rule.
 *
 * URYMosaic is `"type": "module"`, so the rule imports directly with no
 * transpile step. Run with:
 *
 *   node --test test/connectivity-rule.test.mjs     (or: yarn test:unit)
 *
 * The last test is the important one: it pins the KDS rule to the POS's
 * copy. The two are deliberate duplicates (the frontends share no code by
 * design) and they must not drift — a kitchen screen and a till on the
 * same Wi-Fi disagreeing about whether the venue is online would be a
 * genuinely confusing bug to chase.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { nextConnectivity, FAILURES_BEFORE_OFFLINE } from '../src/lib/connectivity-rule.js';

const ONLINE = { online: true, failures: 0 };

test('default threshold is two consecutive failures', () => {
  assert.equal(FAILURES_BEFORE_OFFLINE, 2);
});

test('a successful probe while online holds online and clears the streak', () => {
  assert.deepEqual(nextConnectivity(ONLINE, true), { online: true, failures: 0 });
});

test('a successful probe recovers immediately from offline', () => {
  assert.deepEqual(
    nextConnectivity({ online: false, failures: 5 }, true),
    { online: true, failures: 0 }
  );
});

test('THE FIX: a single failure does NOT declare the screen offline', () => {
  // The KDS previously trusted navigator.onLine outright, so one flap was
  // enough to pop the red toast. This is what stops that.
  assert.deepEqual(nextConnectivity(ONLINE, false), { online: true, failures: 1 });
});

test('a second consecutive failure declares offline', () => {
  const first = nextConnectivity(ONLINE, false);
  assert.deepEqual(nextConnectivity(first, false), { online: false, failures: 2 });
});

test('isolated blips never accumulate into an outage', () => {
  let s = ONLINE;
  for (let i = 0; i < 10; i++) {
    s = nextConnectivity(s, false);
    assert.equal(s.online, true, `blip ${i} must not trip offline`);
    s = nextConnectivity(s, true);
    assert.deepEqual(s, { online: true, failures: 0 });
  }
});

test('a real outage is caught on the second probe, then stays put', () => {
  const seen = [];
  let s = ONLINE;
  for (const ok of [false, false, false, false]) {
    s = nextConnectivity(s, ok);
    seen.push(s.online);
  }
  assert.deepEqual(seen, [true, false, false, false]);
});

test('threshold is configurable (1 restores trigger-happy, 3 needs three)', () => {
  assert.equal(nextConnectivity(ONLINE, false, 1).online, false);
  let s = ONLINE;
  s = nextConnectivity(s, false, 3);
  assert.equal(s.online, true);
  s = nextConnectivity(s, false, 3);
  assert.equal(s.online, true);
  s = nextConnectivity(s, false, 3);
  assert.equal(s.online, false);
});

test('the rule is pure — it does not mutate its input', () => {
  const input = { online: true, failures: 0 };
  nextConnectivity(Object.freeze({ ...input }), false);
  assert.deepEqual(input, { online: true, failures: 0 });
});

test('KDS and POS rules agree on every state/result combination', async () => {
  const posSrc = fileURLToPath(
    new URL('../../pos/src/lib/connectivity-rule.ts', import.meta.url)
  );
  if (!existsSync(posSrc)) {
    // Shouldn't happen in this monorepo, but don't fail the suite over a
    // missing sibling project — just say so.
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

  assert.equal(
    pos.FAILURES_BEFORE_OFFLINE,
    FAILURES_BEFORE_OFFLINE,
    'thresholds drifted between the POS and the KDS'
  );

  // Exhaustive over the inputs that matter: both starting states, a
  // failure streak spanning either side of the threshold, both probe
  // results, and every threshold the callers could pass.
  for (const online of [true, false]) {
    for (let failures = 0; failures <= 4; failures++) {
      for (const ok of [true, false]) {
        for (const threshold of [1, 2, 3]) {
          const state = { online, failures };
          assert.deepEqual(
            nextConnectivity({ ...state }, ok, threshold),
            pos.nextConnectivity({ ...state }, ok, threshold),
            `drift at online=${online} failures=${failures} ok=${ok} threshold=${threshold}`
          );
        }
      }
    }
  }
});
