import React, { useEffect, useState } from 'react';
import {
  TrendingUp,
  DollarSign,
  Utensils,
  ShoppingCart,
  Users,
  Printer,
  RefreshCw,
  UserCircle,
  PieChart,
  Trophy,
  ClipboardList,
  GitMerge,
  ArrowRightLeft,
  RotateCcw,
  CreditCard,
  Tag,
} from 'lucide-react';
import { Card, CardContent, Badge } from '../components/ui';
import { Button } from '../components/ui/button';
import { Spinner } from '../components/ui/spinner';
import { DatePicker } from '../components/ui/date-picker';
import { call } from '../lib/frappe-sdk';
import { formatCurrency, cn } from '../lib/utils';
import { showToast } from '../components/ui/toast';
import { usePOSStore } from '../store/pos-store';
import { useRootStore } from '../store/root-store';
import { canSeeAdminReports } from '../lib/role-utils';
import {
  getCourseSales,
  getSalesByCashier,
  getSalesByCategory,
  getTopBottomItems,
  getMyShiftSummary,
  getShiftHistory,
  getShiftSchedule,
  getMergeReport,
  getTransferReport,
  getPaymentSplitsReport,
  type CourseSalesResponse,
  type SalesByCashierResponse,
  type StaffGrouping,
  type SalesByCategoryResponse,
  type TopBottomItemsResponse,
  type ShiftSummaryResponse,
  type ShiftHistoryResponse,
  type ShiftScheduleResponse,
  type MergeReportResponse,
  type TransferReportResponse,
  type PaymentSplitsResponse,
  type DashboardStatsExtended,
} from '../lib/reports-api';

// Legacy alias — kept so downstream local references compile while the
// real response type now carries admin-only extras (order-type mix,
// payment-mode mix, active cashiers). See reports-api.ts.
type DashboardStats = DashboardStatsExtended;

interface DailySaleItem {
  item_name: string;
  qty: number;
  rate: number;
  amount: number;
}

interface SalesInvoice {
  name: string;
  posting_date: string;
  posting_time: string;
  customer_name: string;
  grand_total: number;
  status: string;
  restaurant_table: string | null;
  items_count: number;
  items?: DailySaleItem[];
}

interface PaymentTotal {
  mode_of_payment: string;
  total_amount: number;
}

interface DailySalesResponse {
  invoices: SalesInvoice[];
  payment_totals: PaymentTotal[];
}

type ReportTab =
  | 'dashboard'
  | 'daily-sales'
  | 'my-shift'
  | 'by-cashier'
  | 'covers'
  | 'by-category'
  | 'top-bottom'
  | 'merges'
  | 'transfers'
  | 'splits';

const todayIso = (): string => new Date().toISOString().split('T')[0];
const daysAgoIso = (n: number): string => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().split('T')[0];
};

