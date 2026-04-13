/**
 * Unmerge dialog for URY Table Merge Log.
 *
 * Three modes based on the state returned by `get_active_table_merge_log`:
 *   1. No post-merge orders on the master → simple confirm. One click
 *      reverses the merge and (if the merge included orders) restores
 *      each source's pre-merge draft.
 *   2. Post-merge orders exist AND the profile's
 *      `custom_allow_unmerge_after_new_orders` is OFF → hard-block with
 *      a list of the blocking orders and a clear explanation.
 *   3. Post-merge orders exist AND the profile allows the unmerge →
 *      table of each post-merge order with a destination picker per
 *      row. Default destination is the master itself; cashier can
 *      reassign any / all orders to source tables.
 *
 * See CLAUDE.md "Fixes log" 2026-04-11 (table merge feature).
 */
import { useMemo, useState } from 'react';
import { AlertTriangle, Merge, Undo2, X } from 'lucide-react';
import { Button } from './ui/button';
import { Select, SelectItem } from './ui/select';
import type { ActiveTableMergeLog } from '../lib/table-api';
import { formatCurrency } from '../lib/utils';

interface TableUnmergeDialogProps {
  mergeLog: ActiveTableMergeLog;
  masterTable: string;
  onCancel: () => void;
  onConfirm: (args: {
    orderAssignments: Record<string, string> | null;
  }) => void;
  loading: boolean;
}

