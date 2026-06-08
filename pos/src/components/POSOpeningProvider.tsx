import { useEffect, useState } from 'react';
import { AlertTriangle, Clock, RefreshCw } from 'lucide-react';
import {
  checkPOSOpening,
  getCurrentPosOpenEntry,
  validatePOSClose,
} from '../lib/pos-opening-api';
import { logout } from '../lib/auth-api';
import { usePOSStore } from '../store/pos-store';
import { extractFrappeServerError } from '../lib/utils';
import POSOpeningDialog from './POSOpeningDialog';
import POSClosingDialog from './POSClosingDialog';
import { Button } from './ui/button';

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
  // Backend `posOpening` errors (typically the URY Shift gate rejecting
  // the open). Surfaced as a dedicated red screen instead of falling
  // through to the opening dialog — otherwise the cashier sees the
  // dialog and the error never reaches them. See CLAUDE.md "Fixes log".
  const [gateError, setGateError] = useState<{
    title: string;
    message: string;
  } | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const { posProfile, terminalName } = usePOSStore();

  const checkPOSStatus = async () => {
    setGateError(null);
    try {
      setIsLoading(true);

      // Pass the registered terminal so the backend scopes the
      // open-check to (terminal, [user]) instead of just branch. See
      // CLAUDE.md "Fixes log" 2026-04-08.
      let openingResponse;
      try {
        openingResponse = await checkPOSOpening(terminalName);
      } catch (err) {
        // The backend's URY Shift gate throws here when the cashier
        // is outside their assigned shift window or has no shift
        // assigned today. Surface the parsed error directly to the
        // user instead of swallowing it and falling through to the
        // opening dialog (the old behavior masked the gate entirely).
        const parsed = extractFrappeServerError(
          err,
          'Failed to check POS opening status.'
        );
        setGateError({
          title: parsed.title || 'Cannot Open POS',
          message: parsed.message,
        });
        setValidation({ type: null, unclosedEntry: null });
        setOutdatedEntry(null);
        return;
      }
      if (openingResponse.message === 1) {
        setValidation({ type: 'opening', unclosedEntry: null });
        setOutdatedEntry(null);
        return;
      }

      // POS is open for this terminal. If the daily-close rule is on,
      // also verify there's no unclosed previous-day entry — also
      // scoped per-terminal.
      if (posProfile?.custom_daily_pos_close === 1) {
        // Resolve the specific open entry so the "Close Previous Session"
        // button can open the in-POS closing dialog against it. Older
        // servers return a bare "Failed" string without the entry name,
        // so we fall back to looking the entry up directly.
        const resolveOpenEntryName = async (): Promise<string | null> => {
          try {
            const open = await getCurrentPosOpenEntry(terminalName);
            return open?.name || null;
          } catch {
            return null;
          }
        };
        try {
          const closeResponse = await validatePOSClose(
            posProfile.name,
            terminalName
          );
          const msg = closeResponse.message;

          // Backend returns {status, unclosed_entry?} (new) but older
          // servers may still return the string "Failed"/"Success".
          const failed =
            typeof msg === 'string'
              ? msg === 'Failed'
              : !!(msg && msg.status === 'Failed');
          if (failed) {
            let entryName =
              typeof msg === 'object' && msg ? msg.unclosed_entry || null : null;
            if (!entryName) entryName = await resolveOpenEntryName();
            setValidation({ type: 'closing', unclosedEntry: entryName });
            setOutdatedEntry(null);
            return;
          }
        } catch (error) {
          console.error('Failed to validate POS close status:', error);
          setValidation({
            type: 'closing',
            unclosedEntry: await resolveOpenEntryName(),
          });
          setOutdatedEntry(null);
          return;
        }
      }

      // Universal stale-date check. ERPXpand's validate_pos_opening_entry
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

  // Backend gate rejection (URY Shift system, no shift assigned, etc.)
  // Renders before the opening dialog so the cashier sees the real
  // reason and can either wait + retry or sign out.
  if (gateError) {
    return (
      <div className="fixed inset-0 bg-gray-50 flex items-center justify-center px-4 z-40">
        <div className="bg-white rounded-xl shadow-2xl p-8 max-w-md w-full">
          <div className="flex justify-center mb-4">
            <div className="flex items-center justify-center h-14 w-14 rounded-full bg-red-100">
              <Clock className="h-7 w-7 text-red-600" />
            </div>
          </div>
          <h2 className="text-xl font-bold text-gray-900 text-center mb-2">
            {gateError.title}
          </h2>
          <p className="text-sm text-gray-600 text-center mb-6 whitespace-pre-line">
            {gateError.message}
          </p>
          <div className="flex gap-3">
            <Button
              onClick={() => checkPOSStatus()}
              className="flex-1 bg-blue-600 hover:bg-blue-700 text-white"
            >
              <RefreshCw className="w-4 h-4 mr-2" />
              Try Again
            </Button>
            <Button
              variant="outline"
              onClick={async () => {
                // Hard sign-out: call Frappe's logout endpoint so the
                // server-side session cookie is invalidated, THEN
                // clear caches and redirect. Just clearing
                // sessionStorage + setting location.href wasn't
                // enough — the server still saw a valid session and
                // bounced the user back to /pos, landing them on the
                // same gate error screen.
                try {
                  await logout();
                } catch {
                  /* ignore — we'll still clear caches + redirect */
                }
                sessionStorage.clear();
                try {
                  localStorage.removeItem('currencySymbol');
                  localStorage.removeItem('currency');
                } catch {
                  /* ignore */
                }
                // Use location.replace so the gate error screen
                // doesn't sit in browser history. Land on /pos —
                // App.tsx will render the URY BiometricLogin page
                // because the session is now Guest.
                window.location.replace('/pos');
              }}
              className="flex-1"
            >
              Sign Out
            </Button>
          </div>
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
  // day and ERPXpand's sales_invoice validator will reject every Payment
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
              ERPXpand blocks all new invoices until this entry is closed.
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

  // The ShiftHoursBanner is mounted by App.tsx INSIDE the h-screen
  // flex column so it participates in the flex layout — putting it
  // here would make it a sibling of the h-screen container, which
  // pushes the Footer below the viewport.
  return <>{children}</>;
};

export default POSOpeningProvider;
