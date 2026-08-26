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

/**
 * How many separate bills one order can be split into. Raised from 6 on
 * 2026-08-26: a table of fourteen guests each wanting their own receipt is a
 * real, routine request, and the old cap simply refused it.
 */
const MAX_BILLS = 30;

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
  const [activeId, setActiveId] = useState<string>('');
  const [progress, setProgress] = useState<string>('');
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


  // Assign to ONE bill at a time. A column per bill only works for two or
  // three; a table of fourteen columns cannot be read, let alone tapped on
  // a tablet. So the cashier picks a bill and taps items into it.
  const activeBill = bills.find((b) => b.id === activeId) || bills[0];

  const bump = (rowName: string, delta: number) => {
    if (!activeBill) return;
    const row = items.find((i) => i.row_name === rowName);
    if (!row) return;
    const mine = activeBill.alloc[rowName] || 0;
    const others = bills
      .filter((b) => b.id !== activeBill.id)
      .reduce((s2, b) => s2 + (b.alloc[rowName] || 0), 0);
    const next = Math.min(Math.max(0, mine + delta), Math.max(0, row.qty - others));
    setBills((prev) =>
      prev.map((b) =>
        b.id === activeBill.id ? { ...b, alloc: { ...b.alloc, [rowName]: next } } : b
      )
    );
  };

  /** Deal every unit out across the bills, round-robin. */
  const spreadEvenly = () => {
    if (!bills.length) return;
    const fresh = bills.map((b) => ({ ...b, alloc: {} as Record<string, number> }));
    let cursor = 0;
    for (const it of items) {
      // Deal in whole units, but never hand out more than the row holds — a
      // fractional qty (0.5 kg) must not round up into stock that isn't there.
      let remaining = it.qty;
      while (remaining > 1e-6) {
        const take = Math.min(1, remaining);
        const target = fresh[cursor % fresh.length];
        target.alloc[it.row_name] = (target.alloc[it.row_name] || 0) + take;
        remaining -= take;
        cursor += 1;
      }
    }
    setBills(fresh);
  };

  const clearAll = () =>
    setBills((prev) => prev.map((b) => ({ ...b, alloc: {} })));

  const totalUnits = items.reduce((s2, it) => s2 + Math.round(it.qty), 0);
  const assignedUnits = items.reduce(
    (s2, it) => s2 + Math.round(allocatedForRow(it.row_name)),
    0
  );

  /**
   * Jump straight to N bills. A table of fourteen should not mean tapping "+"
   * twelve times — the cashier types the headcount and gets the bills.
   */
  const setBillCount = (raw: string) => {
    const want = Math.round(Number(raw) || 0);
    if (!want) return;
    const n = Math.min(MAX_BILLS, Math.max(2, want));
    setBills((prev) => {
      if (n === prev.length) return prev;
      if (n < prev.length) return prev.slice(0, n);
      const cust = defaultCustomer || source?.customer || '';
      const custName =
        defaultCustomerName || source?.customer_name || source?.customer || '';
      const next = [...prev];
      while (next.length < n) next.push(newBill(cust, custName, defaultMode));
      return next;
    });
  };

  const addBill = () => {
    if (bills.length >= MAX_BILLS) return;
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
      setProgress(`Settling ${payload.length} bills…`);
      const result = await splitInvoiceByItem(sourceInvoice, payload, table);
      // Print each settled bill's itemized receipt in turn. A print
      // failure shouldn't undo the split (the bills are already paid).
      // Printing must stay sequential — receipts would interleave otherwise —
      // so at fourteen bills the cashier needs to see it advancing.
      if (posProfile) {
        let printed = 0;
        for (const billName of result.bills) {
          printed += 1;
          setProgress(`Printing receipt ${printed} of ${result.bills.length}…`);
          try {
            // eslint-disable-next-line no-await-in-loop
            await printOrder({ orderId: billName, posProfile });
          } catch (printErr) {
            console.error('Split receipt print failed:', printErr);
          }
        }
      }
      setProgress('');
      setDone(true);
      showToast.success(
        `Split into ${result.bills.length} bills · paid & printed.`
      );
      setTimeout(() => onComplete(), 900);
    } catch (err) {
      const parsed = extractFrappeServerError(err, 'Split failed.');
      setProgress('');
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
            Set how many bills you need, pick one, then tap items into it.
            Every bill prints its own receipt.
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
          <Input
            type="number"
            min="2"
            max={MAX_BILLS}
            value={bills.length}
            onChange={(e) => setBillCount(e.target.value)}
            disabled={submitting}
            size="sm"
            className="w-16 text-center font-semibold"
            title="How many bills"
          />
          <span className="text-sm text-gray-500">bills</span>
          <Button
            type="button"
            variant="secondary"
            size="icon"
            onClick={addBill}
            disabled={bills.length >= MAX_BILLS}
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

        {/* Progress + bulk actions */}
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
          <div className="text-sm">
            <span
              className={cn(
                'font-semibold',
                fullyAllocated ? 'text-green-600' : 'text-amber-600'
              )}
            >
              {assignedUnits} of {totalUnits}
            </span>{' '}
            <span className="text-gray-500">items assigned</span>
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={spreadEvenly}
              disabled={submitting}
              className="h-7 text-xs"
            >
              Split evenly
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={clearAll}
              disabled={submitting}
              className="h-7 text-xs"
            >
              Clear
            </Button>
          </div>
        </div>

        {/* Bill selector — scrolls sideways, so any number of bills fits */}
        <div className="-mx-1 mb-3 flex gap-2 overflow-x-auto px-1 pb-1">
          {bills.map((b, i) => {
            const count = items.reduce(
              (s2, it) => s2 + Math.round(b.alloc[it.row_name] || 0),
              0
            );
            const isActive = activeBill?.id === b.id;
            return (
              <button
                key={b.id}
                type="button"
                onClick={() => setActiveId(b.id)}
                disabled={submitting}
                className={cn(
                  'shrink-0 rounded-lg border px-3 py-2 text-left transition-colors',
                  isActive
                    ? 'border-blue-600 bg-blue-50 ring-1 ring-blue-600'
                    : count === 0
                      ? // An empty bill blocks the whole settle, so make it
                        // findable at a glance rather than by hunting.
                        'border-amber-400 bg-amber-50 hover:border-amber-500'
                      : 'border-gray-200 bg-white hover:border-gray-300'
                )}
              >
                <div
                  className={cn(
                    'text-xs font-semibold',
                    isActive ? 'text-blue-700' : 'text-gray-700'
                  )}
                >
                  Bill {i + 1}
                </div>
                {count === 0 ? (
                  <div className="text-[11px] font-medium text-amber-600">
                    empty
                  </div>
                ) : (
                  <div className="text-[11px] text-gray-500">
                    {count} item{count === 1 ? '' : 's'} ·{' '}
                    {formatCurrency(billSubtotal(b))}
                  </div>
                )}
              </button>
            );
          })}
        </div>

        {/* Items — tap to add to the bill selected above */}
        <div className="rounded-lg border border-gray-200">
          <div className="border-b border-gray-100 bg-gray-50 px-3 py-1.5 text-xs font-semibold text-gray-500">
            Tap an item to add it to{' '}
            <span className="text-blue-700">
              Bill {bills.findIndex((b) => b.id === activeBill?.id) + 1}
            </span>
          </div>
          {items.map((it) => {
            const left = it.qty - allocatedForRow(it.row_name);
            const mine = activeBill?.alloc[it.row_name] || 0;
            const exhausted = left < 1e-6 && mine < 1e-6;
            return (
              <div
                key={it.row_name}
                onClick={() => !submitting && !exhausted && bump(it.row_name, 1)}
                className={cn(
                  'flex items-center gap-2 border-t border-gray-100 px-3 py-2 first:border-t-0',
                  exhausted
                    ? 'bg-gray-50 opacity-60'
                    : 'cursor-pointer hover:bg-blue-50/50'
                )}
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-gray-900">
                    {it.item_name}
                  </div>
                  <div className="text-xs text-gray-400">
                    {formatCurrency(it.rate)} each · {Number(left.toFixed(2))} of{' '}
                    {it.qty} left
                  </div>
                </div>
                <div
                  className="flex shrink-0 items-center gap-1"
                  onClick={(e) => e.stopPropagation()}
                >
                  <Button
                    type="button"
                    variant="secondary"
                    size="icon"
                    className="h-7 w-7"
                    onClick={() => bump(it.row_name, -1)}
                    disabled={submitting || mine < 1e-6}
                  >
                    <Minus className="h-3.5 w-3.5" />
                  </Button>
                  <span
                    className={cn(
                      'w-7 text-center text-sm font-semibold',
                      mine > 0 ? 'text-blue-700' : 'text-gray-300'
                    )}
                  >
                    {Number(mine.toFixed(2))}
                  </span>
                  <Button
                    type="button"
                    variant="secondary"
                    size="icon"
                    className="h-7 w-7"
                    onClick={() => bump(it.row_name, 1)}
                    disabled={submitting || left < 1e-6}
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            );
          })}
        </div>

        {/* Payer + method for the selected bill */}
        {activeBill && (
          <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50/40 p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-semibold text-gray-900">
                Bill {bills.findIndex((b) => b.id === activeBill.id) + 1} — payer
                &amp; method
              </span>
              <span className="text-sm font-bold text-gray-900">
                ≈ {formatCurrency(billSubtotal(activeBill))}
              </span>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <BillCustomerPicker
                valueName={activeBill.customerName || activeBill.customer}
                onPick={(id, name) =>
                  setBills((prev) =>
                    prev.map((x) =>
                      x.id === activeBill.id
                        ? { ...x, customer: id, customerName: name }
                        : x
                    )
                  )
                }
              />
              <Select
                value={activeBill.mode}
                onValueChange={(v) =>
                  setBills((prev) =>
                    prev.map((x) =>
                      x.id === activeBill.id ? { ...x, mode: v } : x
                    )
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
        )}
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
                <Loader2 className="h-4 w-4 animate-spin" />
                {progress || 'Settling…'}
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
