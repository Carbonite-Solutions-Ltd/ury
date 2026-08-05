import { call } from './frappe-sdk';
import { OrderType, OrderStatusType } from '../data/order-types';

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
  // The invoice's OWN status as returned by the backend. Distinct from
  // OrderStatusType, which is the sidebar FILTER and additionally carries
  // pseudo-statuses ('Pending KOTs', 'Room Charges', 'Incoming Transfers')
  // that no invoice ever literally has. 'Cancelled' was missing here even
  // though the backend sets it on docstatus=2, so Orders.tsx's check for
  // it was flagged as a comparison that could never match.
  status: 'Draft' | 'Unbilled' | 'Recently Paid' | 'Paid' | 'Consolidated' | 'Return' | 'Cancelled';
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
  /**
   * iHotel: 1 when this invoice has been charged to a hotel room via
   * `charge_invoice_to_room`. docstatus stays 0 forever — GL entries
   * come from iHotel's own checkout flow when the guest settles.
   */
  custom_charge_to_room?: number;
  /** 1 while a captain's cancellation is with the kitchen. The order is
   *  locked: it cannot be paid or edited until they accept. */
  custom_cancel_pending?: number;
  /** iHotel Room the draft is tagged against (persists from Customer picker). */
  custom_hotel_room?: string | null;
  /** Take-away / delivery contact (optional, editable after the fact). */
  custom_order_contact_name?: string | null;
  custom_order_contact_mobile?: string | null;
  /** iHotel Profile the charge is written to. */
  custom_ihotel_profile?: string | null;
  /** Times this bill has been printed (drives the cashier reprint cap). */
  custom_print_count?: number;
  /** Assigned URY Waiter (when the profile uses waiters). */
  custom_waiter?: string | null;
  /** Reason captured when the order was cancelled (Cancelled filter). */
  cancel_reason?: string | null;
}

