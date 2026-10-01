import { useEffect, useState } from 'react';
import { Monitor, X, Building2, AlertTriangle, Check } from 'lucide-react';
import { Button } from './ui';
import { getTerminals, saveTerminal, TerminalConfig } from '../lib/terminal-api';
import {
  groupTerminalsByBranch,
  clearBranchScopedCaches,
} from '../lib/branch-scope';
import { extractFrappeServerError } from '../lib/utils';

/**
 * Switch the till this device is trading on.
 *
 * ⚠ WHY THIS IS GROUPED BY BRANCH AND WARNS BEFORE SWITCHING.
 * A terminal picks the POS Profile, which picks the branch, which picks the
 * menu — and **each menu has its own price list**. On this client the same
 * item is priced very differently per outlet (COKE 12.00 vs 35.00, STAR L/S
 * 25.00 vs 55.00), so trading on the wrong branch undercharges by roughly
 * half. A flat list of every terminal is how that mistake gets made, so the
 * branch is a heading here rather than a detail on the row.
 *
 * Switching DISCARDS the cart. It has to: the lines in it were priced by the
 * branch being left, and carrying them across is precisely the error this
 * dialog exists to prevent. That is stated before the user commits, with the
 * count, rather than discovered afterwards.
 *
 * Offered whenever the user can reach more than one terminal — not by role.
 * The server re-checks branch access on the switch itself
 * (`_require_branch_access`), so this only decides whether to show the door.
 */

interface TerminalSwitchDialogProps {
  isOpen: boolean;
  onClose: () => void;
  currentTerminal: string | null;
  /** Lines in the cart right now — they are cleared by a switch. */
  cartItemCount?: number;
}

const TerminalSwitchDialog = ({
  isOpen,
  onClose,
  currentTerminal,
  cartItemCount = 0,
}: TerminalSwitchDialogProps) => {
  const [terminals, setTerminals] = useState<TerminalConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);

  // Re-fetch on every open. The dialog stays mounted, so without this it
  // would show whatever the terminal list was the first time it opened —
  // the same stale-state trap already fixed in CommentDialog.
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;

    setLoading(true);
    setError(null);
    setPicked(null);

    getTerminals()
      .then((list) => {
        if (cancelled) return;
        setTerminals(
          list.map((t) => ({ ...t, terminal: t.terminal || (t as { name?: string }).name || '' }))
        );
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          extractFrappeServerError(err, "Couldn't load your terminals.").message
        );
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const groups = groupTerminalsByBranch(terminals);
  const pickedTerminal = terminals.find((t) => t.terminal === picked) || null;
  const changingBranch =
    !!pickedTerminal &&
    !!currentTerminal &&
    pickedTerminal.branch !==
      terminals.find((t) => t.terminal === currentTerminal)?.branch;

  const handleSwitch = () => {
    if (!picked || picked === currentTerminal) return;
    setSwitching(true);
    // Drop the previous branch's menu, prices, profile and cart BEFORE the
    // new terminal is saved, so the reload cannot repopulate from them.
    clearBranchScopedCaches();
    saveTerminal(picked);
    window.location.reload();
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-start sm:items-center justify-center z-50 overflow-y-auto p-4">
      <div className="bg-white rounded-lg max-w-lg w-full shadow-xl my-auto">
        <div className="flex items-center justify-between p-6 pb-4">
          <div className="flex items-center gap-2">
            <Monitor className="w-5 h-5 text-blue-600" />
            <h2 className="text-lg font-semibold text-gray-900">Switch Till</h2>
          </div>
          <Button
            onClick={onClose}
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0"
            disabled={switching}
          >
            <X className="w-4 h-4" />
          </Button>
        </div>

        <div className="px-6 pb-2">
          <p className="text-sm text-gray-600">
            Each till belongs to one branch and loads that branch's menu and
            prices. Pick the till you're actually working on.
          </p>
        </div>

        <div className="px-6 py-4 max-h-[50vh] overflow-y-auto">
          {loading && (
            <p className="text-sm text-gray-500 py-6 text-center">
              Loading your tills...
            </p>
          )}

          {!loading && error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
              {error}
            </div>
          )}

          {!loading &&
            !error &&
            groups.map((group) => (
              <div key={group.branch} className="mb-5 last:mb-0">
                <div className="flex items-center gap-1.5 mb-2">
                  <Building2 className="w-3.5 h-3.5 text-gray-400" />
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                    {group.branch}
                  </h3>
                </div>
                <div className="space-y-2">
                  {group.terminals.map((t) => {
                    const isCurrent = t.terminal === currentTerminal;
                    const unconfigured = !t.pos_profile;
                    const isPicked = picked === t.terminal;
                    return (
                      <button
                        key={t.terminal}
                        type="button"
                        disabled={unconfigured || isCurrent || switching}
                        onClick={() => setPicked(t.terminal)}
                        className={[
                          'w-full text-left rounded-lg border p-3 transition',
                          isPicked
                            ? 'border-blue-500 bg-blue-50 ring-1 ring-blue-500'
                            : 'border-gray-200 hover:border-blue-300 hover:bg-gray-50',
                          unconfigured || isCurrent
                            ? 'opacity-60 cursor-not-allowed hover:border-gray-200 hover:bg-transparent'
                            : '',
                        ].join(' ')}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium text-gray-900 truncate">
                            {t.terminal}
                          </span>
                          {isCurrent && (
                            <span className="shrink-0 inline-flex items-center gap-1 text-xs font-semibold text-green-700">
                              <Check className="w-3.5 h-3.5" />
                              Current
                            </span>
                          )}
                          {isPicked && !isCurrent && (
                            <Check className="w-4 h-4 text-blue-600 shrink-0" />
                          )}
                        </div>
                        <div className="text-xs text-gray-500 mt-0.5 truncate">
                          {unconfigured ? (
                            <span className="text-red-600">
                              Not configured — no POS Profile linked
                            </span>
                          ) : (
                            <>
                              {t.pos_profile}
                              {t.description ? ` · ${t.description}` : ''}
                            </>
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
        </div>

        {/* Stated before committing, not discovered afterwards. */}
        {picked && cartItemCount > 0 && (
          <div className="mx-6 mb-2 rounded-lg border border-amber-300 bg-amber-50 p-3 flex gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-700 shrink-0 mt-0.5" />
            <p className="text-xs text-amber-900">
              The <strong>{cartItemCount}</strong>{' '}
              {cartItemCount === 1 ? 'item' : 'items'} in your cart will be
              cleared. They were priced by {changingBranch ? 'the branch you’re leaving' : 'the current till'}.
            </p>
          </div>
        )}

        <div className="flex gap-3 justify-end p-6 pt-3 border-t border-gray-100">
          <Button onClick={onClose} variant="outline" disabled={switching}>
            Cancel
          </Button>
          <Button
            onClick={handleSwitch}
            disabled={!picked || picked === currentTerminal || switching}
            className="bg-blue-600 hover:bg-blue-700"
          >
            {switching ? 'Switching...' : 'Switch Till'}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default TerminalSwitchDialog;
