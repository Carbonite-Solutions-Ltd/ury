import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Users,
  RefreshCw,
  Receipt,
  Loader2,
  UserRound,
  ClipboardList,
  Search,
  ChevronDown,
  ChevronRight,
  GripVertical,
  ArrowRightLeft,
  PauseCircle,
} from 'lucide-react';
import { Input } from '../components/ui/input';
import { useRootStore } from '../store/root-store';
import {
  getWaitersWithPendingOrders,
  reassignOrderWaiter,
  type WaiterWithOrders,
  type WaiterPendingOrder,
} from '../lib/waiter-api';
import {
  getHeldOrders,
  resumeOrder,
  type HeldOrder,
} from '../lib/hold-api';
import { formatCurrency, extractFrappeServerError, cn } from '../lib/utils';
import { showToast } from '../components/ui/toast';
import { Button } from '../components/ui/button';
import { Spinner } from '../components/ui/spinner';

type DragState = { order: WaiterPendingOrder; fromWaiter: string } | null;

// Move an order between waiters in the local list (optimistic update).
const moveOrderLocally = (
  list: WaiterWithOrders[],
  orderName: string,
  from: string,
  to: string
): WaiterWithOrders[] => {
  let moved: WaiterPendingOrder | null = null;
  const stripped = list.map((w) => {
    if (w.name !== from) return w;
    const found = w.orders.find((o) => o.name === orderName);
    if (found) moved = found;
    return { ...w, orders: w.orders.filter((o) => o.name !== orderName) };
  });
  if (!moved) return list;
  return stripped.map((w) =>
    w.name === to ? { ...w, orders: [moved as WaiterPendingOrder, ...w.orders] } : w
  );
};

