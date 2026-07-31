import { StateCreator } from 'zustand';
import { OrderType, OrderStatusType } from '../../data/order-types';
import { call } from '../../lib/frappe-sdk';
import { getIncomingTransfers } from '../../lib/transfer-api';
import {
  getPOSInvoices,
  getPOSInvoiceItems,
  getCashierUsersForTerminal,
  getActiveMergeLogForInvoice,
  mergeOrders,
  unmergeOrders,
  POSInvoiceItem,
  POSInvoiceTax,
  CashierUser,
  ActiveMergeLog,
} from '../../lib/invoice-api';
import { searchPosInvoice } from '../../lib/invoice-api';
import { getSavedTerminal } from '../../lib/terminal-api';
import { storage } from '../../lib/storage';

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
  /** Set when this invoice has been merged into another. Hidden from list. */
  custom_merged_into?: string | null;
  /** Active merge log name when this invoice is the master of a merge. */
  merge_log_name?: string | null;
  /** Number of source invoices in the active merge log. */
  merge_source_count?: number;
  /** ERPNext native — 1 when this invoice itself is a return doc. */
  is_return?: number;
  /** Original invoice this return was issued against. */
  return_against?: string | null;
  /** Count of active (docstatus=1) returns written against this invoice. */
  active_return_count?: number;
  /** iHotel: 1 when this draft has been charged to a hotel room. */
  custom_charge_to_room?: number;
  /** 1 while a captain's cancellation is with the kitchen. The order is
   *  locked: it cannot be paid or edited until they accept. */
  custom_cancel_pending?: number;
  custom_hotel_room?: string | null;
  /** Take-away / delivery contact (optional, editable after the fact). */
  custom_order_contact_name?: string | null;
  custom_order_contact_mobile?: string | null;
  custom_ihotel_profile?: string | null;
  /** Times this bill has been printed (drives the cashier reprint cap). */
  custom_print_count?: number;
  /** Assigned URY Waiter (when the profile uses waiters). */
  custom_waiter?: string | null;
  /** Reason captured when the order was cancelled (Cancelled filter). */
  cancel_reason?: string | null;
  /** Transfer workflow: denormalized state ('Pending Incoming' etc). */
  custom_transfer_status?: string | null;
  /** Present on rows from the Incoming Transfers filter. */
  transfer_meta?: {
    transfer: string;
    from_user: string;
    from_full_name: string;
    requested_at: string;
    hop_number: number;
  };
}

export type OrdersViewMode = 'card' | 'list';

/**
 * `cashierFilter` semantics:
 *  - "mine" → my own orders (default for everyone, the only option for cashiers)
 *  - "all"  → orders from any URY Cashier / URY Captain on this terminal's branch
 *  - any other string → a specific user id
 *
 * Backend re-validates and silently downgrades non-captain users.
 */
export type OrdersCashierFilter = string;

const todayIso = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const VIEW_MODE_KEY_PREFIX = 'ury_pos_orders_view_mode:';
const loadViewModeFor = (user: string | null): OrdersViewMode => {
  if (!user) return 'card';
  const stored = storage.getItem(VIEW_MODE_KEY_PREFIX + user);
  return stored === 'list' ? 'list' : 'card';
};
const persistViewModeFor = (user: string | null, mode: OrdersViewMode) => {
  if (!user) return;
  storage.setItem(VIEW_MODE_KEY_PREFIX + user, mode);
};

export interface OrdersState {
  orders: POSInvoice[];
  orderLoading: boolean;
  error: string | null;
  pagination: {
    currentPage: number;
    hasNextPage: boolean;
    itemsPerPage: number;
  };
  selectedStatus: OrderStatusType;
  selectedOrder: POSInvoice | null;
  selectedOrderItems: POSInvoiceItem[];
  selectedOrderTaxes: POSInvoiceTax[];
  selectedOrderLoading: boolean;
  selectedOrderError: string | null;
  orderSearchQuery: string;
  /** Posting date filter (YYYY-MM-DD). Defaults to today. */
  selectedDate: string;
  /** Card or list. Per-user, persisted to localStorage. */
  viewMode: OrdersViewMode;
  /** "mine", "all", or a specific user id. Default "mine". */
  cashierFilter: OrdersCashierFilter;
  /** Cashier dropdown options for the captain's filter. */
  cashierUsers: CashierUser[];
  cashierUsersLoading: boolean;
  /** When true, the Orders page is in "merge mode" — cards wobble + are selectable. */
  mergeMode: boolean;
  /** Selected invoice names while in merge mode. */
  mergeSelection: string[];
  /** A merge or unmerge call is in flight. */
  mergeLoading: boolean;
  /**
   * The most recent Active merge log where `selectedOrder` is the
   * master, or null. Set when an order is selected. Used by the right
   * panel to render the Unmerge button.
   */
  selectedOrderMergeLog: ActiveMergeLog | null;
}

