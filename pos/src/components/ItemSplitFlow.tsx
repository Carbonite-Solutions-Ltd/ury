import React, { useEffect, useMemo, useState } from 'react';
import { Plus, Minus, Loader2, CheckCircle2, User, Search } from 'lucide-react';
import { cn, formatCurrency, extractFrappeServerError } from '../lib/utils';
import { Button, Input, Select, SelectItem } from './ui';
import { showToast } from './ui/toast';
import {
  getOrderItemsForSplit,
  splitInvoiceByItem,
  type SplitSource,
  type SplitBill,
} from '../lib/split-api';
import { searchCustomers } from '../lib/customer-api';
import { printOrder } from '../lib/print';
import type { PosProfileCombined } from '../lib/pos-profile-api';

interface ItemSplitFlowProps {
  sourceInvoice: string;
  table: string | null;
  defaultCustomer: string;
  defaultCustomerName: string;
  posProfile: PosProfileCombined | null;
  paymentModes: string[];
  defaultMode: string;
  /** Called to dismiss the whole Payment dialog. */
  onCancel: () => void;
  /** Called after a successful split (refresh Orders + clear selection). */
  onComplete: () => void;
}

interface Bill {
  id: string;
  customer: string;
  customerName: string;
  mode: string;
  /** row_name -> allocated qty */
  alloc: Record<string, number>;
}

const newBill = (
  customer: string,
  customerName: string,
  mode: string
): Bill => ({
  id: `b-${Math.random().toString(36).slice(2, 9)}`,
  customer,
  customerName,
  mode,
  alloc: {},
});

