import React, { useEffect, useState, useRef } from 'react';
import {
  TrendingUp,
  DollarSign,
  ShoppingCart,
  Users,
  Calendar,
  Printer,
  RefreshCw,
  UserCircle,
  PieChart,
  Trophy,
  ClipboardList,
} from 'lucide-react';
import { Card, CardContent, Badge } from '../components/ui';
import { Button } from '../components/ui/button';
import { Spinner } from '../components/ui/spinner';
import { call } from '../lib/frappe-sdk';
import { formatCurrency } from '../lib/utils';
import { showToast } from '../components/ui/toast';
import { usePOSStore } from '../store/pos-store';
import { useRootStore } from '../store/root-store';
import { canSeeAdminReports } from '../lib/role-utils';
import {
  getSalesByCashier,
  getSalesByCategory,
  getTopBottomItems,
  getMyShiftSummary,
  type SalesByCashierResponse,
  type SalesByCategoryResponse,
  type TopBottomItemsResponse,
  type ShiftSummaryResponse,
} from '../lib/reports-api';

interface DashboardStats {
  total_sales: number;
  total_orders: number;
  total_customers: number;
  average_order_value: number;
  top_selling_items: Array<{
    item_name: string;
    quantity: number;
    total_amount: number;
  }>;
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
  | 'by-category'
  | 'top-bottom';

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
  // New report data slots
  const [shiftSummary, setShiftSummary] =
    useState<ShiftSummaryResponse | null>(null);
  const [salesByCashier, setSalesByCashier] =
    useState<SalesByCashierResponse | null>(null);
  const [salesByCategory, setSalesByCategory] =
    useState<SalesByCategoryResponse | null>(null);
  const [topBottom, setTopBottom] =
    useState<TopBottomItemsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const printRef = useRef<HTMLDivElement>(null);

  const { terminalName } = usePOSStore();
  const { user } = useRootStore();
  const isAdmin = canSeeAdminReports(user);

  const isRangeTab =
    activeTab === 'by-cashier' ||
    activeTab === 'by-category' ||
    activeTab === 'top-bottom';
  const isSingleDateTab =
    activeTab === 'dashboard' || activeTab === 'daily-sales';

  useEffect(() => {
    if (activeTab === 'dashboard') {
      fetchDashboardStats();
    } else if (activeTab === 'daily-sales') {
      fetchDailySales();
    } else if (activeTab === 'my-shift') {
      fetchShiftSummary();
    } else if (activeTab === 'by-cashier') {
      fetchSalesByCashier();
    } else if (activeTab === 'by-category') {
      fetchSalesByCategory();
    } else if (activeTab === 'top-bottom') {
      fetchTopBottom();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, selectedDate, fromDate, toDate, terminalName]);

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

  const fetchSalesByCashier = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getSalesByCashier({
        from_date: fromDate,
        to_date: toDate,
        terminal: terminalName,
      });
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

  const handleRefresh = () => {
    if (activeTab === 'dashboard') fetchDashboardStats();
    else if (activeTab === 'daily-sales') fetchDailySales();
    else if (activeTab === 'my-shift') fetchShiftSummary();
    else if (activeTab === 'by-cashier') fetchSalesByCashier();
    else if (activeTab === 'by-category') fetchSalesByCategory();
    else if (activeTab === 'top-bottom') fetchTopBottom();
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

  const formatDateTime = (date: string, time: string) => {
    return new Date(date + ' ' + time).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
      hour12: true
    });
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
            {/* Single-date picker for Dashboard + Daily Sales */}
            {isSingleDateTab && (
              <div className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2 border border-gray-200">
                <Calendar className="w-4 h-4 text-gray-500" />
                <input
                  type="date"
                  value={selectedDate}
                  onChange={(e) => setSelectedDate(e.target.value)}
                  className="text-sm bg-transparent border-none focus:outline-none"
                />
              </div>
            )}

            {/* From/To range picker for admin reports */}
            {isRangeTab && (
              <div className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2 border border-gray-200">
                <Calendar className="w-4 h-4 text-gray-500" />
                <input
                  type="date"
                  value={fromDate}
                  onChange={(e) => setFromDate(e.target.value)}
                  max={toDate}
                  className="text-sm bg-transparent border-none focus:outline-none"
                />
                <span className="text-xs text-gray-400">to</span>
                <input
                  type="date"
                  value={toDate}
                  onChange={(e) => setToDate(e.target.value)}
                  min={fromDate}
                  max={todayIso()}
                  className="text-sm bg-transparent border-none focus:outline-none"
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
              <Button
                variant="default"
                size="sm"
                onClick={handlePrint}
                disabled={salesInvoices.length === 0}
              >
                <Printer className="w-4 h-4 mr-2" />
                Print Report
              </Button>
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
          <ShiftSummaryView summary={shiftSummary} />
        ) : activeTab === 'by-cashier' ? (
          <SalesByCashierView report={salesByCashier} />
        ) : activeTab === 'by-category' ? (
          <SalesByCategoryView report={salesByCategory} />
        ) : activeTab === 'top-bottom' ? (
          <TopBottomView report={topBottom} />
        ) : activeTab === 'dashboard' ? (
          <div className="max-w-7xl mx-auto space-y-6">
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
                            <tr key={invoice.name} className="hover:bg-gray-50">
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

  const diff = (p: { opening_amount: number; expected_amount: number; closing_amount: number }) =>
    (p.closing_amount || 0) - (p.opening_amount || 0) - (p.expected_amount || 0);

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

function SalesByCashierView({
  report,
}: {
  report: SalesByCashierResponse | null;
}) {
  if (!report) return <EmptyState message="Loading…" />;
  if (!report.rows.length) {
    return (
      <EmptyState message={`No sales between ${report.from_date} and ${report.to_date}`} />
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
                Sales by Cashier
              </h3>
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