export default function Reports() {
  const [activeTab, setActiveTab] = useState<ReportTab>('dashboard');
  const [loading, setLoading] = useState(false);
  const [selectedDate, setSelectedDate] = useState(todayIso());
  // Range-based tabs (by-cashier / by-category / top-bottom) share
  // one from/to pair. Default is last 7 days.
  const [fromDate, setFromDate] = useState(daysAgoIso(6));
  const [toDate, setToDate] = useState(todayIso());
  const [dashboardStats, setDashboardStats] = useState<DashboardStats | null>(null);
  const [salesInvoices, setSalesInvoices] = useState<SalesInvoice[]>([]);
  const [paymentTotals, setPaymentTotals] = useState<PaymentTotal[]>([]);
  // Daily Sales "Itemized" toggle — on by default. When on, each sale row
  // expands to show its line items (on screen + in the printout).
  const [itemized, setItemized] = useState(true);
  // New report data slots
  const [shiftSummary, setShiftSummary] =
    useState<ShiftSummaryResponse | null>(null);
  // My Shift sub-toggle: "current" = live open shift, "all" = closed
  // history table for the date range, "schedule" = Mon→Sun roster
  // from URY Shift / HRMS Shift Type. State lives at this level so
  // date-range / week changes refetch the right view.
  const [shiftView, setShiftView] = useState<
    'current' | 'all' | 'schedule'
  >('current');
  const [shiftHistory, setShiftHistory] =
    useState<ShiftHistoryResponse | null>(null);
  const [shiftSchedule, setShiftSchedule] =
    useState<ShiftScheduleResponse | null>(null);
  // Schedule view's week cursor — starts at "today's week" Monday.
  // Set via week-navigator buttons (◀ This Week ▶).
  const mondayOf = (d: Date) => {
    const m = new Date(d);
    const dow = (m.getDay() + 6) % 7; // Sun=0 → Mon=0 layout
    m.setDate(m.getDate() - dow);
    return `${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, '0')}-${String(m.getDate()).padStart(2, '0')}`;
  };
  const [scheduleWeekStart, setScheduleWeekStart] = useState<string>(
    mondayOf(new Date())
  );
  const [staffGrouping, setStaffGrouping] = useState<StaffGrouping>('cashier');
  const [courseSales, setCourseSales] = useState<CourseSalesResponse | null>(null);
  const [salesByCashier, setSalesByCashier] =
    useState<SalesByCashierResponse | null>(null);
  const [salesByCategory, setSalesByCategory] =
    useState<SalesByCategoryResponse | null>(null);
  const [topBottom, setTopBottom] =
    useState<TopBottomItemsResponse | null>(null);
  const [mergeReport, setMergeReport] =
    useState<MergeReportResponse | null>(null);
  const [transferReport, setTransferReport] =
    useState<TransferReportResponse | null>(null);
  const [paymentSplits, setPaymentSplits] =
    useState<PaymentSplitsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { terminalName } = usePOSStore();
  const { user } = useRootStore();
  const isAdmin = canSeeAdminReports(user);

  const isRangeTab =
    activeTab === 'by-cashier' ||
    activeTab === 'covers' ||
    activeTab === 'by-category' ||
    activeTab === 'top-bottom' ||
    activeTab === 'merges' ||
    activeTab === 'transfers' ||
    activeTab === 'splits' ||
    (activeTab === 'my-shift' && shiftView === 'all');
  const isSingleDateTab =
    activeTab === 'dashboard' || activeTab === 'daily-sales';

  useEffect(() => {
    if (activeTab === 'dashboard') {
      fetchDashboardStats();
    } else if (activeTab === 'daily-sales') {
      fetchDailySales();
    } else if (activeTab === 'my-shift') {
      if (shiftView === 'current') fetchShiftSummary();
      else if (shiftView === 'all') fetchShiftHistory();
      else fetchShiftSchedule();
    } else if (activeTab === 'covers') {
      fetchCourseSales();
    } else if (activeTab === 'by-cashier') {
      fetchSalesByCashier();
    } else if (activeTab === 'by-category') {
      fetchSalesByCategory();
    } else if (activeTab === 'top-bottom') {
      fetchTopBottom();
    } else if (activeTab === 'merges') {
      fetchMergeReport();
    } else if (activeTab === 'transfers') {
      fetchTransferReport();
    } else if (activeTab === 'splits') {
      fetchPaymentSplits();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    activeTab,
    selectedDate,
    fromDate,
    toDate,
    terminalName,
    shiftView,
    scheduleWeekStart,
  ]);

  const fetchDashboardStats = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await call.get('ury.ury_pos.api.get_dashboard_stats', {
        date: selectedDate
      });
      setDashboardStats(response.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch dashboard stats');
    } finally {
      setLoading(false);
    }
  };

  const fetchDailySales = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await call.get('ury.ury_pos.api.get_daily_sales', {
        date: selectedDate
      });
      const data = response.message as DailySalesResponse;
      setSalesInvoices(data.invoices || []);
      setPaymentTotals(data.payment_totals || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch daily sales');
    } finally {
      setLoading(false);
    }
  };

  const fetchShiftSummary = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getMyShiftSummary(terminalName);
      setShiftSummary(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch shift summary');
    } finally {
      setLoading(false);
    }
  };

  const fetchShiftHistory = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getShiftHistory({
        from_date: fromDate,
        to_date: toDate,
        terminal: terminalName,
      });
      setShiftHistory(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch shift history');
    } finally {
      setLoading(false);
    }
  };

  const fetchShiftSchedule = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getShiftSchedule(scheduleWeekStart, terminalName);
      setShiftSchedule(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch shift schedule');
    } finally {
      setLoading(false);
    }
  };

  const fetchCourseSales = async () => {
    setLoading(true);
    setError(null);
    try {
      setCourseSales(
        await getCourseSales({
          from_date: fromDate,
          to_date: toDate,
          terminal: terminalName,
        })
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch course sales');
    } finally {
      setLoading(false);
    }
  };

  // Re-fetch when the cashier/waiter switch flips. Without this the
  // toggle would move but keep showing the previous grouping's rows.
  useEffect(() => {
    if (activeTab === 'by-cashier') fetchSalesByCashier();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [staffGrouping]);

  const fetchSalesByCashier = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getSalesByCashier(
        { from_date: fromDate, to_date: toDate, terminal: terminalName },
        staffGrouping
      );
      setSalesByCashier(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch sales by cashier');
    } finally {
      setLoading(false);
    }
  };

  const fetchSalesByCategory = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getSalesByCategory({
        from_date: fromDate,
        to_date: toDate,
        terminal: terminalName,
      });
      setSalesByCategory(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch sales by category');
    } finally {
      setLoading(false);
    }
  };

  const fetchTopBottom = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getTopBottomItems({
        from_date: fromDate,
        to_date: toDate,
        terminal: terminalName,
        limit: 10,
      });
      setTopBottom(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch top/bottom items');
    } finally {
      setLoading(false);
    }
  };

  const fetchMergeReport = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getMergeReport({
        from_date: fromDate,
        to_date: toDate,
        terminal: terminalName,
      });
      setMergeReport(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch merge report');
    } finally {
      setLoading(false);
    }
  };

  const fetchTransferReport = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getTransferReport({
        from_date: fromDate,
        to_date: toDate,
        terminal: terminalName,
      });
      setTransferReport(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch transfer report');
    } finally {
      setLoading(false);
    }
  };

  const fetchPaymentSplits = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getPaymentSplitsReport({
        from_date: fromDate,
        to_date: toDate,
        terminal: terminalName,
      });
      setPaymentSplits(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch payment splits');
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = () => {
    if (activeTab === 'dashboard') fetchDashboardStats();
    else if (activeTab === 'daily-sales') fetchDailySales();
    else if (activeTab === 'my-shift') {
      if (shiftView === 'current') fetchShiftSummary();
      else if (shiftView === 'all') fetchShiftHistory();
      else fetchShiftSchedule();
    }
    else if (activeTab === 'covers') fetchCourseSales();
    else if (activeTab === 'by-cashier') fetchSalesByCashier();
    else if (activeTab === 'by-category') fetchSalesByCategory();
    else if (activeTab === 'top-bottom') fetchTopBottom();
    else if (activeTab === 'merges') fetchMergeReport();
    else if (activeTab === 'transfers') fetchTransferReport();
    else if (activeTab === 'splits') fetchPaymentSplits();
  };

  const handlePrint = () => {
    if (activeTab === 'daily-sales' && salesInvoices.length === 0) {
      showToast.error('No sales data to print');
      return;
    }

    const printWindow = window.open('', '', 'width=800,height=600');
    if (!printWindow) {
      showToast.error('Please allow pop-ups to print');
      return;
    }

    const totalSales = salesInvoices.reduce((sum, inv) => sum + inv.grand_total, 0);
    const formattedDate = new Date(selectedDate).toLocaleDateString('en-US', {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    });

    const printContent = `
      <!DOCTYPE html>
      <html>
      <head>
        <title>Daily Sales Report - ${selectedDate}</title>
        <style>
          * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
          }
          body {
            font-family: Arial, sans-serif;
            padding: 20px;
            font-size: 12px;
          }
          .header {
            text-align: center;
            margin-bottom: 30px;
            border-bottom: 2px solid #333;
            padding-bottom: 15px;
          }
          .header h1 {
            font-size: 24px;
            margin-bottom: 5px;
          }
          .header p {
            color: #666;
            font-size: 14px;
          }
          .summary {
            display: flex;
            justify-content: space-around;
            margin-bottom: 20px;
            padding: 15px;
            background: #f5f5f5;
            border-radius: 8px;
          }
          .summary-item {
            text-align: center;
          }
          .summary-item label {
            display: block;
            color: #666;
            font-size: 11px;
            margin-bottom: 5px;
            text-transform: uppercase;
          }
          .summary-item value {
            display: block;
            font-size: 18px;
            font-weight: bold;
            color: #333;
          }
          .payment-section {
            margin-bottom: 25px;
            padding: 15px;
            background: #f9f9f9;
            border-radius: 8px;
            border: 1px solid #e0e0e0;
          }
          .payment-section h3 {
            font-size: 14px;
            margin-bottom: 12px;
            color: #333;
            text-transform: uppercase;
            letter-spacing: 0.5px;
          }
          .payment-methods {
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
          }
          .payment-method {
            flex: 1;
            min-width: 150px;
            padding: 10px 15px;
            background: white;
            border-radius: 6px;
            border: 1px solid #e0e0e0;
            display: flex;
            justify-content: space-between;
            align-items: center;
          }
          .payment-method-name {
            font-size: 12px;
            color: #666;
            font-weight: 500;
          }
          .payment-method-amount {
            font-size: 16px;
            font-weight: bold;
            color: #2563eb;
          }
          table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
          }
          thead {
            background: #f5f5f5;
          }
          th {
            padding: 10px;
            text-align: left;
            font-weight: bold;
            border-bottom: 2px solid #ddd;
            font-size: 11px;
            text-transform: uppercase;
          }
          td {
            padding: 8px 10px;
            border-bottom: 1px solid #eee;
          }
          tr:hover {
            background: #f9f9f9;
          }
          .text-right {
            text-align: right;
          }
          .font-bold {
            font-weight: bold;
          }
          .total-row {
            background: #f5f5f5;
            font-weight: bold;
          }
          .items-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 10px;
            color: #555;
          }
          .items-table td {
            padding: 2px 6px;
            border-bottom: 1px dotted #eee;
          }
          .footer {
            margin-top: 30px;
            text-align: center;
            color: #666;
            font-size: 10px;
            border-top: 1px solid #ddd;
            padding-top: 10px;
          }
          @media print {
            body {
              padding: 10px;
            }
            .no-print {
              display: none;
            }
          }
        </style>
      </head>
      <body>
        <div class="header">
          <h1>Daily Sales Report</h1>
          <p>${formattedDate}</p>
        </div>

        <div class="summary">
          <div class="summary-item">
            <label>Total Sales</label>
            <value>${formatCurrency(totalSales)}</value>
          </div>
          <div class="summary-item">
            <label>Total Orders</label>
            <value>${salesInvoices.length}</value>
          </div>
          <div class="summary-item">
            <label>Average Order</label>
            <value>${formatCurrency(totalSales / salesInvoices.length || 0)}</value>
          </div>
        </div>

        ${paymentTotals.length > 0 ? `
          <div class="payment-section">
            <h3>Payment Methods Breakdown</h3>
            <div class="payment-methods">
              ${paymentTotals.map(payment => `
                <div class="payment-method">
                  <span class="payment-method-name">${payment.mode_of_payment}</span>
                  <span class="payment-method-amount">${formatCurrency(payment.total_amount)}</span>
                </div>
              `).join('')}
            </div>
          </div>
        ` : ''}

        <table>
          <thead>
            <tr>
              <th>Invoice #</th>
              <th>Time</th>
              <th>Customer</th>
              <th>Table</th>
              <th>Items</th>
              <th>Status</th>
              <th class="text-right">Amount</th>
            </tr>
          </thead>
          <tbody>
            ${salesInvoices.map(invoice => `
              <tr>
                <td>${invoice.name}</td>
                <td>${new Date(invoice.posting_date + ' ' + invoice.posting_time).toLocaleTimeString('en-US', {
                  hour: 'numeric',
                  minute: '2-digit',
                  hour12: true
                })}</td>
                <td>${invoice.customer_name}</td>
                <td>${invoice.restaurant_table || '-'}</td>
                <td>${invoice.items_count}</td>
                <td>${invoice.status}</td>
                <td class="text-right">${formatCurrency(invoice.grand_total)}</td>
              </tr>
              ${itemized && (invoice.items?.length ?? 0) > 0 ? `
                <tr>
                  <td colspan="7" style="padding: 0 10px 10px 28px; border-bottom: 1px solid #eee;">
                    <table class="items-table">
                      ${invoice.items!.map(it => `
                        <tr>
                          <td>${it.qty}&times; ${it.item_name}</td>
                          <td class="text-right">@ ${formatCurrency(it.rate)}</td>
                          <td class="text-right">${formatCurrency(it.amount)}</td>
                        </tr>
                      `).join('')}
                    </table>
                  </td>
                </tr>
              ` : ''}
            `).join('')}
            <tr class="total-row">
              <td colspan="6" class="text-right">TOTAL</td>
              <td class="text-right font-bold">${formatCurrency(totalSales)}</td>
            </tr>
          </tbody>
        </table>

        <div class="footer">
          <p>Generated on ${new Date().toLocaleString()}</p>
          <p>Printed by: ${(window as any).frappe?.session?.user || 'System'}</p>
        </div>

        <script>
          window.onload = function() {
            window.print();
            window.onafterprint = function() {
              window.close();
            };
          };
        </script>
      </body>
      </html>
    `;

    printWindow.document.write(printContent);
    printWindow.document.close();
  };


  return (
    <div className="flex flex-col h-full bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Reports</h1>
            <p className="text-sm text-gray-500 mt-1">View your sales performance and analytics</p>
          </div>
          <div className="flex items-center gap-3">
            {/* Shared branded date pickers — popover + react-day-picker
                calendar, whole component clickable, keyboard-friendly. */}
            {isSingleDateTab && (
              <DatePicker
                value={selectedDate}
                onChange={setSelectedDate}
                max={todayIso()}
              />
            )}

            {isRangeTab && (
              <div className="flex items-center gap-2">
                <DatePicker
                  value={fromDate}
                  onChange={setFromDate}
                  max={toDate || todayIso()}
                />
                <span className="text-xs text-gray-500 font-medium">to</span>
                <DatePicker
                  value={toDate}
                  onChange={setToDate}
                  min={fromDate}
                  max={todayIso()}
                />
              </div>
            )}

            <Button
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              disabled={loading}
            >
              <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </Button>

            {activeTab === 'daily-sales' && (
              <>
                <label className="flex items-center gap-1.5 text-sm text-gray-700 select-none cursor-pointer">
                  <input
                    type="checkbox"
                    checked={itemized}
                    onChange={(e) => setItemized(e.target.checked)}
                    className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  Itemized
                </label>
                <Button
                  variant="default"
                  size="sm"
                  onClick={handlePrint}
                  disabled={salesInvoices.length === 0}
                >
                  <Printer className="w-4 h-4 mr-2" />
                  Print Report
                </Button>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-white border-b border-gray-200">
        <div className="px-6">
          <div className="flex space-x-8 overflow-x-auto">
            <TabButton
              active={activeTab === 'dashboard'}
              onClick={() => setActiveTab('dashboard')}
              icon={<TrendingUp className="w-5 h-5" />}
              label="Dashboard"
            />
            <TabButton
              active={activeTab === 'daily-sales'}
              onClick={() => setActiveTab('daily-sales')}
              icon={<ShoppingCart className="w-5 h-5" />}
              label="Daily Sales"
            />
            <TabButton
              active={activeTab === 'my-shift'}
              onClick={() => setActiveTab('my-shift')}
              icon={<ClipboardList className="w-5 h-5" />}
              label="My Shift"
            />
            {isAdmin && (
              <>
                <TabButton
                  active={activeTab === 'covers'}
                  onClick={() => setActiveTab('covers')}
                  icon={<Utensils className="w-5 h-5" />}
                  label="Covers"
                />
                <TabButton
                  active={activeTab === 'by-cashier'}
                  onClick={() => setActiveTab('by-cashier')}
                  icon={<UserCircle className="w-5 h-5" />}
                  label="Sales by Cashier"
                />
                <TabButton
                  active={activeTab === 'by-category'}
                  onClick={() => setActiveTab('by-category')}
                  icon={<PieChart className="w-5 h-5" />}
                  label="Sales by Category"
                />
                <TabButton
                  active={activeTab === 'top-bottom'}
                  onClick={() => setActiveTab('top-bottom')}
                  icon={<Trophy className="w-5 h-5" />}
                  label="Top / Bottom Items"
                />
                <TabButton
                  active={activeTab === 'merges'}
                  onClick={() => setActiveTab('merges')}
                  icon={<GitMerge className="w-5 h-5" />}
                  label="Merges"
                />
                <TabButton
                  active={activeTab === 'transfers'}
                  onClick={() => setActiveTab('transfers')}
                  icon={<ArrowRightLeft className="w-5 h-5" />}
                  label="Transfers"
                />
                <TabButton
                  active={activeTab === 'splits'}
                  onClick={() => setActiveTab('splits')}
                  icon={<CreditCard className="w-5 h-5" />}
                  label="Payment Splits"
                />
              </>
            )}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {loading ? (
          <div className="flex items-center justify-center h-64">
            <Spinner />
          </div>
        ) : error ? (
          <div className="text-center py-12">
            <p className="text-red-600 font-medium">{error}</p>
          </div>
        ) : activeTab === 'my-shift' ? (
          <MyShiftWrap
            view={shiftView}
            onViewChange={setShiftView}
            summary={shiftSummary}
            history={shiftHistory}
            schedule={shiftSchedule}
            scheduleWeekStart={scheduleWeekStart}
            onWeekChange={setScheduleWeekStart}
          />
        ) : activeTab === 'covers' ? (
          <CoversView report={courseSales} />
        ) : activeTab === 'by-cashier' ? (
          <SalesByCashierView
            report={salesByCashier}
            grouping={staffGrouping}
            onGroupingChange={setStaffGrouping}
          />
        ) : activeTab === 'by-category' ? (
          <SalesByCategoryView report={salesByCategory} />
        ) : activeTab === 'top-bottom' ? (
          <TopBottomView report={topBottom} />
        ) : activeTab === 'merges' ? (
          <MergeReportView report={mergeReport} />
        ) : activeTab === 'transfers' ? (
          <TransferReportView report={transferReport} />
        ) : activeTab === 'splits' ? (
          <PaymentSplitsView report={paymentSplits} />
        ) : activeTab === 'dashboard' ? (
          <div className="max-w-7xl mx-auto space-y-6">
            {/* Scope badge — shows whether numbers are branch-wide (admin)
                or per-cashier. Relies on is_admin flag from the server so
                it stays honest even if the frontend role helper drifts. */}
            {dashboardStats && (
              <div className="flex items-center gap-2 text-sm text-gray-600">
                <Badge
                  variant={dashboardStats.scope === 'branch' ? 'default' : 'secondary'}
                  className="text-xs uppercase"
                >
                  {dashboardStats.scope === 'branch'
                    ? 'Branch-wide'
                    : 'My orders'}
                </Badge>
                <span className="text-xs text-gray-500">
                  {dashboardStats.scope === 'branch'
                    ? 'You are seeing every cashier on this branch.'
                    : 'Only your own rings are included.'}
                </span>
              </div>
            )}

            {/* Stats Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <Card>
                <CardContent className="p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-gray-500">Total Sales</p>
                      <p className="text-2xl font-bold text-gray-900 mt-2">
                        {formatCurrency(dashboardStats?.total_sales || 0)}
                      </p>
                    </div>
                    <div className="w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center">
                      <DollarSign className="w-6 h-6 text-blue-600" />
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-gray-500">Total Orders</p>
                      <p className="text-2xl font-bold text-gray-900 mt-2">
                        {dashboardStats?.total_orders || 0}
                      </p>
                    </div>
                    <div className="w-12 h-12 bg-green-100 rounded-full flex items-center justify-center">
                      <ShoppingCart className="w-6 h-6 text-green-600" />
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-gray-500">Customers</p>
                      <p className="text-2xl font-bold text-gray-900 mt-2">
                        {dashboardStats?.total_customers || 0}
                      </p>
                    </div>
                    <div className="w-12 h-12 bg-purple-100 rounded-full flex items-center justify-center">
                      <Users className="w-6 h-6 text-purple-600" />
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-gray-500">Avg Order Value</p>
                      <p className="text-2xl font-bold text-gray-900 mt-2">
                        {formatCurrency(dashboardStats?.average_order_value || 0)}
                      </p>
                    </div>
                    <div className="w-12 h-12 bg-orange-100 rounded-full flex items-center justify-center">
                      <TrendingUp className="w-6 h-6 text-orange-600" />
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Returns tile — visible to everyone but only interesting when
                the count is non-zero. */}
            {dashboardStats && (dashboardStats.returns_count ?? 0) > 0 && (
              <Card>
                <CardContent className="p-6">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 bg-red-100 rounded-full flex items-center justify-center">
                        <RotateCcw className="w-5 h-5 text-red-600" />
                      </div>
                      <div>
                        <p className="text-sm font-medium text-gray-500">Returns</p>
                        <p className="text-xl font-bold text-gray-900">
                          {dashboardStats.returns_count} ·{' '}
                          <span className="text-red-600">
                            −{formatCurrency(dashboardStats.returns_amount || 0)}
                          </span>
                        </p>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Admin-only dashboard extras */}
            {dashboardStats?.is_admin === 1 && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Order type breakdown */}
                <Card>
                  <CardContent className="p-6">
                    <div className="flex items-center gap-2 mb-4">
                      <Tag className="w-5 h-5 text-gray-500" />
                      <h3 className="text-lg font-semibold text-gray-900">
                        Order Type Breakdown
                      </h3>
                    </div>
                    {(dashboardStats.order_type_breakdown || []).length === 0 ? (
                      <p className="text-sm text-gray-500 italic">
                        No orders yet today.
                      </p>
                    ) : (
                      <div className="space-y-2">
                        {(dashboardStats.order_type_breakdown || []).map((row) => (
                          <div
                            key={row.order_type}
                            className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0"
                          >
                            <div>
                              <p className="font-medium text-gray-900">
                                {row.order_type}
                              </p>
                              <p className="text-xs text-gray-500">
                                {row.count} order{row.count === 1 ? '' : 's'}
                              </p>
                            </div>
                            <p className="font-semibold text-gray-900">
                              {formatCurrency(row.amount)}
                            </p>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* Payment mode breakdown */}
                <Card>
                  <CardContent className="p-6">
                    <div className="flex items-center gap-2 mb-4">
                      <CreditCard className="w-5 h-5 text-gray-500" />
                      <h3 className="text-lg font-semibold text-gray-900">
                        Payment Mode Breakdown
                      </h3>
                    </div>
                    {(dashboardStats.payment_mode_breakdown || []).length === 0 ? (
                      <p className="text-sm text-gray-500 italic">
                        No payments recorded today.
                      </p>
                    ) : (
                      <div className="space-y-2">
                        {(dashboardStats.payment_mode_breakdown || []).map((row) => (
                          <div
                            key={row.mode_of_payment}
                            className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0"
                          >
                            <p className="font-medium text-gray-900">
                              {row.mode_of_payment}
                            </p>
                            <p className="font-semibold text-blue-600">
                              {formatCurrency(row.amount)}
                            </p>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
            )}

            {/* Active cashiers (admin only) */}
            {dashboardStats?.is_admin === 1 &&
              (dashboardStats.active_cashiers || []).length > 0 && (
                <Card>
                  <CardContent className="p-6">
                    <div className="flex items-center gap-2 mb-4">
                      <Users className="w-5 h-5 text-gray-500" />
                      <h3 className="text-lg font-semibold text-gray-900">
                        Active Cashiers Today
                      </h3>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead className="bg-gray-50 border-y border-gray-200">
                          <tr>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                              Cashier
                            </th>
                            <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                              Orders
                            </th>
                            <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                              Total
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-200">
                          {(dashboardStats.active_cashiers || []).map((row) => (
                            <tr key={row.user}>
                              <td className="px-4 py-3">
                                <p className="font-medium text-gray-900">
                                  {row.full_name}
                                </p>
                                <p className="text-xs text-gray-500">{row.user}</p>
                              </td>
                              <td className="px-4 py-3 text-right text-gray-600">
                                {row.invoice_count}
                              </td>
                              <td className="px-4 py-3 text-right font-semibold text-gray-900">
                                {formatCurrency(row.grand_total)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>
              )}

            {/* Top Selling Items */}
            {dashboardStats?.top_selling_items && dashboardStats.top_selling_items.length > 0 && (
              <Card>
                <CardContent className="p-6">
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">Top Selling Items</h3>
                  <div className="space-y-3">
                    {dashboardStats.top_selling_items.map((item, index) => (
                      <div key={index} className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center">
                            <span className="text-sm font-bold text-blue-600">#{index + 1}</span>
                          </div>
                          <div>
                            <p className="font-medium text-gray-900">{item.item_name}</p>
                            <p className="text-sm text-gray-500">{item.quantity} sold</p>
                          </div>
                        </div>
                        <p className="font-bold text-gray-900">{formatCurrency(item.total_amount)}</p>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        ) : (
          <div className="max-w-7xl mx-auto">
            {salesInvoices.length === 0 ? (
              <div className="text-center py-12">
                <ShoppingCart className="w-16 h-16 text-gray-400 mx-auto mb-4" />
                <p className="text-gray-500 text-lg">No sales for this date</p>
                <p className="text-gray-400 text-sm mt-2">Try selecting a different date</p>
              </div>
            ) : (
              <>
                {/* Payment Methods Summary */}
                {paymentTotals.length > 0 && (
                  <Card className="mb-4">
                    <CardContent className="p-6">
                      <h3 className="text-lg font-semibold text-gray-900 mb-4">Payment Methods Breakdown</h3>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        {paymentTotals.map((payment, index) => (
                          <div key={index} className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                            <p className="text-xs text-gray-500 mb-1">{payment.mode_of_payment}</p>
                            <p className="text-xl font-bold text-blue-600">{formatCurrency(payment.total_amount)}</p>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                )}

                {/* Sales Invoices Table */}
                <Card>
                  <CardContent className="p-6">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-lg font-semibold text-gray-900">
                        Sales Invoices ({salesInvoices.length})
                      </h3>
                      <p className="text-sm text-gray-500">
                        Total: {formatCurrency(salesInvoices.reduce((sum, inv) => sum + inv.grand_total, 0))}
                      </p>
                    </div>

                    <div className="overflow-x-auto">
                      <table className="w-full">
                        <thead className="bg-gray-50 border-y border-gray-200">
                          <tr>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Invoice</th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Customer</th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Table</th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Items</th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                            <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Amount</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-200">
                          {salesInvoices.map((invoice) => (
                            <React.Fragment key={invoice.name}>
                            <tr className="hover:bg-gray-50">
                              <td className="px-4 py-3 text-sm font-medium text-gray-900">{invoice.name}</td>
                              <td className="px-4 py-3 text-sm text-gray-600">
                                {new Date(invoice.posting_date + ' ' + invoice.posting_time).toLocaleTimeString('en-US', {
                                  hour: 'numeric',
                                  minute: '2-digit',
                                  hour12: true
                                })}
                              </td>
                              <td className="px-4 py-3 text-sm text-gray-900">{invoice.customer_name}</td>
                              <td className="px-4 py-3 text-sm text-gray-600">
                                {invoice.restaurant_table || '-'}
                              </td>
                              <td className="px-4 py-3 text-sm text-gray-600">{invoice.items_count}</td>
                              <td className="px-4 py-3">
                                <Badge variant={invoice.status === 'Paid' ? 'default' : 'secondary'} className="text-xs">
                                  {invoice.status}
                                </Badge>
                              </td>
                              <td className="px-4 py-3 text-sm font-semibold text-gray-900 text-right">
                                {formatCurrency(invoice.grand_total)}
                              </td>
                            </tr>
                            {itemized && (invoice.items?.length ?? 0) > 0 && (
                              <tr className="bg-gray-50/50">
                                <td colSpan={7} className="px-8 pb-3 pt-0">
                                  <div className="rounded-md border border-gray-200 bg-white divide-y divide-gray-100">
                                    {invoice.items!.map((it, i) => (
                                      <div
                                        key={i}
                                        className="flex items-center justify-between px-3 py-1.5 text-xs text-gray-600"
                                      >
                                        <span className="truncate">
                                          <span className="font-medium text-gray-800">
                                            {it.qty}×
                                          </span>{' '}
                                          {it.item_name}
                                          <span className="text-gray-400">
                                            {' '}@ {formatCurrency(it.rate)}
                                          </span>
                                        </span>
                                        <span className="tabular-nums shrink-0 ml-2 font-medium text-gray-700">
                                          {formatCurrency(it.amount)}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                </td>
                              </tr>
                            )}
                            </React.Fragment>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------
// Shared tab button + per-report sub-components
// ---------------------------------------------------------------

interface TabButtonProps {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}

function TabButton({ active, onClick, icon, label }: TabButtonProps) {
  return (
    <button
      onClick={onClick}
      className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors whitespace-nowrap ${
        active
          ? 'border-blue-500 text-blue-600'
          : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
      }`}
    >
      <div className="flex items-center gap-2">
        {icon}
        <span>{label}</span>
      </div>
    </button>
  );
}

// Wrapper: switches between Current Shift / All Shifts / Schedule
// via a pill toggle at the top of the My Shift tab.
interface MyShiftWrapProps {
  view: 'current' | 'all' | 'schedule';
  onViewChange: (v: 'current' | 'all' | 'schedule') => void;
  summary: ShiftSummaryResponse | null;
  history: ShiftHistoryResponse | null;
  schedule: ShiftScheduleResponse | null;
  scheduleWeekStart: string;
  onWeekChange: (week: string) => void;
}

function MyShiftWrap({
  view,
  onViewChange,
  summary,
  history,
  schedule,
  scheduleWeekStart,
  onWeekChange,
}: MyShiftWrapProps) {
  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-1">
          <button
            onClick={() => onViewChange('current')}
            className={cn(
              'px-3 py-1.5 text-sm font-medium rounded-md transition-colors',
              view === 'current'
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            )}
          >
            Current Shift
          </button>
          <button
            onClick={() => onViewChange('all')}
            className={cn(
              'px-3 py-1.5 text-sm font-medium rounded-md transition-colors',
              view === 'all'
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            )}
          >
            All Shifts
          </button>
          <button
            onClick={() => onViewChange('schedule')}
            className={cn(
              'px-3 py-1.5 text-sm font-medium rounded-md transition-colors',
              view === 'schedule'
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            )}
          >
            Schedule
          </button>
        </div>
        <div className="flex items-center gap-2">
          {view === 'schedule' && (
            <ScheduleWeekNav
              weekStart={scheduleWeekStart}
              onChange={onWeekChange}
              schedule={schedule}
            />
          )}
          {view === 'all' && history && history.shifts.length > 0 && (
            <Button
              variant="default"
              size="sm"
              onClick={() => printShiftHistory(history)}
            >
              <Printer className="w-4 h-4 mr-2" />
              Print Shift Report
            </Button>
          )}
          {view === 'schedule' && schedule && schedule.rows.length > 0 && (
            <Button
              variant="default"
              size="sm"
              onClick={() => printShiftSchedule(schedule)}
            >
              <Printer className="w-4 h-4 mr-2" />
              Print Roster
            </Button>
          )}
        </div>
      </div>

      {view === 'current' ? (
        <ShiftSummaryView summary={summary} />
      ) : view === 'all' ? (
        <AllShiftsView history={history} />
      ) : (
        <ScheduleView schedule={schedule} />
      )}
    </div>
  );
}

// Week navigator: ◀ This Week ▶ — moves the week cursor 7 days
// at a time. The "This Week" button snaps back to today's week.
function ScheduleWeekNav({
  weekStart,
  onChange,
  schedule,
}: {
  weekStart: string;
  onChange: (week: string) => void;
  schedule: ShiftScheduleResponse | null;
}) {
  const shift = (delta: number) => {
    const d = new Date(weekStart + 'T00:00:00');
    d.setDate(d.getDate() + delta);
    onChange(
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    );
  };
  const todayWeek = () => {
    const d = new Date();
    const dow = (d.getDay() + 6) % 7;
    d.setDate(d.getDate() - dow);
    onChange(
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    );
  };
  const label = schedule
    ? `${schedule.week_start} → ${schedule.week_end}`
    : weekStart;
  return (
    <div className="inline-flex rounded-lg border border-gray-200 bg-gray-50 overflow-hidden">
      <button
        onClick={() => shift(-7)}
        className="px-2 py-1.5 text-sm hover:bg-gray-100 transition-colors"
        aria-label="Previous week"
      >
        ◀
      </button>
      <button
        onClick={todayWeek}
        className="px-3 py-1.5 text-sm font-medium border-x border-gray-200 hover:bg-gray-100 transition-colors"
        title={label}
      >
        This Week
      </button>
      <button
        onClick={() => shift(7)}
        className="px-2 py-1.5 text-sm hover:bg-gray-100 transition-colors"
        aria-label="Next week"
      >
        ▶
      </button>
    </div>
  );
}

function ShiftSummaryView({ summary }: { summary: ShiftSummaryResponse | null }) {
  if (!summary) return <EmptyState message="Loading…" />;
  if (!summary.has_open_shift) {
    return (
      <div className="max-w-3xl mx-auto text-center py-12">
        <ClipboardList className="w-16 h-16 text-gray-400 mx-auto mb-4" />
        <p className="text-gray-700 text-lg font-medium">No open shift</p>
        <p className="text-gray-500 text-sm mt-2">
          Start a shift via the POS opening dialog to see live totals here.
        </p>
      </div>
    );
  }


  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <Card>
        <CardContent className="p-6">
          <div className="flex items-start justify-between mb-6">
            <div>
              <h3 className="text-lg font-semibold text-gray-900">
                Shift: {summary.opening_entry}
              </h3>
              <p className="text-sm text-gray-500">
                Cashier: {summary.full_name} · Profile: {summary.pos_profile}
              </p>
              <p className="text-sm text-gray-500">
                Started: {summary.period_start_date}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatTile
              label="Paid Invoices"
              value={String(summary.paid_count ?? 0)}
              tone="blue"
            />
            <StatTile
              label="Grand Total"
              value={formatCurrency(summary.grand_total ?? 0)}
              tone="green"
            />
            <StatTile
              label="Unpaid Drafts"
              value={`${summary.draft_count ?? 0} · ${formatCurrency(
                summary.draft_grand_total ?? 0
              )}`}
              tone="orange"
            />
            <StatTile
              label="Tax Collected"
              value={formatCurrency(summary.total_tax ?? 0)}
              tone="purple"
            />
          </div>
        </CardContent>
      </Card>

      {summary.payments && summary.payments.length > 0 && (
        <Card>
          <CardContent className="p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">
              Payment Reconciliation (expected)
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-y border-gray-200">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Mode
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      Opening
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      Collected
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      Expected Total
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {summary.payments.map((p, idx) => (
                    <tr key={idx}>
                      <td className="px-4 py-3 text-gray-900 font-medium">
                        {p.mode_of_payment}
                      </td>
                      <td className="px-4 py-3 text-gray-600 text-right">
                        {formatCurrency(p.opening_amount)}
                      </td>
                      <td className="px-4 py-3 text-gray-600 text-right">
                        {formatCurrency(p.expected_amount)}
                      </td>
                      <td className="px-4 py-3 text-gray-900 font-semibold text-right">
                        {formatCurrency(p.opening_amount + p.expected_amount)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-gray-400 mt-3">
              * Closing totals + variance will be computed when you open the
              End Shift dialog from the header menu.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function StaffToggle({
  value,
  onChange,
}: {
  value: StaffGrouping;
  onChange: (v: StaffGrouping) => void;
}) {
  return (
    <div className="flex rounded-lg border border-gray-300 overflow-hidden shrink-0">
      {(
        [
          ['cashier', 'By Cashier'],
          ['waiter', 'By Waiter'],
        ] as [StaffGrouping, string][]
      ).map(([key, label]) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          className={`px-3 py-1.5 text-xs font-medium ${
            value === key
              ? 'bg-blue-600 text-white'
              : 'bg-white text-gray-700 hover:bg-gray-50'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function SalesByCashierView({
  report,
  grouping,
  onGroupingChange,
}: {
  report: SalesByCashierResponse | null;
  grouping: StaffGrouping;
  onGroupingChange: (v: StaffGrouping) => void;
}) {
  // The toggle renders even while loading / empty, otherwise a grouping
  // with no data would strand the user with no way to switch back.
  const toggle = <StaffToggle value={grouping} onChange={onGroupingChange} />;
  if (!report)
    return (
      <div className="max-w-7xl mx-auto space-y-4">
        <div className="flex justify-end">{toggle}</div>
        <EmptyState message="Loading…" />
      </div>
    );
  if (!report.rows.length) {
    return (
      <div className="max-w-7xl mx-auto space-y-4">
        <div className="flex justify-end">{toggle}</div>
        <EmptyState
          message={`No sales between ${report.from_date} and ${report.to_date}`}
        />
      </div>
    );
  }
  const grand = report.totals.grand_total || 0;
  return (
    <div className="max-w-7xl mx-auto space-y-4">
      <Card>
        <CardContent className="p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900">
                Sales by {report.group_by === 'waiter' ? 'Waiter' : 'Cashier'}
              </h3>
              <div className="mt-2">{toggle}</div>
              <p className="text-sm text-gray-500">
                {report.from_date} → {report.to_date} · {report.rows.length}{' '}
                cashier{report.rows.length === 1 ? '' : 's'}
                {report.terminal ? ` · ${report.terminal}` : ''}
              </p>
            </div>
            <div className="text-right">
              <p className="text-sm text-gray-500">Grand total</p>
              <p className="text-2xl font-bold text-gray-900">
                {formatCurrency(grand)}
              </p>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-y border-gray-200">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Cashier
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Invoices
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Returns
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Discount
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    AOV
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Net
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Grand Total
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {report.rows.map((row) => (
                  <tr key={row.user}>
                    <td className="px-4 py-3">
                      <p className="font-medium text-gray-900">{row.full_name}</p>
                      <p className="text-xs text-gray-500">{row.user}</p>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="font-semibold">{row.sale_count}</span>
                      {row.return_count > 0 && (
                        <span className="text-xs text-red-500 ml-1">
                          (−{row.return_count})
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-600">
                      {row.return_amount > 0
                        ? `−${formatCurrency(row.return_amount)}`
                        : '—'}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-600">
                      {row.discount_amount > 0
                        ? formatCurrency(row.discount_amount)
                        : '—'}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-600">
                      {formatCurrency(row.average_order_value)}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-600">
                      {formatCurrency(row.net_total)}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold text-gray-900">
                      {formatCurrency(row.grand_total)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function SalesByCategoryView({
  report,
}: {
  report: SalesByCategoryResponse | null;
}) {
  if (!report) return <EmptyState message="Loading…" />;
  if (!report.rows.length) {
    return (
      <EmptyState message={`No sales between ${report.from_date} and ${report.to_date}`} />
    );
  }
  const grand = report.totals.total_amount || 0;
  const toneByDept: Record<string, string> = {
    Food: 'bg-green-500',
    Drinks: 'bg-blue-500',
    Other: 'bg-amber-500',
  };
  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <Card>
        <CardContent className="p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h3 className="text-lg font-semibold text-gray-900">
                Sales by Category
              </h3>
              <p className="text-sm text-gray-500">
                {report.from_date} → {report.to_date} · classified via URY
                Menu Course department
                {report.terminal ? ` · ${report.terminal}` : ''}
              </p>
            </div>
            <div className="text-right">
              <p className="text-sm text-gray-500">Total</p>
              <p className="text-2xl font-bold text-gray-900">
                {formatCurrency(grand)}
              </p>
            </div>
          </div>
          <div className="space-y-4">
            {report.rows.map((row) => (
              <div key={row.department}>
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <span
                      className={`w-3 h-3 rounded-full ${
                        toneByDept[row.department] || 'bg-gray-400'
                      }`}
                    />
                    <span className="font-medium text-gray-900">
                      {row.department}
                    </span>
                    <span className="text-xs text-gray-500">
                      ({row.total_qty.toFixed(0)} items · {row.invoice_count} orders)
                    </span>
                  </div>
                  <div className="text-right">
                    <span className="font-semibold text-gray-900">
                      {formatCurrency(row.total_amount)}
                    </span>
                    <span className="text-xs text-gray-500 ml-2">
                      {row.percentage.toFixed(1)}%
                    </span>
                  </div>
                </div>
                <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
                  <div
                    className={`h-full ${
                      toneByDept[row.department] || 'bg-gray-400'
                    }`}
                    style={{ width: `${Math.min(row.percentage, 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function TopBottomView({ report }: { report: TopBottomItemsResponse | null }) {
  if (!report) return <EmptyState message="Loading…" />;
  if (!report.top.length && !report.bottom.length) {
    return (
      <EmptyState message={`No sales between ${report.from_date} and ${report.to_date}`} />
    );
  }
  return (
    <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-6">
      <ItemRankCard
        title="Top Sellers"
        subtitle={`${report.from_date} → ${report.to_date}`}
        items={report.top}
        tone="green"
      />
      <ItemRankCard
        title="Slow Movers"
        subtitle={`${report.from_date} → ${report.to_date}`}
        items={report.bottom}
        tone="red"
      />
    </div>
  );
}

interface ItemRankCardProps {
  title: string;
  subtitle: string;
  items: TopBottomItemsResponse['top'];
  tone: 'green' | 'red';
}

function ItemRankCard({ title, subtitle, items, tone }: ItemRankCardProps) {
  const accent = tone === 'green' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700';
  return (
    <Card>
      <CardContent className="p-6">
        <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
        <p className="text-sm text-gray-500 mb-4">{subtitle}</p>
        {items.length === 0 ? (
          <p className="text-sm text-gray-500 italic">No items</p>
        ) : (
          <div className="space-y-2">
            {items.map((item, idx) => (
              <div
                key={item.item_code}
                className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0"
              >
                <div className="flex items-center gap-3">
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold ${accent}`}
                  >
                    #{idx + 1}
                  </div>
                  <div>
                    <p className="font-medium text-gray-900">{item.item_name}</p>
                    <p className="text-xs text-gray-500">
                      {item.total_qty.toFixed(0)} sold · {item.order_count} orders
                    </p>
                  </div>
                </div>
                <p className="font-semibold text-gray-900">
                  {formatCurrency(item.total_amount)}
                </p>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface StatTileProps {
  label: string;
  value: string;
  tone: 'blue' | 'green' | 'orange' | 'purple';
}

function StatTile({ label, value, tone }: StatTileProps) {
  const map = {
    blue: 'bg-blue-50 text-blue-700',
    green: 'bg-green-50 text-green-700',
    orange: 'bg-orange-50 text-orange-700',
    purple: 'bg-purple-50 text-purple-700',
  } as const;
  return (
    <div className={`rounded-lg p-4 ${map[tone]}`}>
      <p className="text-xs uppercase font-medium opacity-80">{label}</p>
      <p className="text-xl font-bold mt-1">{value}</p>
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="max-w-3xl mx-auto text-center py-12">
      <p className="text-gray-500">{message}</p>
    </div>
  );
}

// ---------------------------------------------------------------
// Schedule view — Mon→Sun roster grid driven by URY Shift /
// HRMS Shift Type. Highlights the current user's row.
// ---------------------------------------------------------------

function ScheduleView({
  schedule,
}: {
  schedule: ShiftScheduleResponse | null;
}) {
  if (!schedule) return <EmptyState message="Loading…" />;

  if (schedule.mode === 'Disabled') {
    return (
      <div className="max-w-3xl mx-auto text-center py-12">
        <ClipboardList className="w-16 h-16 text-gray-400 mx-auto mb-4" />
        <p className="text-gray-700 text-lg font-medium">
          Shift system is disabled on this POS Profile
        </p>
        <p className="text-gray-500 text-sm mt-2">
          Set <span className="font-mono">custom_shift_system_mode</span> to{' '}
          <strong>URY Shift</strong> or <strong>HRMS Shift Type</strong> on the
          POS Profile to start showing the weekly roster here.
        </p>
      </div>
    );
  }

  if (schedule.rows.length === 0) {
    return (
      <div className="max-w-3xl mx-auto text-center py-12">
        <ClipboardList className="w-16 h-16 text-gray-400 mx-auto mb-4" />
        <p className="text-gray-700 text-lg font-medium">
          No active shift assignments this week
        </p>
        <p className="text-gray-500 text-sm mt-2">
          {schedule.mode === 'URY Shift'
            ? 'Open URY Shift Assignment in the desk and add some rows for this branch.'
            : 'Open Shift Assignment (HRMS) in the desk and add some rows for this branch.'}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-sm text-gray-600">
        <div className="flex items-center gap-2">
          <Badge className="bg-blue-100 text-blue-700 text-xs uppercase">
            {schedule.mode}
          </Badge>
          <span>
            {schedule.branch} · {schedule.week_start} → {schedule.week_end}
          </span>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200 sticky top-0 z-10">
                <tr>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">
                    Cashier
                  </th>
                  {schedule.days.map((d) => (
                    <th
                      key={d.day_name}
                      className="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase border-l border-gray-100"
                    >
                      <div>{d.day_name.slice(0, 3)}</div>
                      <div className="text-[10px] text-gray-400 font-normal mt-0.5">
                        {d.date.slice(5)}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {schedule.rows.map((row) => (
                  <tr
                    key={row.user}
                    className={cn(
                      'transition-colors',
                      row.is_me
                        ? 'bg-blue-50 hover:bg-blue-100'
                        : 'hover:bg-gray-50'
                    )}
                  >
                    <td className="px-3 py-3 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <span
                          className={cn(
                            'font-medium',
                            row.is_me ? 'text-blue-900' : 'text-gray-900'
                          )}
                        >
                          {row.full_name}
                        </span>
                        {row.is_me && (
                          <Badge className="bg-blue-600 text-white text-[10px] uppercase px-1.5 py-0">
                            You
                          </Badge>
                        )}
                      </div>
                      <p className="text-xs text-gray-500">{row.user}</p>
                    </td>
                    {schedule.days.map((d) => {
                      const cell = row.assignments[d.day_name];
                      return (
                        <td
                          key={d.day_name}
                          className="px-3 py-3 text-center border-l border-gray-100"
                        >
                          {cell ? (
                            <div className="inline-flex flex-col items-center">
                              <span
                                className={cn(
                                  'text-xs font-semibold rounded px-2 py-0.5',
                                  row.is_me
                                    ? 'bg-blue-200 text-blue-900'
                                    : 'bg-gray-100 text-gray-800'
                                )}
                              >
                                {cell.shift_name}
                              </span>
                              <span className="text-[10px] text-gray-500 mt-0.5">
                                {cell.start_time} – {cell.end_time}
                              </span>
                            </div>
                          ) : (
                            <span className="text-gray-300">—</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <p className="text-xs text-gray-500">
        {schedule.rows.length} cashier{schedule.rows.length === 1 ? '' : 's'}{' '}
        scheduled this week
        {schedule.rows.some((r) => r.is_me) && ' · your row is highlighted'}.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------
// Notice-board print template for the schedule — same paper-style
// layout as the shift history print, but the body is the Mon→Sun
// roster grid.
// ---------------------------------------------------------------

function printShiftSchedule(schedule: ShiftScheduleResponse) {
  const win = window.open('', '_blank', 'width=1100,height=700');
  if (!win) {
    showToast.error('Please allow pop-ups to print');
    return;
  }
  const printedAt = new Date().toLocaleString('en-US');

  const headerCells = schedule.days
    .map(
      (d) => `
        <th>
          ${d.day_name.slice(0, 3)}<br>
          <small>${d.date.slice(5)}</small>
        </th>`
    )
    .join('');

  const rowsHtml = schedule.rows
    .map((row) => {
      const cells = schedule.days
        .map((d) => {
          const cell = row.assignments[d.day_name];
          if (!cell) return '<td class="empty">—</td>';
          return `
            <td class="${row.is_me ? 'me-cell' : ''}">
              <strong>${cell.shift_name}</strong><br>
              <small>${cell.start_time} – ${cell.end_time}</small>
            </td>`;
        })
        .join('');
      return `
        <tr class="${row.is_me ? 'me-row' : ''}">
          <td class="cashier">
            <strong>${row.full_name}</strong>
            ${row.is_me ? '<span class="me-badge">YOU</span>' : ''}
            <br><small>${row.user}</small>
          </td>
          ${cells}
        </tr>`;
    })
    .join('');

  const html = `
    <!doctype html>
    <html>
    <head>
      <title>Shift Roster — ${schedule.branch} — ${schedule.week_start} → ${schedule.week_end}</title>
      <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Helvetica Neue', Arial, sans-serif; padding: 24px; color: #1f2937; font-size: 12px; }
        .header { text-align: center; border-bottom: 3px double #1f2937; padding-bottom: 12px; margin-bottom: 16px; }
        .header h1 { font-size: 22px; font-weight: 700; letter-spacing: 1px; }
        .header .meta { font-size: 13px; color: #4b5563; margin-top: 4px; }
        table { width: 100%; border-collapse: collapse; font-size: 11px; }
        th, td { padding: 8px; text-align: center; border: 1px solid #d1d5db; vertical-align: middle; }
        th { background: #f3f4f6; font-weight: 600; font-size: 10px; text-transform: uppercase; color: #4b5563; }
        td.cashier { text-align: left; background: #f9fafb; min-width: 160px; }
        td.empty { color: #d1d5db; background: #fafafa; }
        tr.me-row td { background: #eff6ff !important; }
        td.me-cell { background: #dbeafe !important; }
        .me-badge { display: inline-block; background: #2563eb; color: white; font-size: 8px; padding: 1px 4px; border-radius: 2px; vertical-align: top; margin-left: 4px; }
        small { font-size: 9px; color: #6b7280; }
        .footer { text-align: center; margin-top: 24px; font-size: 9px; color: #9ca3af; border-top: 1px solid #e5e7eb; padding-top: 8px; }
        .signatures { display: flex; gap: 40px; margin-top: 36px; }
        .sig { flex: 1; text-align: center; border-top: 1px solid #1f2937; padding-top: 4px; font-size: 11px; color: #4b5563; text-transform: uppercase; letter-spacing: 1px; }
        @media print { body { padding: 12px; } .no-print { display: none; } }
      </style>
    </head>
    <body>
      <div class="header">
        <h1>SHIFT ROSTER</h1>
        <div class="meta">
          ${schedule.branch} · ${schedule.week_start} → ${schedule.week_end}
          · ${schedule.mode}
        </div>
      </div>

      <table>
        <thead>
          <tr>
            <th style="text-align:left">Cashier</th>
            ${headerCells}
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>

      <div class="signatures">
        <div class="sig">Manager Signature</div>
        <div class="sig">Date Posted</div>
      </div>

      <div class="footer">Generated ${printedAt}</div>

      <script>
        window.onload = function() {
          window.print();
          window.onafterprint = function() { window.close(); };
        };
      </script>
    </body>
    </html>
  `;

  win.document.write(html);
  win.document.close();
}

// ---------------------------------------------------------------
// All Shifts view — closed shift history table for the date window
// + cross-shift payment reconciliation summary. Notice-board style
// so admins can hit Print and pin it up.
// ---------------------------------------------------------------

function AllShiftsView({ history }: { history: ShiftHistoryResponse | null }) {
  if (!history) return <EmptyState message="Loading…" />;
  if (history.shifts.length === 0) {
    return (
      <EmptyState
        message={`No closed shifts between ${history.from_date} and ${history.to_date}`}
      />
    );
  }

  const { shifts, summary, scope, from_date, to_date, branch } = history;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <StatTile
          label="Shifts Closed"
          value={String(summary.shift_count)}
          tone="blue"
        />
        <StatTile
          label="Grand Total"
          value={formatCurrency(summary.grand_total)}
          tone="green"
        />
        <StatTile
          label="Net Total"
          value={formatCurrency(summary.net_total)}
          tone="purple"
        />
      </div>

      <Card>
        <CardContent className="p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900">
                Shift History
              </h3>
              <p className="text-sm text-gray-500">
                {from_date} → {to_date} · {branch}
                {scope === 'user' && ' · my shifts only'}
              </p>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-y border-gray-200">
                <tr>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Closed
                  </th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Cashier
                  </th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Profile
                  </th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Open → Close
                  </th>
                  <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Invoices
                  </th>
                  <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Net
                  </th>
                  <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Grand
                  </th>
                  <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Variance
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {shifts.map((s) => {
                  const variance = s.payments.reduce(
                    (sum, p) => sum + (p.difference || 0),
                    0
                  );
                  return (
                    <tr key={s.name}>
                      <td className="px-3 py-3 text-xs text-gray-600 whitespace-nowrap">
                        {s.posting_date}
                        <p className="font-mono text-[10px] text-gray-400">
                          {s.name}
                        </p>
                      </td>
                      <td className="px-3 py-3">
                        <p className="font-medium text-gray-900">
                          {s.full_name}
                        </p>
                        <p className="text-xs text-gray-500">{s.user}</p>
                      </td>
                      <td className="px-3 py-3 text-gray-600">
                        {s.pos_profile}
                      </td>
                      <td className="px-3 py-3 text-xs text-gray-600 whitespace-nowrap">
                        {shortDateTime(s.period_start_date)}
                        <br />→ {shortDateTime(s.period_end_date)}
                      </td>
                      <td className="px-3 py-3 text-right text-gray-600">
                        {s.invoice_count}
                      </td>
                      <td className="px-3 py-3 text-right text-gray-600">
                        {formatCurrency(s.net_total)}
                      </td>
                      <td className="px-3 py-3 text-right font-semibold text-gray-900">
                        {formatCurrency(s.grand_total)}
                      </td>
                      <td
                        className={cn(
                          'px-3 py-3 text-right font-medium whitespace-nowrap',
                          variance > 0
                            ? 'text-green-600'
                            : variance < 0
                            ? 'text-red-600'
                            : 'text-gray-400'
                        )}
                      >
                        {variance === 0
                          ? '—'
                          : `${variance > 0 ? '+' : ''}${formatCurrency(
                              variance
                            )}`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {summary.by_mode.length > 0 && (
        <Card>
          <CardContent className="p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-3">
              Payment Reconciliation Summary
            </h3>
            <p className="text-sm text-gray-500 mb-4">
              Aggregated across all {summary.shift_count} shift
              {summary.shift_count === 1 ? '' : 's'} in the window.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-y border-gray-200">
                  <tr>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Mode
                    </th>
                    <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      Opening
                    </th>
                    <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      Expected
                    </th>
                    <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      Counted
                    </th>
                    <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      Variance
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {summary.by_mode.map((m) => (
                    <tr key={m.mode_of_payment}>
                      <td className="px-3 py-3 font-medium text-gray-900">
                        {m.mode_of_payment}
                      </td>
                      <td className="px-3 py-3 text-right text-gray-600">
                        {formatCurrency(m.opening_amount)}
                      </td>
                      <td className="px-3 py-3 text-right text-gray-600">
                        {formatCurrency(m.expected_amount)}
                      </td>
                      <td className="px-3 py-3 text-right text-gray-600">
                        {formatCurrency(m.closing_amount)}
                      </td>
                      <td
                        className={cn(
                          'px-3 py-3 text-right font-medium',
                          m.difference > 0
                            ? 'text-green-600'
                            : m.difference < 0
                            ? 'text-red-600'
                            : 'text-gray-400'
                        )}
                      >
                        {m.difference === 0
                          ? '—'
                          : `${m.difference > 0 ? '+' : ''}${formatCurrency(
                              m.difference
                            )}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------
// Notice-board print template — opens a print window with a clean
// tabular layout (branch + date range header, shift table, payment
// reconciliation summary, signature lines). The window auto-fires
// the browser Print dialog on load and closes itself after.
// ---------------------------------------------------------------

function printShiftHistory(history: ShiftHistoryResponse) {
  const win = window.open('', '_blank', 'width=900,height=700');
  if (!win) {
    showToast.error('Please allow pop-ups to print');
    return;
  }
  const fmt = (n: number) =>
    n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const sign = (n: number) => (n > 0 ? `+${fmt(n)}` : fmt(n));
  const printedAt = new Date().toLocaleString('en-US');

  const shiftRows = history.shifts
    .map((s) => {
      const variance = s.payments.reduce(
        (sum, p) => sum + (p.difference || 0),
        0
      );
      const open = new Date(s.period_start_date.replace(' ', 'T'));
      const close = new Date(s.period_end_date.replace(' ', 'T'));
      const fmtTime = (d: Date) =>
        isNaN(d.getTime())
          ? '—'
          : d.toLocaleString('en-US', {
              month: 'short',
              day: 'numeric',
              hour: 'numeric',
              minute: '2-digit',
              hour12: true,
            });
      return `
        <tr>
          <td>${s.posting_date}</td>
          <td>${s.full_name}<br><small>${s.user}</small></td>
          <td>${s.pos_profile}</td>
          <td>${fmtTime(open)}<br>→ ${fmtTime(close)}</td>
          <td class="text-right">${s.invoice_count}</td>
          <td class="text-right">${fmt(s.net_total)}</td>
          <td class="text-right strong">${fmt(s.grand_total)}</td>
          <td class="text-right ${
            variance > 0 ? 'pos' : variance < 0 ? 'neg' : ''
          }">${variance === 0 ? '—' : sign(variance)}</td>
        </tr>
      `;
    })
    .join('');

  const reconRows = history.summary.by_mode
    .map(
      (m) => `
      <tr>
        <td>${m.mode_of_payment}</td>
        <td class="text-right">${fmt(m.opening_amount)}</td>
        <td class="text-right">${fmt(m.expected_amount)}</td>
        <td class="text-right">${fmt(m.closing_amount)}</td>
        <td class="text-right ${
          m.difference > 0 ? 'pos' : m.difference < 0 ? 'neg' : ''
        }">${m.difference === 0 ? '—' : sign(m.difference)}</td>
      </tr>
    `
    )
    .join('');

  const html = `
    <!doctype html>
    <html>
    <head>
      <title>Shift Report — ${history.branch} — ${history.from_date} → ${history.to_date}</title>
      <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Helvetica Neue', Arial, sans-serif; padding: 24px; color: #1f2937; font-size: 12px; }
        .header { text-align: center; border-bottom: 3px double #1f2937; padding-bottom: 12px; margin-bottom: 16px; }
        .header h1 { font-size: 22px; font-weight: 700; letter-spacing: 1px; }
        .header .meta { font-size: 13px; color: #4b5563; margin-top: 4px; }
        .summary { display: flex; justify-content: space-around; gap: 12px; margin: 12px 0 18px; padding: 10px 8px; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; }
        .summary div { text-align: center; }
        .summary label { font-size: 10px; text-transform: uppercase; color: #6b7280; letter-spacing: 0.5px; display: block; }
        .summary .v { font-size: 16px; font-weight: 700; margin-top: 2px; }
        h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: #1f2937; margin: 16px 0 8px; border-bottom: 1px solid #d1d5db; padding-bottom: 4px; }
        table { width: 100%; border-collapse: collapse; font-size: 11px; }
        th { background: #f3f4f6; padding: 8px 6px; text-align: left; font-weight: 600; font-size: 10px; text-transform: uppercase; color: #4b5563; border-bottom: 2px solid #d1d5db; }
        td { padding: 8px 6px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }
        .text-right { text-align: right; }
        .strong { font-weight: 700; color: #111827; }
        .pos { color: #059669; font-weight: 600; }
        .neg { color: #dc2626; font-weight: 600; }
        small { font-size: 9px; color: #9ca3af; }
        .signatures { display: flex; gap: 40px; margin-top: 36px; }
        .sig { flex: 1; text-align: center; border-top: 1px solid #1f2937; padding-top: 4px; font-size: 11px; color: #4b5563; text-transform: uppercase; letter-spacing: 1px; }
        .footer { text-align: center; margin-top: 24px; font-size: 9px; color: #9ca3af; border-top: 1px solid #e5e7eb; padding-top: 8px; }
        @media print { body { padding: 12px; } .no-print { display: none; } }
      </style>
    </head>
    <body>
      <div class="header">
        <h1>SHIFT REPORT</h1>
        <div class="meta">${history.branch} · ${history.from_date} → ${history.to_date}</div>
      </div>

      <div class="summary">
        <div>
          <label>Shifts Closed</label>
          <div class="v">${history.summary.shift_count}</div>
        </div>
        <div>
          <label>Grand Total</label>
          <div class="v">${fmt(history.summary.grand_total)}</div>
        </div>
        <div>
          <label>Net Total</label>
          <div class="v">${fmt(history.summary.net_total)}</div>
        </div>
      </div>

      <h2>Shifts</h2>
      <table>
        <thead>
          <tr>
            <th>Closed</th>
            <th>Cashier</th>
            <th>Profile</th>
            <th>Open → Close</th>
            <th class="text-right">Inv</th>
            <th class="text-right">Net</th>
            <th class="text-right">Grand</th>
            <th class="text-right">Var</th>
          </tr>
        </thead>
        <tbody>${shiftRows}</tbody>
      </table>

      ${
        reconRows
          ? `
        <h2>Payment Reconciliation</h2>
        <table>
          <thead>
            <tr>
              <th>Mode</th>
              <th class="text-right">Opening</th>
              <th class="text-right">Expected</th>
              <th class="text-right">Counted</th>
              <th class="text-right">Variance</th>
            </tr>
          </thead>
          <tbody>${reconRows}</tbody>
        </table>
      `
          : ''
      }

      <div class="signatures">
        <div class="sig">Cashier Signature</div>
        <div class="sig">Supervisor Signature</div>
      </div>

      <div class="footer">Generated ${printedAt}</div>

      <script>
        window.onload = function() {
          window.print();
          window.onafterprint = function() { window.close(); };
        };
      </script>
    </body>
    </html>
  `;

  win.document.write(html);
  win.document.close();
}

// ---------------------------------------------------------------
// Merge report view — two stacked tables, one for order merges and
// one for table merges. Merge Log and Table Merge Log share the
// same acting-user + status + timestamp columns so the sub-tables
// share a common shape.
// ---------------------------------------------------------------

function MergeReportView({ report }: { report: MergeReportResponse | null }) {
  if (!report) return <EmptyState message="Loading…" />;
  const { summary, order_merges, table_merges } = report;
  const hasAny = order_merges.length > 0 || table_merges.length > 0;
  if (!hasAny) {
    return (
      <EmptyState
        message={`No merges between ${report.from_date} and ${report.to_date}`}
      />
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <StatTile
          label="Order Merges"
          value={`${summary.order_merge_count} · ${summary.order_merge_active} active`}
          tone="blue"
        />
        <StatTile
          label="Table Merges"
          value={`${summary.table_merge_count} · ${summary.table_merge_active} active`}
          tone="purple"
        />
      </div>

      {order_merges.length > 0 && (
        <Card>
          <CardContent className="p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">
              Order Merges
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-y border-gray-200">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Log
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Master
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      Sources
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      Sources Total
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Merged by
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Merged at
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Status
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {order_merges.map((row) => (
                    <tr key={row.name}>
                      <td className="px-4 py-3 font-mono text-xs text-gray-600">
                        {row.name}
                      </td>
                      <td className="px-4 py-3 font-medium text-gray-900">
                        {row.master_invoice}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-600">
                        {row.source_count}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-600">
                        {formatCurrency(row.sources_total)}
                      </td>
                      <td className="px-4 py-3">
                        <p className="text-gray-900">
                          {row.merged_by_full_name}
                        </p>
                        {row.status === 'Unmerged' &&
                          row.unmerged_by_full_name && (
                            <p className="text-xs text-gray-500">
                              undone by {row.unmerged_by_full_name}
                            </p>
                          )}
                      </td>
                      <td className="px-4 py-3 text-gray-600">
                        {shortDateTime(row.merged_at)}
                        {row.status === 'Unmerged' && row.unmerged_at && (
                          <p className="text-xs text-gray-500">
                            undone {shortDateTime(row.unmerged_at)}
                          </p>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <Badge
                          variant={row.status === 'Active' ? 'default' : 'secondary'}
                          className={`text-xs ${
                            row.status === 'Active'
                              ? 'bg-blue-100 text-blue-700'
                              : 'bg-gray-100 text-gray-600'
                          }`}
                        >
                          {row.status}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {table_merges.length > 0 && (
        <Card>
          <CardContent className="p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">
              Table Merges
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-y border-gray-200">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Log
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Master Table
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      Sources
                    </th>
                    <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                      Orders Merged
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Merged by
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Merged at
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Status
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {table_merges.map((row) => (
                    <tr key={row.name}>
                      <td className="px-4 py-3 font-mono text-xs text-gray-600">
                        {row.name}
                      </td>
                      <td className="px-4 py-3 font-medium text-gray-900">
                        {row.master_table}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-600">
                        {row.source_count}
                      </td>
                      <td className="px-4 py-3 text-center">
                        {row.merged_orders === 1 ? (
                          <Badge className="text-xs bg-green-100 text-green-700">
                            Yes
                          </Badge>
                        ) : (
                          <span className="text-xs text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <p className="text-gray-900">
                          {row.merged_by_full_name}
                        </p>
                        {row.status === 'Unmerged' &&
                          row.unmerged_by_full_name && (
                            <p className="text-xs text-gray-500">
                              undone by {row.unmerged_by_full_name}
                            </p>
                          )}
                      </td>
                      <td className="px-4 py-3 text-gray-600">
                        {shortDateTime(row.merged_at)}
                        {row.status === 'Unmerged' && row.unmerged_at && (
                          <p className="text-xs text-gray-500">
                            undone {shortDateTime(row.unmerged_at)}
                          </p>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <Badge
                          variant={row.status === 'Active' ? 'default' : 'secondary'}
                          className={`text-xs ${
                            row.status === 'Active'
                              ? 'bg-purple-100 text-purple-700'
                              : 'bg-gray-100 text-gray-600'
                          }`}
                        >
                          {row.status}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------
// Transfer report view — every POS Invoice that was transferred to
// another cashier at shift-close time. Cashiers can't see this
// (admin-only); captains use it to audit "who dumped what onto
// whom" during the end-of-day draft-transfer flow.
// ---------------------------------------------------------------

function TransferReportView({
  report,
}: {
  report: TransferReportResponse | null;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  if (!report) return <EmptyState message="Loading…" />;
  const { summary, events } = report;
  if (events.length === 0) {
    return (
      <EmptyState
        message={`No shift-close transfers between ${report.from_date} and ${report.to_date}`}
      />
    );
  }

  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const eventKey = (e: typeof events[number]) =>
    `${e.opening_entry || '-'}|${e.from_cashier || '-'}|${e.to_cashier}`;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatTile
          label="Events"
          value={String(summary.event_count)}
          tone="orange"
        />
        <StatTile
          label="Invoices moved"
          value={String(summary.count)}
          tone="blue"
        />
        <StatTile
          label="Total moved"
          value={formatCurrency(summary.total_amount)}
          tone="green"
        />
        <StatTile
          label="Distinct pairs"
          value={String(summary.distinct_pairs)}
          tone="purple"
        />
      </div>

      <Card>
        <CardContent className="p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-1">
            Shift-Close Transfers
          </h3>
          <p className="text-sm text-gray-500 mb-4">
            Grouped by shift close. Click a row to expand the list of
            invoices reassigned in that event.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-y border-gray-200">
                <tr>
                  <th className="px-2 py-3 w-6"></th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    From
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    To
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Shift
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    When
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Invoices
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Total
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {events.map((ev) => {
                  const key = eventKey(ev);
                  const isOpen = expanded.has(key);
                  return (
                    <React.Fragment key={key}>
                      <tr
                        className={cn(
                          'cursor-pointer hover:bg-gray-50 transition-colors',
                          isOpen && 'bg-orange-50'
                        )}
                        onClick={() => toggle(key)}
                      >
                        <td className="px-2 py-3 text-gray-400 text-center">
                          <span className="inline-block transition-transform">
                            {isOpen ? '▾' : '▸'}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-700">
                          {ev.from_cashier_full_name || '?'}
                        </td>
                        <td className="px-4 py-3 text-gray-900 font-medium">
                          <ArrowRightLeft className="inline w-3 h-3 mr-1 text-orange-500" />
                          {ev.to_cashier_full_name}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs text-gray-600">
                          {ev.opening_entry || '—'}
                        </td>
                        <td className="px-4 py-3 text-gray-600">
                          {shortDateTime(ev.transfer_time)}
                        </td>
                        <td className="px-4 py-3 text-right font-semibold">
                          {ev.count}
                        </td>
                        <td className="px-4 py-3 text-right font-semibold text-gray-900">
                          {formatCurrency(ev.total_amount)}
                        </td>
                      </tr>
                      {isOpen && (
                        <tr>
                          <td colSpan={7} className="bg-orange-50/50 p-0">
                            <div className="px-8 py-3">
                              <table className="w-full text-xs">
                                <thead>
                                  <tr className="text-gray-500 uppercase text-[10px]">
                                    <th className="text-left py-2 px-2 font-medium">
                                      Invoice
                                    </th>
                                    <th className="text-left py-2 px-2 font-medium">
                                      Customer
                                    </th>
                                    <th className="text-left py-2 px-2 font-medium">
                                      Table
                                    </th>
                                    <th className="text-left py-2 px-2 font-medium">
                                      Posting Date
                                    </th>
                                    <th className="text-left py-2 px-2 font-medium">
                                      Terminal
                                    </th>
                                    <th className="text-left py-2 px-2 font-medium">
                                      Status
                                    </th>
                                    <th className="text-right py-2 px-2 font-medium">
                                      Amount
                                    </th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {ev.invoices.map((inv) => (
                                    <tr
                                      key={inv.name}
                                      className="border-t border-orange-200/50"
                                    >
                                      <td className="py-2 px-2 font-mono text-gray-900">
                                        {inv.name}
                                      </td>
                                      <td className="py-2 px-2 text-gray-700">
                                        {inv.customer_name || inv.customer || '—'}
                                      </td>
                                      <td className="py-2 px-2 text-gray-700">
                                        {inv.restaurant_table || '—'}
                                      </td>
                                      <td className="py-2 px-2 text-gray-700">
                                        {inv.posting_date}
                                      </td>
                                      <td className="py-2 px-2 text-gray-700">
                                        {inv.custom_terminal || '—'}
                                      </td>
                                      <td className="py-2 px-2">
                                        <Badge
                                          variant="secondary"
                                          className={`text-[10px] ${
                                            inv.status === 'Paid'
                                              ? 'bg-green-100 text-green-700'
                                              : 'bg-gray-100 text-gray-600'
                                          }`}
                                        >
                                          {inv.status}
                                        </Badge>
                                      </td>
                                      <td className="py-2 px-2 text-right font-semibold text-gray-900">
                                        {formatCurrency(inv.grand_total)}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------
// Payment Splits view — paid POS Invoices with multi-mode
// settlement. Row per invoice, per-mode breakdown inline.
// ---------------------------------------------------------------

function PaymentSplitsView({
  report,
}: {
  report: PaymentSplitsResponse | null;
}) {
  if (!report) return <EmptyState message="Loading…" />;
  const { summary, rows } = report;
  if (rows.length === 0) {
    return (
      <EmptyState
        message={`No split payments between ${report.from_date} and ${report.to_date}`}
      />
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <StatTile
          label="Split Invoices"
          value={String(summary.count)}
          tone="blue"
        />
        <StatTile
          label="Total amount"
          value={formatCurrency(summary.total_amount)}
          tone="green"
        />
      </div>

      {summary.by_mode.length > 0 && (
        <Card>
          <CardContent className="p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-3">
              Mode Breakdown
            </h3>
            <p className="text-sm text-gray-500 mb-4">
              Aggregated per-mode totals across all split invoices in
              the window.
            </p>
            <div className="flex flex-wrap gap-3">
              {summary.by_mode.map((m) => (
                <div
                  key={m.mode_of_payment}
                  className="bg-gray-50 rounded-lg p-4 border border-gray-200 min-w-[160px]"
                >
                  <p className="text-xs text-gray-500">
                    {m.mode_of_payment}
                  </p>
                  <p className="text-lg font-bold text-blue-600 mt-1">
                    {formatCurrency(m.amount)}
                  </p>
                  <p className="text-[11px] text-gray-400">
                    {m.count} payment{m.count === 1 ? '' : 's'}
                  </p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-1">
            Split-Payment Invoices
          </h3>
          <p className="text-sm text-gray-500 mb-4">
            Invoices settled with two or more payment rows — covers
            Split Bill flow AND single-payer mixed-mode settlements.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-y border-gray-200">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Invoice
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    When
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Cashier
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Customer
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Split
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Amount
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {rows.map((row) => (
                  <tr key={row.name}>
                    <td className="px-4 py-3">
                      <p className="font-mono text-xs text-gray-900">
                        {row.name}
                      </p>
                      {row.restaurant_table && (
                        <p className="text-xs text-gray-500">
                          {row.restaurant_table}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                      {row.posting_date}
                      <p className="text-xs text-gray-400">
                        {row.posting_time}
                      </p>
                    </td>
                    <td className="px-4 py-3 text-gray-700">
                      {row.owner_full_name}
                    </td>
                    <td className="px-4 py-3 text-gray-700">
                      {row.customer_name || row.customer || '—'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {row.payments.map((p, idx) => (
                          <span
                            key={idx}
                            className="inline-flex items-center gap-1 text-xs bg-blue-50 text-blue-700 rounded-full px-2 py-0.5 border border-blue-100"
                          >
                            <span className="font-medium">
                              {p.mode_of_payment}
                            </span>
                            <span className="text-blue-500">
                              {formatCurrency(p.amount)}
                            </span>
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right font-semibold text-gray-900">
                      {formatCurrency(row.grand_total)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function shortDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso.replace(' ', 'T'));
  if (isNaN(d.getTime())) return iso.slice(0, 16);
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

/**
 * Covers — how each menu course is selling, drilling into its items.
 *
 * A course row is collapsed by default; expanding it lists the items
 * inside with how many bills each appeared on, units sold and revenue.
 * `bill_count` is a DISTINCT count of invoices, not a row count, so two
 * lines of the same course on one bill count once.
 */
function CoversView({ report }: { report: CourseSalesResponse | null }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  if (!report) return <EmptyState message="Loading…" />;
  if (!report.courses.length) {
    return (
      <EmptyState
        message={`No sales between ${report.from_date} and ${report.to_date}`}
      />
    );
  }
  const toggle = (course: string) =>
    setOpen((cur) => {
      const next = new Set(cur);
      if (next.has(course)) next.delete(course);
      else next.add(course);
      return next;
    });

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatTile
          label="Courses"
          value={String(report.totals.course_count)}
          tone="blue"
        />
        <StatTile label="Items sold" value={String(report.totals.qty)} tone="purple" />
        <StatTile
          label="Total"
          value={formatCurrency(report.totals.amount)}
          tone="green"
        />
      </div>

      <Card>
        <CardContent className="p-6">
          <div className="mb-4">
            <h3 className="text-lg font-semibold text-gray-900">Covers by Course</h3>
            <p className="text-sm text-gray-500">
              {report.from_date} to {report.to_date} · tap a course to see its items
            </p>
          </div>

          <div className="space-y-2">
            {report.courses.map((c) => {
              const expanded = open.has(c.course);
              return (
                <div
                  key={c.course}
                  className="border border-gray-200 rounded-lg overflow-hidden"
                >
                  <button
                    onClick={() => toggle(c.course)}
                    className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 text-left"
                  >
                    <span className="text-gray-400 shrink-0">
                      {expanded ? '▾' : '▸'}
                    </span>
                    <span className="flex-1 min-w-0">
                      <span className="block font-medium text-gray-900 truncate">
                        {c.course}
                      </span>
                      <span className="block text-xs text-gray-500">
                        {c.bill_count} bill{c.bill_count === 1 ? '' : 's'} ·{' '}
                        {c.qty} sold · {c.item_count} item
                        {c.item_count === 1 ? '' : 's'}
                      </span>
                    </span>
                    <span className="text-right shrink-0">
                      <span className="block font-semibold text-gray-900">
                        {formatCurrency(c.amount)}
                      </span>
                      <span className="block text-xs text-gray-500">
                        {c.percentage}%
                      </span>
                    </span>
                  </button>

                  {expanded && (
                    <div className="border-t border-gray-100 bg-gray-50 overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-xs uppercase tracking-wide text-gray-500">
                            <th className="py-2 px-4 font-medium">Item</th>
                            <th className="py-2 px-3 font-medium text-right">Times</th>
                            <th className="py-2 px-3 font-medium text-right">Qty</th>
                            <th className="py-2 px-4 font-medium text-right">Total</th>
                          </tr>
                        </thead>
                        <tbody>
                          {c.items.map((i) => (
                            <tr
                              key={i.item_code}
                              className="border-t border-gray-100"
                            >
                              <td className="py-2 px-4">
                                <span className="block text-gray-900">
                                  {i.item_name || i.item_code}
                                </span>
                                <span className="block text-xs text-gray-500">
                                  {i.item_code}
                                </span>
                              </td>
                              <td className="py-2 px-3 text-right text-gray-700">
                                {i.bill_count}
                              </td>
                              <td className="py-2 px-3 text-right text-gray-700">
                                {i.qty}
                              </td>
                              <td className="py-2 px-4 text-right font-medium text-gray-900">
                                {formatCurrency(i.amount)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
