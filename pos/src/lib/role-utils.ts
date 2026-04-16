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
