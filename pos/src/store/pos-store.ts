import { create } from 'zustand';
import { v4 as uuidv4 } from 'uuid';
import { storage } from '../lib/storage';
import { getRestaurantMenu, getAggregatorMenu, MenuItem as APIMenuItem } from '../lib/menu-api';
import { getCurrencyInfo, PosProfileCombined, getCombinedPosProfile } from '../lib/pos-profile-api';
import { getMenuCourses } from '../lib/menu-course-api';
import { getCustomerGroups, getCustomerTerritories } from '../lib/customer-api';
import { DEFAULT_ORDER_TYPE, OrderType } from '../data/order-types';
import { getTableOrder, TableOrder } from '../lib/order-api';
import { getPaymentModes } from '../lib/payment-api';
import { Waiter } from '../lib/waiter-api';

// Constants
const MAX_QUANTITY = 99;
const MIN_QUANTITY = 0;
const ITEMS_PER_PAGE = 10;

// Custom error class for cart operations
class CartError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CartError';
  }
}

// Extend the API MenuItem to include UI-specific properties
export interface MenuItem extends Omit<APIMenuItem, 'rate' | 'item_image'> {
  id: string;
  name: string;
  image: string | null;
  price: number;
  quantity?: number;
  description?: string;
  special_dish?: 1 | 0;
  variants?: Array<{ id: string; name: string; price: number }>;
  addons?: Array<{ id: string; name: string; price: number; category: 'sides' | 'drinks' | 'desserts' }>;
  selectedVariant?: { id: string; name: string; price: number };
  selectedAddons?: Array<{ id: string; name: string; price: number }>;
  uniqueId?: string;
  tax_rate?: number;
}

export interface Customer {
  id: string;
  name: string;
  phone: string;
}

export interface OrderItem extends MenuItem {
  quantity: number;
  selectedVariant?: { id: string; name: string; price: number };
  selectedAddons?: { id: string; name: string; price: number }[];
  uniqueId?: string;
  comment?: string;
}

export interface PaymentMode {
  id: string;
  name: string;
  enabled: boolean;
}

export interface Order {
  id: string;
  cartId: string;
  customerId?: string;
  paymentModeId: string;
  paymentMode: string;
  orderType: OrderType;
  status: 'pending' | 'paid' | 'preparing' | 'ready' | 'completed' | 'cancelled';
  totalAmount: number;
  paidAmount: number;
  createdAt: string;
  updatedAt: string;
}

interface CartTotals {
  subtotal: number;
  tax: number;
  total: number;
  itemCount: number;
}

interface Aggregator {
  customer: string;
}

interface POSState {
  menuItems: MenuItem[];
  categories: string[];
  activeOrders: OrderItem[];
  selectedCategory: string;
  selectedTable: string | null;
  selectedRoom: string | null;
  searchQuery: string;
  selectedCustomer: Customer | null;
  selectedWaiter: Waiter | null;
  selectedOrderType: OrderType;
  quickFilter: 'all' | 'special';
  selectedItem: MenuItem | null;
  cartId: string | null;
  loading: boolean;
  menuLoading: boolean;
  orderLoading: boolean;
  profileLoading: boolean;
  error: string | null;
  paymentModes: string[];
  orders: Order[];
  selectedAggregator: Aggregator | null;
  currency: string;
  currencySymbol: string | null;
  isUpdatingOrder: boolean;
  // When an EXISTING order is opened for editing, a snapshot of each cart
  // line's original quantity keyed by uniqueId. Used to stop a cashier
  // from removing / reducing the original items below what was already
  // ordered (only a captain can). Empty for brand-new orders.
  lockedItemQtys: Record<string, number>;
  orderId: string | null;
  posProfile: PosProfileCombined | null;
  customerGroups: string[];
  territories: string[];
  tableOrder: TableOrder | null;
  isInitializing: boolean;
  orderComment: string;
  terminalName: string | null;
  terminalDescription: string | null;
  /** Branch the registered terminal belongs to. Displayed in the Header chip. */
  terminalBranch: string | null;
  /** POS Profile name bound to the registered terminal. Displayed in the Header chip. */
  terminalPosProfile: string | null;
  /**
   * Shift watcher state. Set by the ShiftHoursBanner when the open
   * entry's `period_start_date` is older than `posProfile.custom_shift_hours`.
   * `shiftBlocked` is only true when the profile also has
   * `custom_block_orders_after_shift_end` enabled — in that case
   * OrderPanel disables the submit button.
   */
  shiftExpired: boolean;
  shiftBlocked: boolean;
  /**
   * iHotel: the selected hotel room for the current draft order when the
   * cashier has picked "Hotel Guest" in the customer picker. Persisted back
   * to the POS Invoice via `sync_order` so it survives reloads. The actual
   * folio write happens when the cashier confirms "Charge to Room" in the
   * Payment dialog.
   */
  hotelRoom: string | null;
  /** iHotel Profile name that matches (customer, hotel_room). Resolved at room-pick time. */
  ihotelProfile: string | null;
}

