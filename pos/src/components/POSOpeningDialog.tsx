import { useEffect, useMemo, useState } from 'react';
import { RefreshCw, AlertTriangle, Clock, DoorOpen, CheckCircle2, Loader2 } from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { usePOSStore } from '../store/pos-store';
import { useRootStore } from '../store/root-store';
import {
  createAndSubmitPOSOpening,
  getCurrentPosOpenEntry,
  getOpeningBalanceDetails,
  hasMainCashierOpened,
  type OpeningBalanceRow,
} from '../lib/pos-opening-api';
import { extractFrappeServerError } from '../lib/utils';
import POSClosingDialog from './POSClosingDialog';

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
 * Entry without ever sending the user to the Frappe desk. In multi-cashier
 * mode it detects whether the current user is the "main cashier" (captain)
 * and adapts: main cashier sees the full form; sub-cashiers see a one-click
 * "Join Session" button once the captain has opened, or a "waiting for main
 * cashier" screen otherwise.
 *
 * For (b) it shows a focused message + a "Close Previous Session" deep-link
 * to the specific unclosed entry. A full in-POS closing dialog is phase-2
 * backlog.
 */
const POSOpeningDialog = ({ type, onOpened, unclosedEntry }: POSOpeningDialogProps) => {
  const { posProfile, terminalName } = usePOSStore();
  const { user } = useRootStore();

  // ───── closing-issue branch ─────
  if (type === 'closing') {
    const closingHref = unclosedEntry
      ? `${window.location.origin}/app/pos-opening-entry/${encodeURIComponent(unclosedEntry)}`
      : `${window.location.origin}/app/pos-opening-entry`;

    return (
      <DialogShell
        icon={<AlertTriangle className="h-8 w-8 text-orange-600" />}
        iconBg="bg-orange-100"
        title="Previous POS Not Closed"
        subtitle={
          unclosedEntry
            ? `Entry ${unclosedEntry} is still open. Close it before starting today's session.`
            : 'A previous POS Opening Entry is still open. Close it before starting today.'
        }
      >
        <Button
          onClick={() => window.open(closingHref, '_blank')}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 px-6 rounded-lg"
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
  posProfile: ReturnType<typeof usePOSStore>['posProfile'];
  user: ReturnType<typeof useRootStore>['user'];
  terminalName: string | null;
  onOpened: () => void;
}

type OpeningMode =
  | { kind: 'loading' }
  | { kind: 'main-cashier' } // show full form
  | { kind: 'sub-cashier-ready' } // show Join Session button (legacy, unreachable under new model)
  | { kind: 'sub-cashier-waiting'; mainCashier: string } // show waiting screen (legacy, unreachable)
  | {
      kind: 'existing-entry';
      entryName: string | null;
      message: string;
    }; // ERPNext rejected with "POS Opening Entry Exists" — deep-link to that entry

const OpeningBranch = ({ posProfile, user, terminalName, onOpened }: OpeningBranchProps) => {
  const [mode, setMode] = useState<OpeningMode>({ kind: 'loading' });
  const [balanceRows, setBalanceRows] = useState<OpeningBalanceRow[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [showClosingDialog, setShowClosingDialog] = useState(false);

  const multiCashier = posProfile?.custom_enable_multiple_cashier === 1;
  const currentUser = user?.name || null;

  // Identify the main cashier (captain) from the POS Profile's applicable_for_users child table.
  const mainCashierUser = useMemo(() => {
    if (!multiCashier || !posProfile?.applicable_for_users) return null;
    const row = posProfile.applicable_for_users.find(u => u.custom_main_cashier === 1);
    return row?.user || null;
  }, [multiCashier, posProfile]);

  // Resolve which opening mode to show. Also seed balance rows.
  useEffect(() => {
    let cancelled = false;

    const resolve = async () => {
      if (!posProfile || !currentUser) return;

      // Non-multi-cashier: everyone sees the full form.
      if (!multiCashier) {
        const rows = await getOpeningBalanceDetails();
        if (cancelled) return;
        setBalanceRows(rows);
        setMode({ kind: 'main-cashier' });
        return;
      }

      // Multi-cashier: branch on whether the current user is the captain.
      if (mainCashierUser && currentUser === mainCashierUser) {
        const rows = await getOpeningBalanceDetails();
        if (cancelled) return;
        setBalanceRows(rows);
        setMode({ kind: 'main-cashier' });
        return;
      }

      // Sub-cashier path: has the captain opened yet?
      if (mainCashierUser) {
        try {
          const captainOpen = await hasMainCashierOpened(mainCashierUser, posProfile.name);
          if (cancelled) return;

          if (captainOpen) {
            // Preload zero-balance rows so "Join Session" creates a valid entry.
            const rows = await getOpeningBalanceDetails();
            if (cancelled) return;
            setBalanceRows(rows.map(r => ({ ...r, opening_amount: 0 })));
            setMode({ kind: 'sub-cashier-ready' });
          } else {
            setMode({ kind: 'sub-cashier-waiting', mainCashier: mainCashierUser });
          }
        } catch (err) {
          console.error('Failed to resolve main cashier status:', err);
          // Fall back to the full form — safer to let them try than to hard-block.
          const rows = await getOpeningBalanceDetails();
          if (cancelled) return;
          setBalanceRows(rows);
          setMode({ kind: 'main-cashier' });
        }
        return;
      }

      // Multi-cashier flag set but no captain marked — misconfiguration.
      // Fall through to the full form so the user can still proceed.
      const rows = await getOpeningBalanceDetails();
      if (cancelled) return;
      setBalanceRows(rows);
      setMode({ kind: 'main-cashier' });
    };

    resolve();
    return () => {
      cancelled = true;
    };
  }, [posProfile, currentUser, multiCashier, mainCashierUser]);

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

      // ERPNext throws this when there's already an open entry for the
      // same POS Profile (regardless of terminal). Look up which entry
      // is blocking and switch the dialog to a focused "Existing Open
      // Entry" mode with a deep-link button. See CLAUDE.md "Fixes log"
      // 2026-04-09.
      const titleMatches = parsed.title === 'POS Opening Entry Exists';
      const msgMatches = /pos opening entry to create a new pos opening/i.test(
        parsed.message
      );
      if (titleMatches || msgMatches) {
        try {
          const existing = await getCurrentPosOpenEntry(terminalName);
          setMode({
            kind: 'existing-entry',
            entryName: existing?.name || null,
            message: parsed.message,
          });
        } catch {
          setMode({
            kind: 'existing-entry',
            entryName: null,
            message: parsed.message,
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

  // ───── sub-cashier waiting for captain ─────
  if (mode.kind === 'sub-cashier-waiting') {
    return (
      <DialogShell
        icon={<Clock className="h-8 w-8 text-amber-600" />}
        iconBg="bg-amber-100"
        title="Waiting for Main Cashier"
        subtitle={`${mode.mainCashier} hasn't opened the POS yet. Ask them to open first, then reload.`}
      >
        <Button
          onClick={() => window.location.reload()}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 px-6 rounded-lg"
        >
          <RefreshCw className="w-5 h-5 mr-2" />
          Reload
        </Button>
      </DialogShell>
    );
  }

  // ───── sub-cashier ready to join captain's session ─────
  if (mode.kind === 'sub-cashier-ready') {
    return (
      <DialogShell
        icon={<DoorOpen className="h-8 w-8 text-blue-600" />}
        iconBg="bg-blue-100"
        title="Join Session"
        subtitle="Your main cashier has opened the POS. Click below to join."
      >
        {submitError && (
          <div className="mb-3 p-3 rounded-lg bg-red-50 text-red-700 text-sm">
            {submitError}
          </div>
        )}
        <Button
          onClick={handleOpen}
          disabled={submitting}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 px-6 rounded-lg"
        >
          {submitting ? (
            <>
              <Loader2 className="w-5 h-5 mr-2 animate-spin" />
              Joining…
            </>
          ) : (
            <>
              <DoorOpen className="w-5 h-5 mr-2" />
              Join Session
            </>
          )}
        </Button>
      </DialogShell>
    );
  }

  // ───── existing open entry blocking the new one ─────
  // ERPNext's `check_open_pos_exists` rejected the create because the
  // POS Profile already has an open entry (regardless of terminal). The
  // user can't open a new shift until that one is closed. Show a focused
  // card and let them close the entry IN-POS via POSClosingDialog rather
  // than dropping them onto the desk. See CLAUDE.md "Fixes log" 2026-04-09.
  if (mode.kind === 'existing-entry') {
    return (
      <>
        <DialogShell
          icon={<AlertTriangle className="h-8 w-8 text-orange-600" />}
          iconBg="bg-orange-100"
          title="Existing Open Entry"
          subtitle={
            mode.entryName
              ? `Entry ${mode.entryName} is still open on this POS Profile. Close it before starting a new shift.`
              : mode.message
          }
        >
          <Button
            onClick={() => mode.entryName && setShowClosingDialog(true)}
            disabled={!mode.entryName}
            className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 px-6 rounded-lg disabled:opacity-50"
          >
            <DoorOpen className="w-5 h-5 mr-2" />
            Close Existing Entry
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
}

const DialogShell = ({ icon, iconBg, title, subtitle, wide, children }: DialogShellProps) => (
  <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
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
    </div>
  </div>
);

export default POSOpeningDialog;
