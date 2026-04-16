import { call } from './frappe-sdk';

/**
 * Reports endpoints (2026-04-16 — batch 1).
 *
 * Three admin-only cross-cashier reports + one everyone-sees
 * my-shift summary. All scoping / branch / role checks happen
 * server-side; these helpers just wrap the whitelisted calls.
 */

export interface ReportTotals {
  grand_total?: number;
  total_amount?: number;
  invoice_count?: number;
}

export interface SalesByCashierRow {
  user: string;
  full_name: string;
  invoice_count: number;
  sale_count: number;
  return_count: number;
  grand_total: number;
  net_total: number;
  return_amount: number;
  discount_amount: number;
  average_order_value: number;
}

export interface SalesByCashierResponse {
  from_date: string;
  to_date: string;
  branch: string;
  terminal: string | null;
  rows: SalesByCashierRow[];
  totals: ReportTotals;
}

export interface SalesByCategoryRow {
  department: string;
  total_amount: number;
  total_qty: number;
  invoice_count: number;
  percentage: number;
}

export interface SalesByCategoryResponse {
  from_date: string;
  to_date: string;
  branch: string;
  terminal: string | null;
  rows: SalesByCategoryRow[];
  totals: ReportTotals;
}

export interface TopBottomItem {
  item_code: string;
  item_name: string;
  total_qty: number;
  total_amount: number;
  order_count: number;
}

export interface TopBottomItemsResponse {
  from_date: string;
  to_date: string;
  branch: string;
  terminal: string | null;
  limit: number;
  top: TopBottomItem[];
  bottom: TopBottomItem[];
}

export interface ShiftSummaryPayment {
  mode_of_payment: string;
  opening_amount: number;
  expected_amount: number;
  closing_amount: number;
}

export interface ShiftSummaryResponse {
  has_open_shift: 0 | 1;
  user: string;
  full_name?: string;
  opening_entry?: string;
  period_start_date?: string;
  period_end_date?: string;
  pos_profile?: string;
  paid_count?: number;
  draft_count?: number;
  grand_total?: number;
  net_total?: number;
  total_qty?: number;
  total_tax?: number;
  draft_grand_total?: number;
  payments?: ShiftSummaryPayment[];
  terminal?: string | null;
}

export interface ReportDateRange {
  from_date?: string;
  to_date?: string;
  terminal?: string | null;
}

export async function getSalesByCashier(
  range: ReportDateRange = {}
): Promise<SalesByCashierResponse> {
  const params: Record<string, unknown> = {};
  if (range.from_date) params.from_date = range.from_date;
  if (range.to_date) params.to_date = range.to_date;
  if (range.terminal) params.terminal = range.terminal;
  const res = await call.get<{ message: SalesByCashierResponse }>(
    'ury.ury_pos.api.get_sales_by_cashier',
    params
  );
  return res.message;
}

export async function getSalesByCategory(
  range: ReportDateRange = {}
): Promise<SalesByCategoryResponse> {
  const params: Record<string, unknown> = {};
  if (range.from_date) params.from_date = range.from_date;
  if (range.to_date) params.to_date = range.to_date;
  if (range.terminal) params.terminal = range.terminal;
  const res = await call.get<{ message: SalesByCategoryResponse }>(
    'ury.ury_pos.api.get_sales_by_category',
    params
  );
  return res.message;
}

export async function getTopBottomItems(
  range: ReportDateRange & { limit?: number } = {}
): Promise<TopBottomItemsResponse> {
  const params: Record<string, unknown> = {};
  if (range.from_date) params.from_date = range.from_date;
  if (range.to_date) params.to_date = range.to_date;
  if (range.terminal) params.terminal = range.terminal;
  if (range.limit) params.limit = range.limit;
  const res = await call.get<{ message: TopBottomItemsResponse }>(
    'ury.ury_pos.api.get_top_bottom_items',
    params
  );
  return res.message;
}

export async function getMyShiftSummary(
  terminal?: string | null
): Promise<ShiftSummaryResponse> {
  const params: Record<string, unknown> = {};
  if (terminal) params.terminal = terminal;
  const res = await call.get<{ message: ShiftSummaryResponse }>(
    'ury.ury_pos.api.get_my_shift_summary',
    params
  );
  return res.message;
}

// ---------------------------------------------------------------
// Shift history (closed POS Closing Entry rows in a date window)
// ---------------------------------------------------------------

export interface ShiftHistoryPayment {
  mode_of_payment: string;
  opening_amount: number;
  expected_amount: number;
  closing_amount: number;
  difference: number;
}

export interface ShiftHistoryRow {
  name: string;
  user: string;
  full_name: string;
  pos_opening_entry: string;
  pos_profile: string;
  period_start_date: string;
  period_end_date: string;
  posting_date: string;
  grand_total: number;
  net_total: number;
  total_quantity: number;
  invoice_count: number;
  payments: ShiftHistoryPayment[];
}

export interface ShiftHistoryResponse {
  from_date: string;
  to_date: string;
  branch: string;
  terminal: string | null;
  scope: 'user' | 'branch';
  shifts: ShiftHistoryRow[];
  summary: {
    shift_count: number;
    grand_total: number;
    net_total: number;
    by_mode: ShiftHistoryPayment[];
  };
}

