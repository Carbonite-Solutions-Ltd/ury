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
