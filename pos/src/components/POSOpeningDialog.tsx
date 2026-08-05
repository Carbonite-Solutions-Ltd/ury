import { useEffect, useState } from 'react';
import {
  RefreshCw,
  AlertTriangle,
  DoorOpen,
  CheckCircle2,
  Loader2,
  LogOut,
} from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { showToast } from './ui/toast';
import { usePOSStore, type POSStore } from '../store/pos-store';
import { useRootStore, type RootState } from '../store/root-store';
import { logout } from '../lib/auth-api';
import {
  createAndSubmitPOSOpening,
  getCurrentPosOpenEntry,
  getOpeningBalanceDetails,
  type OpeningBalanceRow,
} from '../lib/pos-opening-api';
import { extractFrappeServerError } from '../lib/utils';
import POSClosingDialog from './POSClosingDialog';

/**
 * Sign out from any of the POS-gate screens.
 *
 * These dialogs cover the whole viewport and the POS runs as an
 * installed PWA with NO browser chrome — no address bar, no back
 * button. Without this the cashier is genuinely stuck: if they can't
 * open the POS (wrong user, someone else's shift open, outside their
 * shift window) their only escape is to force-quit the app. Every
 * blocking branch of this dialog therefore offers a way out.
 */
async function handleGateLogout() {
  try {
    await logout();
    // Land on /pos as guest → App.tsx renders the login screen.
    window.location.href = '/pos';
  } catch {
    showToast.error('Failed to sign out. Please try again.');
  }
}

type DialogType = 'opening' | 'closing';

interface POSOpeningDialogProps {
  type: DialogType;
  onOpened: () => void; // called after successful open so the provider can re-check status
  unclosedEntry?: string | null; // for the closing-issue branch: the specific POS Opening Entry pending closure
}

/**
 * Formats a Date as "YYYY-MM-DD HH:mm:ss" in local time — what Frappe's
 * Datetime fieldtype expects. Avoids the timezone drift you get from `.toISOString()`.
 */
const formatLocalDatetime = (d: Date): string => {
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
};

