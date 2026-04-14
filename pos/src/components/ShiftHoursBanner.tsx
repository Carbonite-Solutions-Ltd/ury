/**
 * Shift banner — soft reminder (or hard block when configured) that the
 * cashier's shift is over and they should close the POS.
 *
 * Two backend modes, picked by `posProfile.custom_shift_system_mode`:
 *
 *   - "Disabled" (default / legacy): driven by the per-profile
 *     `custom_shift_hours` (Int). Reads the current open entry's
 *     `period_start_date` once a minute and computes elapsed hours
 *     locally. Shows the banner when elapsed >= shift_hours. A second
 *     flag, `custom_block_orders_after_shift_end`, hard-blocks new
 *     orders via the `shiftBlocked` store flag.
 *
 *   - "URY Shift" / "HRMS Shift Type" (added 2026-04-14): driven by
 *     the new shift system. Polls `get_shift_status(terminal)` every
 *     minute. Shows the banner when the response's `status` is
 *     "after_end" — meaning current time is past the assigned shift's
 *     end_time. The banner renders the assigned shift's name +
 *     end_time so the cashier knows exactly which shift is over. The
 *     hard-block flag is NOT used in shift-system mode (the user
 *     explicitly chose option (a) — soft reminder only).
 *
 * Bypass: Administrator + System Manager skip the shift gate
 * server-side, so the banner never fires for them in shift-system
 * mode (`status = 'bypass'`).
 *
 * See CLAUDE.md "Fixes log" 2026-04-09 (legacy) + 2026-04-14 (shift system).
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, DoorOpen, X } from 'lucide-react';
import { usePOSStore } from '../store/pos-store';
import { getCurrentPosOpenEntry } from '../lib/pos-opening-api';
import { getShiftStatus, type ShiftStatus } from '../lib/shift-api';
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

  const shiftSystemMode = posProfile?.custom_shift_system_mode || 'Disabled';
  const useShiftSystem =
    shiftSystemMode === 'URY Shift' ||
    shiftSystemMode === 'HRMS Shift Type';

  // Legacy mode state.
  const shiftHours = useMemo(
    () => Number(posProfile?.custom_shift_hours || 0),
    [posProfile]
  );
  const blockEnabled = useMemo(
    () => Number(posProfile?.custom_block_orders_after_shift_end || 0) === 1,
    [posProfile]
  );

  // Common state.
  const [openEntryName, setOpenEntryName] = useState<string | null>(null);
  const [elapsedHours, setElapsedHours] = useState<number | null>(null);
  const [shiftStatus, setShiftStatus] = useState<ShiftStatus | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [showClosingDialog, setShowClosingDialog] = useState(false);
  const intervalRef = useRef<number | null>(null);

  // Reset dismiss state whenever the open entry OR the shift status'
  // status field changes (a fresh shift starts).
  useEffect(() => {
    setDismissed(false);
  }, [openEntryName, shiftStatus?.status]);

  // ----- Shift system mode (URY Shift / HRMS Shift Type) -----
  useEffect(() => {
    if (!useShiftSystem) return;

    let cancelled = false;

    const poll = async () => {
      try {
        const status = await getShiftStatus(terminalName);
        if (cancelled) return;
        setShiftStatus(status);
        // Banner shows when status === 'after_end'. Hard block stays
        // off in shift-system mode — user chose soft reminder only.
        const expired = status.status === 'after_end';
        setShiftExpired(expired, false);

        // Also keep the open-entry name fresh so the Close Shift
        // button can deep-link to the right entry.
        const entry = await getCurrentPosOpenEntry(terminalName);
        if (cancelled) return;
        setOpenEntryName(entry?.name || null);
      } catch (err) {
        // Don't break the POS if the endpoint hiccups — just clear
        // the banner state and try again on the next tick.
        console.warn('[shift-system] poll failed', err);
        if (cancelled) return;
        setShiftStatus(null);
        setShiftExpired(false, false);
      }
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
  }, [useShiftSystem, terminalName, setShiftExpired]);

  // ----- Legacy mode (custom_shift_hours) -----
  useEffect(() => {
    // Skip the legacy poll entirely when shift system is active.
    if (useShiftSystem) return;

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

      const hours = (Date.now() - startedAt.getTime()) / (1000 * 60 * 60);
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
  }, [useShiftSystem, shiftHours, blockEnabled, terminalName, setShiftExpired]);

  // ----- Render gating -----
  if (useShiftSystem) {
    if (!shiftStatus || shiftStatus.status !== 'after_end') return null;
  } else {
    if (!shiftHours || shiftHours <= 0) return null;
    if (!shiftExpired) return null;
  }

  // Hard-block banner (legacy mode only) can never be dismissed.
  // Soft banner is dismissible per session — gone until the user reloads.
  if (dismissed && !shiftBlocked) return null;

  // Build the rendered text differently per mode.
  let title: string;
  let detail: string;
  if (useShiftSystem && shiftStatus) {
    title = shiftBlocked
      ? `Shift "${shiftStatus.shift_name}" over — orders blocked.`
      : `Shift "${shiftStatus.shift_name}" is over.`;
    detail = `Ended at ${shiftStatus.end_time}. Time to close the POS.`;
  } else {
    const elapsedLabel =
      elapsedHours !== null ? formatHours(elapsedHours) : '—';
    title = shiftBlocked ? 'Shift over — orders blocked.' : 'Your shift is over.';
    detail = `Open for ${elapsedLabel} (limit ${shiftHours} h). Close the shift${
      shiftBlocked ? ' to start a new one.' : ' before continuing.'
    }`;
  }

  return (
    <>
      <div
        role="alert"
        className={
          // Sits at the top of App.tsx's h-screen flex column.
          // shrink-0 keeps it at its natural height so the rest of the
          // layout (Header + flex-1 routes area + Footer) shrinks
          // around it. Don't add `sticky top-0` — that broke the
          // layout when the banner was outside the column.
          shiftBlocked
            ? 'shrink-0 w-full bg-red-600 text-white shadow z-30'
            : 'shrink-0 w-full bg-orange-500 text-white shadow z-30'
        }
      >
        <div className="mx-auto max-w-screen-xl flex items-center gap-3 px-4 py-2 text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <div className="flex-1 min-w-0">
            <span className="font-semibold">{title}</span>{' '}
            <span className="opacity-90">{detail}</span>
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
