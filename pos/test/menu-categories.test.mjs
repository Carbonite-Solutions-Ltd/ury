/*
 * Unit tests for the POS category rail.
 *
 * Same in-process esbuild transpile as connectivity-rule.test.mjs — no test
 * harness added, nothing to keep in sync.
 *
 *   node --test test/menu-categories.test.mjs   (or: yarn test:unit)
 *
 * The two properties worth pinning are the two reported symptoms: a course
 * with no items must not appear, and a course from another outlet's menu
 * must not appear. Both follow from deriving the rail from the items, so
 * that is what the tests assert.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { transform } from 'esbuild';

const src = readFileSync(new URL('../src/lib/menu-categories.ts', import.meta.url), 'utf8');
const { code } = await transform(src, { loader: 'ts', format: 'esm' });
const { deriveCategories, resolveSelectedCategory } = await import(
  `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
);

const item = (course) => ({ course });

test('lists each course once, alphabetically', () => {
  assert.deepEqual(
    deriveCategories([item('Drinks'), item('Chinese'), item('Drinks'), item('Bar')]),
    ['Bar', 'Chinese', 'Drinks']
  );
});

test('a course with no items on this menu cannot appear', () => {
  // THE REPORTED SYMPTOM. "MENU - STEWS" exists as a URY Menu Course on the
  // site but nothing on this menu uses it, so it is simply absent — there is
  // no zero-count row to hide.
  const got = deriveCategories([item('Chinese'), item('Drinks')]);
  assert.ok(!got.includes('MENU - STEWS'));
  assert.deepEqual(got, ['Chinese', 'Drinks']);
});

test("another outlet's courses cannot leak in", () => {
  const airport = deriveCategories([item('Chinese'), item('Continental')]);
  for (const sitout of ['CHINESE - SITOUT', 'LOCAL & SOUP DISHES', 'MIX & DINE']) {
    assert.ok(!airport.includes(sitout), `${sitout} leaked into Airport`);
  }
});

test('every returned category has at least one item behind it', () => {
  const items = [item('Drinks'), item('Drinks'), item('Pastries')];
  for (const category of deriveCategories(items)) {
    const count = items.filter((i) => i.course === category).length;
    assert.ok(count > 0, `${category} would render a 0 badge`);
  }
});

test('blank, whitespace and missing courses are dropped, not shown as empty rows', () => {
  assert.deepEqual(
    deriveCategories([item('Drinks'), item(''), item('   '), item(null), item(undefined), {}]),
    ['Drinks']
  );
});

test('course names are trimmed so a stray space is not a second category', () => {
  assert.deepEqual(deriveCategories([item('Drinks'), item(' Drinks ')]), ['Drinks']);
});

test('sorting is case-insensitive so caps do not clump at the top', () => {
  // Real data mixes "Chinese" and "CHINESE - SITOUT" style names; a plain
  // sort would put every capitalised name before every lowercase one.
  assert.deepEqual(
    deriveCategories([item('pastries'), item('Bar'), item('CHINESE')]),
    ['Bar', 'CHINESE', 'pastries']
  );
});

test('an empty or missing menu yields an empty rail, not a crash', () => {
  assert.deepEqual(deriveCategories([]), []);
  assert.deepEqual(deriveCategories(null), []);
  assert.deepEqual(deriveCategories(undefined), []);
});

test('the result is a fresh array, not a view onto the input', () => {
  const items = [item('Drinks')];
  deriveCategories(items).push('Injected');
  assert.deepEqual(deriveCategories(items), ['Drinks']);
});

test('a still-valid filter survives a menu reload', () => {
  assert.equal(resolveSelectedCategory('Drinks', ['Bar', 'Drinks']), 'Drinks');
});

test('a filter the new menu has no category for falls back to All Items', () => {
  // Switching order type can swap the whole menu. Leaving "Chinese"
  // selected would show an empty grid with no visible cause.
  assert.equal(resolveSelectedCategory('Chinese', ['Bar', 'Drinks']), '');
});

test('All Items stays All Items', () => {
  assert.equal(resolveSelectedCategory('', ['Bar']), '');
  assert.equal(resolveSelectedCategory('', []), '');
});

test('an empty menu clears the filter rather than stranding it', () => {
  assert.equal(resolveSelectedCategory('Drinks', []), '');
});