const TableUnmergeDialog: React.FC<TableUnmergeDialogProps> = ({
  mergeLog,
  masterTable,
  onCancel,
  onConfirm,
  loading,
}) => {
  const postMergeOrders = mergeLog.post_merge_orders || [];
  const hasPostMergeOrders = postMergeOrders.length > 0;
  const allowAfterNew = mergeLog.custom_allow_unmerge_after_new_orders === 1;

  const destinationChoices = useMemo(() => {
    const destinations: { value: string; label: string }[] = [
      { value: masterTable, label: `${masterTable} (master)` },
    ];
    for (const s of mergeLog.source_tables || []) {
      destinations.push({
        value: s.source_table,
        label: `${s.source_table}${s.original_room ? ' · ' + s.original_room : ''}`,
      });
    }
    return destinations;
  }, [mergeLog, masterTable]);

  // Default every post-merge order to the master.
  const [assignments, setAssignments] = useState<Record<string, string>>(
    () => {
      const out: Record<string, string> = {};
      for (const o of postMergeOrders) out[o.name] = masterTable;
      return out;
    }
  );

  const missingAssignment = postMergeOrders.some(
    (o) => !assignments[o.name]
  );

  const blockedMode = hasPostMergeOrders && !allowAfterNew;

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[92vh] flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-gray-200 px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-100 text-amber-700">
              <Undo2 className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-gray-900">
                Unmerge Tables
              </h2>
              <p className="text-xs text-gray-500 mt-0.5">
                Master: {masterTable} · merged from {mergeLog.source_count}{' '}
                table{mergeLog.source_count === 1 ? '' : 's'}
                {mergeLog.merged_by_full_name
                  ? ` by ${mergeLog.merged_by_full_name}`
                  : ''}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="rounded p-1 text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
            aria-label="Cancel"
            disabled={loading}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {/* Source tables that will come back */}
          <div>
            <div className="text-xs font-semibold text-gray-700 mb-1.5">
              Tables that will be restored
            </div>
            <div className="rounded-md border border-gray-200 bg-gray-50 divide-y divide-gray-200 overflow-hidden">
              {(mergeLog.source_tables || []).map((s) => (
                <div
                  key={s.source_table}
                  className="flex items-center justify-between px-3 py-2 text-xs"
                >
                  <div>
                    <span className="font-medium text-gray-900">
                      {s.source_table}
                    </span>
                    {s.original_room && (
                      <span className="text-gray-500">
                        {' '}
                        · {s.original_room}
                      </span>
                    )}
                  </div>
                  {s.had_active_order === 1 && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 text-blue-800 px-2 py-0.5 font-semibold">
                      <Merge className="w-3 h-3" /> order restored
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Blocked mode: post-merge orders + profile doesn't allow */}
          {blockedMode && (
            <div className="rounded-md border border-red-300 bg-red-50 p-3">
              <div className="flex items-start gap-2 mb-2">
                <AlertTriangle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
                <div className="text-sm font-semibold text-red-900">
                  Unmerge blocked: new orders on the master
                </div>
              </div>
              <div className="text-xs text-red-800 mb-2">
                {postMergeOrders.length} order(s) were placed on{' '}
                {masterTable} after the merge. Unmerging would strand them
                on the hidden source tables. Pay or cancel these orders
                first, OR ask an admin to turn on "Allow Table Unmerge
                After New Orders" on the POS Profile.
              </div>
              <ul className="text-[11px] font-mono text-red-700 space-y-0.5">
                {postMergeOrders.slice(0, 5).map((o) => (
                  <li key={o.name}>
                    • {o.name} · {o.customer_name || o.customer} ·{' '}
                    {formatCurrency(o.grand_total || 0)}
                  </li>
                ))}
                {postMergeOrders.length > 5 && (
                  <li className="text-red-600 italic">
                    (+{postMergeOrders.length - 5} more)
                  </li>
                )}
              </ul>
            </div>
          )}

          {/* Allowed mode with post-merge orders: assignment table */}
          {hasPostMergeOrders && allowAfterNew && (
            <div>
              <div className="text-xs font-semibold text-gray-700 mb-1.5">
                Assign post-merge orders to destination tables
              </div>
              <div className="rounded-md border border-amber-200 bg-amber-50 p-3 mb-2 text-xs text-amber-900">
                These {postMergeOrders.length} order(s) were placed on
                the master after the merge. Pick a destination for each
                one. Default is the master itself.
              </div>
              <div className="rounded-md border border-gray-200 overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 text-gray-700 uppercase tracking-wide">
                    <tr>
                      <th className="text-left px-3 py-2 font-semibold">
                        Order
                      </th>
                      <th className="text-left px-3 py-2 font-semibold">
                        Customer
                      </th>
                      <th className="text-right px-3 py-2 font-semibold">
                        Total
                      </th>
                      <th className="text-left px-3 py-2 font-semibold">
                        Destination
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {postMergeOrders.map((o) => (
                      <tr key={o.name}>
                        <td className="px-3 py-2 font-mono text-gray-700">
                          {o.name}
                        </td>
                        <td className="px-3 py-2 text-gray-700 truncate max-w-[160px]">
                          {o.customer_name || o.customer}
                        </td>
                        <td className="px-3 py-2 text-right font-semibold text-gray-900 tabular-nums">
                          {formatCurrency(o.grand_total || 0)}
                        </td>
                        <td className="px-3 py-2">
                          <Select
                            value={assignments[o.name] || masterTable}
                            onValueChange={(v) =>
                              setAssignments((prev) => ({
                                ...prev,
                                [o.name]: v,
                              }))
                            }
                            size="sm"
                          >
                            {destinationChoices.map((d) => (
                              <SelectItem key={d.value} value={d.value}>
                                {d.label}
                              </SelectItem>
                            ))}
                          </Select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Simple-confirm copy when there are no post-merge orders */}
          {!hasPostMergeOrders && (
            <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700">
              No new orders were placed on {masterTable} after the merge.
              Unmerge will restore the source tables and{' '}
              {mergeLog.merged_orders === 1
                ? "split the combined order back into the sources' original drafts."
                : 'leave the master order on the master table.'}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex gap-3 border-t border-gray-200 px-5 py-4">
          <Button
            onClick={onCancel}
            variant="outline"
            className="flex-1"
            disabled={loading}
          >
            Cancel
          </Button>
          {!blockedMode && (
            <Button
              onClick={() =>
                onConfirm({
                  orderAssignments: hasPostMergeOrders
                    ? assignments
                    : null,
                })
              }
              className="flex-1 bg-amber-600 hover:bg-amber-700 text-white"
              disabled={loading || missingAssignment}
            >
              {loading ? 'Unmerging…' : 'Confirm Unmerge'}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};

export default TableUnmergeDialog;
