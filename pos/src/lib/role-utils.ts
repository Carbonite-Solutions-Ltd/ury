import type { PosProfileCombined } from './pos-profile-api';
import type { User } from '../store/slices/auth-slice';

export const isUserRestrictedFromTableOrders = (
  user: User | null,
  posProfile: PosProfileCombined | null
): boolean => {
  if (!user || !posProfile || !user.roles || !posProfile.role_restricted_for_table_order) {
    return false;
  }

  // Get the restricted roles from the POS profile
  const restrictedRoles = posProfile.role_restricted_for_table_order.map(role => role.role);

  // Check if the user has any of the restricted roles
  const hasRestrictedRole = user.roles.some(role => restrictedRoles.includes(role));

  return hasRestrictedRole;
};

/**
 * Whether the current user is allowed to manage menu/item prices from the
 * POS. Gate for in-POS "Set Price" deep-link buttons (Price Not Set
 * toast, future menu-price quick-edit, etc.) — a cashier shouldn't see
 * buttons they can't act on.
 *
 * Allowed roles: Administrator, System Manager (the framework god roles)
 * plus URY Manager and URY Captain (the URY-side ops roles that already
 * have desk write access on URY Menu). Cashiers are excluded by design —
 * if a cashier hits Price Not Set, they should ask a manager/captain.
 */
export const canManageMenuPrices = (user: User | null): boolean => {
  if (!user) return false;
  if (user.name === 'Administrator') return true;
  if (!user.roles) return false;
  const allowed = ['System Manager', 'URY Manager', 'URY Captain'];
  return user.roles.some((role) => allowed.includes(role));
};

/**
 * Whether the current user can see other cashiers' orders on the same
 * terminal in the Orders page. Cashiers see only their own orders;
 * captains/managers/admins see a "Cashier" filter dropdown that lets
 * them switch between Mine, All Cashiers, or a specific user.
 *
 * Backend enforces the same allowed-roles list in
 * `_resolve_orders_scope` so a malicious frontend can't escalate.
 */
export const canSeeAllTerminalOrders = (user: User | null): boolean => {
  if (!user) return false;
  if (user.name === 'Administrator') return true;
  if (!user.roles) return false;
  const allowed = ['System Manager', 'URY Manager', 'URY Captain'];
  return user.roles.some((role) => allowed.includes(role));
};

/**
 * Whether the current user can re-print an already-printed POS Invoice.
 * Cashiers can print once (the print button hides after invoice_printed
 * goes to 1). Captains / managers / admins can re-print at will. The
 * first print is allowed for everyone — this gate only kicks in for
 * the *re*-print.
 */
export const canReprintInvoice = (user: User | null): boolean => {
  if (!user) return false;
  if (user.name === 'Administrator') return true;
  if (!user.roles) return false;
  const allowed = ['System Manager', 'URY Manager', 'URY Captain'];
  return user.roles.some((role) => allowed.includes(role));
};

/**
 * Whether the current user can use the Merge Orders feature on this
 * POS Profile. Two layers of gating:
 *   1. The user must have URY Cashier or higher.
 *   2. If `posProfile.custom_restrict_merge_to_captain === 1`, only
 *      captains / managers / admins can merge — cashiers see no
 *      Merge Orders button.
 *
 * Backend re-validates the same logic in `_user_can_merge_orders` and
 * additionally enforces "cashiers can only merge their own orders".
 */
export const canMergeOrders = (
  user: User | null,
  posProfile: PosProfileCombined | null
): boolean => {
  if (!user) return false;
  if (user.name === 'Administrator') return true;
  if (!user.roles) return false;

  const captainRoles = ['System Manager', 'URY Manager', 'URY Captain'];
  const isCaptain = user.roles.some((role) => captainRoles.includes(role));
  if (isCaptain) return true;

  // Captain restriction is on — non-captains can't merge.
  if (posProfile?.custom_restrict_merge_to_captain === 1) return false;

  // Otherwise URY Cashier is enough.
  return user.roles.includes('URY Cashier');
};

/**
 * Whether the current user can access admin-ish actions in the user
 * menu dropdown — specifically "Change Terminal" and "Switch to Desk".
 * Cashiers can't switch terminals (they're bound to the one they were
 * registered on) and shouldn't be dropped into the Frappe desk where
 * they can touch unrelated masters.
 *
 * Allowed: Administrator, System Manager, URY Manager, URY Captain.
 * Denied: URY Cashier.
 */