interface POSStore extends POSState {
  fetchMenuItems: () => Promise<void>;
  fetchAggregatorMenu: (aggregator: string) => Promise<void>;
  fetchCategories: () => Promise<void>;
  fetchPaymentModes: () => Promise<void>;
  addToOrder: (item: OrderItem) => Promise<void>;
  removeFromOrder: (uniqueId: string) => Promise<void>;
  updateQuantity: (uniqueId: string, quantity: number) => Promise<void>;
  clearOrder: () => Promise<void>;
  setSelectedCategory: (category: string) => void;
  setSearchQuery: (query: string) => void;
  setSelectedCustomer: (customer: Customer | null) => void;
  setSelectedWaiter: (waiter: Waiter | null) => void;
  setSelectedTable: (table: string | null, room: string | null, doNotLoadOrder?: boolean) => void;
  setSelectedOrderType: (type: OrderType) => void;
  setQuickFilter: (filter: 'all' | 'special') => void;
  setSelectedItem: (item: MenuItem | null) => void;
  initializeCart: () => Promise<void>;
  processPayment: (paymentMode: string, amount: number) => Promise<void>;
  updateOrderStatus: (orderId: string, status: Order['status']) => Promise<void>;
  fetchPosProfile: () => Promise<void>;
  fetchCustomerGroups: () => Promise<void>;
  fetchTerritories: () => Promise<void>;
  fetchCurrencySymbol: () => Promise<void>;
  getCartTotals: () => CartTotals;
  itemExistsInCart: (uniqueId: string) => boolean;
  validateQuantity: (quantity: number) => boolean;
  getItemPrice: (item: OrderItem) => number;
  getItemQuantityFromCart: (item: MenuItem) => number;
  loadTableOrder: (table: string) => Promise<void>;
  clearTableOrder: () => void;
  isMenuInteractionDisabled: () => boolean;
  isOrderInteractionDisabled: () => boolean;
  initializeApp: () => Promise<void>;
  setOrderForUpdate: (orderId: string | null) => void;
  // Snapshot current cart line qtys as the "original" baseline (called
  // after an existing order is hydrated for editing).
  snapshotLockedQtys: () => void;
  resetOrderState: () => void;
  setSelectedAggregator: (aggregator: Aggregator | null) => void;
  setOrderComment: (comment: string) => void;
  setTerminalConfig: (config: {
    terminal: string;
    room: string;
    branch: string;
    description?: string;
    pos_profile?: string;
  }) => void;
  setShiftExpired: (expired: boolean, blocked: boolean) => void;
  setHotelRoom: (room: string | null, profile: string | null) => void;
}

const generateUniqueId = (item: OrderItem): string => {
  const variantId = item.selectedVariant?.id || 'default';
  const addonIds = item.selectedAddons?.map(addon => addon.id).sort().join('-') || 'no-addons';
  return `${item.id}-${variantId}-${addonIds}`;
};

const calculateItemPrice = (item: OrderItem): number => {
  const basePrice = item.selectedVariant?.price || item.price;
  const addonsTotal = item.selectedAddons?.reduce((sum, addon) => sum + addon.price, 0) || 0;
  return basePrice + addonsTotal;
};

