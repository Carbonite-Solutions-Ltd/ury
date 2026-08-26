import { call } from './frappe-sdk';

/**
 * Held bills (2026-08-24).
 *
 * A cashier parks a bill with a reason — the guest stepped out, there is a
 * dispute, a manager is being fetched — and finds it again from the Waiters
 * page rather than leaving it in the Draft list where it looks like an order
 * still being built.
 *
 * Two behaviours worth knowing at the call site:
 *   • Holding FREES the table so the floor can reseat it. Resuming does NOT
 *     take the table back, because someone may be sitting there by now — the
 *     response carries a `note` saying so, which the UI should surface.
 *   • A held bill still blocks the shift close, like any other unpaid draft.
 */

export interface HeldOrder {
  name: string;
  customer: string;
  customer_name: string | null;
  grand_total: number;
  order_type: string | null;
  reason: string | null;
  held_by: string | null;
  held_by_name: string | null;
  held_at: string;
  waiter: string | null;
  waiter_name: string | null;
}

export interface HeldOrdersResponse {
  branch: string;
  orders: HeldOrder[];
  count: number;
}

export async function holdOrder(
  invoice: string,
  reason: string
): Promise<{ invoice: string; held: number; table_freed: string | null }> {
  const res = await call.post<{
    message: { invoice: string; held: number; table_freed: string | null };
  }>('ury.ury_pos.api.hold_order', { invoice, reason });
  return res.message;
}

export async function resumeOrder(
  invoice: string
): Promise<{ invoice: string; held: number; note: string }> {
  const res = await call.post<{
    message: { invoice: string; held: number; note: string };
  }>('ury.ury_pos.api.resume_order', { invoice });
  return res.message;
}

export async function getHeldOrders(): Promise<HeldOrdersResponse> {
  const res = await call.get<{ message: HeldOrdersResponse }>(
    'ury.ury_pos.api.get_held_orders'
  );
  return res.message;
}

/** Never throws — a failed badge lookup must not break the page. */
export async function getHeldOrderCount(): Promise<number> {
  try {
    const res = await call.get<{ message: { count: number } }>(
      'ury.ury_pos.api.get_held_order_count'
    );
    return res.message?.count ?? 0;
  } catch {
    return 0;
  }
}