const Waiters = () => {
  const navigate = useNavigate();
  const openOrderByName = useRootStore((s) => s.openOrderByName);
  const [waiters, setWaiters] = useState<WaiterWithOrders[]>([]);
  const [loading, setLoading] = useState(true);
  const [editLoadingId, setEditLoadingId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  // Per-waiter collapse override. Absent = default (expanded if it has
  // orders, collapsed if empty).
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  // Drag-and-drop reassignment state.
  const [drag, setDrag] = useState<DragState>(null);
  const [dragOverWaiter, setDragOverWaiter] = useState<string | null>(null);
  const [reassigningId, setReassigningId] = useState<string | null>(null);
  const [justMovedId, setJustMovedId] = useState<string | null>(null);
  const [held, setHeld] = useState<HeldOrder[]>([]);
  const [resumingId, setResumingId] = useState<string | null>(null);

  const isCollapsed = (w: WaiterWithOrders) =>
    collapsed[w.name] ?? w.orders.length === 0;
  const toggle = (w: WaiterWithOrders) =>
    setCollapsed((c) => ({
      ...c,
      [w.name]: !(c[w.name] ?? w.orders.length === 0),
    }));

  const load = async () => {
    setLoading(true);
    try {
      // includeEmpty: show every active waiter so any can be a drop target.
      setWaiters(await getWaitersWithPendingOrders(true));
      // Held bills are branch-wide, not per-waiter, so they get their own
      // section above the cards. A failure here must not break the list.
      getHeldOrders()
        .then((h) => setHeld(h.orders))
        .catch(() => setHeld([]));
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

  // Cashier clicks a waiter's order → open it on the Orders page (ready to
  // print + take payment), rather than hydrating it into the POS for editing.
  // The Waiters page is cashier/captain-only (waiters can't reach it), so
  // this is always the cashier flow. 2026-07-16.
  const handleOpenInOrders = async (orderName: string) => {
    setEditLoadingId(orderName);
    try {
      await openOrderByName(orderName);
      navigate('/orders');
    } catch (err) {
      showToast.error(
        err instanceof Error ? err.message : 'Failed to open order'
      );
    } finally {
      setEditLoadingId(null);
    }
  };

  // Drop an order onto a waiter card → reassign it (optimistic, with revert).
  const handleDrop = async (toWaiter: WaiterWithOrders) => {
    const dnd = drag;
    setDragOverWaiter(null);
    setDrag(null);
    if (!dnd || dnd.fromWaiter === toWaiter.name) return;
    const order = dnd.order;
    setReassigningId(order.name);
    // Optimistically move + reveal the destination.
    setWaiters((prev) =>
      moveOrderLocally(prev, order.name, dnd.fromWaiter, toWaiter.name)
    );
    setCollapsed((c) => ({ ...c, [toWaiter.name]: false }));
    try {
      await reassignOrderWaiter(order.name, toWaiter.name);
      showToast.success(`Order ${order.name} moved to ${toWaiter.full_name}`);
      setJustMovedId(order.name);
      setTimeout(
        () => setJustMovedId((cur) => (cur === order.name ? null : cur)),
        1300
      );
    } catch (e) {
      // Revert on failure.
      setWaiters((prev) =>
        moveOrderLocally(prev, order.name, toWaiter.name, dnd.fromWaiter)
      );
      showToast.error(
        extractFrappeServerError(e, 'Failed to move order').message
      );
    } finally {
      setReassigningId(null);
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

  const handleResume = async (order: HeldOrder) => {
    setResumingId(order.name);
    try {
      const res = await resumeOrder(order.name);
      showToast.success({ title: 'Bill resumed', description: res.note });
      setHeld((cur) => cur.filter((o) => o.name !== order.name));
    } catch (err) {
      const p = extractFrappeServerError(err, 'Could not resume this bill.');
      showToast.error({ title: p.title || 'Resume failed', description: p.message });
    } finally {
      setResumingId(null);
    }
  };

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
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="relative max-w-sm flex-1 min-w-[12rem]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search a waiter by name or mobile…"
              className="pl-9"
            />
          </div>
          <p className="text-xs text-gray-400 flex items-center gap-1.5">
            <ArrowRightLeft className="w-3.5 h-3.5" />
            Drag an order onto another waiter to reassign it.
          </p>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        {/* Held bills (2026-08-24). Branch-wide, so it sits above the
            per-waiter cards rather than inside one. Only rendered when
            something is actually parked — an always-present empty panel
            would just be noise on a busy floor. */}
        {held.length > 0 && (
          <div className="mb-5 rounded-lg border border-amber-200 bg-amber-50/60 overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-amber-200 bg-amber-50">
              <PauseCircle className="w-4 h-4 text-amber-700" />
              <h2 className="text-sm font-semibold text-amber-900">Held Bills</h2>
              <span className="ml-auto inline-flex items-center justify-center min-w-[1.5rem] h-6 px-2 rounded-full bg-amber-600 text-white text-xs font-semibold">
                {held.length}
              </span>
            </div>
            <div className="divide-y divide-amber-100">
              {held.map((o) => (
                <div
                  key={o.name}
                  className="flex items-start gap-3 px-4 py-3 hover:bg-amber-50/80"
                >
                  <button
                    onClick={() => handleOpenInOrders(o.name)}
                    className="flex-1 min-w-0 text-left"
                  >
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-gray-900 truncate">
                        {o.name}
                      </span>
                      {o.waiter_name && (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700">
                          {o.waiter_name}
                        </span>
                      )}
                      <span className="text-sm font-semibold text-gray-900">
                        {formatCurrency(o.grand_total)}
                      </span>
                    </div>
                    {o.reason && (
                      <div className="text-xs text-amber-900 mt-0.5">{o.reason}</div>
                    )}
                    <div className="text-[11px] text-gray-500 mt-0.5">
                      Held by {o.held_by_name || o.held_by || 'unknown'}
                      {o.held_at ? ` · ${o.held_at.slice(0, 16)}` : ''}
                    </div>
                  </button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="shrink-0 border-amber-300 text-amber-800 hover:bg-amber-100"
                    onClick={() => handleResume(o)}
                    disabled={resumingId === o.name}
                  >
                    {resumingId === o.name ? (
                      <Spinner className="w-3.5 h-3.5" hideMessage />
                    ) : (
                      'Resume'
                    )}
                  </Button>
                </div>
              ))}
            </div>
          </div>
        )}
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Spinner className="w-8 h-8" />
          </div>
        ) : waiters.length === 0 ? (
          <div className="text-center text-gray-500 py-20">
            <UserRound className="w-10 h-10 mx-auto text-gray-300 mb-3" />
            <p className="font-medium">No waiters yet.</p>
            <p className="text-sm">
              Add a waiter from the POS to start assigning orders.
            </p>
          </div>
        ) : filteredWaiters.length === 0 ? (
          <div className="text-center text-gray-500 py-20">
            <Search className="w-10 h-10 mx-auto text-gray-300 mb-3" />
            <p className="font-medium">No waiters match "{search}".</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 items-start">
            {filteredWaiters.map((w) => {
              const isDropTarget = !!drag && drag.fromWaiter !== w.name;
              const isOver = dragOverWaiter === w.name && isDropTarget;
              return (
                <div
                  key={w.name}
                  onDragOver={(e) => {
                    if (!isDropTarget) return;
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'move';
                    if (dragOverWaiter !== w.name) setDragOverWaiter(w.name);
                  }}
                  onDragLeave={(e) => {
                    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                      setDragOverWaiter((cur) => (cur === w.name ? null : cur));
                    }
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    handleDrop(w);
                  }}
                  className={cn(
                    'bg-white rounded-xl border overflow-hidden transition-all duration-200',
                    isOver &&
                      'border-blue-500 ring-2 ring-blue-400 shadow-xl scale-[1.02] bg-blue-50/40',
                    isDropTarget &&
                      !isOver &&
                      'border-dashed border-blue-300 bg-blue-50/20',
                    !isDropTarget && 'border-gray-200'
                  )}
                >
                  {/* Drop hint banner while hovering a valid target */}
                  {isOver && (
                    <div className="px-4 py-2 bg-blue-600 text-white text-xs font-semibold flex items-center gap-1.5">
                      <ArrowRightLeft className="w-3.5 h-3.5 shrink-0" />
                      Drop to move order to {w.full_name}
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={() => toggle(w)}
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
                      className={cn(
                        'text-xs font-semibold rounded-full px-2.5 py-1 shrink-0',
                        w.orders.length > 0
                          ? 'text-gray-600 bg-gray-100'
                          : 'text-gray-400 bg-gray-50'
                      )}
                      title={`${w.orders.length} pending order${
                        w.orders.length === 1 ? '' : 's'
                      }`}
                    >
                      {w.orders.length}
                    </span>
                    {isCollapsed(w) ? (
                      <ChevronRight className="w-4 h-4 text-gray-400 shrink-0" />
                    ) : (
                      <ChevronDown className="w-4 h-4 text-gray-400 shrink-0" />
                    )}
                  </button>

                  {!isCollapsed(w) &&
                    (w.orders.length === 0 ? (
                      <div
                        className={cn(
                          'mx-3 mb-3 rounded-lg border-2 border-dashed px-4 py-6 text-center text-sm transition-colors',
                          isOver
                            ? 'border-blue-400 text-blue-600 bg-blue-50/50'
                            : 'border-gray-200 text-gray-400'
                        )}
                      >
                        {isDropTarget
                          ? 'Drop an order here'
                          : 'No pending orders.'}
                      </div>
                    ) : (
                      <div className="p-3 space-y-2.5 bg-gray-50/60">
                        {w.orders.map((o, idx) => {
                          const busy =
                            editLoadingId === o.name ||
                            reassigningId === o.name;
                          const dragging = drag?.order.name === o.name;
                          const justMoved = justMovedId === o.name;
                          return (
                            <div
                              key={o.name}
                              draggable={!busy}
                              onDragStart={(e) => {
                                e.dataTransfer.effectAllowed = 'move';
                                e.dataTransfer.setData('text/plain', o.name);
                                setDrag({ order: o, fromWaiter: w.name });
                              }}
                              onDragEnd={() => {
                                setDrag(null);
                                setDragOverWaiter(null);
                              }}
                              onClick={() => !dragging && handleOpenInOrders(o.name)}
                              role="button"
                              tabIndex={0}
                              title="Drag to another waiter to reassign · click to open, print & take payment"
                              className={cn(
                                'group relative rounded-lg border bg-white p-3 transition-all',
                                'cursor-grab active:cursor-grabbing select-none',
                                'hover:border-blue-400 hover:shadow-sm',
                                dragging && 'opacity-40 scale-95',
                                justMoved &&
                                  'ring-2 ring-green-400 border-green-300',
                                !dragging && !justMoved && 'border-gray-200'
                              )}
                            >
                              {busy && (
                                <div className="absolute inset-0 bg-white/70 flex items-center justify-center rounded-lg z-10">
                                  <Loader2 className="w-5 h-5 animate-spin text-blue-600" />
                                </div>
                              )}
                              <div className="flex items-start gap-2">
                                <GripVertical className="w-4 h-4 text-gray-300 group-hover:text-gray-400 shrink-0 mt-0.5" />
                                <div className="min-w-0 flex-1">
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
                                        {o.customer_name ||
                                          o.customer ||
                                          'Walk-in'}
                                      </div>
                                    </div>
                                    <div className="text-right shrink-0">
                                      <div className="font-bold text-gray-900">
                                        {formatCurrency(o.grand_total)}
                                      </div>
                                      <div className="text-[11px] text-blue-600 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 justify-end mt-0.5">
                                        <Receipt className="w-3 h-3" /> Open &amp; pay
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
                                        <ClipboardList className="w-3 h-3" /> No
                                        items
                                      </li>
                                    )}
                                  </ul>
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ))}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default Waiters;