export const usePOSStore = create<POSStore>((set, get) => ({
  menuItems: [],
  categories: [],
  activeOrders: [],
  selectedCategory: '',
  selectedTable: null,
  selectedRoom: null,
  searchQuery: '',
  selectedCustomer: null,
  selectedWaiter: null,
  selectedOrderType: DEFAULT_ORDER_TYPE as OrderType,
  quickFilter: "all",
  selectedItem: null,
  cartId: null,
  loading: false,
  menuLoading: false,
  orderLoading: false,
  profileLoading: false,
  error: null,
  paymentModes: ['Cash'],
  orders: [],
  posProfile: null,
  customerGroups: [],
  territories: [],
  selectedAggregator: null,
  currency: storage.getItem('currency') || 'INR',
  currencySymbol: storage.getItem('currencySymbol') || null,
  tableOrder: null,
  isInitializing: true,
  isUpdatingOrder: false,
  lockedItemQtys: {},
  orderId: null,
  orderComment: '',
  terminalName: null,
  terminalDescription: null,
  terminalBranch: null,
  terminalPosProfile: null,
  shiftExpired: false,
  shiftBlocked: false,
  hotelRoom: null,
  ihotelProfile: null,

  setHotelRoom: (room, profile) => {
    set({ hotelRoom: room, ihotelProfile: profile });
  },

  setTerminalConfig: (config) => {
    set({
      terminalName: config.terminal,
      terminalDescription: config.description || null,
      terminalBranch: config.branch,
      terminalPosProfile: config.pos_profile || null,
      selectedRoom: config.room,
    });
  },

  setShiftExpired: (expired, blocked) => {
    // Only call set when something actually changed — avoids needless
    // re-renders from the 60 s polling timer in ShiftHoursBanner.
    const current = get();
    if (current.shiftExpired === expired && current.shiftBlocked === blocked) {
      return;
    }
    set({ shiftExpired: expired, shiftBlocked: blocked });
  },

  initializeApp: async () => {
    try {
      set({ isInitializing: true, error: null });

      await Promise.allSettled([
        get().fetchPosProfile(),
        get().fetchMenuItems(),
        get().fetchCategories(),
        get().fetchPaymentModes(),
      ]);

      // Each child action sets `error` on its own failure path with a
      // specific, actionable message — don't overwrite those with a
      // generic "Failed to initialize app" string. The POS page's error
      // screen reads `error` directly, so preserving the child message is
      // what makes the user see e.g. "No URY Restaurant is configured for
      // branch 'X'..." See CLAUDE.md "Fixes log" 2026-04-08.
      set({
        isInitializing: false,
        selectedCustomer: {
          id: 'Cash Customer',
          name: 'Cash Customer',
          phone: '',
        },
      });
    } catch (error) {
      // Only unexpected synchronous errors reach here — allSettled never
      // rejects. Keep a fallback so we still unstick the UI.
      set({
        error:
          (error as Error)?.message ||
          'Failed to initialize app. Please refresh the page.',
        isInitializing: false,
      });
    }
  },

  fetchPosProfile: async () => {
    try {
      const cached = sessionStorage.getItem('posProfile');
      if (cached) {
        const profile = JSON.parse(cached);
        set({
          posProfile: profile,
          profileLoading: false,
          currency: profile.currency || 'INR'
        });
        if (!storage.getItem('currencySymbol')) {
          await get().fetchCurrencySymbol();
        }
        return;
      }

      set({ profileLoading: true, error: null });
      // Pass the registered terminal so the backend uses
      // `URY POS Terminal.pos_profile` to resolve the profile
      // deterministically, even when a branch has multiple profiles.
      const combinedProfile = await getCombinedPosProfile(get().terminalName);

      sessionStorage.setItem('posProfile', JSON.stringify(combinedProfile));
      set({ 
        posProfile: combinedProfile, 
        profileLoading: false,
        currency: combinedProfile.currency || 'INR'
      });
      
      if (!storage.getItem('currencySymbol')) {
        await get().fetchCurrencySymbol();
      }
    } catch (error) {
      console.error('Error fetching POS profile:', error);
      set({ 
        error: 'Failed to fetch POS profile',
        profileLoading: false 
      });
    }
  },

  fetchCurrencySymbol: async () => {
    try {
      const currency = get().currency;
      const response = await getCurrencyInfo(currency);
      const { symbol } = response;
      
      set({ currencySymbol: symbol });
      storage.setItem('currencySymbol', symbol);
    } catch (error) {
      console.error('Error fetching currency symbol:', error);
      set({ currencySymbol: get().currency });
      storage.setItem('currencySymbol', get().currency);
    }
  },

  fetchMenuItems: async () => {
    const { posProfile, selectedRoom, selectedOrderType } = get();
    if (!posProfile?.restaurant) return;

    try {
      set({ menuLoading: true, error: null });
      const items = await getRestaurantMenu(posProfile.name, selectedRoom, selectedOrderType);
      
      const menuItems: MenuItem[] = items.map(item => ({
        id: item.item,
        name: item.item_name,
        image: item.item_image || null,
        price: typeof item.rate === 'string' ? parseFloat(item.rate) : item.rate || 0,
        item: item.item,
        item_name: item.item_name,
        item_image: item.item_image,
        course: item.course,
        description: item.description || '',
        special_dish: item.special_dish || 0,
        tax_rate: 0,
      }));

      set({ menuItems });
    } catch (error) {
      // `menu-api.ts` already unwraps Frappe's _server_messages into
      // `new Error(serverMessage)` — keep that friendly text instead of
      // replacing it with a vague fallback. See CLAUDE.md "Fixes log".
      const message =
        (error as Error)?.message || 'Failed to load menu items';
      set({ error: message });
      console.error('Error loading menu items:', error);
    } finally {
      set({ menuLoading: false });
    }
  },

  fetchAggregatorMenu: async (aggregator: string) => {
    try {
      set({ menuLoading: true, error: null });
      const items = await getAggregatorMenu(aggregator);
      
      const menuItems: MenuItem[] = items.map(item => ({
        ...item,
        id: item.item,
        name: item.item_name,
        image: item.item_image || null,
        price: typeof item.rate === 'string' ? parseFloat(item.rate) : item.rate || 0,
        category: item.course
      }));

      set({ menuItems, menuLoading: false });
    } catch (error) {
      set({ error: 'Failed to load aggregator menu', menuLoading: false });
      console.error('Error loading aggregator menu:', error);
    }
  },

  fetchCategories: async () => {
    try {
      const cached = sessionStorage.getItem('menuCategories');
      if (cached) {
        const categories = JSON.parse(cached);
        set({ categories });
        return;
      }

      const courses = await getMenuCourses();
      const categoryNames = courses.map(course => course.name);
      sessionStorage.setItem('menuCategories', JSON.stringify(categoryNames));
      set({ categories: categoryNames });
    } catch (error) {
      set({ error: 'Failed to load menu categories' });
      throw error;
    }
  },

  fetchPaymentModes: async () => {
    try {
      const modes = await getPaymentModes();
      set({ paymentModes: modes });
    } catch (error) {
      console.error('Failed to fetch payment modes:', error);
    }
  },

  initializeCart: async () => {
    set({ cartId: uuidv4() });
  },

  addToOrder: async (item: OrderItem) => {
    try {
      if (!get().validateQuantity(item.quantity)) {
        throw new CartError(`Quantity must be between ${MIN_QUANTITY} and ${MAX_QUANTITY}`);
      }

      const uniqueId = generateUniqueId(item);
      const existingItemIndex = get().activeOrders.findIndex(orderItem => orderItem.uniqueId === uniqueId);

      if (existingItemIndex !== -1) {
        const existingItem = get().activeOrders[existingItemIndex];
        const newQuantity = existingItem.quantity + item.quantity;
        const newComment = item.comment !== undefined ? item.comment : existingItem?.comment || "";

        if (!get().validateQuantity(newQuantity)) {
          throw new CartError(`Cannot add item. Total quantity would exceed ${MAX_QUANTITY}`);
        }

        const newOrders = [...get().activeOrders];
        newOrders[existingItemIndex] = {
          ...existingItem,
          quantity: newQuantity,
          comment: newComment
        };
        
        set({ activeOrders: newOrders });
      } else {
        const newOrders = [...get().activeOrders, { ...item, uniqueId }];
        set({ activeOrders: newOrders });
      }
    } catch (error) {
      if (error instanceof CartError) {
        set({ error: error.message });
      } else {
        set({ error: 'Failed to add item to cart' });
      }
    }
  },

  removeFromOrder: async (uniqueId: string) => {
    try {
      const newOrders = get().activeOrders.filter(item => item.uniqueId !== uniqueId);
      set({ activeOrders: newOrders });
    } catch (error) {
      set({ error: 'Failed to remove item from cart' });
    }
  },

  updateQuantity: async (uniqueId: string, quantity: number) => {
    try {
      if (!get().validateQuantity(quantity)) {
        throw new CartError(`Quantity must be between ${MIN_QUANTITY} and ${MAX_QUANTITY}`);
      }

      const newOrders = get().activeOrders.map(item =>
        item.uniqueId === uniqueId ? { ...item, quantity } : item
      );
      set({ activeOrders: newOrders });
    } catch (error) {
      if (error instanceof CartError) {
        set({ error: error.message });
      } else {
        set({ error: 'Failed to update quantity' });
      }
    }
  },

  clearOrder: async () => {
    try {
      set({ activeOrders: [] });
    } catch (error) {
      set({ error: 'Failed to clear cart' });
    }
  },

  setSelectedCategory: (category) => set({ selectedCategory: category }),
  setSearchQuery: (query) => set({ searchQuery: query }),
  setSelectedCustomer: (customer) => {
    // A hotel room is only valid for the customer it was resolved against
    // (Customer → Guest → iHotel Profile chain). Any customer change
    // invalidates that link, so clear the hotel context defensively.
    const prev = get().selectedCustomer;
    if (!customer || !prev || customer.id !== prev.id) {
      set({ selectedCustomer: customer, hotelRoom: null, ihotelProfile: null });
    } else {
      set({ selectedCustomer: customer });
    }
  },
  setSelectedWaiter: (waiter) => set({ selectedWaiter: waiter }),
  setSelectedTable: (table: string | null, room: string | null, doNotLoadOrder: boolean = false) => {
    set({ selectedTable: table, selectedRoom: room });
    if (table ) {
      if (!doNotLoadOrder) 
        get().loadTableOrder(table);
    } else {
      get().clearTableOrder();
    }
    if (room) {
      get().fetchMenuItems();
    }
  },
  setSelectedOrderType: (type) => {
    const { fetchMenuItems } = get();
    
    set({ 
      activeOrders: [],
      selectedOrderType: type,
      isUpdatingOrder: false,
      orderId: null
    });
    
    if (type !== 'Aggregators') {
      fetchMenuItems();
    }
  },
  setQuickFilter: (filter) => set({ quickFilter: filter }),
  setSelectedItem: (item) => set({ selectedItem: item }),
  setSelectedAggregator: (aggregator) => set({ selectedAggregator: aggregator }),
  setOrderComment: (comment: string) => set({ orderComment: comment }),

  processPayment: async (paymentMode: string, amount: number) => {
    try {
      const { activeOrders, cartId, selectedCustomer, selectedOrderType } = get();
      
      const order: Order = {
        id: uuidv4(),
        cartId: cartId!,
        customerId: selectedCustomer?.id,
        paymentModeId: paymentMode,
        paymentMode,
        orderType: selectedOrderType,
        status: 'paid',
        totalAmount: amount,
        paidAmount: amount,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
      };

      const newOrders = [...get().orders, order];
      set({ orders: newOrders });
      
      await get().clearOrder();
    } catch (error) {
      set({ error: (error as Error).message });
    }
  },

  updateOrderStatus: async (orderId: string, status: Order['status']) => {
    try {
      const newOrders = get().orders.map(order => 
        order.id === orderId 
          ? { ...order, status, updatedAt: new Date().toISOString() }
          : order
      );
      set({ orders: newOrders });
    } catch (error) {
      set({ error: (error as Error).message });
    }
  },

  fetchCustomerGroups: async () => {
    const cached = sessionStorage.getItem('customerGroups');
    if (cached) {
      set({ customerGroups: JSON.parse(cached) });
      return;
    }
    const groups = await getCustomerGroups();
    const names = groups.map((g: any) => g.name);
    set({ customerGroups: names });
    sessionStorage.setItem('customerGroups', JSON.stringify(names));
  },

  fetchTerritories: async () => {
    const cached = sessionStorage.getItem('territories');
    if (cached) {
      set({ territories: JSON.parse(cached) });
      return;
    }
    const terrs = await getCustomerTerritories();
    const names = terrs.map((t: any) => t.name);
    set({ territories: names });
    sessionStorage.setItem('territories', JSON.stringify(names));
  },

  getCartTotals: (): CartTotals => {
    const items = get().activeOrders;
    const itemCount = items.reduce((sum, item) => sum + item.quantity, 0);
    
    const subtotal = items.reduce((sum, item) => {
      const itemPrice = calculateItemPrice(item);
      return sum + (itemPrice * item.quantity);
    }, 0);

    const tax = items.reduce((sum, item) => {
      const itemPrice = calculateItemPrice(item);
      const taxRate = item.tax_rate || 0;
      return sum + (itemPrice * item.quantity * (taxRate / 100));
    }, 0);

    return {
      subtotal,
      tax,
      total: subtotal + tax,
      itemCount
    };
  },

  itemExistsInCart: (uniqueId: string): boolean => {
    return get().activeOrders.some(item => item.uniqueId === uniqueId);
  },

  validateQuantity: (quantity: number): boolean => {
    return !isNaN(quantity) && quantity >= MIN_QUANTITY && quantity <= MAX_QUANTITY;
  },

  getItemPrice: (item: OrderItem): number => {
    return calculateItemPrice(item);
  },

  getItemQuantityFromCart: (item: MenuItem): number => {
    const uniqueId = generateUniqueId(item as OrderItem);
    const cartItem = get().activeOrders.find(orderItem => orderItem.uniqueId === uniqueId);
    return cartItem?.quantity || 0;
  },

  loadTableOrder: async (table: string) => {
    try {
      set({ orderLoading: true, error: null });
      const response = await getTableOrder(table);
      const order = response.message;
      if (order && order.name && order.items && order.items.length > 0) {
        const orderItems: OrderItem[] = order.items.map(item => {
          const orderItem = {
            id: item.item_code,
            name: item.item_name,
            price: item.rate,
            quantity: item.qty,
            amount: item.amount,
            image: item.image || null,
            item: item.item_code,
            item_name: item.item_name,
            item_image: null,
            course: '',
            description: item.description || '',
            special_dish: 0 as 0 | 1,
            tax_rate: 0,
          };
          return {
            ...orderItem,
            uniqueId: generateUniqueId(orderItem as OrderItem)
          } as OrderItem;
        });

        set({
          tableOrder: response,
          activeOrders: orderItems,
          // Baseline of original line quantities — a cashier can't reduce
          // these below what was already ordered (or remove them).
          lockedItemQtys: orderItems.reduce(
            (acc, it) => {
              if (it.uniqueId) acc[it.uniqueId] = it.quantity;
              return acc;
            },
            {} as Record<string, number>
          ),
          selectedCustomer: order.customer ? {
            id: order.customer,
            name: order.customer_name,
            phone: order.mobile_number,
          } : null,
          isUpdatingOrder: true,
          orderId: order.name,
          // Rehydrate the hotel room intent from the draft so the
          // customer picker opens in Hotel Guest mode with the right
          // room pre-selected on reload. The ihotelProfile lookup is
          // deferred to the picker — the draft only stamps the room.
          hotelRoom: order.custom_hotel_room || null,
          ihotelProfile: order.custom_ihotel_profile || null,
        });
      } else {
        set({
          tableOrder: null,
          activeOrders: [],
          selectedCustomer: null,
          selectedWaiter: null,
          isUpdatingOrder: false,
          orderId: null,
          hotelRoom: null,
          ihotelProfile: null,
        });
      }
    } catch (error) {
      set({
        error: 'Failed to load table order',
        tableOrder: null,
        activeOrders: [],
        selectedCustomer: null,
        isUpdatingOrder: false,
        orderId: null,
        hotelRoom: null,
        ihotelProfile: null,
      });
    } finally {
      set({ orderLoading: false });
    }
  },

  clearTableOrder: () => {
    set({
      tableOrder: null,
      activeOrders: [],
      selectedCustomer: null,
      selectedWaiter: null,
      isUpdatingOrder: false,
      orderId: null,
      hotelRoom: null,
      ihotelProfile: null,
    });
  },

  setOrderForUpdate: (orderId: string | null) => {
    set({
      isUpdatingOrder: orderId !== null,
      orderId,
      // Starting fresh (orderId null) clears the baseline; an actual
      // order's baseline is captured separately via snapshotLockedQtys
      // (Orders-page edit flow) or set directly in loadTableOrder.
      ...(orderId === null ? { lockedItemQtys: {} } : {}),
    });
  },

  snapshotLockedQtys: () => {
    const qtys = get().activeOrders.reduce(
      (acc, it) => {
        if (it.uniqueId) acc[it.uniqueId] = it.quantity;
        return acc;
      },
      {} as Record<string, number>
    );
    set({ lockedItemQtys: qtys });
  },

  resetOrderState: () => {
  const { fetchMenuItems, selectedRoom } = get();

  set({
    selectedCustomer: { id: 'Cash Customer', name: 'Cash Customer', phone: '' },
    selectedWaiter: null,
    lockedItemQtys: {},
    selectedTable: null,
    selectedRoom: selectedRoom,
    selectedAggregator: null,
    isUpdatingOrder: false,
    orderId: null,
    activeOrders: [],
    selectedItem: null,
    orderLoading: false,
    menuItems: [],
    error: null,
    selectedOrderType: DEFAULT_ORDER_TYPE,
    orderComment: '',
    hotelRoom: null,
    ihotelProfile: null,
  });

  fetchMenuItems();
},

  isMenuInteractionDisabled: () => {
    const state = get();
    return state.menuLoading || state.profileLoading;
  },

  isOrderInteractionDisabled: () => {
    const state = get();
    return state.orderLoading;
  }
})); 