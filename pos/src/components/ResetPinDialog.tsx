/**
 * ResetPinDialog — self-service PIN change for any signed-in cashier.
 *
 * Mounted from the user-menu dropdown in [Header.tsx](Header.tsx).
 * Backed by `ury.ury.biometric.api.change_pin` which:
 *   - Requires the caller to have an existing enrollment with a PIN set.
 *   - Verifies the old PIN against the stored hash.
 *   - Hashes the new PIN with pbkdf2_sha256 + per-row salt.
 *   - Resets failed attempt counter + clears any active lockout.
 *
 * We don't need to know whether the user actually has an enrollment up
 * front — the dialog surfaces the backend's friendly errors ("Not
 * Enrolled" / "PIN Not Set") if they don't. Users who haven't been
 * enrolled simply see a clear "ask your captain" message.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { KeyRound, Loader2, CheckCircle2, X } from 'lucide-react';
import { Button } from './ui/button';
import { showToast } from './ui/toast';
import { changePin } from '../lib/biometric-api';
import { extractFrappeServerError } from '../lib/utils';

interface Props {
  open: boolean;
  onClose: () => void;
  /**
   * Forced expiry mode (2026-06-05): non-dismissible, the old PIN is
   * preset (the user just authenticated with it), and on success we call
   * `onCompleted` instead of closing — the caller redirects to the POS.
   */
  forced?: boolean;
  /** The PIN the user just logged in with. Used as the old PIN in forced mode. */
  presetOldPin?: string;
  /** Called after a successful change in forced mode. */
  onCompleted?: () => void;
}

function PinDigits({
  value,
  onChange,
  autoFocus,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  autoFocus?: boolean;
  label: string;
}) {
  const refs = useRef<Array<HTMLInputElement | null>>([]);
  const digits = useMemo(() => {
    const arr = Array(6).fill('');
    for (let i = 0; i < Math.min(value.length, 6); i++) arr[i] = value[i];
    return arr;
  }, [value]);

  const onCellChange = (idx: number, raw: string) => {
    const clean = raw.replace(/\D/g, '').slice(-1);
    const next = digits.slice();
    next[idx] = clean;
    onChange(next.join('').slice(0, 6));
    if (clean && idx < 5) refs.current[idx + 1]?.focus();
  };
  const onCellKey = (idx: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace' && !digits[idx] && idx > 0) refs.current[idx - 1]?.focus();
  };
  const onPaste = (idx: number, e: React.ClipboardEvent<HTMLInputElement>) => {
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
    if (pasted.length > 1) {
      e.preventDefault();
      onChange(pasted);
      refs.current[Math.min(pasted.length, 5)]?.focus();
    }
  };

  return (
    <div>
      <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">
        {label}
      </label>
      <div className="flex gap-2 justify-center">
        {digits.map((d, i) => (
          <input
            key={i}
            ref={(el) => {
              refs.current[i] = el;
            }}
            autoFocus={autoFocus && i === 0}
            type="password"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={1}
            value={d}
            onChange={(e) => onCellChange(i, e.target.value)}
            onKeyDown={(e) => onCellKey(i, e)}
            onPaste={(e) => onPaste(i, e)}
            className="w-11 h-14 text-center text-2xl font-bold rounded-lg border-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
        ))}
      </div>
    </div>
  );
}

export default function ResetPinDialog({
  open,
  onClose,
  forced = false,
  presetOldPin,
  onCompleted,
}: Props) {
  const [oldPin, setOldPin] = useState('');
  const [newPin, setNewPin] = useState('');
  const [confirmPin, setConfirmPin] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Forced mode: seed the old PIN from the just-used login PIN.
  useEffect(() => {
    if (forced && presetOldPin) setOldPin(presetOldPin);
  }, [forced, presetOldPin, open]);

  const reset = useCallback(() => {
    setOldPin('');
    setNewPin('');
    setConfirmPin('');
    setError(null);
    setSuccess(false);
    setSubmitting(false);
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [onClose, reset]);

  const mismatch = newPin.length === 6 && confirmPin.length === 6 && newPin !== confirmPin;
  const sameAsOld = newPin.length === 6 && oldPin.length === 6 && newPin === oldPin;
  const canSubmit =
    oldPin.length === 6 && newPin.length === 6 && confirmPin.length === 6 && !mismatch && !sameAsOld && !submitting;

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      await changePin({ old_pin: oldPin, new_pin: newPin });
      setSuccess(true);
      showToast.success({
        title: 'PIN updated',
        description: 'Use the new PIN next time you sign in.',
      });
      // Auto-close after a brief success flash. In forced mode, hand off
      // to the caller (which redirects to the POS) instead of closing.
      setTimeout(() => {
        if (forced && onCompleted) {
          onCompleted();
        } else {
          handleClose();
        }
      }, 1200);
    } catch (err) {
      const parsed = extractFrappeServerError(err, 'Could not change your PIN.');
      setError(parsed.message);
      // Clear the old PIN so the user can retry without leaving stale digits
      setOldPin('');
    } finally {
      setSubmitting(false);
    }
  }, [canSubmit, oldPin, newPin, handleClose, forced, onCompleted]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center px-4">
      <div className="bg-white rounded-2xl shadow-xl max-w-md w-full overflow-hidden">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 flex items-start justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center shrink-0">
              <KeyRound className="text-blue-700" size={20} />
            </div>
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-gray-900">
                {forced ? 'Your PIN has expired' : 'Reset PIN'}
              </h2>
              <p className="text-xs text-gray-500">
                {forced
                  ? 'Set a new 6-digit PIN to continue.'
                  : 'Change the 6-digit PIN you use to sign in.'}
              </p>
            </div>
          </div>
          {!forced && (
            <button
              type="button"
              onClick={handleClose}
              className="text-gray-400 hover:text-gray-700 p-1 rounded-md hover:bg-gray-100"
            >
              <X size={18} />
            </button>
          )}
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-5">
          {success ? (
            <div className="text-center py-4">
              <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-emerald-100 mb-3">
                <CheckCircle2 className="text-emerald-700" size={32} />
              </div>
              <div className="text-base font-semibold text-gray-900">PIN changed</div>
              <div className="text-sm text-gray-500 mt-1">Use it next time you sign in.</div>
            </div>
          ) : (
            <>
              {!forced && (
                <PinDigits value={oldPin} onChange={setOldPin} autoFocus label="Current PIN" />
              )}
              <PinDigits value={newPin} onChange={setNewPin} autoFocus={forced} label="New PIN" />
              <PinDigits value={confirmPin} onChange={setConfirmPin} label="Confirm New PIN" />

              {mismatch && (
                <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">
                  New PINs don't match.
                </div>
              )}
              {sameAsOld && (
                <div className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
                  New PIN must be different from the current PIN.
                </div>
              )}
              {error && (
                <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">
                  {error}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        {!success && (
          <div className="px-6 pb-6 pt-2 flex items-center justify-end gap-2">
            {!forced && (
              <Button variant="outline" onClick={handleClose} disabled={submitting}>
                Cancel
              </Button>
            )}
            <Button onClick={handleSubmit} disabled={!canSubmit} className="bg-blue-600 hover:bg-blue-700">
              {submitting ? (
                <>
                  <Loader2 size={14} className="animate-spin" /> Saving…
                </>
              ) : (
                <>
                  <KeyRound size={14} /> Update PIN
                </>
              )}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
