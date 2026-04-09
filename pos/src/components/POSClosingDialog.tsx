/**
 * In-POS POS Closing Entry dialog. Replaces the deep-link-to-desk
 * fallback used by the Existing-Entry branch of POSOpeningDialog and by
 * the ShiftHoursBanner's "Close Shift" button.
 *
 * Backed by two whitelisted endpoints:
 *   - `ury.ury_pos.api.preview_pos_closing_entry(opening_entry)` — wraps
 *     ERPNext's `make_closing_entry_from_opening` and returns the
 *     prefilled payment rows (opening + expected per mode).
 *   - `ury.ury_pos.api.submit_pos_closing_entry(opening_entry, closing_amounts)`
 *     — sets the user's counted amounts onto the doc and submits it.
 *
 * The dialog renders one row per payment mode showing:
 *   - opening_amount (read-only, from the opening entry's balance_details)
 *   - expected_amount (read-only, what ERPNext computed from POS Invoices)
 *   - closing_amount (editable, defaults to expected so a one-click
 *     "matches expected" close works)
 *   - difference (live-computed, color-coded)
 *
 * See CLAUDE.md "Fixes log" 2026-04-09.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  DoorClosed,
  Loader2,
  X,
} from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import {
  previewClosingEntry,
  submitClosingEntry,
  type POSClosingPaymentRow,
  type POSClosingPreview,
} from '../lib/pos-closing-api';
import { extractFrappeServerError, formatCurrency } from '../lib/utils';

interface POSClosingDialogProps {
  /** Name of the POS Opening Entry to close. */
  openingEntry: string;
  /** Called when the cashier closes the modal without submitting. */
  onCancel: () => void;
  /** Called after a successful submit, with the new closing entry's name. */
  onClosed: (closingEntryName: string) => void;
}

type DialogState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'form'; preview: POSClosingPreview; rows: POSClosingPaymentRow[] }
  | { kind: 'submitting' }
  | { kind: 'success'; closingEntryName: string };

