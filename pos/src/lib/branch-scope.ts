/**
 * Branch / terminal scoping for the POS.
 *
 * A URY POS Terminal is bound to one POS Profile, which belongs to one
 * Branch, which resolves one menu — and **each menu carries its own price
 * list**. On this client the same item is routinely priced very differently
 * per branch (COKE 12.00 at one outlet, 35.00 at the other), so serving one
 * branch's menu while trading on another is not a cosmetic bug: it sells
 * stock at roughly half price.
 *
 * Two jobs live here:
 *
 *   1. **The cache keys** (`offlineMenuKeys`). Every durable copy of a menu
 *      must be keyed by the POS Profile it came from. See the warning on
 *      that function — a non-keyed fallback is exactly how one branch's
 *      prices reach another.
 *
 *   2. **The switch** (`clearBranchScopedCaches`). Changing terminal has to
 *      drop everything derived from the old branch, or the POS comes back up
 *      showing the previous outlet's menu, profile and cart.
 *
 * The grouping helpers are pure so the switcher can be tested without a
 * browser.
 */

export interface TerminalOption {
  terminal: string;
  branch?: string | null;
  pos_profile?: string | null;
  description?: string | null;
  room?: string | null;
}

export interface BranchGroup {
  branch: string;
  terminals: TerminalOption[];
}

const UNASSIGNED = 'Unassigned';

/**
 * Terminals grouped by branch, branches alphabetical, terminals
 * alphabetical inside each.
 *
 * The setup screen and the switcher both render this. A flat list of every
 * terminal across every branch is how someone picks the wrong outlet by
 * mistake — the grouping is the point, not decoration.
 */
export function groupTerminalsByBranch(
  terminals: ReadonlyArray<TerminalOption> | null | undefined
): BranchGroup[] {
  const byBranch = new Map<string, TerminalOption[]>();

  for (const t of terminals ?? []) {
    if (!t?.terminal) continue;
    const branch = (t.branch ?? '').trim() || UNASSIGNED;
    const bucket = byBranch.get(branch);
    if (bucket) bucket.push(t);
    else byBranch.set(branch, [t]);
  }

  return Array.from(byBranch.entries())
    .sort((a, b) => a[0].localeCompare(b[0], undefined, { sensitivity: 'base' }))
    .map(([branch, list]) => ({
      branch,
      terminals: [...list].sort((a, b) =>
        a.terminal.localeCompare(b.terminal, undefined, { sensitivity: 'base' })
      ),
    }));
}

/** Distinct branches the user can reach. */
export function accessibleBranches(
  terminals: ReadonlyArray<TerminalOption> | null | undefined
): string[] {
  return groupTerminalsByBranch(terminals).map((g) => g.branch);
}

/**
 * Is there anywhere to switch TO?
 *
 * Deliberately "more than one terminal", not "more than one branch" and not
 * a role check. A cashier listed on two branches has a real reason to
 * switch and used to have no way to; gating this on Manager/Captain is the
 * kind of over-tight check this app is trying to shed. The server still
 * enforces access on every switch (`_require_branch_access`), so this only
 * decides whether to offer the control.
 */
export function canSwitchTerminal(
  terminals: ReadonlyArray<TerminalOption> | null | undefined
): boolean {
  return (terminals ?? []).filter((t) => t?.terminal).length > 1;
}

/**
 * Keys for the durable offline copy of a menu.
 *
 * ⚠ BOTH keys are scoped to the POS Profile, and the fallback one especially.
 * It used to be a bare `ury_offline_menu_last` shared by every profile, so
 * this sequence served one branch's prices on another branch's till:
 *
 *   trade on Airport  -> last = Airport menu
 *   switch to Sitout  -> Sitout has no copy yet
 *   menu fetch fails  -> fall back to "last" = **Airport prices**
 *
 * and a failed fetch is routine on this client's link, which is the whole
 * reason the durable copy exists. Keying it per profile makes the fallback
 * able to serve only the same profile it was written by, so the leak cannot
 * happen while keeping the offline benefit across room / order-type changes.
 */
export function offlineMenuKeys(
  posProfile: string,
  room: string | null | undefined,
  orderType: string | null | undefined
): { ctxKey: string; lastKey: string } {
  return {
    ctxKey: `ury_offline_menu:${posProfile}:${room || ''}:${orderType || ''}`,
    lastKey: `ury_offline_menu_last:${posProfile}`,
  };
}

/**
 * localStorage prefixes holding data derived from one branch's menu/profile.
 *
 * Everything matching is dropped on a terminal switch.
 */
export const BRANCH_SCOPED_LOCAL_PREFIXES = [
  'ury_offline_menu', // covers both the per-context and per-profile fallback
  'pos_profile', // legacy full-profile copy written by older builds
] as const;

/**
 * Keys that must SURVIVE a switch, documented so nobody widens the sweep
 * into them by accident.
 *
 * ⚠ `ury_order_outbox` above all. It holds orders taken offline that have
 * not reached the server yet — clearing it loses real sales. Each queued
 * order carries its own POS Profile in its payload, so it settles against
 * the branch it was rung on regardless of where the device is now.
 */
export const SWITCH_SAFE_LOCAL_KEYS = [
  'ury_order_outbox',
  'ury_pos_terminal', // replaced by the switch itself, not cleared
  'currency',
  'currencySymbol',
  'ury_min_screen_width',
] as const;

/** True when `key` is branch-derived and should be dropped on a switch. */
export function isBranchScopedKey(key: string): boolean {
  if ((SWITCH_SAFE_LOCAL_KEYS as readonly string[]).includes(key)) return false;
  return BRANCH_SCOPED_LOCAL_PREFIXES.some((p) => key.startsWith(p));
}

/**
 * Drop everything the previous branch put in the browser.
 *
 * sessionStorage goes wholesale — it holds the cart, the POS Profile, the
 * payment modes and the customer lookups, all of which belong to the branch
 * being left. The cart is the one with a visible consequence, so the
 * switcher warns before calling this.
 */
export function clearBranchScopedCaches(): void {
  try {
    sessionStorage.clear();
  } catch {
    /* private mode / blocked storage — nothing cached to leak either */
  }

  try {
    const doomed: string[] = [];
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (key && isBranchScopedKey(key)) doomed.push(key);
    }
    doomed.forEach((key) => localStorage.removeItem(key));
  } catch {
    /* ditto */
  }
}
