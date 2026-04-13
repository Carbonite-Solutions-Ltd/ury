import React, { useEffect, useMemo, useRef } from 'react';
import {
  Clock,
  User,
  UserCheck,
  Receipt,
  Printer,
  Pencil,
  X,
  CheckCircle,
  LayoutGrid,
  List as ListIcon,
  GitMerge,
  Undo2,
  RotateCcw,
  BedDouble,
} from 'lucide-react';
import { Badge, Button, Card, CardContent } from '../components/ui';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../components/ui/dialog';
import { showToast } from '../components/ui/toast';
import OrderStatusSidebar from '../components/OrderStatusSidebar';
import { useRootStore } from '../store/root-store';
import { cn, formatCurrency } from '../lib/utils';
import { Spinner } from '../components/ui/spinner';
import { Textarea } from '../components/ui/textarea';
import { usePOSStore } from '../store/pos-store';
import { useNavigate } from 'react-router-dom';
import PaymentDialog from '../components/PaymentDialog';
import ReturnDialog from '../components/ReturnDialog';
import { printOrder } from '../lib/print';
import { call } from '../lib/frappe-sdk';
import type { POSInvoice } from '../store/slices/orders-slice';
import {
  canMergeOrders,
  canReprintInvoice,
  canReturnOrders,
} from '../lib/role-utils';
import {
  reversePosReturn,
  type ReturnResult,
} from '../lib/invoice-api';
import { extractFrappeServerError } from '../lib/utils';
import '../components/ui/merge-mode.css';

const todayIso = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

// "Apr 9, 11:00 AM" when the date is today; full date+time otherwise.
// Keeps the list dense for the common (today) case but stays unambiguous
// when the user is browsing yesterday or a date months back.
const formatOrderDateTime = (date: string, time: string): string => {
  const dt = new Date(`${date} ${time}`);
  if (Number.isNaN(dt.getTime())) return '';
  const isToday = date === todayIso();
  const opts: Intl.DateTimeFormatOptions = isToday
    ? { hour: 'numeric', minute: 'numeric', hour12: true }
    : { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: 'numeric', hour12: true };
  return dt.toLocaleString('en-US', opts);
};

const formatTimeOnly = (date: string, time: string): string => {
  const dt = new Date(`${date} ${time}`);
  if (Number.isNaN(dt.getTime())) return '';
  return dt.toLocaleString('en-US', { hour: 'numeric', minute: 'numeric', hour12: true });
};

const getOrderTotal = (order: POSInvoice): number =>
  order.rounded_total || order.grand_total || 0;

const getBadgeVariant = (status: string) => {
  switch (status) {
    case 'Draft':
    case 'Unbilled':
      return 'secondary';
    case 'Recently Paid':
    case 'Paid':
    case 'Consolidated':
      return 'default';
    case 'Return':
      return 'destructive';
    default:
      return 'default';
  }
};

