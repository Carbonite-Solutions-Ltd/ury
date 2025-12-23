import React, { useEffect, useState, useRef } from 'react';
import { 
  TrendingUp, 
  DollarSign, 
  ShoppingCart, 
  Users, 
  Calendar,
  Printer,
  RefreshCw
} from 'lucide-react';
import { Card, CardContent, Badge } from '../components/ui';
import { Button } from '../components/ui/button';
import { Spinner } from '../components/ui/spinner';
import { call } from '../lib/frappe-sdk';
import { formatCurrency } from '../lib/utils';
import { showToast } from '../components/ui/toast';

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

export default function Reports() {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'daily-sales'>('dashboard');
  const [loading, setLoading] = useState(false);
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().split('T')[0]);
  const [dashboardStats, setDashboardStats] = useState<DashboardStats | null>(null);
  const [salesInvoices, setSalesInvoices] = useState<SalesInvoice[]>([]);
  const [error, setError] = useState<string | null>(null);
  const printRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (activeTab === 'dashboard') {
      fetchDashboardStats();
    } else if (activeTab === 'daily-sales') {
      fetchDailySales();
    }
  }, [activeTab, selectedDate]);

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
      setSalesInvoices(response.message || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch daily sales');
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = () => {
    if (activeTab === 'dashboard') {
      fetchDashboardStats();
    } else {
      fetchDailySales();
    }
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
            margin-bottom: 30px;
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
            {/* Date Picker */}
            <div className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2 border border-gray-200">
              <Calendar className="w-4 h-4 text-gray-500" />
              <input
                type="date"
                value={selectedDate}
                onChange={(e) => setSelectedDate(e.target.value)}
                className="text-sm bg-transparent border-none focus:outline-none"
              />
            </div>
            
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
          <div className="flex space-x-8">
            <button
              onClick={() => setActiveTab('dashboard')}
              className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === 'dashboard'
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <TrendingUp className="w-5 h-5" />
                <span>Dashboard</span>
              </div>
            </button>
            <button
              onClick={() => setActiveTab('daily-sales')}
              className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === 'daily-sales'
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <ShoppingCart className="w-5 h-5" />
                <span>Daily Sales</span>
              </div>
            </button>
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
            )}
          </div>
        )}
      </div>
    </div>
  );
}