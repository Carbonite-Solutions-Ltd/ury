/**
 * ReturnDialog — issue a full or partial return against a paid POS Invoice.
 *
 * Flow:
 *   1. Loads the original invoice's items via `getReturnPreview`.
 *   2. Shows each item with a quantity stepper (0 → original qty).
 *      Cashier picks which rows + how many to refund.
 *   3. Cashier picks a single refund Mode of Payment.
 *   4. Submit builds a `{row_name, qty}[]` list and POSTs to
 *      `createPosReturn` which wraps ERPNext's `make_return_doc` on
 *      the backend to handle all the accounting gymnastics (negative
 *      taxes, stock reversal, GL entries).
 *
 * See CLAUDE.md "Fixes log" 2026-04-10 (Split + Return features).
 */
import { useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  Loader2,
  Minus,
  Plus,
  RotateCcw,
  X,
} from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Select, SelectItem } from './ui/select';
import {
  createPosReturn,
  getReturnPreview,
  type ReturnPreview,
  type ReturnPreviewItem,
  type ReturnResult,
} from '../lib/invoice-api';
import { usePOSStore } from '../store/pos-store';
import { extractFrappeServerError, formatCurrency } from '../lib/utils';
import { DEFAULT_PAYMENT_MODE } from '../data/order-types';

interface ReturnDialogProps {
  invoiceName: string;
  onCancel: () => void;
  onReturned: (result: ReturnResult) => void;
}

type DialogState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | {
      kind: 'form';
      preview: ReturnPreview;
      picks: Record<string, number>; // row_name -> qty to refund
      refundMode: string;
      notes: string;
    }
  | { kind: 'submitting' }
  | { kind: 'success'; result: ReturnResult };

const clampQty = (value: number, max: number) =>
  Math.max(0, Math.min(max, value));