export const canAccessDeskAndTerminalSwitch = (
  user: User | null
): boolean => {
  if (!user) return false;
  if (user.name === 'Administrator') return true;
  if (!user.roles) return false;
  const allowed = ['System Manager', 'URY Manager', 'URY Captain'];
  return user.roles.some((role) => allowed.includes(role));
};

/**
 * Whether the current user can return orders on this POS Profile.
 * Defaults to captain-only: `custom_restrict_returns_to_captain` starts
 * at 1 (ON) and can be flipped OFF per profile to let cashiers return
 * their own orders. Captains / managers / admins can always return.
 *
 * Backend re-validates the same gate in `_user_can_return_orders`.
 */
/**
 * Whether the current user can see the cross-cashier admin reports
 * (Sales by Cashier, Sales by Category, Top / Bottom Items) on the
 * Reports page. Cashiers see only their own shift summary + the
 * existing per-user Daily Sales + Dashboard tabs.
 *
 * Backend re-validates the same role list in
 * ``_user_can_see_admin_reports`` so a malicious frontend can't
 * escalate by spoofing the endpoint.
 */
export const canSeeAdminReports = (user: User | null): boolean => {
  if (!user) return false;
  if (user.name === 'Administrator') return true;
  if (!user.roles) return false;
  const allowed = ['System Manager', 'URY Manager', 'URY Captain'];
  return user.roles.some((role) => allowed.includes(role));
};

export const canReturnOrders = (
  user: User | null,
  posProfile: PosProfileCombined | null
): boolean => {
  if (!user) return false;

  // Master switch (2026-06-05). Returns are OFF by default. When off,
  // NOBODY can return — not even a captain. Evaluated before every role
  // check. Backend mirrors this in `_user_can_return_orders`.
  if (posProfile?.custom_enable_returns !== 1) return false;

  if (user.name === 'Administrator') return true;
  if (!user.roles) return false;

  const captainRoles = ['System Manager', 'URY Manager', 'URY Captain'];
  const isCaptain = user.roles.some((role) => captainRoles.includes(role));
  if (isCaptain) return true;

  // Default ON (undefined) is treated as restricted, matching the backend.
  const restrict =
    posProfile?.custom_restrict_returns_to_captain ?? 1;
  if (restrict === 1) return false;

  return user.roles.includes('URY Cashier');
};

/**
 * Whether the current user can INITIATE an invoice transfer at shift
 * close. Captain-only (2026-06-05): a regular cashier closing with
 * unpaid drafts must pay or cancel them. Backend re-validates in
 * `submit_pos_closing_entry`.
 */
export const canTransferOnClose = (user: User | null): boolean => {
  if (!user) return false;
  if (user.name === 'Administrator') return true;
  if (!user.roles) return false;
  const captainRoles = ['System Manager', 'URY Manager', 'URY Captain'];
  return user.roles.some((role) => captainRoles.includes(role));
};

/**
 * Whether the current user can split an order's items into separate
 * bills. Any URY billing role can split; the backend additionally
 * enforces "a plain cashier can only split their own order" in
 * `split_invoice_by_item`.
 */
export const canSplitOrders = (user: User | null): boolean => {
  if (!user) return false;
  if (user.name === 'Administrator') return true;
  if (!user.roles) return false;
  const allowed = ['System Manager', 'URY Manager', 'URY Captain', 'URY Cashier'];
  return user.roles.some((role) => allowed.includes(role));
};

/**
 * Whether the current user is a "waiter only" — a URY Waiter who isn't an
 * elevated user (Administrator / System Manager / URY Manager / URY Captain).
 * These users get the SIMPLIFIED POS: they place orders + see their own
 * orders/tables, but do no payments, invoicing, printing or shift close
 * (the cashier does all that). 2026-07-14.
 *
 * Matches the backend self-waiter gate (`_get_self_waiter_for_user`): the
 * URY Waiter role + not elevated. A user who is ALSO a cashier is still
 * treated as a waiter here — don't give the waiter role to a cashier.
 */
export const isWaiterOnly = (user: User | null): boolean => {
  if (!user || !user.roles) return false;
  if (user.name === 'Administrator') return false;
  const elevated = ['System Manager', 'URY Manager', 'URY Captain'];
  if (user.roles.some((role) => elevated.includes(role))) return false;
  return user.roles.includes('URY Waiter');
};

