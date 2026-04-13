import { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import {
  checkPOSOpening,
  getCurrentPosOpenEntry,
  validatePOSClose,
} from '../lib/pos-opening-api';
import { usePOSStore } from '../store/pos-store';
import POSOpeningDialog from './POSOpeningDialog';
import POSClosingDialog from './POSClosingDialog';
import ShiftHoursBanner from './ShiftHoursBanner';

interface POSOpeningProviderProps {
  children: React.ReactNode;
}

type ValidationType = 'opening' | 'closing' | null;

interface ValidationState {
  type: ValidationType;
  unclosedEntry: string | null;
}

// Local-timezone "YYYY-MM-DD" for today. Used to compare against the
// opening entry's `period_start_date`, which Frappe stores in site
// timezone without an offset suffix — so as long as the POS device is
// in the same timezone as the Frappe site (the normal case), string
// comparison on the date portion is accurate.
const localToday = (): string => {
  const d = new Date();
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const POSOpeningProvider = ({ children }: POSOpeningProviderProps) => {
  const [validation, setValidation] = useState<ValidationState>({
    type: null,
    unclosedEntry: null,
  });
  const [outdatedEntry, setOutdatedEntry] = useState<{
    name: string;
    startDate: string;
  } | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const { posProfile, terminalName } = usePOSStore();

  const checkPOSStatus = async () => {
    try {
      setIsLoading(true);

      // Pass the registered terminal so the backend scopes the
      // open-check to (terminal, [user]) instead of just branch. See
      // CLAUDE.md "Fixes log" 2026-04-08.
      const openingResponse = await checkPOSOpening(terminalName);
      if (openingResponse.message === 1) {
        setValidation({ type: 'opening', unclosedEntry: null });
        setOutdatedEntry(null);
        return;
      }

      // POS is open for this terminal. If the daily-close rule is on,
      // also verify there's no unclosed previous-day entry — also
      // scoped per-terminal.
      if (posProfile?.custom_daily_pos_close === 1) {
        try {
          const closeResponse = await validatePOSClose(
            posProfile.name,
            terminalName
          );
          const msg = closeResponse.message;

          // Backend returns {status, unclosed_entry?} (new) but older
          // servers may still return the string "Failed"/"Success".
          if (typeof msg === 'string') {
            if (msg === 'Failed') {
              setValidation({ type: 'closing', unclosedEntry: null });
              setOutdatedEntry(null);
              return;
            }
          } else if (msg && msg.status === 'Failed') {
            setValidation({
              type: 'closing',
              unclosedEntry: msg.unclosed_entry || null,
            });
            setOutdatedEntry(null);
            return;
          }
        } catch (error) {
          console.error('Failed to validate POS close status:', error);
          setValidation({ type: 'closing', unclosedEntry: null });
          setOutdatedEntry(null);
          return;
        }
      }

      // Universal stale-date check. ERPNext's validate_pos_opening_entry
      // (sales_invoice.py) rejects any invoice whose POS Opening Entry's
      // period_start_date isn't today — regardless of profile settings
      // or shift_hours. If the cashier opens the POS on 2026-04-10 with
      // an entry from 2026-04-09, every Payment attempt throws
      // "Outdated POS Opening Entry". Catch it at POS load so the
      // cashier doesn't waste time building an order they can't submit.
      try {
        const entry = await getCurrentPosOpenEntry(terminalName);
        if (entry?.period_start_date) {
          const entryDate = entry.period_start_date.slice(0, 10);
          if (entryDate && entryDate < localToday()) {
            setOutdatedEntry({ name: entry.name, startDate: entryDate });
            setValidation({ type: null, unclosedEntry: null });
            return;
          }
        }
      } catch (error) {
        console.error('Failed to check entry date:', error);
        // Non-fatal — if we can't look it up, fall through to the normal
        // POS render. The Payment-time error will still surface.
      }

      setValidation({ type: null, unclosedEntry: null });
      setOutdatedEntry(null);
    } catch (error) {
      console.error('Failed to check POS opening status:', error);
      // On failure, assume POS is not opened so the user gets an
      // actionable screen rather than a silent broken POS page.
      setValidation({ type: 'opening', unclosedEntry: null });
      setOutdatedEntry(null);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    // Only check once the POS profile is loaded — we need it for the
    // captain-detection logic in the opening dialog.
    if (posProfile) {
      checkPOSStatus();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [posProfile]);

  if (isLoading) {
    return (
      <div className="fixed inset-0 bg-white flex items-center justify-center z-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Checking POS status...</p>
        </div>
      </div>
    );
  }

  if (validation.type) {
    // After a successful open inside the dialog we do a full reload so the
    // menu items, categories, payment modes and POS profile all refetch
    // cleanly — the dialog already clears sessionStorage before calling us.
    // See CLAUDE.md "Fixes log" for the reload-cache rationale.
    const handleOpened = () => window.location.reload();

    return (
      <POSOpeningDialog
        type={validation.type}
        unclosedEntry={validation.unclosedEntry}
        onOpened={handleOpened}
      />
    );
  }

  // Outdated POS Opening Entry — the entry was opened on a previous
  // day and ERPNext's sales_invoice validator will reject every Payment
  // until it's closed. Surface the closing dialog directly with a red
  // banner explaining why. Cancel reloads the page; since the entry is
  // still outdated, the check re-fires and the cashier sees this again —
  // effectively "can't escape" without actually closing the shift.
  if (outdatedEntry) {
    return (
      <div className="fixed inset-0 bg-gray-50 flex flex-col items-center justify-start pt-8 px-4 z-40 overflow-auto">
        <div
          role="alert"
          className="w-full max-w-2xl mb-4 rounded-lg border border-red-300 bg-red-50 text-red-900 px-4 py-3 flex items-start gap-3"
        >
          <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
          <div className="text-sm">
            <div className="font-semibold mb-1">
              Outdated POS Opening Entry
            </div>
            <div>
              The current shift was opened on{' '}
              <span className="font-mono">{outdatedEntry.startDate}</span>.
              ERPNext blocks all new invoices until this entry is closed.
              Please close the shift below to start a new one.
            </div>
          </div>
        </div>
        <POSClosingDialog
          openingEntry={outdatedEntry.name}
          onCancel={() => window.location.reload()}
          onClosed={() => window.location.reload()}
        />
      </div>
    );
  }

  return (
    <>
      <ShiftHoursBanner />
      {children}
    </>
  );
};

export default POSOpeningProvider;
