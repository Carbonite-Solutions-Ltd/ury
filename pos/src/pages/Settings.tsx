import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  Loader2,
  RefreshCw,
  Settings as SettingsIcon,
  Info,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../components/ui/button';
import { usePOSStore } from '../store/pos-store';
import { extractFrappeServerError } from '../lib/utils';
import {
  getKotCoverageAudit,
  type KotCoverageAudit,
} from '../lib/settings-api';

/**
 * POS Settings — admin / manager only (see `canAccessSettings`, enforced
 * server-side by `_user_can_manage_settings`).
 *
 * Deliberately built as a stack of independent SECTIONS rather than one
 * page of fields, so further settings can be dropped in without
 * restructuring anything. Today it holds one section: the KOT routing
 * coverage check.
 */
const Settings = () => {
  const navigate = useNavigate();

  return (
    <div className="flex-1 min-h-0 overflow-y-auto bg-gray-50">
      <div className="max-w-4xl mx-auto px-4 py-6">
        <div className="flex items-center gap-3 mb-6">
          <Button
            variant="outline"
            onClick={() => navigate(-1)}
            className="border-gray-300 text-gray-700 hover:bg-white shrink-0"
          >
            <ChevronLeft className="w-4 h-4 mr-1" />
            Back
          </Button>
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-9 h-9 rounded-lg bg-blue-100 flex items-center justify-center shrink-0">
              <SettingsIcon className="w-5 h-5 text-blue-700" />
            </div>
            <div className="min-w-0">
              <h1 className="text-xl font-bold text-gray-900">Settings</h1>
              <p className="text-xs text-gray-500">
                Configuration checks and POS options.
              </p>
            </div>
          </div>
        </div>

        <KotCoverageSection />
      </div>
    </div>
  );
};

/**
 * "Kitchen / Bar Routing" check.
 *
 * Surfaces the silent failure mode of Production Unit mode: an item group
 * that belongs to no production unit produces NO KOT — it bills correctly
 * and never appears on any kitchen or bar screen, with no error logged.
 * On a live site a BEER DRINKS group sat unattached for months and every
 * beer was invisible to the bar. This makes that checkable in seconds.
 */