/**
 * Captain / Manager / Admin tier. The canonical "elevated user" check
 * used for order-lifecycle actions a plain cashier shouldn't have:
 *   - Cancelling an order (the X on a draft) — 2026-06-11.
 *   - Freely editing an already-made order's items (a cashier can only
 *     INCREASE original-item qty; never decrease below the original or
 *     remove an original line, which previously let them delete the
 *     whole order by emptying it). New items they add this session stay
 *     fully editable.
 *
 * Allowed: Administrator, System Manager, URY Manager, URY Captain.
 * Backend should re-validate where it matters.
 */
export const isCaptainOrAbove = (user: User | null): boolean => {
  if (!user) return false;
  if (user.name === 'Administrator') return true;
  if (!user.roles) return false;
  const allowed = ['System Manager', 'URY Manager', 'URY Captain'];
  return user.roles.some((role) => allowed.includes(role));
};

/**
 * Whether the current user may choose to MARK a bill printed instead of
 * physically printing it. When true, the Print / Reprint button opens a
 * PrintChoiceDialog ("Print to Printer" vs "Mark as Printed") rather
 * than going straight to the printer.
 *
 * This exists for admins testing invoices and payments, who otherwise
 * burn a physical receipt on every single test order. "Mark as Printed"
 * calls the same `qz_print_update` endpoint a real print calls, so the
 * invoice still gets `invoice_printed = 1` and the Payment button still
 * unlocks — the ONLY difference is that nothing is sent to a printer.
 *
 * Deliberately TIGHTER than `isCaptainOrAbove`: only Administrator and
 * System Manager, i.e. actual system administrators. URY Manager and
 * URY Captain are floor-ops roles who should be printing real bills for
 * customers, and giving them a one-click "pretend I printed it" button
 * on live orders is a control we don't want to hand out by default.
 * Widen the list here if a site genuinely needs it.
 */
/**
 * Whether the current user can open the POS Settings page (avatar menu →
 * Settings). Administrator / System Manager / URY Manager only.
 *
 * Deliberately EXCLUDES URY Captain, unlike most of the "elevated"
 * helpers here: Settings exposes branch-wide configuration diagnostics,
 * which is an owner/manager concern rather than a floor-ops one.
 *
 * Backend mirrors this in `_user_can_manage_settings`, which is the
 * authoritative check — every settings endpoint re-validates, so hiding
 * the menu item is only a UX courtesy.
 */
export const canAccessSettings = (user: User | null): boolean => {
  if (!user) return false;
  if (user.name === 'Administrator') return true;
  if (!user.roles) return false;
  const allowed = ['System Manager', 'URY Manager'];
  return user.roles.some((role) => allowed.includes(role));
};

export const canSkipPhysicalPrint = (user: User | null): boolean => {
  if (!user) return false;
  if (user.name === 'Administrator') return true;
  if (!user.roles) return false;
  return user.roles.includes('System Manager');
};

/**
 * Who may close the day (2026-08-05).
 *
 * DELIBERATELY NARROWER than `isCaptainOrAbove`: **ExPOS Manager only**,
 * plus Administrator / System Manager as a break-glass. Captains and
 * cashiers can no longer close.
 *
 * This REVERSES the soft gate agreed on 2026-07-29, which warned and
 * recorded but never blocked. That warning was written around a single
 * captain being unavailable; in practice URY Manager is the widest of
 * the three URY roles, so a hard gate does not strand a shift the way
 * a captain-only rule would have.
 *
 * ⚠ THE ONE THING THAT MAKES THIS DANGEROUS is POS Profile's
 * `custom_daily_pos_close`. With that on, an unclosed previous day
 * blocks the POS entirely - so "no manager was around last night"
 * becomes "nobody can trade this morning". Administrator and System
 * Manager are kept here precisely so that state is recoverable. Do not
 * remove them without providing another way out.
 *
 * Backend `submit_pos_closing_entry` enforces the same list; this is
 * the UI half.
 */
export const canCloseShift = (user: User | null): boolean => {
  if (!user) return false;
  if (user.name === 'Administrator') return true;
  return user.roles.some((r) =>
    ['System Manager', 'URY Manager'].includes(r)
  );
};
