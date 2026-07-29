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
import {
  KeyRound,
  Loader2,
  CheckCircle2,
  X,
  Search,
  UserCog,
  ArrowLeft,
} from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { showToast } from './ui/toast';
import {
  changePin,
  getMyPinStatus,
  adminSetUserPin,
  searchUsersForLogin,
  type MyPinStatus,
  type LoginUserCandidate,
} from '../lib/biometric-api';
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

  // Who this dialog is acting on. 'self' is everyone's default; captains
  // and admins can switch to 'other' to set a PIN for a cashier who has
  // forgotten theirs (or never had one).
  const [mode, setMode] = useState<'self' | 'other'>('self');
  const [status, setStatus] = useState<MyPinStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<LoginUserCandidate[]>([]);
  const [searching, setSearching] = useState(false);
  const [target, setTarget] = useState<LoginUserCandidate | null>(null);
  const searchDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Forced mode: seed the old PIN from the just-used login PIN.
  useEffect(() => {
    if (forced && presetOldPin) setOldPin(presetOldPin);
  }, [forced, presetOldPin, open]);

  // Ask the server whether this user already HAS a PIN. Without a PIN
  // there is nothing to verify, so we must not demand a "current PIN"
  // they have never had — that was the dead end this fixes. Skipped in
  // forced mode, which by definition means a PIN already exists.
  useEffect(() => {
    if (!open || forced) return;
    let cancelled = false;
    setStatusLoading(true);
    getMyPinStatus()
      .then((s) => {
        if (!cancelled) setStatus(s);
      })
      .catch(() => {
        // Fail SAFE: assume a PIN exists, so we ask for the old one. The
        // backend enforces the real rule either way, so the worst case is
        // an extra field, never an unguarded change.
        if (!cancelled) setStatus(null);
      })
      .finally(() => {
        if (!cancelled) setStatusLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, forced]);

  // Debounced user search for the admin "set someone else's PIN" mode.
  useEffect(() => {
    if (mode !== 'other') return;
    if (searchDebounce.current) clearTimeout(searchDebounce.current);
    if (!query.trim()) {
      setResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    searchDebounce.current = setTimeout(async () => {
      try {
        setResults(await searchUsersForLogin(query));
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 220);
    return () => {
      if (searchDebounce.current) clearTimeout(searchDebounce.current);
    };
  }, [query, mode]);

  const reset = useCallback(() => {
    setOldPin('');
    setNewPin('');
    setConfirmPin('');
    setError(null);
    setSuccess(false);
    setSubmitting(false);
    setMode('self');
    setQuery('');
    setResults([]);
    setTarget(null);
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [onClose, reset]);

  // Setting someone ELSE's PIN never needs an old PIN — that's the whole
  // point of an admin reset. Setting your OWN first PIN doesn't either.
  // Only replacing an existing PIN of your own does. `status === null`
  // (lookup failed) falls back to requiring it.
  const needsOldPin =
    mode === 'self' && (forced || status === null || status.has_pin === 1);
  const isFirstPin = mode === 'self' && !forced && status?.has_pin === 0;
  const canSetForOthers = status?.can_set_for_others === 1 && !forced;

  const mismatch = newPin.length === 6 && confirmPin.length === 6 && newPin !== confirmPin;
  const sameAsOld =
    needsOldPin && newPin.length === 6 && oldPin.length === 6 && newPin === oldPin;
  const canSubmit =
    (!needsOldPin || oldPin.length === 6) &&
    (mode !== 'other' || !!target) &&
    newPin.length === 6 &&
    confirmPin.length === 6 &&
    !mismatch &&
    !sameAsOld &&
    !submitting &&
    !statusLoading;

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      if (mode === 'other' && target) {
        await adminSetUserPin({ user: target.name, new_pin: newPin });
        showToast.success({
          title: `PIN set for ${target.full_name || target.name}`,
          description: 'They can sign in with it now. The change has been logged.',
        });
      } else {
        await changePin({
          new_pin: newPin,
          // Omit entirely rather than sending an empty string — the
          // backend treats a falsy old_pin as "not supplied".
          ...(needsOldPin ? { old_pin: oldPin } : {}),
        });
        showToast.success({
          title: isFirstPin ? 'PIN set' : 'PIN updated',
          description: 'Use the new PIN next time you sign in.',
        });
      }
      setSuccess(true);
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
      const parsed = extractFrappeServerError(err, 'Could not set the PIN.');
      setError(parsed.message);
      // Clear the old PIN so the user can retry without leaving stale digits
      setOldPin('');
    } finally {
      setSubmitting(false);
    }
  }, [
    canSubmit,
    mode,
    target,
    oldPin,
    newPin,
    needsOldPin,
    isFirstPin,
    handleClose,
    forced,
    onCompleted,
  ]);

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
                {forced
                  ? 'Your PIN has expired'
                  : mode === 'other'
                    ? 'Set PIN for a User'
                    : isFirstPin
                      ? 'Set Your PIN'
                      : 'Reset PIN'}
              </h2>
              <p className="text-xs text-gray-500">
                {forced
                  ? 'Set a new 6-digit PIN to continue.'
                  : mode === 'other'
                    ? "Pick a user and give them a new 6-digit PIN."
                    : isFirstPin
                      ? "You don't have a PIN yet. Choose a 6-digit PIN to sign in with."
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
              <div className="text-base font-semibold text-gray-900">
                {mode === 'other'
                  ? `PIN set for ${target?.full_name || target?.name || 'user'}`
                  : isFirstPin
                    ? 'PIN set'
                    : 'PIN changed'}
              </div>
              <div className="text-sm text-gray-500 mt-1">
                {mode === 'other'
                  ? 'They can sign in with it now. The change has been logged.'
                  : 'Use it next time you sign in.'}
              </div>
            </div>
          ) : statusLoading ? (
            <div className="flex items-center justify-center py-8 text-gray-400">
              <Loader2 size={18} className="animate-spin" />
              <span className="ml-2 text-sm">Checking your PIN…</span>
            </div>
          ) : (
            <>
              {/* Admin: switch between own PIN and someone else's. */}
              {canSetForOthers && mode === 'self' && (
                <button
                  type="button"
                  onClick={() => {
                    setMode('other');
                    setError(null);
                    setOldPin('');
                  }}
                  className="w-full flex items-center gap-2 text-sm text-blue-700 hover:text-blue-800 hover:bg-blue-50 rounded-md px-3 py-2 border border-blue-200"
                >
                  <UserCog size={16} />
                  Set a PIN for another user instead
                </button>
              )}

              {mode === 'other' && (
                <div className="space-y-3">
                  <button
                    type="button"
                    onClick={() => {
                      setMode('self');
                      setTarget(null);
                      setQuery('');
                      setError(null);
                    }}
                    className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-800"
                  >
                    <ArrowLeft size={14} /> Back to my own PIN
                  </button>

                  {target ? (
                    <div className="flex items-center justify-between gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2.5">
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-gray-900 truncate">
                          {target.full_name || target.name}
                        </div>
                        <div className="text-xs text-gray-500 truncate">{target.name}</div>
                        <div className="text-xs text-gray-500 mt-0.5">
                          {target.has_pin === 1
                            ? 'Has a PIN — it will be replaced.'
                            : 'No PIN yet — this will be their first.'}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => setTarget(null)}
                        className="text-xs text-gray-500 hover:text-gray-900 shrink-0"
                      >
                        Change
                      </button>
                    </div>
                  ) : (
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1.5">
                        Which user?
                      </label>
                      <div className="relative">
                        <Search
                          size={16}
                          className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none"
                        />
                        <Input
                          autoFocus
                          value={query}
                          onChange={(e) => setQuery(e.target.value)}
                          placeholder="Search by name or email…"
                          className="pl-9"
                        />
                        {searching && (
                          <Loader2
                            size={14}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 animate-spin"
                          />
                        )}
                      </div>
                      {results.length > 0 && (
                        <div className="mt-2 divide-y divide-gray-100 border border-gray-200 rounded-lg overflow-y-auto overscroll-contain max-h-52 bg-white">
                          {results.map((u) => (
                            <button
                              key={u.name}
                              type="button"
                              onClick={() => setTarget(u)}
                              className="w-full text-left px-3 py-2.5 hover:bg-blue-50 focus:bg-blue-50 focus:outline-none"
                            >
                              <div className="text-sm text-gray-900 truncate">
                                {u.full_name || u.name}
                              </div>
                              <div className="text-xs text-gray-500 truncate">{u.name}</div>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {needsOldPin && (
                <PinDigits value={oldPin} onChange={setOldPin} autoFocus={!forced} label="Current PIN" />
              )}
              {(mode === 'self' || target) && (
                <>
                  <PinDigits
                    value={newPin}
                    onChange={setNewPin}
                    autoFocus={forced || isFirstPin}
                    label="New PIN"
                  />
                  <PinDigits value={confirmPin} onChange={setConfirmPin} label="Confirm New PIN" />
                </>
              )}

              {mode === 'other' && target && (
                <p className="text-xs text-gray-500">
                  This change is recorded against your name in the PIN change
                  log. Tell {target.full_name || target.name} their new PIN
                  privately and ask them to change it.
                </p>
              )}

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
