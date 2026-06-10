import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Users,
  RefreshCw,
  Edit,
  Loader2,
  UserRound,
  ClipboardList,
  Search,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { Input } from '../components/ui/input';
import { usePOSStore } from '../store/pos-store';
import {
  getWaitersWithPendingOrders,
  type WaiterWithOrders,
} from '../lib/waiter-api';
import { formatCurrency, extractFrappeServerError } from '../lib/utils';
import { showToast } from '../components/ui/toast';
import { Button } from '../components/ui/button';
import { Spinner } from '../components/ui/spinner';

const Waiters = () => {
  const navigate = useNavigate();
  const posStore = usePOSStore();
  const [waiters, setWaiters] = useState<WaiterWithOrders[]>([]);
  const [loading, setLoading] = useState(true);
  const [editLoadingId, setEditLoadingId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  // Per-waiter collapse state. Absent = expanded (default).
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const toggle = (name: string) =>
    setCollapsed((c) => ({ ...c, [name]: !c[name] }));

  const load = async () => {
    setLoading(true);
    try {
      setWaiters(await getWaitersWithPendingOrders());
    } catch (e) {
      showToast.error(
        extractFrappeServerError(e, 'Failed to load waiters').message
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  // Open a waiter's order in the POS for editing. Mirrors Orders.tsx
  // handleEditOrder — fetch the order, hydrate the POS store, navigate home.
  const handleEditOrder = async (orderName: string) => {
    setEditLoadingId(orderName);
    try {
      const res = await fetch(
        `/api/method/frappe.client.get?doctype=POS+Invoice&name=${encodeURIComponent(
          orderName
        )}`
      );
      if (!res.ok) throw new Error('Failed to fetch order details');
      const data = await res.json();
      const order = data.message;
      posStore.resetOrderState();
      posStore.setSelectedOrderType(order.order_type);
      posStore.setOrderForUpdate(order.name);
      if (order.restaurant_table) {
        posStore.setSelectedTable(
          order.restaurant_table,
          order.custom_restaurant_room || null,
          true
        );
      }
      posStore.setSelectedCustomer({
        id: order.customer,
        name: order.customer_name,
        phone: order.mobile_number,
      });
      const items = (order.items || []).map((item: any) => ({
        id: item.item_code,
        name: item.item_name,
        price: item.rate,
        quantity: item.qty,
        amount: item.amount,
        image: item.image || null,
        uniqueId: item.name,
        item: item.item_code,
        item_name: item.item_name,
        item_image: null,
        course: '',
        description: item.description || '',
        special_dish: 0,
        tax_rate: 0,
      }));
      for (const cartItem of items) {
        await posStore.addToOrder(cartItem);
      }
      navigate('/');
    } catch (err) {
      showToast.error(
        err instanceof Error ? err.message : 'Failed to edit order'
      );
    } finally {
      setEditLoadingId(null);
    }
  };

  const totalPending = waiters.reduce((s, w) => s + w.orders.length, 0);

  const filteredWaiters = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return waiters;
    return waiters.filter(
      (w) =>
        w.full_name.toLowerCase().includes(q) ||
        (w.mobile_number || '').toLowerCase().includes(q)
    );
  }, [waiters, search]);

  return (
    <div className="h-full flex flex-col bg-gray-50">
      {/* Header */}
      <div className="shrink-0 bg-white border-b border-gray-200 px-4 sm:px-6 py-3 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Users className="w-5 h-5 text-blue-600" />
            <h1 className="text-lg font-bold text-gray-900">Waiters</h1>
            <span className="text-xs text-gray-500">
              {totalPending} pending order{totalPending === 1 ? '' : 's'}
            </span>
          </div>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw
              className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`}
            />
            Refresh
          </Button>
        </div>
        <div className="relative max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search a waiter by name or mobile…"
            className="pl-9"
          />
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Spinner className="w-8 h-8" />
          </div>
        ) : waiters.length === 0 ? (
          <div className="text-center text-gray-500 py-20">
            <UserRound className="w-10 h-10 mx-auto text-gray-300 mb-3" />
            <p className="font-medium">No pending waiter orders.</p>
            <p className="text-sm">
              Only waiters with pending (unpaid) orders show here. An order
              leaves this list once it's paid.
            </p>
          </div>
        ) : filteredWaiters.length === 0 ? (
          <div className="text-center text-gray-500 py-20">
            <Search className="w-10 h-10 mx-auto text-gray-300 mb-3" />
            <p className="font-medium">No waiters match "{search}".</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 items-start">
            {filteredWaiters.map((w) => (
              <div
                key={w.name}
                className="bg-white rounded-xl border border-gray-200 overflow-hidden"
              >
                <button
                  type="button"
                  onClick={() => toggle(w.name)}
                  className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-100/70 transition-colors"
                >
                  <div className="w-9 h-9 rounded-full bg-blue-100 flex items-center justify-center shrink-0">
                    <UserRound className="w-4 h-4 text-blue-700" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold text-gray-900 truncate">
                      {w.full_name}
                    </div>
                    {w.mobile_number && (
                      <div className="text-xs text-gray-500 truncate">
                        {w.mobile_number}
                      </div>
                    )}
                  </div>
                  <span
                    className="text-xs font-semibold text-gray-600 bg-gray-100 rounded-full px-2.5 py-1 shrink-0"
                    title={`${w.orders.length} pending order${
                      w.orders.length === 1 ? '' : 's'
                    }`}
                  >
                    {w.orders.length}
                  </span>
                  {collapsed[w.name] ? (
                    <ChevronRight className="w-4 h-4 text-gray-400 shrink-0" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-gray-400 shrink-0" />
                  )}
                </button>

                {!collapsed[w.name] &&
                  (w.orders.length === 0 ? (
                  <div className="px-4 py-4 text-sm text-gray-400 italic">
                    No pending orders.
                  </div>
                ) : (
                  <div className="p-3 space-y-2.5 bg-gray-50/60">
                    {w.orders.map((o, idx) => (
                      <div
                        key={o.name}
                        onClick={() => handleEditOrder(o.name)}
                        role="button"
                        tabIndex={0}
                        title="Click to edit this order"
                        className="group relative rounded-lg border border-gray-200 bg-white p-3 cursor-pointer hover:border-blue-400 hover:shadow-sm transition-all"
                      >
                        {editLoadingId === o.name && (
                          <div className="absolute inset-0 bg-white/70 flex items-center justify-center rounded-lg z-10">
                            <Loader2 className="w-5 h-5 animate-spin text-blue-600" />
                          </div>
                        )}
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              {w.orders.length > 1 && (
                                <span className="text-[10px] font-bold uppercase tracking-wide text-blue-700 bg-blue-50 border border-blue-200 rounded px-1.5 py-0.5">
                                  Invoice {idx + 1} of {w.orders.length}
                                </span>
                              )}
                              <span className="font-mono text-sm font-medium text-gray-800">
                                {o.name}
                              </span>
                            </div>
                            <div className="text-xs text-gray-500 mt-0.5">
                              {o.order_type}
                              {o.restaurant_table
                                ? ` · Table ${o.restaurant_table}`
                                : ''}
                              {' · '}
                              {o.customer_name || o.customer || 'Walk-in'}
                            </div>
                          </div>
                          <div className="text-right shrink-0">
                            <div className="font-bold text-gray-900">
                              {formatCurrency(o.grand_total)}
                            </div>
                            <div className="text-[11px] text-blue-600 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 justify-end mt-0.5">
                              <Edit className="w-3 h-3" /> Edit
                            </div>
                          </div>
                        </div>
                        {/* Items */}
                        <ul className="mt-2 space-y-0.5 border-t border-gray-100 pt-2">
                          {o.items.map((it, ii) => (
                            <li
                              key={ii}
                              className="flex items-center justify-between text-xs text-gray-600"
                            >
                              <span className="truncate">
                                <span className="font-medium text-gray-800">
                                  {it.qty}×
                                </span>{' '}
                                {it.item_name}
                              </span>
                              <span className="tabular-nums shrink-0 ml-2">
                                {formatCurrency(it.amount)}
                              </span>
                            </li>
                          ))}
                          {o.items.length === 0 && (
                            <li className="text-xs text-gray-400 italic flex items-center gap-1">
                              <ClipboardList className="w-3 h-3" /> No items
                            </li>
                          )}
                        </ul>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default Waiters;
