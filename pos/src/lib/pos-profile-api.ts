import { DOCTYPES } from '../data/doctypes';
import { call, db } from './frappe-sdk';

// Limited fields response
export interface PosProfileLimited {
  pos_profile: string;
  branch: string;
  company: string;
  waiter: string;
  warehouse: string;
  cashier: string;
  print_format: string | null;
  qz_print: number;
  qz_host: string | null;
  printer: string | null;
  print_type: string;
  tableAttention: number;
  paid_limit: number;
  disable_rounded_total: number;
  enable_discount: number;
  multiple_cashier: number;
  owner: string;
  edit_order_type?: number;
  /** Terminal name that resolved this profile — echoed back from the server. */
  terminal?: string | null;
  /** Shift length in hours. 0 = disabled. */
  custom_shift_hours?: number;
  /** When 1, OrderPanel disables new orders once the shift hours are exceeded. */
  custom_block_orders_after_shift_end?: number;
  /** When 1, only captains/managers can use the Orders page Merge Orders button. */
  custom_restrict_merge_to_captain?: number;
  /**
   * When 1 (default), only captains/managers can return orders from the
   * Orders page right panel. Flip to 0 to let cashiers return their own.
   */
  custom_restrict_returns_to_captain?: number;
  /**
   * Master switch for the Return feature (2026-06-05). OFF (0) by
   * default — returns are hidden everywhere unless an admin turns this
   * on. Evaluated before custom_restrict_returns_to_captain.
   */
  custom_enable_returns?: number;
  /**
   * How many times a single unpaid order may be transferred between
   * cashiers at shift close (per-invoice hop count). 0 disables
   * transfers. Default 2.
   */
  custom_max_invoice_transfers?: number;
  /** iHotel integration master switch (per-profile). */
  custom_ihotel_enabled?: number;
  /** Default Charge Type written onto the iHotel Profile's folio row. */
  custom_ihotel_charge_type?: string | null;
  /**
   * Shift system mode. "Disabled" falls back to the legacy
   * `custom_shift_hours` reminder. "URY Shift" uses URY Shift
   * Assignment + URY Shift records. "HRMS Shift Type" uses ERPNext
   * HRMS Shift Type + Shift Assignment via Employee. See CLAUDE.md
   * "Fixes log" 2026-04-14.
   */
  custom_shift_system_mode?: 'Disabled' | 'URY Shift' | 'HRMS Shift Type';
  /**
   * Unified print routing config (2026-04-16). Replaces the legacy
   * per-order-type printer fields. When `custom_print_mode` is unset
   * the backend falls back to the legacy `custom_table_order_printer`
   * / `custom_parcel_order_printer` chain. All the routing
   * (Food/Drinks → which printer) is resolved server-side in
   * `ury_print.resolve_kot_print_plan` — the React POS only reads
   * `custom_print_mode` to decide the client print path (QZ vs
   * CUPS vs Disabled).
   */
  custom_print_mode?: 'QZ Tray' | 'CUPS (Direct)' | 'Disabled' | null;
  custom_bill_printer?: string | null;
  custom_kitchen_kot_printer?: string | null;
  custom_bar_kot_printer?: string | null;
  custom_parcel_kot_printer?: string | null;
  custom_drinks_kot_route?: 'Bar' | 'Kitchen' | 'Bill' | null;
  custom_food_kot_route?: 'Kitchen' | 'Bar' | 'Bill' | null;
  custom_takeaway_kot_route?: 'Parcel' | 'Kitchen' | null;
  custom_print_fallback_mode?:
    | 'Fallback to Bill Printer'
    | 'Fail Silently'
    | 'Fail with Alert'
    | null;
}

export interface PosProfileLimitedResponse {
  message: PosProfileLimited;
}

interface RolePermission {
  name: string;
  owner: string;
  creation: string;
  modified: string;
  modified_by: string;
  docstatus: number;
  idx: number;
  role: string;
  parent: string;
  parentfield: string;
  parenttype: string;
  doctype: string;
}

/**
 * POS Profile User (child table applicable_for_users).
 * `custom_main_cashier` marks the "captain" in multi-cashier mode.
 */
export interface PosProfileUser {
  user: string;
  custom_main_cashier?: 0 | 1;
}

/**
 * POS Profile payment row (child table payments).
 * Used to seed the opening-balance form.
 */
export interface PosProfilePayment {
  mode_of_payment: string;
  default?: 0 | 1;
}

// Full POS Profile response
export interface PosProfileFull {
  name: string;
  owner: string;
  creation: string;
  modified: string;
  modified_by: string;
  docstatus: number;
  idx: number;
  company: string;
  customer: string | null;
  country: string;
  disabled: number;
  warehouse: string;
  campaign: string | null;
  company_address: string | null;
  restaurant: string;
  branch: string;
  currency: string;
  role_allowed_for_billing: RolePermission[];
  role_restricted_for_table_order?: RolePermission[];
  paid_limit?: number;
  applicable_for_users?: PosProfileUser[];
  payments?: PosProfilePayment[];
  custom_enable_multiple_cashier?: 0 | 1;
}

