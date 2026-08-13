import { useEffect, useState } from 'react';
import { AlertTriangle, Loader2, Wallet, X } from 'lucide-react';
import { Button } from './ui/button';
import { showToast } from './ui/toast';
import { extractFrappeServerError, formatCurrency } from '../lib/utils';
import {
  changeInvoicePaymentMode,
  getInvoicePaymentRows,
  type InvoicePaymentsResponse,
} from '../lib/invoice-api';

/**
 * Correct the mode of payment on a settled bill.
 *
 * Exists because a cashier who takes cash but taps "Card" previously had
 * no way to put it right, leaving the till short on one tender and long
 * on another.
 *
 * The window is deliberately narrow and enforced server-side: only
 * BEFORE the bill is consolidated into the accounts at shift close. A
 * POS Invoice posts no GL of its own, so until consolidation this is a
 * clean correction; afterwards the money is already booked against the
 * old account and editing here would silently desync the POS from the
 * ledger. The dialog asks the backend whether it's allowed rather than
 * guessing, and shows the reason when it isn't.
 */
const ChangePaymentModeDialog = ({
  invoice,
  onClose,
  onChanged,
}: {
  invoice: string;
  onClose: () => void;
  onChanged: () => void;
}) => {
  const [data, setData] = useState<InvoicePaymentsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string>('');
  const [mode, setMode] = useState<string>('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getInvoicePaymentRows(invoice)
      .then((d) => {
        setData(d);
        // One tender is the common case — preselect it so the cashier
        // only has to pick the correct method.
        if (d.rows.length === 1) {
          setSelected(d.rows[0].row);
          setMode(d.rows[0].mode_of_payment);
        }
      })
      .catch((err) =>
        setError(extractFrappeServerError(err, 'Could not load the payment.').message)
      );
  }, [invoice]);

  const current = data?.rows.find((r) => r.row === selected);
  const dirty = !!current && mode !== current.mode_of_payment;

  const submit = async () => {
    if (!selected || !dirty) return;
    setSaving(true);
    try {
      const res = await changeInvoicePaymentMode(invoice, selected, mode);
      showToast.success(`Payment method changed to ${res.to}`);
      onChanged();
    } catch (err) {
      const p = extractFrappeServerError(err, 'Could not change the payment method.');
      showToast.error({ title: p.title || 'Change failed', description: p.message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg w-full max-w-md shadow-xl">
        <div className="flex items-start justify-between px-5 py-4 border-b border-gray-200">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-blue-100 flex items-center justify-center">
              <Wallet className="w-5 h-5 text-blue-700" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-gray-900">
                Change payment method
              </h3>
              <p className="text-xs text-gray-500">{invoice}</p>
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3">
          {error && <p className="text-sm text-red-700">{error}</p>}
          {!data && !error && (
            <div className="flex items-center gap-2 py-6 text-sm text-gray-500">
              <Loader2 className="w-4 h-4 animate-spin" /> Loading…
            </div>
          )}

          {data && !data.can_change && (
            <div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3">
              <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
              <p className="text-sm text-amber-900">{data.reason}</p>
            </div>
          )}

          {data?.can_change === 1 && (
            <>
              {data.rows.length > 1 && (
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Which payment?
                  </label>
                  <select
                    value={selected}
                    onChange={(e) => {
                      setSelected(e.target.value);
                      const r = data.rows.find((x) => x.row === e.target.value);
                      setMode(r?.mode_of_payment || '');
                    }}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                  >
                    <option value="">Select…</option>
                    {data.rows.map((r) => (
                      <option key={r.row} value={r.row}>
                        {r.mode_of_payment} · {formatCurrency(r.amount)}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {current && (
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Change {formatCurrency(current.amount)} from{' '}
                    <span className="font-semibold">{current.mode_of_payment}</span> to
                  </label>
                  <select
                    value={mode}
                    onChange={(e) => setMode(e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                  >
                    {data.available_modes.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </>
          )}
        </div>

        <div className="px-5 py-4 border-t border-gray-200 flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} className="border-gray-300">
            {data?.can_change === 1 ? 'Cancel' : 'Close'}
          </Button>
          {data?.can_change === 1 && (
            <Button
              onClick={submit}
              disabled={!dirty || saving}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              {saving && <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />}
              Save change
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};

export default ChangePaymentModeDialog;
