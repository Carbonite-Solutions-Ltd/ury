import { call } from './frappe-sdk';
import { OrderType } from '../data/order-types';

export interface POSInvoice {
  name: string;
  invoice_printed: number;
  grand_total: number;
  restaurant_table: string | null;
  cashier: string;
  waiter: string;
  net_total: number;
  posting_time: string;
  total_taxes_and_charges: number;
  customer: string;
  customer_name?: string;
  status: 'Draft' | 'Unbilled' | 'Recently Paid' | 'Paid' | 'Consolidated' | 'Return';
  mobile_number: string;
  posting_date: string;
  rounded_total: number;
  order_type: OrderType;
  custom_order_status?: string;
  custom_terminal?: string | null;
  /** User who created the invoice. The "real" cashier under the new model. */
  owner?: string;
  /** Friendly name from JOIN to tabUser. */
  owner_full_name?: string;
  /**
   * Set when this invoice has been merged into another (the master).
   * The Orders page filters out invoices with this set so the dormant
   * sources don't clutter the list. Cleared on unmerge.
   */
  custom_merged_into?: string | null;
  /**
   * Set on master invoices that have an Active URY Order Merge Log.
   * Powers the "Merged" badge on cards/list rows so the user can spot
   * merged orders at a glance. Populated by getPosInvoice's correlated
   * subquery (no extra round-trip).
   */
  merge_log_name?: string | null;
  /** Number of source invoices in the active merge log. */
  merge_source_count?: number;
  /** ERPNext native — 1 when this invoice itself is a return doc. */
  is_return?: number;
  /** Original invoice this return was issued against. */
  return_against?: string | null;
  /**
   * Count of submitted return invoices written against this invoice.
   * Powers the "Returned" badge on paid cards / list rows / right panel.
   * A cancelled return (docstatus=2) is excluded, so reversing a return
   * removes the badge.
   */
  active_return_count?: number;
}

export interface CashierUser {
  user: string;
  full_name: string;
}

/**
 * Compact summary of an active URY Order Merge Log returned by
 * `get_active_merge_log_for_invoice`. The right panel uses this to
 * decide whether to render the Unmerge button.
 */
export interface ActiveMergeLog {
  name: string;
  merged_at: string | null;
  merged_by: string;
  merged_by_full_name: string;
  source_count: number;
  source_invoices: string[];
}

export interface MergeResult {
  merge_log: string;
  master_invoice: string;
  merged_count: number;
}

export interface UnmergeResult {
  merge_log: string;
  master_invoice: string;
  unmerged_count: number;
}

export interface ReturnPreviewItem {
  row_name: string;
  item_code: string;
  item_name: string;
  /** Original qty on the invoice. */
  qty: number;
  /** Qty already returned via earlier submitted return invoices. */
  qty_already_returned: number;
  /** How much of this row is still returnable (original - already). */
  qty_remaining: number;
  rate: number;
  amount: number;
  uom: string;
  warehouse: string;
}

export interface ReturnPreviewPayment {
  mode_of_payment: string;
  amount: number;
}

export interface ReturnPreview {
  invoice: string;
  customer: string;
  customer_name: string;
  grand_total: number;
  currency: string;
  items: ReturnPreviewItem[];
  payments: ReturnPreviewPayment[];
  /** 1 when every row's qty_remaining is 0 — nothing more can be returned. */
  fully_returned: number;
}

export interface ReturnResult {
  return_invoice: string;
  original_invoice: string;
  refund_amount: number;
}

export interface ReverseReturnResult {
  return_invoice: string;
  original_invoice: string;
}

export interface POSInvoiceItem {
  item_name: string;
  qty: number;
  amount: number;
}

export interface POSInvoiceTax {
  description: string;
  rate: number;
}

interface GetPOSInvoicesResponse {
  message: {
    data: POSInvoice[];
    next: boolean;
  };
}

interface GetPOSInvoicesParams {
  status: POSInvoice['status'];
  limit?: number;
  limit_start?: number;
  paid_limit?: number;
  /** Optional URY POS Terminal name to scope orders to a single till. */
  terminal?: string | null;
  /** Optional posting_date filter (YYYY-MM-DD). */
  posting_date?: string | null;
  /** Cashier scope: "mine" (default), "all", or a specific user id. */
  cashier?: string | null;
}

