import { useEffect, useState } from 'react';
import { Loader2, PauseCircle, X } from 'lucide-react';
import { Button } from './ui/button';
import { showToast } from './ui/toast';
import { extractFrappeServerError, formatCurrency } from '../lib/utils';
import { holdOrder } from '../lib/hold-api';

/**
 * Park a bill with a reason.
 *
 * The reason is REQUIRED and that is the whole point: a held bill with no
 * explanation is exactly the situation this feature exists to prevent —
 * whoever picks it up later needs to know why it is sitting there.
 *
 * The dialog re-seeds on every open. It stays mounted, so without that it
 * would show the previous bill's reason (the same trap already fixed in
 * CommentDialog and OrderContactDialog).
 */
const QUICK_REASONS = [
  'Guest stepped out',
  'Waiting for manager',
  'Bill disputed',
  'Waiting on payment',
];

const HoldBillDialog = ({
  invoice,
  total,
  table,
  onClose,
  onHeld,
}: {
  invoice: string;
  total: number;
  table?: string | null;
  onClose: () => void;
  onHeld: () => void;
}) => {
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setReason('');
  }, [invoice]);

  const submit = async () => {
    const text = reason.trim();
    if (!text) return;
    setSaving(true);
    try {
      const res = await holdOrder(invoice, text);
      showToast.success(
        res.table_freed
          ? `Bill held — ${res.table_freed} is free again`
          : 'Bill held'
      );
      onHeld();
    } catch (err) {
      const p = extractFrappeServerError(err, 'Could not hold this bill.');
      showToast.error({ title: p.title || 'Hold failed', description: p.message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg w-full max-w-md shadow-xl">
        <div className="flex items-start justify-between px-5 py-4 border-b border-gray-200">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-amber-100 flex items-center justify-center">
              <PauseCircle className="w-5 h-5 text-amber-700" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-gray-900">Hold this bill</h3>
              <p className="text-xs text-gray-500">
                {invoice} · {formatCurrency(total)}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">
              Why is it being held? <span className="text-red-600">*</span>
            </label>
            <div className="flex flex-wrap gap-1.5 mb-2">
              {QUICK_REASONS.map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => setReason(r)}
                  className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${
                    reason === r
                      ? 'bg-amber-100 border-amber-300 text-amber-900'
                      : 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              autoFocus
              placeholder="Pick one above or type the reason…"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm resize-none"
            />
          </div>

          {table ? (
            <p className="text-xs text-gray-500 leading-relaxed">
              <span className="font-medium text-gray-700">{table}</span> will be
              released so it can be reseated. Taking the bill off hold later does
              not take the table back.
            </p>
          ) : null}
          <p className="text-xs text-gray-500 leading-relaxed">
            A held bill still has to be settled before the day can be closed.
          </p>
        </div>

        <div className="px-5 py-4 border-t border-gray-200 flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} className="border-gray-300">
            Cancel
          </Button>
          <Button
            onClick={submit}
            disabled={!reason.trim() || saving}
            className="bg-amber-600 hover:bg-amber-700 text-white"
          >
            {saving && <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />}
            Hold Bill
          </Button>
        </div>
      </div>
    </div>
  );
};

export default HoldBillDialog;