// Combined POS Profile with both limited and full fields
export interface PosProfileCombined extends PosProfileFull {
  // Add limited fields that don't exist in full profile
  waiter: string;
  cashier: string;
  print_format: string | null;
  qz_print: number;
  qz_host: string | null;
  printer: string | null;
  print_type: string;
  tableAttention: number;
  paid_limit: number;
  disable_rounded_total: number;
  enable_discount: number;
  multiple_cashier: number;
  edit_order_type?: number;
  view_all_status?: number;
  custom_daily_pos_close?: number;
  custom_shift_hours?: number;
  custom_block_orders_after_shift_end?: number;
  custom_restrict_merge_to_captain?: number;
  custom_restrict_returns_to_captain?: number;
  custom_enable_returns?: number;
  custom_max_invoice_transfers?: number;
  custom_ihotel_enabled?: number;
  custom_ihotel_charge_type?: string | null;
  custom_shift_system_mode?: 'Disabled' | 'URY Shift' | 'HRMS Shift Type';
  custom_print_mode?: 'QZ Tray' | 'CUPS (Direct)' | 'Disabled' | null;
  custom_bill_printer?: string | null;
  custom_kitchen_kot_printer?: string | null;
  custom_bar_kot_printer?: string | null;
  custom_parcel_kot_printer?: string | null;
  custom_drinks_kot_route?: 'Bar' | 'Kitchen' | 'Bill' | null;
  custom_food_kot_route?: 'Kitchen' | 'Bar' | 'Bill' | null;
  custom_takeaway_kot_route?: 'Parcel' | 'Kitchen' | null;
  custom_print_fallback_mode?:
    | 'Fallback to Bill Printer'
    | 'Fail Silently'
    | 'Fail with Alert'
    | null;
}

export interface Currency {
  name: string;
  symbol: string;
  fraction: string;
  fraction_units: number;
  smallest_currency_fraction_value: number;
  number_format: string;
}

export interface PosProfileFullResponse {
  message: PosProfileFull;
}

export async function getPosProfileLimitedFields(
  terminal?: string | null
): Promise<PosProfileLimited> {
  // The backend uses `terminal` to resolve the correct POS Profile
  // deterministically when a branch has multiple profiles.
  // See CLAUDE.md "Fixes log" 2026-04-08 ("URY POS Terminal ↔ POS Profile").
  const params: Record<string, string> = {};
  if (terminal) params.terminal = terminal;
  const res = await call.get('ury.ury_pos.api.getPosProfile', params);
  return res.message;
}

export async function getPosProfileFull(
  posProfileName: string,
  terminal?: string | null
): Promise<PosProfileFull> {
  // Goes through the whitelisted `get_pos_profile_full` method instead
  // of the REST resource endpoint so URY Cashier / URY Captain users
  // don't need a Custom DocPerm row on POS Profile to read their own
  // profile. Backend enforces that the requested profile matches the
  // terminal's binding. See CLAUDE.md "Fixes log" 2026-04-09.
  const params: Record<string, string> = { pos_profile: posProfileName };
  if (terminal) params.terminal = terminal;
  const res = await call.get<{ message: PosProfileFull }>(
    'ury.ury_pos.api.get_pos_profile_full',
    params
  );
  return res.message;
}

export async function getCombinedPosProfile(
  terminal?: string | null
): Promise<PosProfileCombined> {
  const limitedProfile = await getPosProfileLimitedFields(terminal);

  const fullProfile = await getPosProfileFull(
    limitedProfile.pos_profile,
    terminal
  );

  const combinedProfile: PosProfileCombined = {
    ...fullProfile,
    waiter: limitedProfile.waiter,
    cashier: limitedProfile.cashier,
    print_format: limitedProfile.print_format,
    qz_print: limitedProfile.qz_print,
    qz_host: limitedProfile.qz_host,
    printer: limitedProfile.printer,
    print_type: limitedProfile.print_type,
    tableAttention: limitedProfile.tableAttention,
    paid_limit: limitedProfile.paid_limit,
    disable_rounded_total: limitedProfile.disable_rounded_total,
    enable_discount: limitedProfile.enable_discount,
    multiple_cashier: limitedProfile.multiple_cashier,
    edit_order_type: limitedProfile.edit_order_type,
    custom_shift_hours: limitedProfile.custom_shift_hours ?? fullProfile.custom_shift_hours,
    custom_block_orders_after_shift_end:
      limitedProfile.custom_block_orders_after_shift_end ??
      fullProfile.custom_block_orders_after_shift_end,
    custom_restrict_merge_to_captain:
      limitedProfile.custom_restrict_merge_to_captain,
    custom_restrict_returns_to_captain:
      limitedProfile.custom_restrict_returns_to_captain,
    custom_enable_returns: limitedProfile.custom_enable_returns,
    custom_max_invoice_transfers: limitedProfile.custom_max_invoice_transfers,
    custom_ihotel_enabled: limitedProfile.custom_ihotel_enabled,
    custom_ihotel_charge_type: limitedProfile.custom_ihotel_charge_type,
    custom_shift_system_mode: limitedProfile.custom_shift_system_mode,
    custom_print_mode: limitedProfile.custom_print_mode,
    custom_bill_printer: limitedProfile.custom_bill_printer,
    custom_kitchen_kot_printer: limitedProfile.custom_kitchen_kot_printer,
    custom_bar_kot_printer: limitedProfile.custom_bar_kot_printer,
    custom_parcel_kot_printer: limitedProfile.custom_parcel_kot_printer,
    custom_drinks_kot_route: limitedProfile.custom_drinks_kot_route,
    custom_food_kot_route: limitedProfile.custom_food_kot_route,
    custom_takeaway_kot_route: limitedProfile.custom_takeaway_kot_route,
    custom_print_fallback_mode: limitedProfile.custom_print_fallback_mode,
  };

  return combinedProfile;
}

export async function getCurrencyInfo(currencyCode: string): Promise<Currency> {
  const doc = await db.getDoc(DOCTYPES.CURRENCY, currencyCode);
  return doc;
}