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
