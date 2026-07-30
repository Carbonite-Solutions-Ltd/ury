import { call } from './frappe-sdk';

export interface POSInvoiceItem {
  name: string;
  item_code: string;
  item_name: string;
  description: string;
  item_group: string;
  image: string;
  qty: number;
  comment: string;
  rate: number;
  amount: number;
  discount_percentage: number;
  discount_amount: number;
}

export interface POSInvoice {
  name: string;
  title: string;
  customer: string;
  customer_name: string;
  mobile_number: string;
  customer_group: string;
  territory: string;
  posting_date: string;
  posting_time: string;
  order_type: string;
  restaurant_table: string;
  custom_restaurant_room: string;
  status: string;
  total: number;
  grand_total: number;
  items: POSInvoiceItem[];
  /** iHotel: room intent persisted on the draft. Non-zero after charge_invoice_to_room. */
  custom_hotel_room?: string | null;
  custom_charge_to_room?: number;
  custom_ihotel_profile?: string | null;
}

export interface TableOrder {
  message: POSInvoice | null;
}

/**
 * Fetches the current active order/invoice for a table if any exists
 * @param table_no The table number to fetch the order for
 * @returns The order details and customer information if an active order exists
 */
export async function getTableOrder(table_no: string): Promise<TableOrder> {
  const { call } = await import('./frappe-sdk');
  try {
    const res = await call.get('ury.ury.doctype.ury_order.ury_order.get_order_invoice', { 
      table: table_no
    });
    return res as TableOrder;
  } catch (error) {
    console.error('Error fetching table order:', error);
    return { message: null };
  }
} 

export interface SyncOrderRequest {
  table?: string;
  customer?: string;
  items: Array<{
    item: string;
    item_name: string;
    rate: number;
    qty: number;
  }>;
  no_of_pax: number;
  mode_of_payment?: string;
  cashier?: string;
  owner?: string;
  waiter?: string;
  /** Selected URY Waiter (when the profile uses waiters). */
  selected_waiter?: string;
  pos_profile: string;
  invoice: string | null;
  aggregator_id?: string | null;
  order_type: string;
  last_invoice: string | null;
  comments?: string | null;
  room?: string;
  /** Terminal (URY POS Terminal name) that's ringing this invoice. Stamped on the invoice for reporting + reconciliation. */
  terminal?: string | null;
  /** iHotel: when set, the draft is tagged with the selected hotel room so the intent survives reloads. The actual folio write happens at charge_invoice_to_room time. */
  hotel_room?: string | null;
  /**
   * Offline queue idempotency key (Phase B). A client-generated UUID sent
   * on EVERY submit (online + queued). If a queued order is replayed on
   * reconnect, the backend returns the already-created invoice instead of
   * duplicating it. See ury_order.sync_order.
   */
  idempotency_key?: string;
  /**
   * Optional take-away / delivery contact, captured by a prompt on the
   * first submit. Omitted (or blank) leaves any existing value alone —
   * the backend only stamps a non-empty value, so a later update can't
   * wipe a contact the cashier added from the Orders page.
   */
  contact_name?: string;
  contact_mobile?: string;
}

export const syncOrder = async (data: SyncOrderRequest) => {
  return call.post( 'ury.ury.doctype.ury_order.ury_order.sync_order',data);
}; 