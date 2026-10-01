/*
 * Unit tests for branch / till scoping.
 *
 *   node --test test/branch-scope.test.mjs   (or: yarn test:unit)
 *
 * The expensive mistake here is a price leak between branches — the same
 * item is priced very differently per outlet — so the cache keys get the
 * most attention: the old shared fallback key is the one that could serve
 * Airport prices on a Sitout till.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { transform } from 'esbuild';

const src = readFileSync(new URL('../src/lib/branch-scope.ts', import.meta.url), 'utf8');
const { code } = await transform(src, { loader: 'ts', format: 'esm' });
const {
  groupTerminalsByBranch,
  accessibleBranches,
  canSwitchTerminal,
  offlineMenuKeys,
  isBranchScopedKey,
} = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);

const T = (terminal, branch) => ({ terminal, branch });

test('groups terminals under their branch', () => {
  const got = groupTerminalsByBranch([
    T('Airport Main', 'Airport'),
    T('Sitout Kitchen', 'Sitout'),
    T('Airport Bar', 'Airport'),
  ]);
  assert.deepEqual(
    got.map((g) => [g.branch, g.terminals.map((t) => t.terminal)]),
    [
      ['Airport', ['Airport Bar', 'Airport Main']],
      ['Sitout', ['Sitout Kitchen']],
    ]
  );
});

test('branches and terminals are both sorted, so the list is stable', () => {
  const got = groupTerminalsByBranch([T('b', 'Zeta'), T('a', 'Alpha')]);
  assert.deepEqual(got.map((g) => g.branch), ['Alpha', 'Zeta']);
});

test('a terminal with no branch is kept, not silently dropped', () => {
  // Dropping it would hide a real, selectable till from the picker.
  const got = groupTerminalsByBranch([T('Orphan', null), T('Main', 'Airport')]);
  assert.deepEqual(got.map((g) => g.branch), ['Airport', 'Unassigned']);
});

test('rows with no terminal name are ignored', () => {
  assert.equal(groupTerminalsByBranch([{ terminal: '' }, T('A', 'X')]).length, 1);
});

test('empty and missing input give an empty list', () => {
  assert.deepEqual(groupTerminalsByBranch([]), []);
  assert.deepEqual(groupTerminalsByBranch(null), []);
  assert.deepEqual(groupTerminalsByBranch(undefined), []);
});

test('accessibleBranches lists each branch once', () => {
  assert.deepEqual(
    accessibleBranches([T('a', 'Airport'), T('b', 'Airport'), T('c', 'Sitout')]),
    ['Airport', 'Sitout']
  );
});

test('the switcher is offered on more than one till, including within one branch', () => {
  assert.equal(canSwitchTerminal([T('a', 'Airport'), T('b', 'Airport')]), true);
  assert.equal(canSwitchTerminal([T('a', 'Airport'), T('b', 'Sitout')]), true);
});

test('a user with one till is not offered a switch', () => {
  assert.equal(canSwitchTerminal([T('only', 'Airport')]), false);
  assert.equal(canSwitchTerminal([]), false);
  assert.equal(canSwitchTerminal(null), false);
});

// ── the price leak ────────────────────────────────────────────────────

test('the fallback menu key is per POS Profile, not shared', () => {
  // THE BUG. A shared 'ury_offline_menu_last' let a failed fetch on one
  // branch fall back to the other branch's menu — and its prices.
  const airport = offlineMenuKeys('Airport', null, 'Dine In');
  const sitout = offlineMenuKeys('Sitout', null, 'Dine In');
  assert.notEqual(airport.lastKey, sitout.lastKey);
  assert.ok(airport.lastKey.includes('Airport'));
  assert.ok(sitout.lastKey.includes('Sitout'));
});

test('two profiles never share a context key either', () => {
  assert.notEqual(
    offlineMenuKeys('Airport', 'Room 1', 'Dine In').ctxKey,
    offlineMenuKeys('Sitout', 'Room 1', 'Dine In').ctxKey
  );
});

test('within one profile the fallback IS shared across room and order type', () => {
  // That sharing is the point of the fallback — it just must not cross
  // profiles. Same profile, different context: same lastKey, different ctx.
  const dine = offlineMenuKeys('Airport', null, 'Dine In');
  const away = offlineMenuKeys('Airport', 'Room 2', 'Take Away');
  assert.equal(dine.lastKey, away.lastKey);
  assert.notEqual(dine.ctxKey, away.ctxKey);
});

test('a missing room or order type still yields a usable key', () => {
  const k = offlineMenuKeys('Airport', null, null);
  assert.ok(k.ctxKey.startsWith('ury_offline_menu:Airport:'));
  assert.ok(!k.ctxKey.includes('null'));
});

// ── what a switch clears, and what it must not ────────────────────────

test('menu copies and the legacy profile copy are cleared on a switch', () => {
  assert.ok(isBranchScopedKey('ury_offline_menu:Airport::Dine In'));
  assert.ok(isBranchScopedKey('ury_offline_menu_last:Airport'));
  assert.ok(isBranchScopedKey('pos_profile'));
});

test('queued offline orders SURVIVE a switch', () => {
  // Clearing the outbox would destroy sales taken offline that have not
  // reached the server yet. Each one carries its own POS Profile.
  assert.equal(isBranchScopedKey('ury_order_outbox'), false);
});

test('device and site settings survive a switch', () => {
  for (const key of ['ury_pos_terminal', 'currency', 'currencySymbol', 'ury_min_screen_width']) {
    assert.equal(isBranchScopedKey(key), false, `${key} must survive`);
  }
});

test('unrelated keys are left alone', () => {
  assert.equal(isBranchScopedKey('ury_pwa_install_dismissed'), false);
  assert.equal(isBranchScopedKey('ury_offline_waiters'), false);
});