interface GetPOSInvoiceItemsResponse {
  message: [POSInvoiceItem[], POSInvoiceTax[]];
}

export async function getPOSInvoices({
  status,
  limit,
  limit_start,
  paid_limit,
  terminal,
  posting_date,
  cashier,
}: GetPOSInvoicesParams) {
  try {
    // Use paid_limit as the limit for Recently Paid status
    const actualLimit = status === 'Recently Paid' && paid_limit ? paid_limit : limit;

    const params: Record<string, unknown> = {
      status,
      limit: actualLimit,
      limit_start,
    };
    if (terminal) params.terminal = terminal;
    if (posting_date) params.posting_date = posting_date;
    if (cashier) params.cashier = cashier;

    const response = await call.get<GetPOSInvoicesResponse>(
      'ury.ury_pos.api.getPosInvoice',
      params
    );

    return {
      invoices: response.message.data,
      hasMore: response.message.next,
    };
  } catch (error) {
    console.error('Error fetching POS invoices:', error);
    throw new Error('Failed to fetch POS invoices');
  }
}

/**
 * Merge a list of POS Invoices into a single master. The first
 * invoice in the list becomes the master; the rest are flagged via
 * `custom_merged_into` and their items appended. Backend creates a
 * `URY Order Merge Log` with snapshots so the operation can be
 * reversed via `unmergeOrders`.
 */
export async function mergeOrders(
  invoiceNames: string[],
  notes?: string
): Promise<MergeResult> {
  const res = await call.post<{ message: MergeResult }>(
    'ury.ury_pos.api.merge_pos_invoices',
    {
      invoices: invoiceNames,
      notes: notes || null,
    }
  );
  return res.message;
}

/**
 * Reverse a previous merge by its log name. Restores the master's
 * pre-merge items and clears `custom_merged_into` on each source.
 * Only allowed while the master is still unpaid (Draft, docstatus 0).
 */
export async function unmergeOrders(mergeLogName: string): Promise<UnmergeResult> {
  const res = await call.post<{ message: UnmergeResult }>(
    'ury.ury_pos.api.unmerge_pos_invoices',
    { merge_log: mergeLogName }
  );
  return res.message;
}

/**
 * Look up the most recent Active URY Order Merge Log where this
 * invoice is the master. Returns null when there isn't one. Used by
 * the right panel of the Orders page to decide whether to render
 * the Unmerge button.
 */
export async function getActiveMergeLogForInvoice(
  invoiceName: string | null
): Promise<ActiveMergeLog | null> {
  if (!invoiceName) return null;
  try {
    const res = await call.get<{ message: ActiveMergeLog | null }>(
      'ury.ury_pos.api.get_active_merge_log_for_invoice',
      { invoice: invoiceName }
    );
    return res.message || null;
  } catch (error) {
    console.error('Error fetching active merge log:', error);
    return null;
  }
}

/**
 * Fetch the item list + payment breakdown for a paid POS Invoice so
 * the ReturnDialog can render a qty-picker per row. Backend enforces
 * the `custom_restrict_returns_to_captain` gate; a cashier without
 * permission will get a thrown ValidationError here.
 */
export async function getReturnPreview(
  invoiceName: string
): Promise<ReturnPreview> {
  const res = await call.get<{ message: ReturnPreview }>(
    'ury.ury_pos.api.get_return_preview',
    { invoice: invoiceName }
  );
  return res.message;
}

/**
 * Create and submit a return POS Invoice against `invoiceName`. `items`
 * is the per-row pick: each entry is `{row_name, qty}` where qty is the
 * POSITIVE quantity to refund (the backend flips the sign). `refund_mode`
 * is the single Mode of Payment the customer is being refunded in.
 */