export interface CashierUser {
  /** Cashier: the user id (filtered by owner). Waiter: "waiter:<record>". */
  user: string;
  full_name: string;
  /** "cashier" or "waiter" — drives the dropdown grouping. */
  kind?: 'cashier' | 'waiter';
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
  /** Sidebar filter, not an invoice status - see the note on POSInvoice.status. */
  status: OrderStatusType;
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

/**
 * Return the number of draft POS Invoices that still have at least
 * one URY KOT with kot_printed=0. Drives the live badge next to the
 * "Pending KOTs" entry in the Orders page sidebar. Scope follows the
 * same rules as getPOSInvoices (branch + optional terminal + optional
 * posting_date + cashier scope), so the badge counts the pending KOTs of
 * the cashier who rang the orders — matching the Pending KOTs list.
 */
export async function getPendingKotCount(
  terminal?: string | null,
  posting_date?: string | null,
  cashier?: string | null
): Promise<number> {
  try {
    const params: Record<string, unknown> = {};
    if (terminal) params.terminal = terminal;
    if (posting_date) params.posting_date = posting_date;
    if (cashier) params.cashier = cashier;
    const response = await call.get<{ message: { count: number } }>(
      'ury.ury_pos.api.get_pending_kot_count',
      params
    );
    return response?.message?.count ?? 0;
  } catch (error) {
    console.error('Error fetching pending KOT count:', error);
    return 0;
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

export interface InvoicePrintParts {
  html: string;
  style: string;
}

/**
 * The raw two halves of a rendered print format.
 *
 * `frappe.www.printview.get_html_and_style` returns BOTH `html` and
 * `style`, and the style is where essentially all of the receipt's
 * appearance lives — on a real POS format it is roughly three times the
 * size of the markup (12,998 vs 4,770 chars measured on
 * "POS Landing Receipt Print Format").
 *
 * This used to return `message.html` alone and silently drop the style,
 * which is why a bill printed from the POS came out as unstyled plain
 * text while the same invoice printed from the desk looked correct: the
 * FORMAT was resolving fine all along, its CSS just never left the
 * server. See CLAUDE.md "Fixes log" 2026-08-05.
 */
export async function getInvoicePrintParts(
  invoiceId: string,
  printFormat: string
): Promise<InvoicePrintParts> {
  try {
    const response = await call.get<{ message: InvoicePrintParts }>(
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
    return {
      // Inline the images here so EVERY consumer - the QZ print path,
      // the split-receipt loop and the admin preview - gets a
      // self-contained document. Doing it at the single fetch point
      // means a new caller cannot forget to, which is how the
      // stylesheet went missing for so long.
      html: await inlinePrintImages(response.message?.html ?? ''),
      style: response.message?.style ?? '',
    };
  } catch (error) {
    console.error('Error fetching invoice print HTML:', error);
    throw new Error('Failed to fetch invoice print HTML');
  }
}

/**
 * Assemble a self-contained document QZ (or an iframe) can render.
 *
 * `prefixHtml` is injected INSIDE <body>, above the receipt — the split
 * banner needs to be part of the document, not concatenated in front of
 * its doctype.
 */
export function composePrintDocument(
  parts: InvoicePrintParts,
  prefixHtml = ''
): string {
  return [
    '<!DOCTYPE html>',
    '<html><head><meta charset="utf-8">',
    // Print formats reference site files with RELATIVE urls, e.g. the
    // logo is <img src="/files/logo.bmp">. In the browser that resolves
    // against the Frappe origin; in a standalone document handed to QZ
    // there is no base at all, so it resolves to nothing and the image
    // never loads. Worse, the format carries
    // onerror="this.parentNode.style.display='none'", so the logo does
    // not even fail visibly - it silently disappears from the receipt.
    // See CLAUDE.md "Fixes log" 2026-08-05.
    `<base href="${window.location.origin}/">`,
    `<style>${parts.style}</style>`,
    '</head><body>',
    prefixHtml,
    parts.html,
    '</body></html>',
  ].join('');
}

/**
 * Rewrite same-origin <img src> to self-contained data: URIs.
 *
 * A <base href> alone is not enough for printing. It fixes ADDRESSING,
 * but the renderer still has to fetch the file over HTTP and finish
 * doing so before the page is sent to the printer - and a print that
 * races an image fetch drops the logo intermittently, which is worse
 * than dropping it every time because it looks like a printer fault.
 * Inlining removes the fetch entirely, so the document QZ receives is
 * complete the moment it arrives.
 *
 * Best-effort by design: an image that cannot be fetched is left with
 * its original src, so behaviour is never worse than before the fix.
 */
export async function inlinePrintImages(html: string): Promise<string> {
  const srcs = Array.from(
    html.matchAll(/<img[^>]+src\s*=\s*["']([^"']+)["']/gi),
    (m) => m[1]
  ).filter((src) => src && !src.startsWith('data:'));

  const unique = Array.from(new Set(srcs));
  if (!unique.length) return html;

  const toDataUri = async (src: string): Promise<[string, string] | null> => {
    try {
      // credentials: same-origin so /files/* behind Frappe's session
      // check is actually readable.
      const res = await fetch(src, { credentials: 'same-origin' });
      if (!res.ok) return null;
      const blob = await res.blob();
      const uri = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(String(reader.result));
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
      return [src, uri];
    } catch {
      return null;
    }
  };

  const resolved = (await Promise.all(unique.map(toDataUri))).filter(
    (r): r is [string, string] => r !== null
  );

  let out = html;
  for (const [src, uri] of resolved) {
    // Split/join rather than a RegExp: a file path can contain regex
    // metacharacters and we want a literal replacement.
    out = out.split(`"${src}"`).join(`"${uri}"`).split(`'${src}'`).join(`'${uri}'`);
  }
  return out;
}

/** Convenience: fetch and compose in one step. */
export async function getInvoicePrintHtml(invoiceId: string, printFormat: string) {
  return composePrintDocument(await getInvoicePrintParts(invoiceId, printFormat));
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
export interface OrderContactUpdateResult {
  invoice: string;
  contact_name: string | null;
  contact_mobile: string | null;
}

/**
 * Set or clear the take-away / delivery contact on an existing order.
 *
 * Sending a blank string CLEARS the field, so a mistyped number can be
 * removed rather than only overwritten. Works on paid orders too — for a
 * delivery that's usually when the number is finally known.
 */
export async function updateOrderContact(args: {
  invoice: string;
  contact_name?: string;
  contact_mobile?: string;
}): Promise<OrderContactUpdateResult> {
  const res = await call.post<{ message: OrderContactUpdateResult }>(
    'ury.ury.doctype.ury_order.ury_order.update_order_contact',
    args
  );
  return res.message;
}