export default function Orders() {
  const {
    orders,
    orderLoading,
    error,
    selectedStatus,
    pagination,
    selectedOrder,
    selectedOrderItems,
    selectedOrderTaxes,
    selectedOrderLoading,
    selectedOrderError,
    fetchOrders,
    setSelectedStatus,
    goToNextPage,
    goToPreviousPage,
    selectOrder,
    clearSelectedOrder,
    orderSearchQuery,
    selectedDate,
    resetSelectedDateToToday,
    viewMode,
    setViewMode,
    hydrateViewMode,
    cashierFilter,
    user,
    mergeMode,
    mergeSelection,
    mergeLoading,
    selectedOrderMergeLog,
    enterMergeMode,
    exitMergeMode,
    toggleMergeSelection,
    mergeSelectedOrders,
    unmergeOrder,
  } = useRootStore();

  const posStore = usePOSStore();
  const navigate = useNavigate();
  const mounted = useRef(false);
  const [cancelDialogOpen, setCancelDialogOpen] = React.useState(false);
  const [cancelReason, setCancelReason] = React.useState('');
  const [cancelLoading, setCancelLoading] = React.useState(false);
  const [editLoading, setEditLoading] = React.useState(false);
  const [showPaymentDialog, setShowPaymentDialog] = React.useState(false);
  const [isPrinting, setIsPrinting] = React.useState(false);
  const [showReturnDialog, setShowReturnDialog] = React.useState(false);
  const [reverseLoading, setReverseLoading] = React.useState(false);

  // Hydrate the per-user view-mode preference once we know who's logged
  // in. The slice's default ('card') is overridden if the user's last
  // session set it to 'list'.
  useEffect(() => {
    if (user?.name) {
      hydrateViewMode(user.name);
    }
  }, [user?.name, hydrateViewMode]);

  useEffect(() => {
    fetchOrders();
  }, [fetchOrders]);

  useEffect(() => {
    // Skip the first run because the mount-time fetchOrders effect
    // above has already issued the initial request.
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    fetchOrders();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderSearchQuery]);

  // Show the cashier column only when the captain has flipped the scope
  // off "mine" — otherwise every row would say the same name.
  const showCashierColumn = useMemo(
    () => cashierFilter !== 'mine',
    [cashierFilter]
  );

  const canMerge = useMemo(
    () => canMergeOrders(user, posStore.posProfile),
    [user, posStore.posProfile]
  );

  const canReprint = useMemo(() => canReprintInvoice(user), [user]);

  const canReturn = useMemo(
    () => canReturnOrders(user, posStore.posProfile),
    [user, posStore.posProfile]
  );

  // Treat a POS Invoice as a "Return document" when its custom_order_status
  // carries the Return label OR ERPNext's native `is_return` flag is set.
  // The Orders page currently reads from the `status` column (which is
  // "Return" for negative-qty invoices), plus we peek at `is_return` via
  // a future-proofing check on the payload.
  const isReturnDoc = (order: POSInvoice | null): boolean => {
    if (!order) return false;
    return order.status === 'Return' ||
      (order as any).is_return === 1 ||
      (order as any).is_return === true;
  };

  const handleReturned = async (_result: ReturnResult) => {
    setShowReturnDialog(false);
    showToast.success('Return processed');
    await fetchOrders();
    clearSelectedOrder();
  };

  const handleReverseReturn = async () => {
    if (!selectedOrder) return;
    if (!isReturnDoc(selectedOrder)) return;
    setReverseLoading(true);
    try {
      await reversePosReturn(selectedOrder.name);
      showToast.success('Return reversed');
      await fetchOrders();
      clearSelectedOrder();
    } catch (err) {
      const parsed = extractFrappeServerError(err, 'Failed to reverse return.');
      showToast.error({
        title: parsed.title || 'Reverse Failed',
        description: parsed.message,
      });
    } finally {
      setReverseLoading(false);
    }
  };

  // An order is mergeable in merge mode only if it's still a Draft
  // (unpaid). Returns / Paid / Consolidated rows are dimmed and not
  // selectable. Backend re-validates regardless.
  const isOrderMergeable = (order: POSInvoice) =>
    order.status === 'Draft' &&
    !order.custom_merged_into;

  const handleOrderClick = (order: POSInvoice) => {
    if (mergeMode) {
      if (!isOrderMergeable(order)) return;
      toggleMergeSelection(order.name);
      return;
    }
    selectOrder(order);
  };

  const handleMergeSubmit = async () => {
    const result = await mergeSelectedOrders();
    if (result?.master) {
      showToast.success(`Merged into ${result.master}`);
    } else {
      const errMsg = useRootStore.getState().error;
      if (errMsg) showToast.error(errMsg);
    }
  };

  const handleUnmerge = async () => {
    if (!selectedOrderMergeLog) return;
    const ok = await unmergeOrder(selectedOrderMergeLog.name);
    if (ok) {
      showToast.success('Unmerged successfully');
    } else {
      const errMsg = useRootStore.getState().error;
      if (errMsg) showToast.error(errMsg);
    }
  };

  async function handleCancelOrder() {
    if (!selectedOrder) return;
    if (!cancelReason.trim()) {
      showToast.error('Please enter a reason for cancellation.');
      return;
    }
    setCancelLoading(true);
    try {
      await call.post('ury.ury.doctype.ury_order.ury_order.cancel_order', {
        invoice_id: selectedOrder.name,
        reason: cancelReason
      })
      showToast.success('Order cancelled successfully');
      setCancelDialogOpen(false);
      setCancelReason('');
      clearSelectedOrder();
      fetchOrders();
    } catch (err) {
      showToast.error(err instanceof Error ? err.message : 'Failed to cancel order');
    } finally {
      setCancelLoading(false);
    }
  }

  async function handleEditOrder() {
    if (!selectedOrder) return;
    setEditLoading(true);
    try {
      const res = await fetch(`/api/method/frappe.client.get?doctype=POS+Invoice&name=${selectedOrder.name}`);
      if (!res.ok) throw new Error('Failed to fetch order details');
      const data = await res.json();
      const order = data.message;
      // Fill POS store
      posStore.resetOrderState();
      posStore.setSelectedOrderType(order.order_type);
      posStore.setOrderForUpdate(order.name);
      if (order.restaurant_table) {
        posStore.setSelectedTable(order.restaurant_table, order.custom_restaurant_room || null,true);
      }
      posStore.setSelectedCustomer({ id: order.customer, name: order.customer_name, phone: order.mobile_number });
      // Fill cart
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
      // Redirect to POS page
      navigate('/');
    } catch (err) {
      showToast.error(err instanceof Error ? err.message : 'Failed to edit order');
    } finally {
      setEditLoading(false);
    }
  }

  async function handlePrintOrder() {
    if (!selectedOrder || !posStore.posProfile) return;
    setIsPrinting(true);
    try {
      await printOrder({
        orderId: selectedOrder.name,
        posProfile: posStore.posProfile
      });
      showToast.success(`Printed Successfully`);
      // Locally update selectedOrder.invoice_printed to 1
      if (selectedOrder && typeof selectedOrder === 'object') {
        selectOrder({ ...selectedOrder, invoice_printed: 1 });
      }
      // If order was Unbilled, set to Draft and reload draft orders
      if (selectedStatus === 'Unbilled') {
        showToast.info('Order moved to Draft after printing.');
        setSelectedStatus('Draft');
        fetchOrders();
      }
    } catch (err: any) {
      showToast.error('Print failed: ' + (err?.message || err));
    } finally {
      setIsPrinting(false);
    }
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <p className="text-xl font-semibold text-red-600 mb-2">Failed to load orders</p>
          <p className="text-gray-600">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Left Sidebar - Order Types */}
      <OrderStatusSidebar
        selectedStatus={selectedStatus}
        setSelectedStatus={setSelectedStatus}
      />

      {/* Middle Section - Order list / cards */}
      <div className="flex-1 flex flex-col h-screen overflow-hidden pr-96">
        {/* Top toolbar — switches into a merge bar when merge mode is on */}
        {mergeMode ? (
          <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-3 text-sm text-amber-900">
              <GitMerge className="w-4 h-4" />
              <span className="font-semibold">Merge Mode</span>
              <span className="text-xs text-amber-700">
                Tap two or more draft orders to merge them.{' '}
                <span className="font-medium">{mergeSelection.length}</span>{' '}
                selected
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Button
                onClick={() => exitMergeMode()}
                variant="outline"
                size="sm"
                className="border-amber-300 text-amber-900 hover:bg-amber-100"
                disabled={mergeLoading}
              >
                Cancel
              </Button>
              <Button
                onClick={handleMergeSubmit}
                size="sm"
                className="bg-amber-600 hover:bg-amber-700 text-white disabled:opacity-50"
                disabled={mergeSelection.length < 2 || mergeLoading}
              >
                {mergeLoading ? (
                  <>
                    <Spinner className="w-3.5 h-3.5 mr-1.5" hideMessage />
                    Merging…
                  </>
                ) : (
                  <>
                    <GitMerge className="w-3.5 h-3.5 mr-1.5" />
                    Merge {mergeSelection.length > 1 ? `${mergeSelection.length} orders` : ''}
                  </>
                )}
              </Button>
            </div>
          </div>
        ) : (
          <div className="bg-white border-b border-gray-200 px-4 py-2 flex items-center justify-between shrink-0">
            <div className="text-xs text-gray-500">
              {orders.length > 0 && (
                <span>
                  Showing <span className="font-medium text-gray-700">{orders.length}</span>{' '}
                  {orders.length === 1 ? 'order' : 'orders'}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {canMerge && (
                <Button
                  onClick={() => enterMergeMode()}
                  variant="outline"
                  size="xs"
                  className="border-gray-300 text-gray-700 hover:bg-gray-50"
                >
                  <GitMerge className="w-3.5 h-3.5 mr-1.5" />
                  Merge Orders
                </Button>
              )}
              <div className="inline-flex rounded-md border border-gray-200 bg-white shadow-sm overflow-hidden">
                <button
                  onClick={() => setViewMode('card', user?.name || null)}
                  aria-label="Card view"
                  className={cn(
                    'px-3 py-1.5 inline-flex items-center gap-1.5 text-xs font-medium transition-colors',
                    viewMode === 'card'
                      ? 'bg-gray-100 text-gray-900'
                      : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
                  )}
                >
                  <LayoutGrid className="w-3.5 h-3.5" />
                  Card
                </button>
                <button
                  onClick={() => setViewMode('list', user?.name || null)}
                  aria-label="List view"
                  className={cn(
                    'px-3 py-1.5 inline-flex items-center gap-1.5 text-xs font-medium transition-colors border-l border-gray-200',
                    viewMode === 'list'
                      ? 'bg-gray-100 text-gray-900'
                      : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
                  )}
                >
                  <ListIcon className="w-3.5 h-3.5" />
                  List
                </button>
              </div>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto bg-gray-50 p-4 pb-40">
          {orderLoading ? (
            <div className="flex items-center justify-center h-full">
              <Spinner />
            </div>
          ) : orders.length === 0 ? (
            <div className="text-center mt-16">
              <p className="text-lg font-medium text-gray-700">No orders found</p>
              <p className="text-sm text-gray-500 mt-1">
                No <span className="font-medium">{selectedStatus}</span> orders for{' '}
                <span className="font-medium">{selectedDate}</span> on this terminal.
              </p>
              {selectedDate !== todayIso() && (
                <Button
                  onClick={() => resetSelectedDateToToday()}
                  variant="outline"
                  className="mt-4"
                  size="sm"
                >
                  Reset to Today
                </Button>
              )}
            </div>
          ) : viewMode === 'list' ? (
            <div className="max-w-screen-xl mx-auto bg-white border border-gray-200 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-xs text-gray-600 uppercase">
                  <tr>
                    <th className="text-left px-4 py-2.5 font-medium">Order #</th>
                    <th className="text-left px-3 py-2.5 font-medium">Customer</th>
                    <th className="text-left px-3 py-2.5 font-medium">Type / Table</th>
                    {showCashierColumn && (
                      <th className="text-left px-3 py-2.5 font-medium">Cashier</th>
                    )}
                    <th className="text-left px-3 py-2.5 font-medium">Time</th>
                    <th className="text-right px-3 py-2.5 font-medium">Total</th>
                    <th className="text-right px-4 py-2.5 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {orders.map((order) => {
                    const mergeable = isOrderMergeable(order);
                    const isSelectedForMerge =
                      mergeMode && mergeSelection.includes(order.name);
                    return (
                    <tr
                      key={order.name}
                      onClick={() => handleOrderClick(order)}
                      className={cn(
                        'transition-colors',
                        mergeMode && mergeable && 'cursor-pointer hover:bg-amber-50',
                        mergeMode && !mergeable && 'opacity-40 cursor-not-allowed',
                        !mergeMode && 'cursor-pointer hover:bg-gray-50',
                        !mergeMode &&
                          selectedOrder?.name === order.name &&
                          'bg-blue-50 hover:bg-blue-50',
                        isSelectedForMerge && 'bg-amber-50 hover:bg-amber-100'
                      )}
                    >
                      <td className="px-4 py-2 text-gray-900 font-medium" title={order.name}>
                        <span className="inline-flex items-center gap-2 max-w-[12rem]">
                          {isSelectedForMerge && (
                            <CheckCircle className="w-4 h-4 text-amber-600 shrink-0" />
                          )}
                          <span className="block truncate">{order.name}</span>
                        </span>
                      </td>
                      <td className="px-3 py-2 text-gray-700">
                        {order.customer_name || order.customer}
                      </td>
                      <td className="px-3 py-2 text-gray-600">
                        {order.restaurant_table
                          ? `${order.restaurant_table} · ${order.order_type}`
                          : order.order_type}
                      </td>
                      {showCashierColumn && (
                        <td className="px-3 py-2 text-gray-600">
                          {order.owner_full_name || order.owner || '—'}
                        </td>
                      )}
                      <td className="px-3 py-2 text-gray-500 tabular-nums">
                        {formatTimeOnly(order.posting_date, order.posting_time)}
                      </td>
                      <td className="px-3 py-2 text-right text-gray-900 font-semibold tabular-nums">
                        {formatCurrency(getOrderTotal(order))}
                      </td>
                      <td className="px-4 py-2 text-right">
                        <div className="inline-flex items-center gap-1.5 justify-end flex-wrap">
                          {order.merge_log_name && (
                            <Badge
                              variant="default"
                              className="bg-amber-500 hover:bg-amber-600 text-white flex items-center gap-1 px-2 py-0.5"
                              title={`Merged from ${order.merge_source_count || 0} order${order.merge_source_count === 1 ? '' : 's'} — click to unmerge`}
                            >
                              <GitMerge className="w-3 h-3" />
                              <span className="text-xs">
                                Merged
                                {order.merge_source_count && order.merge_source_count > 0
                                  ? ` +${order.merge_source_count}`
                                  : ''}
                              </span>
                            </Badge>
                          )}
                          {(order.active_return_count ?? 0) > 0 && !order.is_return && (
                            <Badge
                              variant="default"
                              className="bg-orange-500 hover:bg-orange-600 text-white flex items-center gap-1 px-2 py-0.5"
                              title={`${order.active_return_count} active return${order.active_return_count === 1 ? '' : 's'} against this invoice`}
                            >
                              <RotateCcw className="w-3 h-3" />
                              <span className="text-xs">Returned</span>
                            </Badge>
                          )}
                          {order.custom_charge_to_room === 1 && (
                            <Badge
                              variant="default"
                              className="bg-amber-600 hover:bg-amber-700 text-white flex items-center gap-1 px-2 py-0.5"
                              title={`Charged to Room ${order.custom_hotel_room || ''}`}
                            >
                              <BedDouble className="w-3 h-3" />
                              <span className="text-xs">
                                Room {order.custom_hotel_room || ''}
                              </span>
                            </Badge>
                          )}
                          {order.custom_order_status === 'Served' && (
                            <Badge
                              variant="default"
                              className="bg-green-600 hover:bg-green-700 text-white flex items-center gap-1 px-2 py-0.5"
                            >
                              <CheckCircle className="w-3 h-3" />
                              <span className="text-xs">Served</span>
                            </Badge>
                          )}
                          <Badge variant={getBadgeVariant(order.status)}>
                            {order.status}
                          </Badge>
                        </div>
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 max-w-screen-xl mx-auto">
              {orders.map((order, idx) => {
                const mergeable = isOrderMergeable(order);
                const isSelectedForMerge = mergeMode && mergeSelection.includes(order.name);
                return (
                <Card
                  key={order.name}
                  className={cn(
                    'relative p-0 bg-white hover:shadow-md transition-shadow flex flex-col overflow-hidden',
                    selectedOrder?.name === order.name && !mergeMode && 'ring-2 ring-blue-500 shadow-lg',
                    mergeMode && mergeable && `ury-wobble ury-wobble-delay-${idx % 6} cursor-pointer`,
                    mergeMode && !mergeable && 'opacity-40 cursor-not-allowed',
                    !mergeMode && 'cursor-pointer',
                    isSelectedForMerge && 'ring-2 ring-amber-500 shadow-lg'
                  )}
                  onClick={() => handleOrderClick(order)}
                >
                  <CardContent className="p-0 flex flex-col h-full">
                    {isSelectedForMerge && (
                      <div className="absolute top-2 right-2 z-10 flex items-center justify-center w-6 h-6 rounded-full bg-amber-500 text-white shadow">
                        <CheckCircle className="w-4 h-4" />
                      </div>
                    )}
                    <div className="p-3 bg-gray-50 border-b">
                      <h3 className="font-medium text-gray-900 text-sm truncate" title={order.name}>
                        {order.name}
                      </h3>
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="text-xs text-gray-500">
                            {order.restaurant_table ? `Table ${order.restaurant_table} • ` : ''}{order.order_type}
                          </p>
                        </div>
                        <div className="flex items-center gap-1.5 flex-wrap justify-end">
                          {/* Merged badge — set on master invoices that
                              have an Active URY Order Merge Log. Click
                              the card to open the right panel and use
                              the Unmerge button. */}
                          {order.merge_log_name && (
                            <Badge
                              variant="default"
                              className="bg-amber-500 hover:bg-amber-600 text-white flex items-center gap-1 px-2 py-0.5"
                              title={`Merged from ${order.merge_source_count || 0} order${order.merge_source_count === 1 ? '' : 's'} — click to unmerge`}
                            >
                              <GitMerge className="w-3 h-3" />
                              <span className="text-xs">
                                Merged
                                {order.merge_source_count && order.merge_source_count > 0
                                  ? ` +${order.merge_source_count}`
                                  : ''}
                              </span>
                            </Badge>
                          )}
                          {/* Returned badge — count of active (docstatus=1)
                              return invoices written against this one.
                              Hidden on invoices that ARE returns themselves. */}
                          {(order.active_return_count ?? 0) > 0 && !order.is_return && (
                            <Badge
                              variant="default"
                              className="bg-orange-500 hover:bg-orange-600 text-white flex items-center gap-1 px-2 py-0.5"
                              title={`${order.active_return_count} active return${order.active_return_count === 1 ? '' : 's'} against this invoice`}
                            >
                              <RotateCcw className="w-3 h-3" />
                              <span className="text-xs">Returned</span>
                            </Badge>
                          )}
                          {/* Room Charged badge — iHotel charged draft. */}
                          {order.custom_charge_to_room === 1 && (
                            <Badge
                              variant="default"
                              className="bg-amber-600 hover:bg-amber-700 text-white flex items-center gap-1 px-2 py-0.5"
                              title={`Charged to Room ${order.custom_hotel_room || ''}`}
                            >
                              <BedDouble className="w-3 h-3" />
                              <span className="text-xs">
                                Room {order.custom_hotel_room || ''}
                              </span>
                            </Badge>
                          )}
                          {/* Served Badge */}
                          {order.custom_order_status === 'Served' && (
                            <Badge variant="default" className="bg-green-600 hover:bg-green-700 text-white flex items-center gap-1 px-2 py-0.5">
                              <CheckCircle className="w-3 h-3" />
                              <span className="text-xs">Served</span>
                            </Badge>
                          )}
                          {/* Status Badge */}
                          <Badge variant={getBadgeVariant(order.status)}>
                            {order.status}
                          </Badge>
                        </div>
                      </div>
                    </div>

                    {/* Content section - matches MenuCard padding and structure */}
                    <div className="flex-1 p-3 flex flex-col">
                      <div>
                        <p className="text-sm text-gray-900">
                          {order.customer_name || order.customer}
                        </p>
                      </div>

                      {/* Cashier — only when the captain has flipped the scope off "mine" */}
                      {showCashierColumn && (
                        <div className="flex items-center gap-2 text-xs text-gray-500 mt-1">
                          <UserCheck className="w-3.5 h-3.5" />
                          <span>{order.owner_full_name || order.owner}</span>
                        </div>
                      )}

                      <div className="flex items-center gap-2 text-xs text-gray-500 mt-1">
                        <Clock className="w-3.5 h-3.5" />
                        <span>{formatOrderDateTime(order.posting_date, order.posting_time)}</span>
                      </div>

                      {/* Total - pushed to bottom like MenuCard */}
                      <div className="mt-auto pt-2">
                        <span className="text-sm font-semibold text-gray-900 tabular-nums">
                          {formatCurrency(getOrderTotal(order))}
                        </span>
                      </div>
                    </div>
                  </CardContent>
                </Card>
                );
              })}
            </div>
          )}
          {/* Pagination Controls */}
          {!orderLoading && (
            <div className="py-4">
              <div className="flex justify-center items-center gap-x-4 max-w-screen-xl mx-auto">
                <Button
                  onClick={goToPreviousPage}
                  disabled={pagination.currentPage === 1}
                  variant="outline"
                  className='w-20'
                  size="xs"
                >
                  Previous
                </Button>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">
                    Page {pagination.currentPage}
                  </span>
                </div>
                <Button
                  onClick={goToNextPage}
                  disabled={!pagination.hasNextPage}
                  variant="outline"
                  className='w-20'
                  size="xs"
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Right Section - Order Details */}
      <div className="w-96 bg-white border-l border-gray-200 flex flex-col h-[calc(100vh-4rem)] fixed right-0 z-10">
        {!selectedOrder ? (
          <div className="text-center h-full flex flex-col items-center justify-center text-gray-500 p-6">
            <p className="text-lg font-medium mb-2">Select an order to view details</p>
            <p className="text-sm">Click on any order card to view its details</p>
          </div>
        ) : selectedOrderLoading ? (
          <div className="flex items-center justify-center h-full">
            <Spinner />
          </div>
        ) : selectedOrderError ? (
          <div className="text-center h-full flex flex-col items-center justify-center text-red-500 p-6">
            <p className="text-lg font-medium mb-2">Failed to load order details</p>
            <p className="text-sm">{selectedOrderError}</p>
          </div>
        ) : (
          <>
            {/* Fixed Header */}
            <div className="sticky top-0 left-0 right-0 z-20 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between min-h-[64px]">
              <h2
                className="text-xl font-semibold text-gray-900 truncate max-w-[10rem]"
                title={selectedOrder.name}
              >
                {selectedOrder.name}
              </h2>
              <div className="flex items-center gap-2">
                {/* Only show edit and cancel buttons for Draft, Unbilled, and Recently Paid orders */}
                {(selectedOrder.status === 'Draft' || selectedOrder.status === 'Unbilled' || selectedOrder.status === 'Recently Paid') && (
                  <>
                    <button
                      type="button"
                      className="inline-flex items-center justify-center rounded-md p-2 bg-gray-100 hover:bg-gray-200 text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      aria-label="Edit order"
                      onClick={handleEditOrder}
                      disabled={editLoading}
                    >
                      <Pencil className="w-4 h-4" />
                      {editLoading && <span className="ml-2 text-xs">Loading...</span>}
                    </button>
                    <button
                      type="button"
                      className="inline-flex items-center justify-center rounded-md p-2 bg-gray-100 hover:bg-gray-200 text-red-600 focus:outline-none focus:ring-2 focus:ring-red-500"
                      aria-label="Cancel order"
                      onClick={() => setCancelDialogOpen(true)}
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </>
                )}
                {/* Served Badge in Header */}
                {selectedOrder.custom_order_status === 'Served' && (
                  <Badge variant="default" className="bg-green-600 hover:bg-green-700 text-white flex items-center gap-1">
                    <CheckCircle className="w-3.5 h-3.5" />
                    <span>Served</span>
                  </Badge>
                )}
                {/* Returned Badge in Header — when this invoice has
                    any active returns written against it. */}
                {(selectedOrder.active_return_count ?? 0) > 0 &&
                  !selectedOrder.is_return && (
                    <Badge
                      variant="default"
                      className="bg-orange-500 hover:bg-orange-600 text-white flex items-center gap-1"
                      title={`${selectedOrder.active_return_count} active return${selectedOrder.active_return_count === 1 ? '' : 's'}`}
                    >
                      <RotateCcw className="w-3.5 h-3.5" />
                      <span>Returned</span>
                    </Badge>
                  )}
                {/* Room Charged badge — iHotel charged draft. */}
                {selectedOrder.custom_charge_to_room === 1 && (
                  <Badge
                    variant="default"
                    className="bg-amber-600 hover:bg-amber-700 text-white flex items-center gap-1"
                    title={`Charged to Room ${selectedOrder.custom_hotel_room || ''}`}
                  >
                    <BedDouble className="w-3.5 h-3.5" />
                    <span>Room {selectedOrder.custom_hotel_room || ''}</span>
                  </Badge>
                )}
                <Badge variant={getBadgeVariant(selectedOrder.status)}>
                  {selectedOrder.status}
                </Badge>
              </div>
            </div>
            {/* Cancel Order Dialog */}
            <Dialog open={cancelDialogOpen} onOpenChange={setCancelDialogOpen}>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Cancel Order</DialogTitle>
                  <DialogDescription>
                    Please provide a reason for cancelling this order.
                  </DialogDescription>
                </DialogHeader>
                <div className="px-6 mb-3">
                <Textarea
                  placeholder="Enter cancel reason"
                  value={cancelReason}
                  onChange={e => setCancelReason(e.target.value)}
                  disabled={cancelLoading}
                  autoFocus
                />
                </div>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setCancelDialogOpen(false)} disabled={cancelLoading}>
                    Close
                  </Button>
                  <Button variant="danger" onClick={handleCancelOrder} disabled={cancelLoading}>
                    {cancelLoading ? 'Cancelling...' : 'Confirm Cancel'}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
            {/* Scrollable Content Area */}
            <div className="flex-1 overflow-y-auto p-6 pb-40">
              {/* Order Header (now only info, not name/buttons) */}
              <div className="mb-6">
                {/* Two-column Order Info */}
                <div className="grid grid-cols-2 gap-4">
                  {/* First column: customer and time */}
                  <div className="space-y-3">
                    <div className="flex items-center gap-3 text-sm">
                      <User className="w-4 h-4 text-gray-500" />
                      <span className="text-gray-900 font-medium">
                        {selectedOrder.customer_name || selectedOrder.customer}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-sm">
                      <Clock className="w-4 h-4 text-gray-500" />
                      <span className="text-gray-600">{formatOrderDateTime(selectedOrder.posting_date, selectedOrder.posting_time)}</span>
                    </div>
                  </div>
                  {/* Second column: waiter and table */}
                  <div className="space-y-3">
                    <div className="flex items-center gap-3 text-sm">
                      <UserCheck className="w-4 h-4 text-gray-500" />
                      <span className="text-gray-600">{selectedOrder.waiter}</span>
                    </div>
                    {selectedOrder.restaurant_table && (
                      <div className="flex items-center gap-3 text-sm">
                        <Receipt className="w-4 h-4 text-gray-500" />
                        <span className="text-gray-600">{selectedOrder.restaurant_table}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Order Items */}
              <div className="mb-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Order Items</h3>
                <div className="space-y-3">
                  {selectedOrderItems.map((item, index) => (
                    <div key={index} className="flex justify-between items-start py-2 border-b border-gray-100">
                      <div className="flex-1">
                        <p className="text-sm font-medium text-gray-900">{item.item_name}</p>
                        <p className="text-xs text-gray-500">Qty: {item.qty}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-semibold text-gray-900">
                          {formatCurrency(item.amount)}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Taxes */}
              {selectedOrderTaxes.length > 0 && (
                <div className="mb-6">
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">Taxes & Charges</h3>
                  <div className="space-y-2">
                    {selectedOrderTaxes.map((tax, index) => (
                      <div key={index} className="flex justify-between items-center py-1">
                        <span className="text-sm text-gray-600">{tax.description}</span>
                        <span className="text-sm font-medium text-gray-900">
                          {formatCurrency(tax.rate)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Unmerge banner — shown when this invoice is the master
                of an Active URY Order Merge Log AND it's still unpaid. */}
            {selectedOrderMergeLog &&
              selectedOrder.status === 'Draft' && (
                <div className="border-t border-amber-200 bg-amber-50 px-6 py-3 sticky bottom-[88px] left-0 right-0 z-10">
                  <div className="flex items-center gap-3">
                    <GitMerge className="w-4 h-4 text-amber-700 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-semibold text-amber-900">
                        Merged from {selectedOrderMergeLog.source_count}{' '}
                        {selectedOrderMergeLog.source_count === 1
                          ? 'order'
                          : 'orders'}
                      </p>
                      <p className="text-[11px] text-amber-700 truncate">
                        by {selectedOrderMergeLog.merged_by_full_name || selectedOrderMergeLog.merged_by}
                      </p>
                    </div>
                    <Button
                      onClick={handleUnmerge}
                      variant="outline"
                      size="xs"
                      disabled={mergeLoading}
                      className="border-amber-300 text-amber-900 hover:bg-amber-100 shrink-0"
                    >
                      {mergeLoading ? (
                        <Spinner className="w-3 h-3" hideMessage />
                      ) : (
                        <>
                          <Undo2 className="w-3 h-3 mr-1" />
                          Unmerge
                        </>
                      )}
                    </Button>
                  </div>
                </div>
              )}

            {/* Sticky Bottom Section - Single Row: Print | Payment | Total */}
            <div className="border-t border-gray-200 p-6 bg-gray-50 sticky bottom-0 left-0 right-0 z-10">
              <div className="flex items-center gap-3 w-full">
                {/* Print Icon Button — hidden after first print for cashiers.
                    Captains / Managers / Admins can always re-print. */}
                {(selectedOrder.invoice_printed === 0 || canReprint) && (
                  <Button
                    variant="outline"
                    size="icon"
                    className="flex-shrink-0"
                    onClick={handlePrintOrder}
                    aria-label="Print"
                    disabled={isPrinting}
                  >
                    {isPrinting ? <Spinner className="w-5 h-5" hideMessage /> : <Printer className="w-5 h-5" />}
                  </Button>
                )}
                {/* Payment Button - Only show for Draft, Unbilled, and Recently Paid orders.
                    Charged-to-room drafts are excluded — iHotel will post the real
                    accounting when the guest settles their folio at checkout. */}
                {(selectedOrder.status === 'Draft' || selectedOrder.status === 'Unbilled' || selectedOrder.status === 'Recently Paid') &&
                 selectedOrder.custom_charge_to_room !== 1 && (
                  <Button
                    className="flex-1"
                    onClick={() => {
                      if (String(selectedOrder.invoice_printed) === '0') {
                        showToast.error('Please print invoice before making payment');
                        return;
                      }
                      setShowPaymentDialog(true);
                    }}
                  >
                    Payment
                  </Button>
                )}
                {/* Return Button — only for paid invoices (not drafts, not
                    already-returned docs). Permission-gated via the
                    POS Profile's custom_restrict_returns_to_captain
                    flag. Backend re-validates. */}
                {canReturn &&
                  (selectedOrder.status === 'Paid' ||
                    selectedOrder.status === 'Consolidated') &&
                  !isReturnDoc(selectedOrder) && (
                    <Button
                      variant="outline"
                      className="flex-1 border-orange-300 text-orange-700 hover:bg-orange-50"
                      onClick={() => setShowReturnDialog(true)}
                    >
                      <RotateCcw className="w-4 h-4 mr-1.5" />
                      Return
                    </Button>
                  )}
                {/* Undo Return Button — only for submitted return invoices.
                    Cancels the return via ERPNext's native cancel(), which
                    reverses the stock movement and GL entries. */}
                {canReturn && isReturnDoc(selectedOrder) && (
                  <Button
                    variant="outline"
                    className="flex-1 border-amber-300 text-amber-700 hover:bg-amber-50"
                    onClick={handleReverseReturn}
                    disabled={reverseLoading}
                  >
                    {reverseLoading ? (
                      <Spinner className="w-4 h-4 mr-1.5" hideMessage />
                    ) : (
                      <Undo2 className="w-4 h-4 mr-1.5" />
                    )}
                    Undo Return
                  </Button>
                )}
                {/* Total */}
                <span className="ml-auto text-xl font-bold text-gray-900 whitespace-nowrap">
                  {formatCurrency(getOrderTotal(selectedOrder))}
                </span>
              </div>
            </div>
          </>
        )}
      </div>
      {showPaymentDialog && selectedOrder && (
        <PaymentDialog
          onClose={() => setShowPaymentDialog(false)}
          grandTotal={selectedOrder.grand_total}
          roundedTotal={selectedOrder.rounded_total || selectedOrder.grand_total}
          invoice={selectedOrder.name}
          customer={selectedOrder.customer}
          posProfile={posStore.posProfile?.name || ''}
          table={selectedOrder.restaurant_table || null}
          cashier={posStore.posProfile?.cashier || ''}
          owner={posStore.posProfile?.cashier || ''}
          fetchOrders={fetchOrders}
          clearSelectedOrder={clearSelectedOrder}
          hotelRoom={selectedOrder.custom_hotel_room || null}
          hotelRoomLabel={selectedOrder.customer_name || null}
        />
      )}
      {showReturnDialog && selectedOrder && (
        <ReturnDialog
          invoiceName={selectedOrder.name}
          onCancel={() => setShowReturnDialog(false)}
          onReturned={handleReturned}
        />
      )}
    </div>
  );
};