export async function getShiftHistory(
  range: ReportDateRange = {}
): Promise<ShiftHistoryResponse> {
  const params: Record<string, unknown> = {};
  if (range.from_date) params.from_date = range.from_date;
  if (range.to_date) params.to_date = range.to_date;
  if (range.terminal) params.terminal = range.terminal;
  const res = await call.get<{ message: ShiftHistoryResponse }>(
    'ury.ury_pos.api.get_shift_history',
    params
  );
  return res.message;
}

// ---------------------------------------------------------------
// Shift schedule (Mon→Sun roster from URY Shift / HRMS Shift Type)
// ---------------------------------------------------------------

export interface ShiftScheduleCell {
  shift_name: string;
  shift: string;
  start_time: string; // HH:MM
  end_time: string;
  assignment: string | null;
}

export interface ShiftScheduleRow {
  user: string;
  full_name: string;
  is_me: boolean;
  assignments: Record<string, ShiftScheduleCell>; // keyed by day name
}

export interface ShiftScheduleDay {
  day_name: string;
  date: string; // yyyy-MM-dd
}

export interface ShiftScheduleResponse {
  mode: 'URY Shift' | 'HRMS Shift Type' | 'Disabled';
  branch: string;
  pos_profile: string | null;
  week_start: string;
  week_end: string;
  days: ShiftScheduleDay[];
  rows: ShiftScheduleRow[];
  current_user: string;
}

export async function getShiftSchedule(
  weekStart?: string,
  terminal?: string | null
): Promise<ShiftScheduleResponse> {
  const params: Record<string, unknown> = {};
  if (weekStart) params.week_start = weekStart;
  if (terminal) params.terminal = terminal;
  const res = await call.get<{ message: ShiftScheduleResponse }>(
    'ury.ury_pos.api.get_shift_schedule',
    params
  );
  return res.message;
}

// ---------------------------------------------------------------
// Merge report + Transfer report (admin only)
// ---------------------------------------------------------------

export interface OrderMergeRow {
  name: string;
  master_invoice: string;
  status: 'Active' | 'Unmerged';
  merged_at: string;
  merged_by: string;
  merged_by_full_name: string;
  unmerged_at: string | null;
  unmerged_by: string | null;
  unmerged_by_full_name: string | null;
  notes: string | null;
  source_count: number;
  sources_total: number;
}

export interface TableMergeRow {
  name: string;
  master_table: string;
  status: 'Active' | 'Unmerged';
  merged_at: string;
  merged_by: string;
  merged_by_full_name: string;
  unmerged_at: string | null;
  unmerged_by: string | null;
  unmerged_by_full_name: string | null;
  merged_orders: number;
  notes: string | null;
  source_count: number;
}

export interface MergeReportResponse {
  from_date: string;
  to_date: string;
  branch: string;
  terminal: string | null;
  order_merges: OrderMergeRow[];
  table_merges: TableMergeRow[];
  summary: {
    order_merge_count: number;
    order_merge_active: number;
    table_merge_count: number;
    table_merge_active: number;
  };
}

export interface TransferRow {
  name: string;
  new_cashier: string;
  new_cashier_full_name: string;
  from_cashier: string | null;
  from_cashier_full_name: string | null;
  opening_entry: string | null;
  transfer_time: string;
  status: string;
  docstatus: number;
  grand_total: number;
  customer: string | null;
  customer_name: string | null;
  restaurant_table: string | null;
  posting_date: string;
  custom_terminal: string | null;
}

export interface TransferReportResponse {
  from_date: string;
  to_date: string;
  branch: string;
  terminal: string | null;
  rows: TransferRow[];
  summary: {
    count: number;
    total_amount: number;
    distinct_pairs: number;
  };
}

export async function getMergeReport(
  range: ReportDateRange = {}
): Promise<MergeReportResponse> {
  const params: Record<string, unknown> = {};
  if (range.from_date) params.from_date = range.from_date;
  if (range.to_date) params.to_date = range.to_date;
  if (range.terminal) params.terminal = range.terminal;
  const res = await call.get<{ message: MergeReportResponse }>(
    'ury.ury_pos.api.get_merge_report',
    params
  );
  return res.message;
}

export async function getTransferReport(
  range: ReportDateRange = {}
): Promise<TransferReportResponse> {
  const params: Record<string, unknown> = {};
  if (range.from_date) params.from_date = range.from_date;
  if (range.to_date) params.to_date = range.to_date;
  if (range.terminal) params.terminal = range.terminal;
  const res = await call.get<{ message: TransferReportResponse }>(
    'ury.ury_pos.api.get_transfer_report',
    params
  );
  return res.message;
}

// ---------------------------------------------------------------
// Dashboard response shape (extended 2026-04-16 batch 2)
// ---------------------------------------------------------------

export interface DashboardOrderTypeRow {
  order_type: string;
  count: number;
  amount: number;
}

export interface DashboardPaymentModeRow {
  mode_of_payment: string;
  amount: number;
}

export interface DashboardActiveCashierRow {
  user: string;
  full_name: string;
  invoice_count: number;
  grand_total: number;
}

export interface DashboardStatsExtended {
  is_admin: 0 | 1;
  scope: 'user' | 'branch';
  date: string;
  total_sales: number;
  total_orders: number;
  total_customers: number;
  average_order_value: number;
  returns_count: number;
  returns_amount: number;
  top_selling_items: Array<{
    item_name: string;
    quantity: number;
    total_amount: number;
  }>;
  // Admin-only (omitted when is_admin === 0).
  order_type_breakdown?: DashboardOrderTypeRow[];
  payment_mode_breakdown?: DashboardPaymentModeRow[];
  active_cashiers?: DashboardActiveCashierRow[];
}