const formatLocalDate = (d: Date): string => {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

/**
 * The dialog shown when either (a) no POS Opening Entry is open for the
 * user's branch, or (b) a previous-day entry is still unclosed and the
 * daily-close rule is enabled.
 *
 * For (a) it renders an in-POS form that creates + submits a POS Opening
 * Entry without ever sending the user to the Frappe desk.
 *
 * There is NO "Join Session" / "waiting for main cashier" flow any more,
 * and there must not be one again. It was removed on 2026-07-28 because
 * it could never work: the button called `handleOpen`, i.e. it tried to
 * CREATE a second POS Opening Entry — exactly what ERPNext's
 * `check_open_pos_exists` refuses whenever the profile already has one
 * open. Clicking "Join Session" was therefore guaranteed to produce
 * "…is open. Close the POS or cancel the existing POS Opening Entry…",
 * which pushed cashiers toward closing the captain's shift. It never
 * joined anything.
 *
 * Under the current model there is one open entry per POS Profile and
 * `posOpening()` returns 0 for everyone once it exists — so a second
 * cashier never reaches this dialog at all. The existing-entry branch
 * below is now only a safety net, and it refuses to offer a Close button
 * for someone else's shift.
 *
 * For (b) it shows a focused message + a "Close Previous Session" button
 * that opens the in-POS POSClosingDialog for the specific unclosed entry
 * (same flow as the existing-entry branch) — never the Frappe desk.
 */
const POSOpeningDialog = ({ type, onOpened, unclosedEntry }: POSOpeningDialogProps) => {
  const { posProfile, terminalName } = usePOSStore();
  const { user } = useRootStore();
  const [showClosingDialog, setShowClosingDialog] = useState(false);

  // ───── closing-issue branch ─────
  // A previous-day entry is still open and the daily-close rule is on.
  // Let the cashier close it IN-POS via POSClosingDialog (same flow as
  // the existing-entry branch) instead of dropping them on the Frappe
  // desk. See CLAUDE.md "Fixes log" 2026-06-05.
  if (type === 'closing') {
    return (
      <>
        <DialogShell
          icon={<AlertTriangle className="h-8 w-8 text-orange-600" />}
          iconBg="bg-orange-100"
          title="Previous POS Not Closed"
          showLogout
          subtitle={
            unclosedEntry
              ? `Entry ${unclosedEntry} is still open. Close it before starting today's session.`
              : 'A previous POS Opening Entry is still open. Close it before starting today.'
          }
        >
          <Button
            onClick={() => unclosedEntry && setShowClosingDialog(true)}
            disabled={!unclosedEntry}
            className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 px-6 rounded-lg disabled:opacity-50"
          >
            <DoorOpen className="w-5 h-5 mr-2" />
            Close Previous Session
          </Button>
          <Button
            onClick={() => window.location.reload()}
            variant="outline"
            className="w-full mt-3 border-gray-300 text-gray-700 hover:bg-gray-50 font-medium py-3 px-6 rounded-lg"
          >
            <RefreshCw className="w-5 h-5 mr-2" />
            I've Closed It — Reload
          </Button>
        </DialogShell>

        {showClosingDialog && unclosedEntry && (
          <POSClosingDialog
            openingEntry={unclosedEntry}
            onCancel={() => setShowClosingDialog(false)}
            onClosed={() => {
              // Closing succeeded — reload so the opening flow re-runs
              // against a now-clean profile.
              setShowClosingDialog(false);
              window.location.reload();
            }}
          />
        )}
      </>
    );
  }

  // ───── opening-issue branch ─────
  return (
    <OpeningBranch
      posProfile={posProfile}
      user={user}
      terminalName={terminalName}
      onOpened={onOpened}
    />
  );
};

/**
 * The opening branch has enough moving parts (multi-cashier detection,
 * async main-cashier check, form state, submission state) that it lives
 * in its own component so the early-return for `closing` stays clean.
 */
interface OpeningBranchProps {
  posProfile: POSStore['posProfile'];
  user: RootState['user'];
  terminalName: string | null;
  onOpened: () => void;
}

type OpeningMode =
  | { kind: 'loading' }
  | { kind: 'open-form' } // show the full opening form
  | {
      kind: 'existing-entry';
      entryName: string | null;
      message: string;
      isMine: boolean;
      openedBy: string | null;
    }; // ERPNext rejected the create because the profile already has an open entry

const OpeningBranch = ({ posProfile, user, terminalName, onOpened }: OpeningBranchProps) => {
  const [mode, setMode] = useState<OpeningMode>({ kind: 'loading' });
  const [balanceRows, setBalanceRows] = useState<OpeningBalanceRow[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [showClosingDialog, setShowClosingDialog] = useState(false);

  const currentUser = user?.name || null;

  // Seed the opening form. Every user who actually reaches this dialog
  // sees the same form — there is no captain/sub-cashier fork any more.
  // If someone has already opened this POS Profile, `posOpening()`
  // returns 0 and the provider never renders this dialog in the first
  // place, so reaching here genuinely means "nobody has opened yet".
  useEffect(() => {
    let cancelled = false;

    const resolve = async () => {
      if (!posProfile || !currentUser) return;
      try {
        const rows = await getOpeningBalanceDetails();
        if (cancelled) return;
        setBalanceRows(rows);
      } catch (err) {
        console.error('Failed to load opening balance rows:', err);
        if (cancelled) return;
        setBalanceRows([]);
      }
      setMode({ kind: 'open-form' });
    };

    resolve();
    return () => {
      cancelled = true;
    };
  }, [posProfile, currentUser]);

  const handleOpen = async () => {
    if (!posProfile || !currentUser) return;
    setSubmitError(null);
    setSubmitting(true);

    try {
      const now = new Date();
      await createAndSubmitPOSOpening({
        period_start_date: formatLocalDatetime(now),
        posting_date: formatLocalDate(now),
        company: posProfile.company,
        pos_profile: posProfile.name,
        branch: posProfile.branch,
        user: currentUser,
        balance_details: balanceRows,
        // Stamp the registered terminal so the new entry is scoped
        // to this physical till. Backend `validate_terminal_branch`
        // hook verifies the terminal's branch matches.
        ...(terminalName ? { custom_terminal: terminalName } : {}),
      });

      // Success state — brief confirmation before the provider reloads.
      setSubmitted(true);
      // Clear stale sessionStorage caches (menu categories, payment modes,
      // posProfile) before reloading so any desk-side menu/config changes
      // show up. See CLAUDE.md "Fixes log".
      sessionStorage.clear();
      setTimeout(onOpened, 700);
    } catch (err: any) {
      console.error('Failed to open POS Entry:', err);

      // Use the shared parser so we (a) prefer the raise_exception=1
      // message, (b) strip HTML like ERPNext's <strong>{profile}</strong>
      // wrapper, (c) get the title for switch-on-title rendering.
      const parsed = extractFrappeServerError(
        err,
        'Failed to open POS Entry. Please try again.'
      );

      // Two different ERPNext guards can reject the create, and BOTH
      // need to land in the existing-entry branch:
      //
      //  * "POS Opening Entry Exists"  — check_open_pos_exists: this
      //    POS Profile already has an open entry (any user, any till).
      //  * "Cannot Assign Cashier"     — check_user_already_assigned:
      //    THIS user already has an open entry somewhere. That is what
      //    fires when a cashier opens a second browser/terminal, and it
      //    used to fall through to a dead-end raw error with no way out.
      const titleMatches =
        parsed.title === 'POS Opening Entry Exists' ||
        parsed.title === 'Cannot Assign Cashier';
      const msgMatches =
        /pos opening entry to create a new pos opening/i.test(parsed.message) ||
        /currently assigned to another pos/i.test(parsed.message);
      if (titleMatches || msgMatches) {
        try {
          const existing = await getCurrentPosOpenEntry(terminalName);
          setMode({
            kind: 'existing-entry',
            entryName: existing?.name || null,
            message: parsed.message,
            isMine: existing?.is_mine === 1,
            openedBy: existing?.opened_by || null,
          });
        } catch {
          setMode({
            kind: 'existing-entry',
            entryName: null,
            message: parsed.message,
            isMine: false,
            openedBy: null,
          });
        }
        setSubmitting(false);
        return;
      }

      setSubmitError(parsed.message);
      setSubmitting(false);
    }
  };

  const updateRow = (idx: number, value: string) => {
    const amount = value === '' ? 0 : Number(value);
    if (Number.isNaN(amount)) return;
    setBalanceRows(rows =>
      rows.map((r, i) => (i === idx ? { ...r, opening_amount: amount } : r))
    );
  };

  // ───── success flash ─────
  if (submitted) {
    return (
      <DialogShell
        icon={<CheckCircle2 className="h-8 w-8 text-green-600" />}
        iconBg="bg-green-100"
        title="POS Opened"
        subtitle="Loading menu…"
      >
        <div className="flex items-center justify-center py-2">
          <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
        </div>
      </DialogShell>
    );
  }

  // ───── loading the mode resolution ─────
  if (mode.kind === 'loading') {
    return (
      <DialogShell
        icon={<Loader2 className="h-8 w-8 text-blue-600 animate-spin" />}
        iconBg="bg-blue-100"
        title="Checking session…"
        subtitle="One moment."
      >
        <div />
      </DialogShell>
    );
  }

  // ───── existing open entry blocking the new one ─────
  // Safety net only. Normally `posOpening()` returns 0 as soon as the
  // profile has an open entry, so nobody gets here. If we DO get here,
  // an ERPNext guard rejected the create, and who owns the blocking
  // entry decides what we may offer:
  //
  //   * it's mine  → offer to close it in-POS (the shift really is ours)
  //   * it's someone else's → show it read-only. We must NOT invite a
  //     cashier to close a colleague's shift: that consolidates their
  //     invoices under our count and was how the old flow pushed people
  //     into closing the captain's day just to get into the POS.
  if (mode.kind === 'existing-entry') {
    const canClose = mode.isMine && !!mode.entryName;
    return (
      <>
        <DialogShell
          icon={<AlertTriangle className="h-8 w-8 text-orange-600" />}
          iconBg="bg-orange-100"
          title={mode.isMine ? 'Your Shift Is Still Open' : 'POS Already Open'}
          showLogout
          subtitle={
            mode.entryName
              ? mode.isMine
                ? `Your entry ${mode.entryName} is still open. Close it before starting a new shift.`
                : `${mode.openedBy || 'Another cashier'} already opened this POS (${mode.entryName}). You don't need to open it — just reload to start serving.`
              : mode.message
          }
        >
          {canClose ? (
            <Button
              onClick={() => setShowClosingDialog(true)}
              className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 px-6 rounded-lg"
            >
              <DoorOpen className="w-5 h-5 mr-2" />
              Close My Shift
            </Button>
          ) : (
            mode.entryName && (
              <p className="mb-3 p-3 rounded-lg bg-gray-50 text-gray-600 text-sm">
                Only {mode.openedBy || 'the cashier who opened it'} or a manager
                should close this shift. Closing it here would settle their
                takings under your count.
              </p>
            )
          )}
          <Button
            onClick={() => window.location.reload()}
            variant={canClose ? 'outline' : 'default'}
            className={
              canClose
                ? 'w-full mt-3 border-gray-300 text-gray-700 hover:bg-gray-50 font-medium py-3 px-6 rounded-lg'
                : 'w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 px-6 rounded-lg'
            }
          >
            <RefreshCw className="w-5 h-5 mr-2" />
            Reload
          </Button>
        </DialogShell>

        {showClosingDialog && mode.entryName && (
          <POSClosingDialog
            openingEntry={mode.entryName}
            onCancel={() => setShowClosingDialog(false)}
            onClosed={() => {
              // Closing succeeded — reload so the opening dialog
              // re-runs against a now-clean profile.
              setShowClosingDialog(false);
              window.location.reload();
            }}
          />
        )}
      </>
    );
  }

  // ───── main cashier / non-multi-cashier full form ─────
  return (
    <DialogShell
      icon={<DoorOpen className="h-8 w-8 text-blue-600" />}
      iconBg="bg-blue-100"
      title="Open POS Entry"
      showLogout
      subtitle="Enter your starting cash balances to begin the session."
      wide
    >
      {submitError && (
        <div className="mb-3 p-3 rounded-lg bg-red-50 text-red-700 text-sm">
          {submitError}
        </div>
      )}

      {/* Context strip — read-only at a glance */}
      <div className="mb-4 grid grid-cols-2 gap-2 text-xs text-gray-500">
        <div>
          <div className="uppercase tracking-wide">Cashier</div>
          <div className="text-gray-900 text-sm font-medium truncate">
            {user?.full_name || user?.name}
          </div>
        </div>
        <div>
          <div className="uppercase tracking-wide">Branch</div>
          <div className="text-gray-900 text-sm font-medium truncate">
            {posProfile?.branch}
          </div>
        </div>
      </div>

      {/* Balance rows */}
      <div className="mb-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
          Opening Balances
        </div>
        {balanceRows.length === 0 ? (
          <div className="text-sm text-gray-400 italic">
            No payment modes configured on this POS Profile.
          </div>
        ) : (
          <div className="space-y-2">
            {balanceRows.map((row, idx) => (
              <div key={row.mode_of_payment} className="flex items-center gap-3">
                <label className="flex-1 text-sm text-gray-700 truncate">
                  {row.mode_of_payment}
                </label>
                <Input
                  type="number"
                  min={0}
                  step="0.01"
                  value={row.opening_amount}
                  onChange={e => updateRow(idx, e.target.value)}
                  className="w-32 text-right"
                />
              </div>
            ))}
          </div>
        )}
      </div>

      <Button
        onClick={handleOpen}
        disabled={submitting || balanceRows.length === 0}
        className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 px-6 rounded-lg"
      >
        {submitting ? (
          <>
            <Loader2 className="w-5 h-5 mr-2 animate-spin" />
            Opening…
          </>
        ) : (
          <>
            <DoorOpen className="w-5 h-5 mr-2" />
            Open POS
          </>
        )}
      </Button>
    </DialogShell>
  );
};

/**
 * Thin modal shell shared by every state of the dialog so we don't
 * repeat the backdrop + card chrome in every branch.
 */
interface DialogShellProps {
  icon: React.ReactNode;
  iconBg: string;
  title: string;
  subtitle: string;
  wide?: boolean;
  children: React.ReactNode;
  /**
   * Render a "Sign out" escape hatch under the card's actions. On for
   * every branch that can BLOCK the user (open form, existing entry,
   * previous-day close); off for transient states (loading, the success
   * flash) where there is nothing to be stuck on.
   */
  showLogout?: boolean;
}

const DialogShell = ({
  icon,
  iconBg,
  title,
  subtitle,
  wide,
  children,
  showLogout,
}: DialogShellProps) => (
  // overflow-y-auto + items-start on small screens: the card can be
  // taller than the viewport on a phone (or once the on-screen keyboard
  // eats half the height), and a centred non-scrolling flex child would
  // clip its own top and bottom with no way to reach them.
  <div className="fixed inset-0 bg-black/50 flex items-start sm:items-center justify-center z-50 overflow-y-auto py-6">
    <div
      className={`bg-white rounded-lg p-8 ${
        wide ? 'max-w-lg' : 'max-w-md'
      } w-full mx-4 shadow-xl`}
    >
      <div className="text-center">
        <div
          className={`mx-auto flex items-center justify-center h-16 w-16 rounded-full mb-6 ${iconBg}`}
        >
          {icon}
        </div>
        <h2 className="text-2xl font-bold text-gray-900 mb-2">{title}</h2>
        <p className="text-gray-600 mb-6">{subtitle}</p>
      </div>
      <div>{children}</div>
      {showLogout && (
        <div className="mt-6 pt-4 border-t border-gray-100 text-center">
          <button
            type="button"
            onClick={handleGateLogout}
            className="inline-flex items-center justify-center gap-2 text-sm text-gray-500 hover:text-red-600 font-medium"
          >
            <LogOut className="w-4 h-4" />
            Sign out
          </button>
          <p className="mt-1 text-xs text-gray-400">
            Signed in as the wrong user? Sign out to switch.
          </p>
        </div>
      )}
    </div>
  </div>
);

export default POSOpeningDialog;
