import { call } from './frappe-sdk';

/**
 * Waiter API client (2026-06-10).
 *
 * When the POS Profile has `custom_use_waiter` on, the cashier picks a
 * waiter (URY Waiter) when creating a new order; the waiter is stamped on
 * the invoice. The Waiters page lists waiters and their pending orders.
 * Backend lives in `ury.ury_pos.api`.
 */

export interface Waiter {
  name: string;
  full_name: string;
  mobile_number: string | null;
}

export interface WaiterPendingOrderItem {
  item_name: string;
  qty: number;
  rate: number;
  amount: number;
}

export interface WaiterPendingOrder {
  name: string;
  customer: string | null;
  customer_name: string | null;
  grand_total: number;
  restaurant_table: string | null;
  order_type: string | null;
  invoice_printed: number;
  creation: string;
  items: WaiterPendingOrderItem[];
}

export interface WaiterWithOrders {
  name: string;
  full_name: string;
  mobile_number: string | null;
  orders: WaiterPendingOrder[];
}

/** Active waiters for the order-time picker. Optional name/mobile filter. */
export async function getWaiters(query?: string): Promise<Waiter[]> {
  const res = await call.get<{ message: Waiter[] }>(
    'ury.ury_pos.api.get_waiters',
    query ? { query } : {}
  );
  return res.message || [];
}

/** Quick-add a waiter from the POS. */
export async function createWaiter(
  full_name: string,
  mobile_number?: string
): Promise<Waiter> {
  const res = await call.post<{ message: Waiter }>(
    'ury.ury_pos.api.create_waiter',
    { full_name, mobile_number: mobile_number || null }
  );
  return res.message;
}

/**
 * Every active waiter + their pending (draft) orders for the Waiters page.
 * Pass `includeEmpty` to also return waiters with no pending orders (so they
 * can be drag-and-drop targets).
 */
export async function getWaitersWithPendingOrders(
  includeEmpty = false
): Promise<WaiterWithOrders[]> {
  const res = await call.get<{ message: WaiterWithOrders[] }>(
    'ury.ury_pos.api.get_waiters_with_pending_orders',
    includeEmpty ? { include_empty: 1 } : {}
  );
  return res.message || [];
}

/** Move a draft order to a different waiter (drag-and-drop reassign). */
export async function reassignOrderWaiter(
  invoice: string,
  waiter: string
): Promise<{ invoice: string; waiter: string; changed: number }> {
  const res = await call.post<{
    message: { invoice: string; waiter: string; changed: number };
  }>('ury.ury_pos.api.reassign_order_waiter', { invoice, waiter });
  return res.message;
}

/** Total pending waiter orders on the branch (navbar badge). Never throws. */
export async function getWaiterPendingOrderCount(): Promise<number> {
  try {
    const res = await call.get<{ message: { count: number } }>(
      'ury.ury_pos.api.get_waiter_pending_order_count'
    );
    return res.message?.count || 0;
  } catch {
    return 0;
  }
}
