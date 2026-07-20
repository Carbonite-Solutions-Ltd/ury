import { useEffect, useState } from 'react';
import { Calendar, Receipt, TrendingUp, FileDown, RefreshCw, ShoppingBag } from 'lucide-react';
import { Card, CardContent, Badge, Button } from '../components/ui';
import { Spinner } from '../components/ui/spinner';
import { showToast } from '../components/ui/toast';
import { formatCurrency, cn } from '../lib/utils';
import { getWaiterSales, WaiterSalesReport } from '../lib/waiter-api';

/**
 * "My Sales" — a waiter's own sales report (2026-07-16).
 *
 * Shows the orders she served (self-placed AND rung for her by a cashier)
 * over a selectable date range, with a summary, a per-day breakdown, the
 * order list, and a PDF export (browser print → "Save as PDF", the same
 * pattern the Reports page uses).
 *
 * Scoping is server-side (`get_waiter_sales` resolves her own URY Waiter
 * record), so this page can't show anyone else's numbers.
 */

const todayIso = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate()
  ).padStart(2, '0')}`;
};

const addDays = (iso: string, days: number): string => {
  const d = new Date(iso + 'T00:00:00');
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate()
  ).padStart(2, '0')}`;
};

const startOfMonth = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
};

const prettyDate = (iso: string): string =>
  new Date(iso + 'T00:00:00').toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });

const prettyTime = (t: string | null): string => {
  if (!t) return '';
  // posting_time comes back as "18:19:15.617582"
  const [h, m] = t.split(':');
  const hour = parseInt(h, 10);
  const suffix = hour >= 12 ? 'PM' : 'AM';
  const h12 = hour % 12 === 0 ? 12 : hour % 12;
  return `${h12}:${m} ${suffix}`;
};

/** Escape user-supplied text before injecting into the print HTML. */
const esc = (s: unknown): string =>
  String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

type Preset = 'today' | 'yesterday' | 'last7' | 'month';

