import { useEffect, useMemo } from 'react';
import { Calendar, FileText, Users } from 'lucide-react';
import { cn } from '../lib/utils';
import { Button } from './ui';
import { getOrderStatusTypes, OrderStatusType } from '../data/order-types';
import { usePOSStore } from '../store/pos-store';
import { useRootStore } from '../store/root-store';
import { canSeeAllTerminalOrders } from '../lib/role-utils';

interface OrderStatusSidebarProps {
  disabled?: boolean;
  selectedStatus: OrderStatusType;
  setSelectedStatus: (status: OrderStatusType) => void;
  getStatusCount?: (status: OrderStatusType) => number;
}

const todayIso = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const OrderStatusSidebar = ({
  disabled,
  selectedStatus,
  setSelectedStatus,
}: OrderStatusSidebarProps) => {
  const { posProfile } = usePOSStore();
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

  // Get the appropriate status types based on POS profile settings
  const statusTypes = getOrderStatusTypes(
    posProfile?.view_all_status,
    posProfile?.paid_limit
  );

  const showCashierFilter = useMemo(
    () => canSeeAllTerminalOrders(user),
    [user]
  );

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
        'w-64 bg-white border-r border-gray-200 h-full flex flex-col',
        disabled && 'opacity-50 pointer-events-none'
      )}
    >
      <nav className="flex-1 p-6 overflow-y-auto space-y-4">
        {/* ───── Order Status ───── */}
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
          <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3 px-1">
            Order Status
          </h2>

          <div className="space-y-1">
            {statusTypes.map((status) => (
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
                  <FileText className="w-4 h-4 text-gray-500" />
                  <span>{status.label}</span>
                </div>
              </Button>
            ))}
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

        {/* ───── Cashier filter (captain/manager/admin only) ───── */}
        {showCashierFilter && (
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
            <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3 px-1">
              Cashier
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
                <option value="all">All Cashiers</option>
                {cashierUsers.length > 0 && (
                  <optgroup label="Pick a Cashier">
                    {cashierUsers.map((u) => (
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
