/**
 * Which categories the POS sidebar shows.
 *
 * ⚠ THE BUG THIS EXISTS TO PREVENT. The sidebar used to list every
 * `URY Menu Course` on the SITE (`db.getDocList('URY Menu Course')`,
 * unscoped, limit "*"). That doctype is a flat global lookup — one `course`
 * Data field, no branch, no profile, no menu link — so there is no filter
 * that could have scoped it. The result was two visible symptoms with one
 * cause:
 *
 *   1. Courses with a 0 count, because a course nothing on this menu uses
 *      still appeared.
 *   2. Another outlet's courses leaking in — a Sitout course showing on an
 *      Airport terminal.
 *
 * The menu itself was never the problem: `getRestaurantMenu` already
 * resolves branch → URY Restaurant → active / room-wise / order-type-wise
 * menu and returns only that menu's items. So the honest source for "which
 * categories apply here" is the items that came back, and deriving from
 * them makes BOTH symptoms impossible by construction rather than filtering
 * them out after the fact.
 *
 * It also removes a round trip on every boot — and specifically the one
 * `/api/resource` call the service worker does not cache, which is why the
 * categories needed their own `ury_offline_categories` localStorage copy to
 * survive an offline reload. Derived categories ride along with the menu's
 * own cache and so can never disagree with the items on screen.
 */

/** Anything with a course — keeps this usable from the store's MenuItem
 *  and from the aggregator shape without coupling to either. */
export interface HasCourse {
  course?: string | null;
}

/**
 * Distinct, non-blank courses present in `items`, sorted alphabetically.
 *
 * Alphabetical is deliberate. `URY Menu Course` has no sort field, so no
 * admin-controlled order exists to respect; the old list came back in
 * `modified DESC`, which reshuffled itself whenever someone edited a
 * course. A cashier scanning a rail wants the same order every shift.
 */
export function deriveCategories(items: ReadonlyArray<HasCourse> | null | undefined): string[] {
  const seen = new Set<string>();

  for (const item of items ?? []) {
    const course = (item?.course ?? '').trim();
    if (course) {
      seen.add(course);
    }
  }

  return Array.from(seen).sort((a, b) =>
    a.localeCompare(b, undefined, { sensitivity: 'base' })
  );
}

/**
 * Keep the active filter honest when the menu changes under it.
 *
 * Switching order type or room can swap the whole menu (order-type-wise and
 * room-wise menus). Without this, a cashier who had "Chinese" selected lands
 * on a menu that has no Chinese, sees an empty grid, and has no visible
 * cause — the category they are filtered to is no longer in the rail.
 * Falling back to "" shows All Items.
 */
export function resolveSelectedCategory(
  selected: string,
  categories: ReadonlyArray<string>
): string {
  if (!selected) return '';
  return categories.includes(selected) ? selected : '';
}