const KotCoverageSection = () => {
  const { terminalName } = usePOSStore();
  const [audit, setAudit] = useState<KotCoverageAudit | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setAudit(await getKotCoverageAudit(terminalName));
    } catch (err) {
      setError(
        extractFrappeServerError(err, 'Could not run the routing check.').message
      );
      setAudit(null);
    } finally {
      setLoading(false);
    }
  }, [terminalName]);

  useEffect(() => {
    load();
  }, [load]);

  const uncovered = audit?.item_groups.filter((g) => !g.covered) ?? [];
  const emptyProductions =
    audit?.productions.filter((p) => p.item_groups.length === 0) ?? [];

  return (
    <section className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-gray-900">
            Kitchen / Bar Routing
          </h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Checks that every item on the menu reaches a kitchen or bar
            screen.
          </p>
        </div>
        <Button
          variant="outline"
          onClick={load}
          disabled={loading}
          className="border-gray-300 text-gray-700 hover:bg-gray-50 shrink-0"
        >
          {loading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <RefreshCw className="w-4 h-4" />
          )}
          <span className="ml-1.5 hidden sm:inline">Re-check</span>
        </Button>
      </div>

      <div className="px-5 py-4">
        {loading && !audit && (
          <div className="flex items-center justify-center py-8 text-gray-400">
            <Loader2 className="w-5 h-5 animate-spin" />
            <span className="ml-2 text-sm">Checking the menu…</span>
          </div>
        )}

        {error && (
          <div className="p-3 rounded-lg bg-red-50 border border-red-200 flex gap-2.5 text-sm text-red-700">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <div>{error}</div>
          </div>
        )}

        {audit && !error && (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
              <Stat label="Branch" value={audit.branch || '—'} />
              <Stat label="KDS Mode" value={audit.kds_routing_mode} />
              <Stat label="Item Groups" value={String(audit.total_item_groups)} />
              <Stat label="Menu Items" value={String(audit.total_items)} />
            </div>

            {/* Menu Course mode can't silently drop anything, so say so
                instead of raising a false alarm. */}
            {audit.drops_unmatched_items === 0 ? (
              <div className="p-3 rounded-lg bg-blue-50 border border-blue-200 flex gap-2.5 text-sm text-blue-900 mb-4">
                <Info className="w-4 h-4 shrink-0 mt-0.5" />
                <div>
                  This profile is in <strong>Menu Course</strong> mode. Items
                  that match no production unit still get a ticket (split by
                  department downstream), so nothing is lost — the list below
                  is informational.
                </div>
              </div>
            ) : uncovered.length === 0 ? (
              <div className="p-3 rounded-lg bg-emerald-50 border border-emerald-200 flex gap-2.5 text-sm text-emerald-900 mb-4">
                <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
                <div>
                  Every item group on this branch's menus routes to a
                  production unit. Nothing will be dropped.
                </div>
              </div>
            ) : (
              <div className="p-3 rounded-lg bg-red-50 border border-red-200 flex gap-2.5 text-sm text-red-800 mb-4">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <div>
                  <p className="font-semibold mb-1">
                    {audit.uncovered_item_total} item
                    {audit.uncovered_item_total === 1 ? '' : 's'} in{' '}
                    {uncovered.length} group
                    {uncovered.length === 1 ? '' : 's'} will NOT reach any
                    screen.
                  </p>
                  <p>
                    This profile is in <strong>URY Production Unit</strong>{' '}
                    mode, so an item whose group belongs to no production unit
                    gets no ticket at all. It still bills and prints on the
                    receipt — it just never appears in the kitchen or bar, with
                    no error shown. Add the group(s) below to the right
                    production unit in the desk.
                  </p>
                </div>
              </div>
            )}

            {emptyProductions.length > 0 && (
              <div className="p-3 rounded-lg bg-amber-50 border border-amber-200 flex gap-2.5 text-sm text-amber-900 mb-4">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold">
                    {emptyProductions.map((p) => p.production).join(', ')}
                  </span>{' '}
                  {emptyProductions.length === 1 ? 'has' : 'have'} no item
                  groups configured, so {emptyProductions.length === 1 ? 'it' : 'they'}{' '}
                  will never receive an order.
                </div>
              </div>
            )}

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-gray-500 border-b border-gray-200">
                    <th className="py-2 pr-3 font-medium">Item Group</th>
                    <th className="py-2 pr-3 font-medium">Items</th>
                    <th className="py-2 pr-3 font-medium">Goes To</th>
                    <th className="py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.item_groups.map((g) => (
                    <tr
                      key={g.item_group}
                      className={`border-b border-gray-100 last:border-0 ${
                        !g.covered && audit.drops_unmatched_items === 1
                          ? 'bg-red-50/60'
                          : ''
                      }`}
                    >
                      <td className="py-2.5 pr-3">
                        <div className="font-medium text-gray-900">
                          {g.item_group}
                        </div>
                        {g.sample_items.length > 0 && (
                          <div className="text-xs text-gray-500 truncate max-w-xs">
                            {g.sample_items.join(', ')}
                          </div>
                        )}
                      </td>
                      <td className="py-2.5 pr-3 text-gray-700">
                        {g.item_count}
                      </td>
                      <td className="py-2.5 pr-3 text-gray-700">
                        {g.productions.length > 0 ? (
                          g.productions.join(', ')
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="py-2.5">
                        {g.covered ? (
                          <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            Routed
                          </span>
                        ) : audit.drops_unmatched_items === 1 ? (
                          <span className="inline-flex items-center gap-1 text-xs font-medium text-red-700">
                            <AlertTriangle className="w-3.5 h-3.5" />
                            No ticket
                          </span>
                        ) : (
                          <span className="text-xs text-gray-500">
                            Fallback ticket
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {audit.item_groups.length === 0 && (
                    <tr>
                      <td colSpan={4} className="py-6 text-center text-gray-400">
                        No menu items found for this branch.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {audit.menus_checked.length > 0 && (
              <p className="mt-3 text-xs text-gray-400">
                Menus checked: {audit.menus_checked.join(', ')}
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
};

const Stat = ({ label, value }: { label: string; value: string }) => (
  <div className="rounded-lg bg-gray-50 border border-gray-200 px-3 py-2">
    <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
    <div className="text-sm font-semibold text-gray-900 truncate" title={value}>
      {value}
    </div>
  </div>
);

export default Settings;