export interface OrdersActions {
  fetchOrders: (page?: number) => Promise<void>;
  updateOrderStatus: (orderId: string, status: POSInvoice['status']) => Promise<void>;
  goToNextPage: () => Promise<void>;
  goToPreviousPage: () => Promise<void>;
  setSelectedStatus: (status: OrderStatusType) => Promise<void>;
  selectOrder: (order: POSInvoice) => Promise<void>;
  /** Open a specific invoice on the Orders page by name (from the Waiters
   *  page): pre-search + pre-select so the cashier lands on it, ready to
   *  print / take payment. */
  openOrderByName: (name: string) => Promise<void>;
  clearSelectedOrder: () => void;
  setOrderSearchQuery: (query: string) => void;
  setSelectedDate: (date: string) => Promise<void>;
  resetSelectedDateToToday: () => Promise<void>;
  setViewMode: (mode: OrdersViewMode, userName?: string | null) => void;
  hydrateViewMode: (userName: string | null) => void;
  setCashierFilter: (filter: OrdersCashierFilter) => Promise<void>;
  fetchCashierUsers: () => Promise<void>;
  enterMergeMode: () => void;
  exitMergeMode: () => void;
  toggleMergeSelection: (invoiceName: string) => void;
  mergeSelectedOrders: (notes?: string) => Promise<{ master: string } | null>;
  unmergeOrder: (mergeLogName: string) => Promise<boolean>;
}

export type OrdersSlice = OrdersState & OrdersActions;

const ITEMS_PER_PAGE = 10;

export const createOrdersSlice: StateCreator<
  OrdersSlice,
  [],
  [],
  OrdersSlice
