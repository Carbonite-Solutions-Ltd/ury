import { call } from './frappe-sdk';

/**
 * Kitchen → waiter change requests (2026-07-16).
 *
 * When the kitchen can't cook an order as rung (out of stock, can't honour
 * a special instruction) they raise a TEXT request from the KDS. The KOT
 * goes ON HOLD ("Awaiting Confirmation", Serve disabled) and the waiter is
 * alerted here. She checks with the customer, edits the order normally if
 * they agree, then Confirms — or Rejects, which means "cook it as
 * originally ordered". The kitchen never changes quantities or prices, so
 * this flow never touches the invoice.
 */

export interface KitchenChangeRequest {
  kot: string;
  change_request: string;
  change_item: string | null;
  change_requested_by: string | null;
  change_requested_at: string | null;
  invoice: string;
  customer_name: string | null;
  restaurant_table: string | null;
  grand_total: number;
}

/** Pending change requests for the current user. Never throws (badge use). */
export async function getKitchenChangeRequests(): Promise<KitchenChangeRequest[]> {
  try {
    const res = await call.get<{ message: KitchenChangeRequest[] }>(
      'ury.ury.api.ury_kot_display.get_kitchen_change_requests'
    );
    return res.message || [];
  } catch {
    return [];
  }
}

/**
 * Answer a kitchen request.
 *  - `confirm` — customer agreed to what the kitchen proposed.
 *  - `update`  — revise the item's SPECIAL REQUEST (`itemNote`) and/or send
 *    a note back. Only the instruction changes — never quantities, items or
 *    price; re-ringing the order stays the cashier's job.
 *  - `cancel`  — customer no longer wants it. Cancels the KITCHEN order; the
 *    card leaves the board once the kitchen accepts.
 * Whatever the answer, the kitchen must Accept it before the card clears.
 */
export async function respondKotChange(
  kot: string,
  action: 'confirm' | 'update' | 'cancel',
  opts?: { note?: string; itemNote?: string }
): Promise<{ kot: string; status: string }> {
  const res = await call.post<{ message: { kot: string; status: string } }>(
    'ury.ury.api.ury_kot_display.respond_kot_change',
    {
      kot,
      action,
      note: opts?.note || null,
      item_note: opts?.itemNote || null,
    }
  );
  return res.message;
}