/** Small per-bill customer picker — reuses the global customer search. */
const BillCustomerPicker: React.FC<{
  valueName: string;
  onPick: (id: string, name: string) => void;
}> = ({ valueName, onPick }) => {
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    if (!open || !term.trim()) {
      setResults([]);
      return;
    }
    setSearching(true);
    const h = setTimeout(() => {
      searchCustomers(term)
        .then((r) => {
          setResults(r);
          setSearching(false);
        })
        .catch(() => setSearching(false));
    }, 300);
    return () => clearTimeout(h);
  }, [term, open]);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2 py-1.5 text-left text-xs hover:border-gray-300"
      >
        <User className="h-3.5 w-3.5 shrink-0 text-gray-400" />
        <span className="truncate font-medium text-gray-800">{valueName}</span>
      </button>
      {open && (
        <div className="absolute z-20 mt-1 w-64 rounded-lg border border-gray-200 bg-white p-2 shadow-lg">
          <div className="flex items-center gap-1.5 rounded-md border border-gray-200 px-2">
            <Search className="h-3.5 w-3.5 text-gray-400" />
            <input
              autoFocus
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              placeholder="Search customer..."
              className="w-full py-1.5 text-xs outline-none"
            />
          </div>
          <div className="mt-1 max-h-40 overflow-y-auto">
            {searching && (
              <div className="px-2 py-2 text-xs text-gray-400">Searching…</div>
            )}
            {!searching && results.length === 0 && term.trim() && (
              <div className="px-2 py-2 text-xs text-gray-400">No matches.</div>
            )}
            {results.map((c: any) => {
              const name =
                c.content?.match(/Customer Name : ([^|]+)/)?.[1]?.trim() ||
                c.name;
              return (
                <button
                  key={c.name}
                  type="button"
                  onClick={() => {
                    onPick(c.name, name);
                    setOpen(false);
                    setTerm('');
                  }}
                  className="block w-full truncate rounded px-2 py-1.5 text-left text-xs hover:bg-blue-50"
                >
                  {name}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

const ItemSplitFlow: React.FC<ItemSplitFlowProps> = ({
  sourceInvoice,
  table,
  defaultCustomer,
  defaultCustomerName,
  posProfile,
  paymentModes,
  defaultMode,
  onCancel,
  onComplete,
}) => {
  const [source, setSource] = useState<SplitSource | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [bills, setBills] = useState<Bill[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getOrderItemsForSplit(sourceInvoice)
      .then((s) => {
        if (!active) return;
        setSource(s);
        const cust = defaultCustomer || s.customer;
        const custName = defaultCustomerName || s.customer_name || s.customer;
        setBills([
          newBill(cust, custName, defaultMode),
          newBill(cust, custName, defaultMode),
        ]);
      })
      .catch((err) => {
        if (!active) return;
        const parsed = extractFrappeServerError(err, 'Failed to load order.');
        setLoadError(parsed.message);
      });
    return () => {
      active = false;
    };
  }, [sourceInvoice, defaultCustomer, defaultCustomerName, defaultMode]);

  const items = source?.items || [];

  const allocatedForRow = (rowName: string) =>
    bills.reduce((s, b) => s + (b.alloc[rowName] || 0), 0);

  const billSubtotal = (bill: Bill) =>
    items.reduce(
      (s, it) => s + (bill.alloc[it.row_name] || 0) * it.rate,
      0
    );

  const setAlloc = (billId: string, rowName: string, raw: string) => {
    const row = items.find((i) => i.row_name === rowName);
    if (!row) return;
    let v = Math.max(0, Number(raw) || 0);
    const others = bills
      .filter((b) => b.id !== billId)
      .reduce((s, b) => s + (b.alloc[rowName] || 0), 0);
    v = Math.min(v, Math.max(0, row.qty - others));
    setBills((prev) =>
      prev.map((b) =>
        b.id === billId ? { ...b, alloc: { ...b.alloc, [rowName]: v } } : b
      )
    );
  };

  const addBill = () => {
    if (bills.length >= 6) return;
    const cust = defaultCustomer || source?.customer || '';
    const custName =
      defaultCustomerName || source?.customer_name || source?.customer || '';
    setBills((prev) => [...prev, newBill(cust, custName, defaultMode)]);
  };

  const removeBill = (id: string) => {
    if (bills.length <= 2) return;
    setBills((prev) => prev.filter((b) => b.id !== id));
  };

  const fullyAllocated = useMemo(
    () =>
      items.length > 0 &&
      items.every((it) => Math.abs(it.qty - allocatedForRow(it.row_name)) < 1e-6),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [items, bills]
  );
  const everyBillHasItems = bills.every((b) =>
    Object.values(b.alloc).some((q) => q > 0)
  );
  const everyBillHasMode = bills.every((b) => !!b.mode);
  const canSubmit =
    fullyAllocated && everyBillHasItems && everyBillHasMode && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit || !source) return;
    setSubmitting(true);
    setError(null);
    const payload: SplitBill[] = bills.map((b) => ({
      customer: b.customer,
      payment_mode: b.mode,
      allocations: items
        .filter((it) => (b.alloc[it.row_name] || 0) > 0)
        .map((it) => ({ source_row: it.row_name, qty: b.alloc[it.row_name] })),
    }));
    try {
      const result = await splitInvoiceByItem(sourceInvoice, payload, table);
      // Print each settled bill's itemized receipt in turn. A print
      // failure shouldn't undo the split (the bills are already paid).
      if (posProfile) {
        for (const billName of result.bills) {
          try {
            // eslint-disable-next-line no-await-in-loop
            await printOrder({ orderId: billName, posProfile });
          } catch (printErr) {
            console.error('Split receipt print failed:', printErr);
          }
        }
      }
      setDone(true);
      showToast.success(
        `Split into ${result.bills.length} bills · paid & printed.`
      );
      setTimeout(() => onComplete(), 900);
    } catch (err) {
      const parsed = extractFrappeServerError(err, 'Split failed.');
      setError(parsed.message);
      showToast.error({
        title: parsed.title || 'Split Failed',
        description: parsed.message,
      });
      setSubmitting(false);
    }
  };

  if (loadError) {
    return (
      <div className="p-8 text-center">
        <p className="text-sm text-red-600">{loadError}</p>
        <Button onClick={onCancel} variant="secondary" className="mt-4">
          Close
        </Button>
      </div>
    );
  }

  if (!source) {
    return (
      <div className="flex items-center justify-center gap-2 p-12 text-gray-500">
        <Loader2 className="h-5 w-5 animate-spin" /> Loading order…
      </div>
    );
  }

  if (done) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 p-12">
        <CheckCircle2 className="h-12 w-12 text-green-500" />
        <p className="text-lg font-semibold text-gray-900">Split complete</p>
        <p className="text-sm text-gray-500">Receipts sent to the printer.</p>
      </div>
    );
  }

  return (
    <div className="flex max-h-[88vh] flex-col">
      <div className="flex items-center justify-between border-b border-gray-200 p-4">
        <div>
          <h2 className="text-xl font-bold text-gray-900">Split by Item</h2>
          <p className="text-xs text-gray-500">
            Assign every item to a bill, pick a payer + payment method, then
            settle all bills at once.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="secondary"
            size="icon"
            onClick={() => removeBill(bills[bills.length - 1].id)}
            disabled={bills.length <= 2}
            className="h-8 w-8"
            title="Remove bill"
          >
            <Minus className="h-4 w-4" />
          </Button>
          <span className="min-w-[3.5rem] text-center text-sm font-semibold">
            {bills.length} bills
          </span>
          <Button
            type="button"
            variant="secondary"
            size="icon"
            onClick={addBill}
            disabled={bills.length >= 6}
            className="h-8 w-8"
            title="Add bill"
          >
            <Plus className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {error && (
          <div className="mb-3 rounded-lg border border-red-200 bg-red-50 p-2.5 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Allocation matrix */}
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500">
              <tr>
                <th className="px-3 py-2 text-left font-semibold">Item</th>
                <th className="px-2 py-2 text-center font-semibold">Total</th>
                {bills.map((_, i) => (
                  <th key={i} className="px-2 py-2 text-center font-semibold">
                    Bill {i + 1}
                  </th>
                ))}
                <th className="px-2 py-2 text-center font-semibold">Left</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => {
                const left = it.qty - allocatedForRow(it.row_name);
                return (
                  <tr key={it.row_name} className="border-t border-gray-100">
                    <td className="px-3 py-2">
                      <div className="font-medium text-gray-900">
                        {it.item_name}
                      </div>
                      <div className="text-xs text-gray-400">
                        {formatCurrency(it.rate)} each
                      </div>
                    </td>
                    <td className="px-2 py-2 text-center text-gray-600">
                      {it.qty}
                    </td>
                    {bills.map((b) => (
                      <td key={b.id} className="px-2 py-2">
                        <Input
                          type="number"
                          min="0"
                          step="any"
                          value={b.alloc[it.row_name] || ''}
                          onChange={(e) =>
                            setAlloc(b.id, it.row_name, e.target.value)
                          }
                          size="sm"
                          className="w-16 text-center"
                          disabled={submitting}
                        />
                      </td>
                    ))}
                    <td
                      className={cn(
                        'px-2 py-2 text-center text-xs font-semibold',
                        Math.abs(left) < 1e-6
                          ? 'text-green-600'
                          : 'text-amber-600'
                      )}
                    >
                      {Number(left.toFixed(2))}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Per-bill cards */}
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {bills.map((b, i) => (
            <div
              key={b.id}
              className="rounded-lg border border-gray-200 bg-gray-50/60 p-3"
            >
              <div className="mb-2 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-600 text-xs font-bold text-white">
                    {i + 1}
                  </div>
                  <span className="text-sm font-semibold text-gray-900">
                    Bill {i + 1}
                  </span>
                </div>
                <span className="text-sm font-bold text-gray-900">
                  ≈ {formatCurrency(billSubtotal(b))}
                </span>
              </div>
              <div className="space-y-2">
                <BillCustomerPicker
                  valueName={b.customerName || b.customer}
                  onPick={(id, name) =>
                    setBills((prev) =>
                      prev.map((x) =>
                        x.id === b.id
                          ? { ...x, customer: id, customerName: name }
                          : x
                      )
                    )
                  }
                />
                <Select
                  value={b.mode}
                  onValueChange={(v) =>
                    setBills((prev) =>
                      prev.map((x) => (x.id === b.id ? { ...x, mode: v } : x))
                    )
                  }
                  disabled={submitting}
                  size="sm"
                >
                  {paymentModes.map((m) => (
                    <SelectItem key={m} value={m}>
                      {m}
                    </SelectItem>
                  ))}
                </Select>
              </div>
              <div className="mt-1 text-[11px] text-gray-400">
                Exact total (incl. tax) is computed at settlement.
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-gray-200 p-4">
        <div className="text-xs">
          {!fullyAllocated ? (
            <span className="text-amber-600">
              Allocate every item before settling.
            </span>
          ) : !everyBillHasItems ? (
            <span className="text-amber-600">Every bill needs at least one item.</span>
          ) : (
            <span className="text-green-600 font-semibold">
              Ready — all items allocated.
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {submitting ? (
              <span className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" /> Settling…
              </span>
            ) : (
              `Complete Split & Pay (${bills.length})`
            )}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default ItemSplitFlow;