export default function WaiterSales() {
  const [fromDate, setFromDate] = useState<string>(todayIso());
  const [toDate, setToDate] = useState<string>(todayIso());
  const [report, setReport] = useState<WaiterSalesReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (from: string, to: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await getWaiterSales(from, to);
      setReport(res);
    } catch (err: any) {
      // Surface the backend's friendly message (e.g. "Not a Waiter").
      const msg =
        err?.message || 'Could not load your sales. Please try again.';
      setError(msg);
      setReport(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(fromDate, toDate);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fromDate, toDate]);

  const applyPreset = (p: Preset) => {
    const today = todayIso();
    if (p === 'today') {
      setFromDate(today);
      setToDate(today);
    } else if (p === 'yesterday') {
      const y = addDays(today, -1);
      setFromDate(y);
      setToDate(y);
    } else if (p === 'last7') {
      setFromDate(addDays(today, -6));
      setToDate(today);
    } else {
      setFromDate(startOfMonth());
      setToDate(today);
    }
  };

  const activePreset = (): Preset | null => {
    const today = todayIso();
    if (fromDate === today && toDate === today) return 'today';
    const y = addDays(today, -1);
    if (fromDate === y && toDate === y) return 'yesterday';
    if (fromDate === addDays(today, -6) && toDate === today) return 'last7';
    if (fromDate === startOfMonth() && toDate === today) return 'month';
    return null;
  };

  const handleDownloadPdf = () => {
    if (!report || report.invoices.length === 0) {
      showToast.error('No sales to export for this date range.');
      return;
    }
    const win = window.open('', '_blank', 'width=900,height=700');
    if (!win) {
      showToast.error('Please allow pop-ups to save the PDF.');
      return;
    }

    const rangeLabel =
      report.from_date === report.to_date
        ? prettyDate(report.from_date)
        : `${prettyDate(report.from_date)} — ${prettyDate(report.to_date)}`;

    const dayRows =
      report.by_day.length > 1
        ? `
        <h2>Daily Breakdown</h2>
        <table>
          <thead><tr><th>Date</th><th class="num">Orders</th><th class="num">Total</th></tr></thead>
          <tbody>
            ${report.by_day
              .map(
                (d) => `<tr>
                  <td>${esc(prettyDate(d.posting_date))}</td>
                  <td class="num">${d.order_count}</td>
                  <td class="num">${esc(formatCurrency(d.total))}</td>
                </tr>`
              )
              .join('')}
          </tbody>
        </table>`
        : '';

    const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>My Sales - ${esc(report.waiter_name)} - ${esc(report.from_date)}</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; color: #111; padding: 28px; }
    h1 { font-size: 20px; margin-bottom: 2px; }
    .sub { color: #555; font-size: 13px; margin-bottom: 18px; }
    h2 { font-size: 14px; margin: 22px 0 8px; text-transform: uppercase; letter-spacing: .04em; color: #444; }
    .cards { display: flex; gap: 12px; margin-bottom: 8px; }
    .card { flex: 1; border: 1px solid #ddd; border-radius: 6px; padding: 12px; }
    .card .label { font-size: 11px; text-transform: uppercase; color: #666; letter-spacing: .04em; }
    .card .value { font-size: 19px; font-weight: 700; margin-top: 4px; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th, td { border-bottom: 1px solid #e5e5e5; padding: 7px 6px; text-align: left; }
    th { background: #f6f6f6; font-size: 11px; text-transform: uppercase; letter-spacing: .03em; color: #444; }
    .num { text-align: right; }
    tfoot td { font-weight: 700; border-top: 2px solid #333; border-bottom: none; }
    .foot { margin-top: 22px; font-size: 11px; color: #777; border-top: 1px solid #e5e5e5; padding-top: 8px; }
    @media print { body { padding: 0; } }
  </style>
</head>
<body>
  <h1>My Sales — ${esc(report.waiter_name)}</h1>
  <div class="sub">${esc(rangeLabel)}</div>

  <div class="cards">
    <div class="card"><div class="label">Orders</div><div class="value">${report.summary.order_count}</div></div>
    <div class="card"><div class="label">Total Sales</div><div class="value">${esc(formatCurrency(report.summary.total_sales))}</div></div>
    <div class="card"><div class="label">Average Order</div><div class="value">${esc(formatCurrency(report.summary.average_order))}</div></div>
  </div>

  ${dayRows}

  <h2>Orders</h2>
  <table>
    <thead>
      <tr>
        <th>Order</th><th>Date</th><th>Time</th><th>Customer</th>
        <th>Table</th><th class="num">Items</th><th class="num">Total</th>
      </tr>
    </thead>
    <tbody>
      ${report.invoices
        .map(
          (inv) => `<tr>
            <td>${esc(inv.name)}</td>
            <td>${esc(inv.posting_date)}</td>
            <td>${esc(prettyTime(inv.posting_time))}</td>
            <td>${esc(inv.customer_name || '')}</td>
            <td>${esc(inv.restaurant_table || (inv.order_type || ''))}</td>
            <td class="num">${inv.items_count}</td>
            <td class="num">${esc(formatCurrency(inv.grand_total))}</td>
          </tr>`
        )
        .join('')}
    </tbody>
    <tfoot>
      <tr>
        <td colspan="6">Total (${report.summary.order_count} orders)</td>
        <td class="num">${esc(formatCurrency(report.summary.total_sales))}</td>
      </tr>
    </tfoot>
  </table>

  <div class="foot">Generated ${esc(new Date().toLocaleString())}</div>
  <script>
    window.onload = function () {
      window.print();
      window.onafterprint = function () { window.close(); };
    };
  </script>
</body>
</html>`;

    win.document.write(html);
    win.document.close();
  };

  const preset = activePreset();
  const presetBtn = (p: Preset, label: string) => (
    <button
      key={p}
      onClick={() => applyPreset(p)}
      className={cn(
        'shrink-0 px-3 py-1.5 rounded-full text-xs font-medium transition-colors whitespace-nowrap',
        preset === p
          ? 'bg-blue-600 text-white'
          : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
      )}
    >
      {label}
    </button>
  );

  return (
    <div className="flex flex-col h-full bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-4 sm:px-6 py-3 shrink-0">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-lg sm:text-xl font-semibold text-gray-900 truncate">
              My Sales
            </h1>
            {report && (
              <p className="text-xs text-gray-500 truncate">
                {report.waiter_name}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button
              variant="outline"
              size="sm"
              onClick={() => load(fromDate, toDate)}
              disabled={loading}
              className="border-gray-300 text-gray-700"
            >
              <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
            </Button>
            <Button
              size="sm"
              onClick={handleDownloadPdf}
              disabled={loading || !report || report.invoices.length === 0}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              <FileDown className="w-4 h-4 mr-1.5" />
              PDF
            </Button>
          </div>
        </div>

        {/* Presets */}
        <div className="mt-3 flex items-center gap-2 overflow-x-auto pb-0.5">
          {presetBtn('today', 'Today')}
          {presetBtn('yesterday', 'Yesterday')}
          {presetBtn('last7', 'Last 7 days')}
          {presetBtn('month', 'This month')}
        </div>

        {/* Date range */}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5">
            <Calendar className="w-4 h-4 text-gray-400" />
            <input
              type="date"
              value={fromDate}
              max={toDate}
              onChange={(e) => setFromDate(e.target.value)}
              className="px-2 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <span className="text-gray-400 text-sm">to</span>
          <input
            type="date"
            value={toDate}
            min={fromDate}
            max={todayIso()}
            onChange={(e) => setToDate(e.target.value)}
            className="px-2 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        {loading ? (
          <div className="flex items-center justify-center h-64">
            <Spinner message="Loading your sales..." />
          </div>
        ) : error ? (
          <div className="max-w-md mx-auto text-center py-12">
            <Receipt className="w-12 h-12 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-800 font-medium">{error}</p>
          </div>
        ) : !report || report.invoices.length === 0 ? (
          <div className="text-center py-12">
            <ShoppingBag className="w-14 h-14 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-600 text-lg font-medium">No sales yet</p>
            <p className="text-gray-400 text-sm mt-1">
              Paid orders you served in this date range will show up here.
            </p>
          </div>
        ) : (
          <div className="max-w-4xl mx-auto space-y-4">
            {/* Summary */}
            <div className="grid grid-cols-3 gap-2 sm:gap-3">
              <Card>
                <CardContent className="p-3 sm:p-4">
                  <p className="text-[11px] uppercase tracking-wide text-gray-500">
                    Orders
                  </p>
                  <p className="mt-1 text-xl sm:text-2xl font-bold text-gray-900">
                    {report.summary.order_count}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-3 sm:p-4">
                  <p className="text-[11px] uppercase tracking-wide text-gray-500">
                    Total Sales
                  </p>
                  <p className="mt-1 text-xl sm:text-2xl font-bold text-green-700">
                    {formatCurrency(report.summary.total_sales)}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-3 sm:p-4">
                  <p className="text-[11px] uppercase tracking-wide text-gray-500">
                    Avg Order
                  </p>
                  <p className="mt-1 text-xl sm:text-2xl font-bold text-gray-900">
                    {formatCurrency(report.summary.average_order)}
                  </p>
                </CardContent>
              </Card>
            </div>

            {/* Daily breakdown (multi-day ranges only) */}
            {report.by_day.length > 1 && (
              <Card>
                <CardContent className="p-0">
                  <div className="px-4 py-3 border-b border-gray-200 flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-gray-500" />
                    <h2 className="text-sm font-semibold text-gray-900">
                      Daily Breakdown
                    </h2>
                  </div>
                  <div className="divide-y divide-gray-100">
                    {report.by_day.map((d) => (
                      <div
                        key={d.posting_date}
                        className="px-4 py-2.5 flex items-center justify-between text-sm"
                      >
                        <span className="text-gray-700">
                          {prettyDate(d.posting_date)}
                        </span>
                        <span className="flex items-center gap-3">
                          <span className="text-xs text-gray-500">
                            {d.order_count}{' '}
                            {d.order_count === 1 ? 'order' : 'orders'}
                          </span>
                          <span className="font-semibold text-gray-900 tabular-nums">
                            {formatCurrency(d.total)}
                          </span>
                        </span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Orders */}
            <Card>
              <CardContent className="p-0">
                <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-gray-900">Orders</h2>
                  <Badge variant="default" className="bg-gray-600">
                    {report.invoices.length}
                  </Badge>
                </div>
                <div className="divide-y divide-gray-100">
                  {report.invoices.map((inv) => (
                    <div key={inv.name} className="px-4 py-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="font-medium text-gray-900 text-sm truncate">
                            {inv.name}
                          </p>
                          <p className="text-xs text-gray-500 mt-0.5 truncate">
                            {inv.customer_name || 'Customer'}
                            {inv.restaurant_table
                              ? ` · Table ${inv.restaurant_table}`
                              : inv.order_type
                              ? ` · ${inv.order_type}`
                              : ''}
                            {` · ${inv.items_count} item${
                              inv.items_count === 1 ? '' : 's'
                            }`}
                          </p>
                        </div>
                        <div className="text-right shrink-0">
                          <p className="font-semibold text-gray-900 tabular-nums">
                            {formatCurrency(inv.grand_total)}
                          </p>
                          <p className="text-xs text-gray-400">
                            {inv.posting_date} · {prettyTime(inv.posting_time)}
                          </p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}
