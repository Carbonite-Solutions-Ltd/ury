import { useCallback, useEffect, useMemo, useState } from 'react';
import { Calendar, FileText, Users, X } from 'lucide-react';
import { cn } from '../lib/utils';
import { Button } from './ui';
import { getOrderStatusTypes, OrderStatusType } from '../data/order-types';
import { usePOSStore } from '../store/pos-store';
import { useRootStore } from '../store/root-store';
import { canSeeAllTerminalOrders, isWaiterOnly } from '../lib/role-utils';
import { getPendingKotCount } from '../lib/invoice-api';
import { getIncomingTransferCount } from '../lib/transfer-api';

interface OrderStatusSidebarProps {
  disabled?: boolean;
  selectedStatus: OrderStatusType;
  setSelectedStatus: (status: OrderStatusType) => void;
  getStatusCount?: (status: OrderStatusType) => number;
  /**
   * Version counter the parent bumps whenever an order list refresh
   * should also re-poll the pending-KOT badge (e.g. after firing held
   * KOTs via the Print Invoice button). Undefined means "ignore". The
   * sidebar also polls on its own every 15s so the badge never gets
   * stale for longer than a small window.
   */
  refreshVersion?: number;
  /** Drawer state on < lg (below lg it's a slide-in drawer; lg+ static). */
  open?: boolean;
  /** Close the drawer (< lg). */
  onClose?: () => void;
}