export async function createPosReturn(
  invoiceName: string,
  items: Array<{ row_name: string; qty: number }>,
  refundMode: string,
  notes?: string
): Promise<ReturnResult> {
  const res = await call.post<{ message: ReturnResult }>(
    'ury.ury_pos.api.create_pos_return',
    {
      invoice: invoiceName,
      items,
      refund_mode: refundMode,
      notes: notes || null,
    }
  );
  return res.message;
}

/**
 * Reverse a submitted return POS Invoice. Calls ERPNext's native
 * cancel() so all GL / stock entries get reversed automatically.
 * The original invoice is untouched.
 */
export async function reversePosReturn(
  returnInvoiceName: string
): Promise<ReverseReturnResult> {
  const res = await call.post<{ message: ReverseReturnResult }>(
    'ury.ury_pos.api.reverse_pos_return',
    { return_invoice: returnInvoiceName }
  );
  return res.message;
}

/**
 * List the cashier users (URY Cashier or URY Captain role) attached to
 * the terminal's branch via the URY User child table. Used by the
 * captain's "Cashier" filter dropdown on the Orders page.
 */
export async function getCashierUsersForTerminal(
  terminal: string | null
): Promise<CashierUser[]> {
  if (!terminal) return [];
  try {
    const response = await call.get<{ message: CashierUser[] }>(
      'ury.ury_pos.api.get_cashier_users_for_terminal',
      { terminal }
    );
    return response.message || [];
  } catch (error) {
    console.error('Error fetching cashier users:', error);
    return [];
  }
}

export async function getPOSInvoiceItems(invoiceId: string) {
  try {
    const response = await call.get<GetPOSInvoiceItemsResponse>(
      'ury.ury_pos.api.getPosInvoiceItems',
      {
        invoice: invoiceId
      }
    );

    return {
      items: response.message[0],
      taxes: response.message[1]
    };
  } catch (error) {
    console.error('Error fetching POS invoice items:', error);
    throw new Error('Failed to fetch POS invoice items');
  }
}

export async function updateInvoiceStatus(
  invoice: string,
  status: POSInvoice['status']
) {
  try {
    await call.post('ury.ury_pos.api.updatePosInvoiceStatus', {
      invoice,
      status,
    });
  } catch (error) {
    console.error('Error updating invoice status:', error);
    throw new Error('Failed to update invoice status');
  }
} 

export async function searchPosInvoice(
  query: string,
  status: string,
  options?: {
    terminal?: string | null;
    posting_date?: string | null;
    cashier?: string | null;
  }
) {
  try {
    const params: Record<string, unknown> = { query, status };
    if (options?.terminal) params.terminal = options.terminal;
    if (options?.posting_date) params.posting_date = options.posting_date;
    if (options?.cashier) params.cashier = options.cashier;
    const response = await call.get('ury.ury_pos.api.searchPosInvoice', params);
    return response.message;
  } catch (error) {
    console.error('Error searching POS invoices:', error);
    throw error;
  }
}

export async function getInvoicePrintHtml(invoiceId: string, printFormat: string) {
  try {
    const response = await call.get<{ message: { html: string } }>(
      'frappe.www.printview.get_html_and_style',
      {
        doc: 'POS Invoice',
        name: invoiceId,
        print_format: printFormat,
        _lang: 'en',
        no_letterhead: 1,
        letterhead:"No Letterhead",
        settings:{}
      }
    );
    return response.message.html;
  } catch (error) {
    console.error('Error fetching invoice print HTML:', error);
    throw new Error('Failed to fetch invoice print HTML');
  }
} 

export async function networkPrint(orderId: string, printer: string, printFormat: string) {
  await call.post('ury.ury.api.ury_print.network_printing', {
    doctype: 'POS Invoice',
    name: orderId,
    printer_setting: printer,
    print_format: printFormat,
  });
}

export async function selectNetworkPrinter(orderId: string, posProfile: string, printFormat?: string | null) {
  await call.post('ury.ury.api.ury_print.select_network_printer', {
    invoice_id: orderId,
    pos_profile: posProfile,
    print_format: printFormat,
  });
}


export async function updatePrintStatus(orderId: string) {
  await call.post('ury.ury.api.ury_print.qz_print_update', { invoice: orderId });
} 