const ReturnDialog: React.FC<ReturnDialogProps> = ({
  invoiceName,
  onCancel,
  onReturned,
}) => {
  const { paymentModes } = usePOSStore();
  const [state, setState] = useState<DialogState>({ kind: 'loading' });

  // Load the preview on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const preview = await getReturnPreview(invoiceName);
        if (cancelled) return;
        // Default picks = 0 for every row (nothing selected yet).
        const picks: Record<string, number> = {};
        for (const row of preview.items) picks[row.row_name] = 0;

        // Pick a sensible default refund mode: prefer the original
        // invoice's first mode, then the POS default, then whatever's
        // available.
        const firstOriginal = preview.payments[0]?.mode_of_payment;
        const defaultMode =
          firstOriginal && paymentModes.includes(firstOriginal)
            ? firstOriginal
            : paymentModes.includes(DEFAULT_PAYMENT_MODE)
            ? DEFAULT_PAYMENT_MODE
            : paymentModes[0] || DEFAULT_PAYMENT_MODE;

        setState({
          kind: 'form',
          preview,
          picks,
          refundMode: defaultMode,
          notes: '',
        });
      } catch (err) {
        if (cancelled) return;
        const parsed = extractFrappeServerError(
          err,
          'Failed to load invoice details for return.'
        );
        setState({ kind: 'error', message: parsed.message });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [invoiceName, paymentModes]);

  const refundTotal = useMemo(() => {
    if (state.kind !== 'form') return 0;
    return state.preview.items.reduce((sum, item) => {
      const qty = state.picks[item.row_name] || 0;
      return sum + qty * item.rate;
    }, 0);
  }, [state]);

  const anyPicked = useMemo(() => {
    if (state.kind !== 'form') return false;
    return Object.values(state.picks).some((q) => q > 0);
  }, [state]);

  const setPick = (rowName: string, value: number, maxQty: number) => {
    setState((prev) => {
      if (prev.kind !== 'form') return prev;
      return {
        ...prev,
        picks: { ...prev.picks, [rowName]: clampQty(value, maxQty) },
      };
    });
  };

  const incPick = (row: ReturnPreviewItem) => {
    if (state.kind !== 'form') return;
    setPick(row.row_name, (state.picks[row.row_name] || 0) + 1, row.qty_remaining);
  };
  const decPick = (row: ReturnPreviewItem) => {
    if (state.kind !== 'form') return;
    setPick(row.row_name, (state.picks[row.row_name] || 0) - 1, row.qty_remaining);
  };

  const returnAll = () => {
    if (state.kind !== 'form') return;
    const picks: Record<string, number> = {};
    // Only fill rows that still have something to return — exhausted
    // rows (qty_remaining = 0) stay at 0.
    for (const row of state.preview.items) picks[row.row_name] = row.qty_remaining;
    setState({ ...state, picks });
  };
  const clearAll = () => {
    if (state.kind !== 'form') return;
    const picks: Record<string, number> = {};
    for (const row of state.preview.items) picks[row.row_name] = 0;
    setState({ ...state, picks });
  };

  const handleSubmit = async () => {
    if (state.kind !== 'form') return;
    if (!anyPicked) return;

    const items = Object.entries(state.picks)
      .filter(([, qty]) => qty > 0)
      .map(([row_name, qty]) => ({ row_name, qty }));

    setState({ kind: 'submitting' });
    try {
      const result = await createPosReturn(
        invoiceName,
        items,
        state.refundMode,
        state.notes || undefined
      );
      setState({ kind: 'success', result });
      // Give the success state a moment to show, then notify parent.
      setTimeout(() => onReturned(result), 900);
    } catch (err) {
      const parsed = extractFrappeServerError(err, 'Return failed.');
      setState({
        kind: 'error',
        message: parsed.title
          ? `${parsed.title}: ${parsed.message}`
          : parsed.message,
      });
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[92vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-orange-100 text-orange-600">
              <RotateCcw className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-gray-900">Return Order</h2>
              <p className="text-xs text-gray-500">Invoice {invoiceName}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="rounded p-1 text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {state.kind === 'loading' && (
            <div className="flex flex-col items-center justify-center py-12 text-gray-500">
              <Loader2 className="w-6 h-6 animate-spin mb-2" />
              <div className="text-sm">Loading invoice details…</div>
            </div>
          )}

          {state.kind === 'error' && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800">
              <div className="font-semibold text-sm mb-1">
                Couldn't process return
              </div>
              <div className="text-sm">{state.message}</div>
            </div>
          )}

          {state.kind === 'submitting' && (
            <div className="flex flex-col items-center justify-center py-12 text-gray-600">
              <Loader2 className="w-6 h-6 animate-spin mb-2" />
              <div className="text-sm">Processing return…</div>
            </div>
          )}

          {state.kind === 'success' && (
            <div className="flex flex-col items-center justify-center py-12 text-green-700">
              <CheckCircle2 className="w-10 h-10 mb-2" />
              <div className="text-base font-semibold">Return Processed</div>
              <div className="text-xs text-gray-600 mt-1">
                {state.result.return_invoice}
              </div>
              <div className="text-sm font-semibold text-gray-900 mt-2">
                Refund: {formatCurrency(Math.abs(state.result.refund_amount))}
              </div>
            </div>
          )}

          {state.kind === 'form' && (
            <>
              {/* Shortcut bar */}
              <div className="flex items-center justify-between mb-3">
                <div className="text-xs text-gray-600">
                  Pick how much of each item to refund.
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={returnAll}
                    className="text-xs font-semibold text-blue-600 hover:text-blue-800 underline-offset-2 hover:underline"
                  >
                    Return All
                  </button>
                  <span className="text-gray-300">·</span>
                  <button
                    type="button"
                    onClick={clearAll}
                    className="text-xs font-semibold text-gray-500 hover:text-gray-700 underline-offset-2 hover:underline"
                  >
                    Clear
                  </button>
                </div>
              </div>

              {/* Items list */}
              <div className="space-y-2 mb-4">
                {state.preview.items.map((item) => {
                  const qty = state.picks[item.row_name] || 0;
                  const selected = qty > 0;
                  const exhausted = item.qty_remaining <= 0;
                  const partiallyReturned =
                    item.qty_already_returned > 0 && !exhausted;
                  return (
                    <div
                      key={item.row_name}
                      className={`rounded-lg border p-3 transition-colors ${
                        exhausted
                          ? 'border-gray-200 bg-gray-50 opacity-60'
                          : selected
                          ? 'border-orange-300 bg-orange-50'
                          : 'border-gray-200 bg-white'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-semibold text-gray-900 truncate flex items-center gap-2">
                            {item.item_name}
                            {exhausted && (
                              <span className="inline-flex items-center rounded bg-gray-200 px-1.5 py-0.5 text-[10px] font-semibold text-gray-600">
                                Fully Returned
                              </span>
                            )}
                            {partiallyReturned && (
                              <span className="inline-flex items-center rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">
                                Partial
                              </span>
                            )}
                          </div>
                          <div className="text-xs text-gray-500">
                            Original: {item.qty}
                            {item.qty_already_returned > 0 && (
                              <>
                                {' · '}
                                <span className="text-amber-700">
                                  Returned: {item.qty_already_returned}
                                </span>
                                {' · '}
                                <span className="text-gray-700 font-semibold">
                                  Remaining: {item.qty_remaining}
                                </span>
                              </>
                            )}
                            {' · Rate '}
                            {formatCurrency(item.rate)}
                          </div>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <Button
                            type="button"
                            variant="secondary"
                            size="icon"
                            onClick={() => decPick(item)}
                            disabled={qty <= 0 || exhausted}
                            className="h-7 w-7"
                          >
                            <Minus className="w-3 h-3" />
                          </Button>
                          <Input
                            type="number"
                            min={0}
                            max={item.qty_remaining}
                            step="1"
                            value={String(qty)}
                            onChange={(e) =>
                              setPick(
                                item.row_name,
                                parseFloat(e.target.value || '0'),
                                item.qty_remaining
                              )
                            }
                            size="sm"
                            className="w-16 text-center"
                            disabled={exhausted}
                          />
                          <Button
                            type="button"
                            variant="secondary"
                            size="icon"
                            onClick={() => incPick(item)}
                            disabled={qty >= item.qty_remaining || exhausted}
                            className="h-7 w-7"
                          >
                            <Plus className="w-3 h-3" />
                          </Button>
                          <div className="w-20 text-right text-sm font-semibold text-gray-900">
                            {formatCurrency(qty * item.rate)}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Fully-returned banner — all rows exhausted */}
              {state.preview.fully_returned === 1 && (
                <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900 text-xs">
                  Every item on this invoice has already been returned.
                  Nothing left to refund.
                </div>
              )}

              {/* Refund mode + notes */}
              <div className="rounded-lg bg-gray-50 border border-gray-200 p-3 space-y-3">
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    Refund Mode of Payment
                  </label>
                  <Select
                    value={state.refundMode}
                    onValueChange={(v) =>
                      setState((prev) =>
                        prev.kind === 'form' ? { ...prev, refundMode: v } : prev
                      )
                    }
                    size="sm"
                  >
                    {paymentModes.map((m: any) => {
                      const id = typeof m === 'string' ? m : m.id;
                      const label = typeof m === 'string' ? m : m.name;
                      return (
                        <SelectItem key={id} value={id}>
                          {label}
                        </SelectItem>
                      );
                    })}
                  </Select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    Notes (optional)
                  </label>
                  <Input
                    type="text"
                    value={state.notes}
                    onChange={(e) =>
                      setState((prev) =>
                        prev.kind === 'form'
                          ? { ...prev, notes: e.target.value }
                          : prev
                      )
                    }
                    placeholder="Reason / remarks"
                    size="sm"
                  />
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        {state.kind === 'form' && (
          <div className="border-t border-gray-200 px-5 py-4 flex items-center justify-between gap-4">
            <div>
              <div className="text-xs text-gray-500">Refund total</div>
              <div className="text-xl font-bold text-gray-900">
                {formatCurrency(refundTotal)}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button type="button" variant="secondary" onClick={onCancel}>
                Cancel
              </Button>
              <Button
                type="button"
                variant="default"
                onClick={handleSubmit}
                disabled={!anyPicked}
                className="bg-orange-600 hover:bg-orange-700"
              >
                Process Return
              </Button>
            </div>
          </div>
        )}

        {state.kind === 'error' && (
          <div className="border-t border-gray-200 px-5 py-4 flex justify-end">
            <Button type="button" variant="secondary" onClick={onCancel}>
              Close
            </Button>
          </div>
        )}
      </div>
    </div>
  );
};

export default ReturnDialog;