const todayIso = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const OrderStatusSidebar = ({
  disabled,
  selectedStatus,
  setSelectedStatus,
  refreshVersion,
  open = false,
  onClose,
}: OrderStatusSidebarProps) => {
  const { posProfile, terminalName } = usePOSStore();
  const {
    user,
    selectedDate,
    setSelectedDate,
    resetSelectedDateToToday,
    cashierFilter,
    setCashierFilter,
    cashierUsers,
    fetchCashierUsers,
  } = useRootStore();

  const waiterMode = useMemo(() => isWaiterOnly(user), [user]);

  // Get the appropriate status types based on POS profile settings.
  // Waiters get the trimmed set (Pending / Paid).
  const statusTypes = getOrderStatusTypes(
    posProfile?.view_all_status,
    posProfile?.paid_limit,
    posProfile?.custom_ihotel_enabled,
    posProfile?.custom_max_invoice_transfers,
    waiterMode
  );

  // The global default status is "Draft", which a waiter's trimmed set
  // doesn't include — so on first load a waiter would land on an empty
  // filter. Snap her to the first available status (Pending) when the
  // current one isn't in her list. 2026-07-15.
  useEffect(() => {
    if (statusTypes.length === 0) return;
    const values = statusTypes.map((s) => s.value);
    if (!values.includes(selectedStatus)) {
      setSelectedStatus(statusTypes[0].value as OrderStatusType);
    }
  }, [statusTypes, selectedStatus, setSelectedStatus]);

  // Shown to CASHIERS too as of 2026-08-06, not just captains. A cashier
  // needs to pick a waiter and see what that waiter is running in order
  // to settle their tables. What they may pick is trimmed server-side:
  // get_cashier_users_for_terminal returns every waiter but only the
  // cashier themselves, and _resolve_orders_scope enforces the same rule
  // so a hand-crafted request cannot widen it. Waiters are excluded --
  // they already only ever see their own orders.
  const showCashierFilter = useMemo(
    () => canSeeAllTerminalOrders(user) || !isWaiterOnly(user),
    [user]
  );
  const canPickOtherCashiers = useMemo(
    () => canSeeAllTerminalOrders(user),
    [user]
  );

  const [pendingKotCount, setPendingKotCount] = useState<number>(0);
  const [incomingCount, setIncomingCount] = useState<number>(0);

  const refreshPendingCount = useCallback(async () => {
    const count = await getPendingKotCount(
      terminalName,
      selectedDate,
      cashierFilter
    );
    setPendingKotCount(count);
  }, [terminalName, selectedDate, cashierFilter]);

  const transfersEnabled = (posProfile?.custom_max_invoice_transfers ?? 0) > 0;
  const refreshIncomingCount = useCallback(async () => {
    if (!transfersEnabled) {
      setIncomingCount(0);
      return;
    }
    const count = await getIncomingTransferCount();
    setIncomingCount(count);
  }, [transfersEnabled]);

  // Poll the pending-KOT + incoming-transfer counts on mount, when the
  // date/terminal changes, when the parent tells us to refresh, and on a
  // 15s timer as a safety net. 15s balances "fresh enough to trust"
  // against "not hammering the DB".
  useEffect(() => {
    refreshPendingCount();
    refreshIncomingCount();
    const interval = setInterval(() => {
      refreshPendingCount();
      refreshIncomingCount();
    }, 15000);
    return () => clearInterval(interval);
  }, [refreshPendingCount, refreshIncomingCount, refreshVersion]);

  // Lazy-load the cashier list once when the captain mounts the page.
  useEffect(() => {
    if (showCashierFilter && cashierUsers.length === 0) {
      fetchCashierUsers();
    }
  }, [showCashierFilter, cashierUsers.length, fetchCashierUsers]);

  const today = todayIso();
  const isToday = selectedDate === today;

  return (
    <div
      className={cn(
        'bg-white border-r border-gray-200 h-full flex flex-col z-40',
        // lg+: static left column, always visible.
        'lg:static lg:w-64 lg:translate-x-0 lg:shadow-none',
        // < lg: slide-in drawer from the left (absolute, so it stays inside
        // the Orders area and the parent's overflow-hidden clips it when
        // closed), toggled by the burger icon.
        'absolute inset-y-0 left-0 w-72 max-w-[80vw] transition-transform duration-200',
        open ? 'translate-x-0 shadow-2xl' : '-translate-x-full lg:translate-x-0',
        disabled && 'opacity-50 pointer-events-none'
      )}
    >
      {/* Drawer header with a close button — only on the < lg drawer. */}
      <div className="lg:hidden flex items-center justify-between px-4 py-3 border-b border-gray-200 shrink-0">
        <span className="text-sm font-semibold text-gray-900">Filters</span>
        <button
          type="button"
          aria-label="Close filters"
          onClick={onClose}
          className="inline-flex items-center justify-center rounded-md p-2 -mr-2 text-gray-600 hover:bg-gray-100"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      <nav className="flex-1 p-6 overflow-y-auto space-y-4">
        {/* ───── Order Status ─────
            No card wrapper here (unlike the other sections) so the full
            sidebar width is available for the longer labels like
            "Incoming Transfers" and "Pending KOTs". */}
        <div>
          <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3 px-1">
            Order Status
          </h2>

          <div className="space-y-1">
            {statusTypes.map((status) => {
              const isPendingKots = status.value === 'Pending KOTs';
              const isIncoming = status.value === 'Incoming Transfers';
              const badgeCount = isPendingKots
                ? pendingKotCount
                : isIncoming
                ? incomingCount
                : 0;
              const hasBadge = (isPendingKots || isIncoming) && badgeCount > 0;
              return (
                <Button
                  key={status.value}
                  onClick={() => setSelectedStatus(status.value as OrderStatusType)}
                  variant="ghost"
                  className={cn(
                    'w-full flex items-center justify-between px-3 py-2.5 text-sm font-medium transition-all duration-200 group relative',
                    selectedStatus === status.value
                      ? 'bg-white text-gray-900 shadow-sm font-semibold'
                      : 'text-gray-700 hover:bg-white/60 hover:text-gray-900'
                  )}
                  disabled={disabled}
                >
                  {selectedStatus === status.value && (
                    <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-blue-600 rounded-r-full" />
                  )}
                  <div className="flex items-center gap-3 ml-1">
                    <FileText
                      className={cn(
                        'w-4 h-4',
                        hasBadge
                          ? isIncoming
                            ? 'text-indigo-500'
                            : 'text-orange-500'
                          : 'text-gray-500'
                      )}
                    />
                    <span>{status.label}</span>
                  </div>
                  {hasBadge && (
                    <span
                      className={cn(
                        'min-w-[1.5rem] px-1.5 py-0.5 text-xs font-bold rounded-full text-white',
                        isIncoming ? 'bg-indigo-500' : 'bg-orange-500'
                      )}
                      title={
                        isIncoming
                          ? `${badgeCount} order${
                              badgeCount === 1 ? '' : 's'
                            } offered to you`
                          : `${badgeCount} order${
                              badgeCount === 1 ? '' : 's'
                            } with un-printed KOT`
                      }
                    >
                      {badgeCount}
                    </span>
                  )}
                </Button>
              );
            })}
          </div>
        </div>

        {/* ───── Posting Date ───── */}
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
          <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3 px-1">
            Posting Date
          </h2>

          <div className="relative">
            <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
            <input
              type="date"
              value={selectedDate}
              onChange={(e) => {
                if (e.target.value) {
                  setSelectedDate(e.target.value);
                }
              }}
              max={today}
              disabled={disabled}
              className="w-full pl-9 pr-3 py-2 text-sm bg-white border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:opacity-50"
            />
          </div>

          <Button
            onClick={() => resetSelectedDateToToday()}
            variant="ghost"
            disabled={disabled || isToday}
            className={cn(
              'w-full mt-2 text-xs',
              isToday
                ? 'text-gray-400 cursor-not-allowed'
                : 'text-blue-600 hover:bg-blue-50'
            )}
          >
            {isToday ? 'Showing Today' : 'Reset to Today'}
          </Button>
        </div>

        {/* ───── Staff filter ───── */}
        {showCashierFilter && (
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
            <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3 px-1">
              {canPickOtherCashiers ? 'Cashier' : 'Staff'}
            </h2>

            <div className="relative">
              <Users className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
              <select
                value={cashierFilter}
                onChange={(e) => setCashierFilter(e.target.value)}
                disabled={disabled}
                className="w-full pl-9 pr-3 py-2 text-sm bg-white border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:opacity-50 appearance-none cursor-pointer"
              >
                <option value="mine">My Orders</option>
                {/* "All Staff" and the cashier list are captain-only. The
                    backend would downgrade them to "mine" for a cashier
                    anyway, and an option that silently does something
                    else is worse than one that isn't offered. */}
                {canPickOtherCashiers && <option value="all">All Staff</option>}
                {canPickOtherCashiers &&
                  cashierUsers.some((u) => u.kind !== 'waiter') && (
                  <optgroup label="Pick a Cashier">
                    {cashierUsers
                      .filter((u) => u.kind !== 'waiter')
                      .map((u) => (
                        <option key={u.user} value={u.user}>
                          {u.full_name || u.user}
                        </option>
                      ))}
                  </optgroup>
                )}
                {cashierUsers.some((u) => u.kind === 'waiter') && (
                  <optgroup label="Pick a Waiter">
                    {cashierUsers
                      .filter((u) => u.kind === 'waiter')
                      .map((u) => (
                        <option key={u.user} value={u.user}>
                          {u.full_name || u.user}
                        </option>
                      ))}
                  </optgroup>
                )}
              </select>
            </div>
          </div>
        )}
      </nav>
    </div>
  );
};

export default OrderStatusSidebar;
