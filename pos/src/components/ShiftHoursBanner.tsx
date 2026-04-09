/**
 * Shift hours banner — soft reminder that the cashier's shift is over
 * (and a hard block when the POS Profile opts in to blocking new orders).
 *
 * Driven by two POS Profile settings:
 *   - `custom_shift_hours` (Int): length of a shift in hours. 0 = disabled.
 *   - `custom_block_orders_after_shift_end` (Check): if 1, also disable
 *     OrderPanel's submit button via the `shiftBlocked` store flag.
 *
 * Polls `get_pos_open_entry` once a minute to read the current open
 * entry's `period_start_date`. Computes elapsed hours and updates store
 * flags. Renders a fixed orange banner at the top of the POS when
 * elapsed >= shift_hours.
 *
 * See CLAUDE.md "Fixes log" 2026-04-09.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, DoorOpen, X } from 'lucide-react';
import { usePOSStore } from '../store/pos-store';
import { getCurrentPosOpenEntry } from '../lib/pos-opening-api';
import POSClosingDialog from './POSClosingDialog';

const POLL_INTERVAL_MS = 60_000; // 1 minute

const parseFrappeDateTime = (s: string): Date | null => {
  // Frappe Datetime format: "YYYY-MM-DD HH:mm:ss" (in site timezone)
  if (!s) return null;
  // Replace space with T to make it ISO-ish; without a Z, the browser
  // parses as local time, which is what we want for "elapsed since" math.
  const iso = s.replace(' ', 'T');
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
};

const formatHours = (hours: number): string => {
  if (hours < 1) {
    const minutes = Math.max(0, Math.round(hours * 60));
    return `${minutes} min`;
  }
  if (hours < 10) {
    return `${hours.toFixed(1)} h`;
  }
  return `${Math.round(hours)} h`;
};

const ShiftHoursBanner = () => {
  const {
    posProfile,
    terminalName,
    shiftExpired,
    shiftBlocked,
    setShiftExpired,
  } = usePOSStore();

  const shiftHours = useMemo(
    () => Number(posProfile?.custom_shift_hours || 0),
    [posProfile]
  );
  const blockEnabled = useMemo(
    () => Number(posProfile?.custom_block_orders_after_shift_end || 0) === 1,
    [posProfile]
  );

  const [openEntryName, setOpenEntryName] = useState<string | null>(null);
  const [elapsedHours, setElapsedHours] = useState<number | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [showClosingDialog, setShowClosingDialog] = useState(false);
  const intervalRef = useRef<number | null>(null);

  // Reset dismiss state whenever the underlying entry changes (new shift).
  useEffect(() => {
    setDismissed(false);
  }, [openEntryName]);

  useEffect(() => {
    // No shift enforcement on this profile — make sure store flags are clear.
    if (!shiftHours || shiftHours <= 0) {
      setShiftExpired(false, false);
      setOpenEntryName(null);
      setElapsedHours(null);
      return;
    }

    let cancelled = false;

    const poll = async () => {
      const entry = await getCurrentPosOpenEntry(terminalName);
      if (cancelled) return;

      if (!entry || !entry.period_start_date) {
        setOpenEntryName(null);
        setElapsedHours(null);
        setShiftExpired(false, false);
        return;
      }

      const startedAt = parseFrappeDateTime(entry.period_start_date);
      if (!startedAt) {
        setOpenEntryName(entry.name);
        setElapsedHours(null);
        setShiftExpired(false, false);
        return;
      }

      const hours =
        (Date.now() - startedAt.getTime()) / (1000 * 60 * 60);
      setOpenEntryName(entry.name);
      setElapsedHours(hours);

      const expired = hours >= shiftHours;
      setShiftExpired(expired, expired && blockEnabled);
    };

    poll();
    intervalRef.current = window.setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (intervalRef.current !== null) {
        window.clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [shiftHours, blockEnabled, terminalName, setShiftExpired]);

  // Don't render anything when the feature is off or the shift hasn't expired.
  if (!shiftHours || shiftHours <= 0) return null;
  if (!shiftExpired) return null;

  // Hard-block banner can never be dismissed (it's load-bearing UI). Soft
  // banner is dismissible per session — gone until the user reloads.
  if (dismissed && !shiftBlocked) return null;

  const elapsedLabel =
    elapsedHours !== null ? formatHours(elapsedHours) : '—';

  return (
    <>
      <div
        role="alert"
        className={
          shiftBlocked
            ? 'sticky top-0 z-40 w-full bg-red-600 text-white shadow'
            : 'sticky top-0 z-40 w-full bg-orange-500 text-white shadow'
        }
      >
        <div className="mx-auto max-w-screen-xl flex items-center gap-3 px-4 py-2 text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <div className="flex-1 min-w-0">
            <span className="font-semibold">
              {shiftBlocked
                ? 'Shift over — orders blocked.'
                : 'Your shift is over.'}
            </span>{' '}
            <span className="opacity-90">
              Open for {elapsedLabel} (limit {shiftHours} h). Close the shift
              {shiftBlocked ? ' to start a new one.' : ' before continuing.'}
            </span>
          </div>
          <button
            onClick={() => setShowClosingDialog(true)}
            disabled={!openEntryName}
            className="inline-flex items-center gap-1.5 rounded-md bg-white/15 hover:bg-white/25 border border-white/30 px-2.5 py-1 text-xs font-semibold transition-colors shrink-0 disabled:opacity-50"
          >
            <DoorOpen className="w-3.5 h-3.5" />
            Close Shift
          </button>
          {!shiftBlocked && (
            <button
              onClick={() => setDismissed(true)}
              aria-label="Dismiss"
              className="rounded p-1 hover:bg-white/20 transition-colors shrink-0"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {showClosingDialog && openEntryName && (
        <POSClosingDialog
          openingEntry={openEntryName}
          onCancel={() => setShowClosingDialog(false)}
          onClosed={() => {
            // Closing entry submitted — shift is over. Reload so the
            // POS picks up the now-closed state and the cashier can
            // open a new shift cleanly.
            setShowClosingDialog(false);
            window.location.reload();
          }}
        />
      )}
    </>
  );
};

export default ShiftHoursBanner;
