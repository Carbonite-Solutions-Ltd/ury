import { call } from './frappe-sdk';

/**
 * Item-split API client.
 *
 * Splitting an order by item creates N separate submitted POS Invoices,
 * one per bill, each with its own items + customer + payments. The
 * backend (`ury.ury.doctype.ury_order.ury_order.split_invoice_by_item`)
 * cancels the source draft and builds fresh bills, then we print each
 * settled bill's itemized receipt. See CLAUDE.md "Fixes log" 2026-06-05.
 */

export interface SplitSourceItem {
  row_name: string;
  item_code: string;
  item_name: string;
  qty: number;
  rate: number;
  uom?: string | null;
}

export interface SplitSource {
  invoice: string;
  table: string | null;
  customer: string;
  customer_name: string;
  grand_total: number;
  items: SplitSourceItem[];
}

export interface SplitBillAllocation {
  source_row: string;
  qty: number;
}

export interface SplitBillPayment {
  mode_of_payment: string;
  amount: number;
}

export interface SplitBill {
  customer: string;
  allocations: SplitBillAllocation[];
  /**
   * Single payment method for the whole bill. The backend auto-fills the
   * amount with the computed grand total (incl. tax), so the UI doesn't
   * have to compute per-bill tax. Use `payments` instead for an explicit
   * multi-mode split (not used by the item-split UI).
   */
  payment_mode?: string;
  payments?: SplitBillPayment[];
  additional_discount_percentage?: number;
}

export interface SplitResult {
  source_invoice: string;
  bills: string[];
  table_freed: boolean;
}

/** Fetch the draft order's items (with row names) for the allocator. */
export async function getOrderItemsForSplit(
  invoice: string
): Promise<SplitSource> {
  const res = await call.get<{ message: SplitSource }>(
    'ury.ury.doctype.ury_order.ury_order.get_order_items_for_split',
    { invoice }
  );
  return res.message;
}

/**
 * Split a draft order's items into N separate submitted invoices,
 * settling each with its own customer + payments. Returns the new
 * invoice names so the caller can print each itemized receipt in turn.
 */
export async function splitInvoiceByItem(
  sourceInvoice: string,
  bills: SplitBill[],
  table?: string | null
): Promise<SplitResult> {
  const res = await call.post<{ message: SplitResult }>(
    'ury.ury.doctype.ury_order.ury_order.split_invoice_by_item',
    {
      source_invoice: sourceInvoice,
      bills: JSON.stringify(bills),
      table: table || null,
    }
  );
  return res.message;
}