const POSClosingDialog = ({
  openingEntry,
  onCancel,
  onClosed,
}: POSClosingDialogProps) => {
  const [state, setState] = useState<DialogState>({ kind: 'loading' });
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Initial preview fetch.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const preview = await previewClosingEntry(openingEntry);
        if (cancelled) return;
        setState({
          kind: 'form',
          preview,
          rows: preview.payments.map((p) => ({ ...p })),
        });
      } catch (err) {
        if (cancelled) return;
        const parsed = extractFrappeServerError(
          err,
          'Failed to load closing details.'
        );
        setState({ kind: 'error', message: parsed.message });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [openingEntry]);

  const handleSubmit = async () => {
    if (state.kind !== 'form') return;
    setSubmitError(null);
    setState({ kind: 'submitting' });

    try {
      const closingAmounts: Record<string, number> = {};
      for (const row of state.rows) {
        closingAmounts[row.mode_of_payment] = Number(row.closing_amount) || 0;
      }
      const res = await submitClosingEntry(openingEntry, closingAmounts);
      setState({ kind: 'success', closingEntryName: res.name });
      // Brief confirmation flash, then hand control back to the parent.
      setTimeout(() => onClosed(res.name), 800);
    } catch (err) {
      const parsed = extractFrappeServerError(
        err,
        'Failed to submit closing entry. Please try again.'
      );
      setSubmitError(parsed.message);
      // Restore the form state so the user can edit and retry.
      // We re-derive from the last good preview/rows we had.
      setState((current) => {
        if (current.kind === 'submitting' || current.kind === 'success') {
          // Re-fetch from scratch to be safe — ERPNext may have rejected
          // due to a state change we don't know about.
          return { kind: 'loading' };
        }
        return current;
      });
      // Trigger a re-fetch by re-running the effect via a key change.
      // Simplest approach: re-set state to loading and the useEffect
      // dependency on openingEntry won't fire again, so manually re-run.
      (async () => {
        try {
          const preview = await previewClosingEntry(openingEntry);
          setState({
            kind: 'form',
            preview,
            rows: preview.payments.map((p) => ({ ...p })),
          });
        } catch (innerErr) {
          const innerParsed = extractFrappeServerError(
            innerErr,
            'Failed to reload closing details.'
          );
          setState({ kind: 'error', message: innerParsed.message });
        }
      })();
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl p-8 max-w-4xl w-full mx-4 shadow-2xl max-h-[92vh] flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between mb-6 shrink-0">
          <div className="flex items-center gap-4">
            <div className="flex items-center justify-center h-14 w-14 rounded-full bg-orange-100">
              <DoorClosed className="h-7 w-7 text-orange-600" />
            </div>
            <div>
              <h2 className="text-2xl font-bold text-gray-900">Close POS Shift</h2>
              <p className="text-sm text-gray-500 mt-0.5">
                Entry: {openingEntry}
              </p>
            </div>
          </div>
          {state.kind !== 'submitting' && state.kind !== 'success' && (
            <button
              onClick={onCancel}
              className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
              aria-label="Cancel"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 overflow-y-auto">
          {state.kind === 'loading' && <LoadingBody />}
          {state.kind === 'error' && <ErrorBody message={state.message} />}
          {state.kind === 'form' && (
            <FormBody
              preview={state.preview}
              rows={state.rows}
              submitError={submitError}
              onUpdateRow={(idx, value) => {
                setState((cur) => {
                  if (cur.kind !== 'form') return cur;
                  const next = cur.rows.map((r, i) =>
                    i === idx
                      ? { ...r, closing_amount: parseAmount(value, r.closing_amount) }
                      : r
                  );
                  return { ...cur, rows: next };
                });
              }}
            />
          )}
          {state.kind === 'submitting' && <SubmittingBody />}
          {state.kind === 'success' && (
            <SuccessBody closingEntryName={state.closingEntryName} />
          )}
        </div>

        {/* Footer */}
        {state.kind === 'form' && (
          <div className="flex gap-3 mt-6 pt-4 border-t border-gray-100 shrink-0">
            <Button
              onClick={onCancel}
              variant="outline"
              className="flex-1 border-gray-300 text-gray-700 hover:bg-gray-50 font-medium py-3 text-base rounded-lg"
            >
              Cancel
            </Button>
            <Button
              onClick={handleSubmit}
              className="flex-1 bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 text-base rounded-lg"
            >
              <DoorClosed className="w-5 h-5 mr-2" />
              Close Shift
            </Button>
          </div>
        )}
        {state.kind === 'error' && (
          <div className="flex gap-3 mt-6 pt-4 border-t border-gray-100 shrink-0">
            <Button
              onClick={onCancel}
              variant="outline"
              className="flex-1 border-gray-300 text-gray-700 hover:bg-gray-50 font-medium py-3 text-base rounded-lg"
            >
              Close
            </Button>
          </div>
        )}
      </div>
    </div>
  );
};

const parseAmount = (raw: string, fallback: number): number => {
  if (raw === '' || raw === '-') return 0;
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
};

// ───── body subcomponents ─────

const LoadingBody = () => (
  <div className="flex items-center justify-center py-12">
    <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
    <span className="ml-3 text-sm text-gray-500">
      Calculating shift totals…
    </span>
  </div>
);

const ErrorBody = ({ message }: { message: string }) => (
  <div className="p-4 rounded-lg bg-red-50 border border-red-200 flex gap-3">
    <AlertTriangle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
    <div className="text-sm text-red-700">{message}</div>
  </div>
);

const SubmittingBody = () => (
  <div className="flex items-center justify-center py-12">
    <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
    <span className="ml-3 text-sm text-gray-500">Submitting…</span>
  </div>
);

const SuccessBody = ({
  closingEntryName,
}: {
  closingEntryName: string;
}) => (
  <div className="text-center py-8">
    <div className="inline-flex items-center justify-center h-14 w-14 rounded-full bg-green-100 mb-3">
      <CheckCircle2 className="h-7 w-7 text-green-600" />
    </div>
    <div className="text-lg font-semibold text-gray-900">Shift Closed</div>
    <div className="text-xs text-gray-500 mt-1">
      Closing Entry: {closingEntryName}
    </div>
  </div>
);

interface FormBodyProps {
  preview: POSClosingPreview;
  rows: POSClosingPaymentRow[];
  submitError: string | null;
  onUpdateRow: (idx: number, value: string) => void;
}

const FormBody = ({
  preview,
  rows,
  submitError,
  onUpdateRow,
}: FormBodyProps) => {
  const totalDifference = useMemo(
    () =>
      rows.reduce(
        (sum, r) => sum + ((Number(r.closing_amount) || 0) - (Number(r.expected_amount) || 0)),
        0
      ),
    [rows]
  );

  return (
    <div>
      {/* Summary stats */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <SummaryStat
          label="Invoices"
          value={String(preview.invoice_count)}
        />
        <SummaryStat
          label="Grand Total"
          value={formatCurrency(preview.grand_total)}
        />
        <SummaryStat label="Net Total" value={formatCurrency(preview.net_total)} />
      </div>

      {/* Payment reconciliation */}
      <div className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-3">
        Payment Reconciliation
      </div>
      {rows.length === 0 ? (
        <div className="text-sm text-gray-400 italic py-6">
          No payment modes recorded for this shift.
        </div>
      ) : (
        <div className="rounded-lg border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs text-gray-600 uppercase">
              <tr>
                <th className="text-left px-4 py-3 font-medium">Mode</th>
                <th className="text-right px-3 py-3 font-medium">Opening</th>
                <th className="text-right px-3 py-3 font-medium">Expected</th>
                <th className="text-right px-3 py-3 font-medium">Counted</th>
                <th className="text-right px-4 py-3 font-medium">Diff</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((row, idx) => {
                const diff =
                  (Number(row.closing_amount) || 0) -
                  (Number(row.expected_amount) || 0);
                const diffColor =
                  diff === 0
                    ? 'text-gray-500'
                    : diff > 0
                    ? 'text-green-600'
                    : 'text-red-600';
                return (
                  <tr key={row.mode_of_payment}>
                    <td className="px-4 py-3 text-gray-800 font-medium">
                      {row.mode_of_payment}
                    </td>
                    <td className="px-3 py-3 text-right text-gray-500 tabular-nums">
                      {formatCurrency(row.opening_amount)}
                    </td>
                    <td className="px-3 py-3 text-right text-gray-700 tabular-nums">
                      {formatCurrency(row.expected_amount)}
                    </td>
                    <td className="px-3 py-3 text-right">
                      <Input
                        type="number"
                        step="0.01"
                        value={row.closing_amount}
                        onChange={(e) => onUpdateRow(idx, e.target.value)}
                        className="w-32 text-right h-9 px-3 ml-auto tabular-nums"
                      />
                    </td>
                    <td
                      className={`px-4 py-3 text-right tabular-nums font-semibold ${diffColor}`}
                    >
                      {diff > 0 ? '+' : ''}
                      {formatCurrency(diff)}
                    </td>
                  </tr>
                );
              })}
              <tr className="bg-gray-50">
                <td
                  colSpan={4}
                  className="px-4 py-3 text-right text-xs uppercase tracking-wide text-gray-500 font-semibold"
                >
                  Net Difference
                </td>
                <td
                  className={`px-4 py-3 text-right tabular-nums font-bold text-base ${
                    totalDifference === 0
                      ? 'text-gray-700'
                      : totalDifference > 0
                      ? 'text-green-600'
                      : 'text-red-600'
                  }`}
                >
                  {totalDifference > 0 ? '+' : ''}
                  {formatCurrency(totalDifference)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {submitError && (
        <div className="mt-4 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
          {submitError}
        </div>
      )}
    </div>
  );
};

const SummaryStat = ({ label, value }: { label: string; value: string }) => (
  <div className="rounded-lg bg-gray-50 border border-gray-200 px-4 py-3">
    <div className="text-[11px] uppercase tracking-wide text-gray-500 font-medium">
      {label}
    </div>
    <div className="text-lg font-semibold text-gray-900 truncate mt-1">
      {value}
    </div>
  </div>
);

export default POSClosingDialog;
