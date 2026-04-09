import { StateCreator } from 'zustand';
import { OrderType } from '../../data/order-types';
import { call } from '../../lib/frappe-sdk';
import {
  getPOSInvoices,
  getPOSInvoiceItems,
  getCashierUsersForTerminal,
  POSInvoiceItem,
  POSInvoiceTax,
  CashierUser,
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
  selectedStatus: 'Draft' | 'Unbilled' | 'Recently Paid' | 'Paid' | 'Consolidated' | 'Return';
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
}

export interface OrdersActions {
  fetchOrders: (page?: number) => Promise<void>;
  updateOrderStatus: (orderId: string, status: POSInvoice['status']) => Promise<void>;
  goToNextPage: () => Promise<void>;
  goToPreviousPage: () => Promise<void>;
  setSelectedStatus: (status: POSInvoice['status']) => Promise<void>;
  selectOrder: (order: POSInvoice) => Promise<void>;
  clearSelectedOrder: () => void;
  setOrderSearchQuery: (query: string) => void;
  setSelectedDate: (date: string) => Promise<void>;
  resetSelectedDateToToday: () => Promise<void>;
  setViewMode: (mode: OrdersViewMode, userName?: string | null) => void;
  hydrateViewMode: (userName: string | null) => void;
  setCashierFilter: (filter: OrdersCashierFilter) => Promise<void>;
  fetchCashierUsers: () => Promise<void>;
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
        selectedOrderError: null 
      });

      const { items, taxes } = await getPOSInvoiceItems(order.name);
      
      set({ 
        selectedOrderItems: items,
        selectedOrderTaxes: taxes,
        selectedOrderLoading: false 
      });
    } catch (error) {
      set({ 
        selectedOrderError: error instanceof Error ? error.message : 'Failed to fetch order details',
        selectedOrderLoading: false 
      });
    }
  },

  clearSelectedOrder: () => {
    set({ 
      selectedOrder: null,
      selectedOrderItems: [],
      selectedOrderTaxes: [],
      selectedOrderError: null 
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
}); 