> = (set, get) => ({
  // Initial state
  orders: [],
  orderLoading: false,
  error: null,
  pagination: {
    currentPage: 1,
    hasNextPage: false,
    itemsPerPage: ITEMS_PER_PAGE,
  },
  selectedStatus: 'Draft',
  selectedOrder: null,
  selectedOrderItems: [],
  selectedOrderTaxes: [],
  selectedOrderLoading: false,
  selectedOrderError: null,
  orderSearchQuery: '',
  selectedDate: todayIso(),
  viewMode: 'card',
  cashierFilter: 'mine',
  cashierUsers: [],
  cashierUsersLoading: false,
  mergeMode: false,
  mergeSelection: [],
  mergeLoading: false,
  selectedOrderMergeLog: null,

  // Actions
  fetchOrders: async (page = 1) => {
    try {
      set({ orderLoading: true, error: null });
      const {
        orderSearchQuery,
        selectedStatus,
        selectedDate,
        cashierFilter,
      } = get();

      // Get POS profile to access paid_limit
      const posProfile = sessionStorage.getItem('posProfile');
      const profile = posProfile ? JSON.parse(posProfile) : null;
      const paidLimit = profile?.paid_limit;

      // Always scope to the device's registered terminal — same source
      // of truth as App.tsx and config-slice.
      const terminal = getSavedTerminal();

      // Incoming Transfers is a dedicated view that joins the URY Invoice
      // Transfer doctype (Pending transfers addressed to me). It ignores
      // search/pagination and isn't terminal/date scoped on the backend.
      if (selectedStatus === 'Incoming Transfers') {
        const res = await getIncomingTransfers(terminal, selectedDate);
        set({
          orders: (res.data || []) as POSInvoice[],
          pagination: {
            currentPage: 1,
            hasNextPage: false,
            itemsPerPage: ITEMS_PER_PAGE,
          },
          orderLoading: false,
        });
        return;
      }

      if (orderSearchQuery && orderSearchQuery.trim()) {
        // Use search API
        const res = await searchPosInvoice(orderSearchQuery, selectedStatus, {
          terminal,
          posting_date: selectedDate,
          cashier: cashierFilter,
        });
        set({
          orders: res.data || [],
          pagination: {
            currentPage: 1,
            hasNextPage: false,
            itemsPerPage: ITEMS_PER_PAGE,
          },
          orderLoading: false,
        });
        return;
      }
      // Default fetch
      const limitStart = (page - 1) * ITEMS_PER_PAGE;
      const status = selectedStatus;
      const { invoices, hasMore } = await getPOSInvoices({
        status,
        limit: ITEMS_PER_PAGE,
        limit_start: limitStart,
        paid_limit: paidLimit,
        terminal,
        posting_date: selectedDate,
        cashier: cashierFilter,
      });
      set({
        orders: invoices,
        pagination: {
          currentPage: page,
          hasNextPage: hasMore,
          itemsPerPage: ITEMS_PER_PAGE,
        },
        orderLoading: false,
      });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch orders',
        orderLoading: false,
      });
    }
  },

  goToNextPage: async () => {
    const { pagination, orderLoading } = get();
    if (!orderLoading && pagination.hasNextPage) {
      await get().fetchOrders(pagination.currentPage + 1);
    }
  },

  goToPreviousPage: async () => {
    const { pagination, orderLoading } = get();
    if (!orderLoading && pagination.currentPage > 1) {
      await get().fetchOrders(pagination.currentPage - 1);
    }
  },

  setSelectedStatus: async (status) => {
    set({ selectedStatus: status });
    // Clear selected order when status changes
    get().clearSelectedOrder();
    await get().fetchOrders(1); // Reset to first page when status changes
  },

  setSelectedDate: async (date) => {
    set({ selectedDate: date });
    get().clearSelectedOrder();
    await get().fetchOrders(1);
  },

  resetSelectedDateToToday: async () => {
    await get().setSelectedDate(todayIso());
  },

  setViewMode: (mode, userName) => {
    set({ viewMode: mode });
    persistViewModeFor(userName ?? null, mode);
  },

  hydrateViewMode: (userName) => {
    set({ viewMode: loadViewModeFor(userName) });
  },

  setCashierFilter: async (filter) => {
    set({ cashierFilter: filter });
    get().clearSelectedOrder();
    await get().fetchOrders(1);
  },

  fetchCashierUsers: async () => {
    try {
      set({ cashierUsersLoading: true });
      const terminal = getSavedTerminal();
      const users = await getCashierUsersForTerminal(terminal);
      set({ cashierUsers: users, cashierUsersLoading: false });
    } catch (error) {
      console.error('Error fetching cashier users:', error);
      set({ cashierUsers: [], cashierUsersLoading: false });
    }
  },

  selectOrder: async (order) => {
    try {
      set({
        selectedOrder: order,
        selectedOrderLoading: true,
        selectedOrderError: null,
        selectedOrderMergeLog: null,
      });

      const { items, taxes } = await getPOSInvoiceItems(order.name);

      set({
        selectedOrderItems: items,
        selectedOrderTaxes: taxes,
        selectedOrderLoading: false,
      });

      // Fire-and-forget: ask the backend if this invoice is the master
      // of an Active merge log so the right panel can show the
      // Unmerge button. Doesn't gate selection — if it fails we just
      // don't show the button.
      try {
        const mergeLog = await getActiveMergeLogForInvoice(order.name);
        // Only apply if the user hasn't switched to a different order
        // in the meantime.
        if (get().selectedOrder?.name === order.name) {
          set({ selectedOrderMergeLog: mergeLog });
        }
      } catch (err) {
        console.error('Error fetching merge log:', err);
      }
    } catch (error) {
      set({
        selectedOrderError: error instanceof Error ? error.message : 'Failed to fetch order details',
        selectedOrderLoading: false,
      });
    }
  },

  openOrderByName: async (name) => {
    // Pre-search + today so the Orders list contains the target row and the
    // filters don't hide it (all Waiters-page orders are drafts). Then fetch
    // the doc and pre-select it so the right panel is already open when the
    // Orders page mounts. 2026-07-16.
    set({
      orderSearchQuery: name,
      selectedStatus: 'Draft',
      selectedDate: todayIso(),
    });
    try {
      const res = await fetch(
        `/api/method/frappe.client.get?doctype=POS+Invoice&name=${encodeURIComponent(
          name
        )}`
      );
      if (!res.ok) throw new Error('Failed to load order');
      const doc = (await res.json()).message;
      const order = {
        name: doc.name,
        status: doc.status,
        grand_total: doc.grand_total,
        net_total: doc.net_total,
        rounded_total: doc.rounded_total,
        total_taxes_and_charges: doc.total_taxes_and_charges,
        invoice_printed: doc.invoice_printed,
        restaurant_table: doc.restaurant_table,
        customer: doc.customer,
        customer_name: doc.customer_name,
        mobile_number: doc.mobile_number,
        posting_date: doc.posting_date,
        posting_time: doc.posting_time,
        order_type: doc.order_type,
        cashier: doc.cashier,
        waiter: doc.waiter,
        custom_order_status: doc.custom_order_status,
        custom_terminal: doc.custom_terminal,
        owner: doc.owner,
        custom_waiter: doc.custom_waiter,
        custom_charge_to_room: doc.custom_charge_to_room,
        custom_hotel_room: doc.custom_hotel_room,
        custom_order_contact_name: doc.custom_order_contact_name,
        custom_order_contact_mobile: doc.custom_order_contact_mobile,
        custom_ihotel_profile: doc.custom_ihotel_profile,
        custom_print_count: doc.custom_print_count,
      } as POSInvoice;
      await get().selectOrder(order);
    } catch (error) {
      set({
        selectedOrderError:
          error instanceof Error ? error.message : 'Failed to open order',
      });
    }
  },

  clearSelectedOrder: () => {
    set({
      selectedOrder: null,
      selectedOrderItems: [],
      selectedOrderTaxes: [],
      selectedOrderError: null,
      selectedOrderMergeLog: null,
    });
  },

  updateOrderStatus: async (orderId: string, status: POSInvoice['status']) => {
    try {
      set({ orderLoading: true, error: null });

      await call.post('ury.ury_pos.api.updatePosInvoiceStatus', {
        invoice: orderId,
        status,
      });

      // Refresh the orders list after status update
      await get().fetchOrders(get().pagination.currentPage);
      
      set({ orderLoading: false });
    } catch (error) {
      set({ 
        error: error instanceof Error ? error.message : 'Failed to update order status',
        orderLoading: false 
      });
    }
  },

  setOrderSearchQuery: (query) => set({ orderSearchQuery: query }),

  // ───── Merge / Unmerge ─────

  enterMergeMode: () => {
    set({ mergeMode: true, mergeSelection: [] });
    // Drop any selected order — the right panel makes no sense in merge mode.
    get().clearSelectedOrder();
  },

  exitMergeMode: () => {
    set({ mergeMode: false, mergeSelection: [] });
  },

  toggleMergeSelection: (invoiceName) => {
    const { mergeSelection } = get();
    if (mergeSelection.includes(invoiceName)) {
      set({ mergeSelection: mergeSelection.filter((n) => n !== invoiceName) });
    } else {
      set({ mergeSelection: [...mergeSelection, invoiceName] });
    }
  },

  mergeSelectedOrders: async (notes) => {
    const { mergeSelection } = get();
    if (mergeSelection.length < 2) {
      set({
        error: 'Select at least two orders to merge.',
      });
      return null;
    }
    try {
      set({ mergeLoading: true, error: null });
      const result = await mergeOrders(mergeSelection, notes);
      set({
        mergeMode: false,
        mergeSelection: [],
        mergeLoading: false,
      });
      // Refresh the list so the merged sources disappear and the master
      // shows its new combined item count / total.
      await get().fetchOrders(1);
      return { master: result.master_invoice };
    } catch (error: unknown) {
      const anyErr = error as {
        _server_messages?: string;
        message?: string;
      };
      let msg = 'Failed to merge orders.';
      if (anyErr?._server_messages) {
        try {
          const parsed = JSON.parse(anyErr._server_messages);
          const first = JSON.parse(parsed[parsed.length - 1]);
          msg = first?.message || msg;
        } catch {
          /* keep default */
        }
      } else if (anyErr?.message) {
        msg = anyErr.message;
      }
      set({ error: msg, mergeLoading: false });
      return null;
    }
  },

  unmergeOrder: async (mergeLogName) => {
    try {
      set({ mergeLoading: true, error: null });
      await unmergeOrders(mergeLogName);
      // Drop the selection — the master invoice's content has changed.
      get().clearSelectedOrder();
      await get().fetchOrders(1);
      set({ mergeLoading: false });
      return true;
    } catch (error: unknown) {
      const anyErr = error as {
        _server_messages?: string;
        message?: string;
      };
      let msg = 'Failed to unmerge order.';
      if (anyErr?._server_messages) {
        try {
          const parsed = JSON.parse(anyErr._server_messages);
          const first = JSON.parse(parsed[parsed.length - 1]);
          msg = first?.message || msg;
        } catch {
          /* keep default */
        }
      } else if (anyErr?.message) {
        msg = anyErr.message;
      }
      set({ error: msg, mergeLoading: false });
      return false;
    }
  },
});
