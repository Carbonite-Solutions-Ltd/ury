/**
 * Confirm dialog for merging several URY Tables into a master.
 *
 * Rendered from Table.tsx after the cashier picks 2+ OCCUPIED tables
 * in merge mode. Lets them:
 *   - Change which selected table is the master (defaults to the first)
 *   - Mark each source as "Still in use" (default — hidden behind the
 *     master so the combined order gets rung through from there) OR
 *     "Now empty" (customers vacated that table, it returns to the
 *     Available grid for the next customer)
 *   - Drop in a free-text note for the audit log
 *
 * Every selected table is guaranteed to have a draft order — the
 * Table page blocks selection on available tables and the backend
 * rejects empty-table merges.
 *
 * See CLAUDE.md "Fixes log" 2026-04-11 (table merge feature).
 */
import { useMemo, useState } from 'react';
import { AlertTriangle, Merge, X } from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Select, SelectItem } from './ui/select';
import type { Table } from '../lib/table-api';

type SourceOccupancy = 'still_in_use' | 'now_empty';

interface TableMergeDialogProps {
  selectedTables: Table[];
  onCancel: () => void;
  onConfirm: (args: {
    master: string;
    freedSources: string[];
    notes: string;
  }) => void;
  loading: boolean;
}

const TableMergeDialog: React.FC<TableMergeDialogProps> = ({
  selectedTables,
  onCancel,
  onConfirm,
  loading,
}) => {
  const [master, setMaster] = useState<string>(
    selectedTables[0]?.name ?? ''
  );
  const [notes, setNotes] = useState<string>('');

  // Per-source occupancy. Default is "still_in_use" — safest default
  // since it keeps the old behavior (source hidden behind master).
  const [occupancy, setOccupancy] = useState<Record<string, SourceOccupancy>>(
    () => {
      const out: Record<string, SourceOccupancy> = {};
      for (const t of selectedTables) {
        if (t.name !== master) out[t.name] = 'still_in_use';
      }
      return out;
    }
  );

  const roomsInvolved = useMemo(() => {
    const set = new Set<string>();
    for (const t of selectedTables) set.add(t.restaurant_room);
    return Array.from(set);
  }, [selectedTables]);
  const crossRoom = roomsInvolved.length > 1;

  const sourceList = useMemo(
    () => selectedTables.filter((t) => t.name !== master),
    [selectedTables, master]
  );

  // Sources that the cashier marked as "now empty" — will be sent to
  // the backend so those tables stay Available in the grid.
  const freedSources = useMemo(
    () => sourceList.filter((t) => occupancy[t.name] === 'now_empty').map((t) => t.name),
    [sourceList, occupancy]
  );

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-xl max-h-[92vh] flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-gray-200 px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-100 text-amber-700">
              <Merge className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-gray-900">
                Merge Tables
              </h2>
              <p className="text-xs text-gray-500 mt-0.5">
                {selectedTables.length} tables selected · all have active orders
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

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {/* Master picker */}
          <div>
            <label className="block text-xs font-semibold text-gray-700 mb-1.5">
              Master Table (final combined table)
            </label>
            <Select value={master} onValueChange={setMaster} size="sm">
              {selectedTables.map((t) => (
                <SelectItem key={t.name} value={t.name}>
                  {t.name} · {t.restaurant_room}
                </SelectItem>
              ))}
            </Select>
            <p className="text-[11px] text-gray-500 mt-1.5">
              The combined order will sit on this table. Other tables
              become sources — their orders are merged in.
            </p>
          </div>

          {/* Per-source occupancy picker */}
          <div>
            <div className="text-xs font-semibold text-gray-700 mb-1.5">
              Are the customers still at each source table?
            </div>
            <div className="rounded-md border border-gray-200 bg-gray-50 divide-y divide-gray-200 overflow-hidden">
              {sourceList.length === 0 ? (
                <div className="px-3 py-2 text-xs italic text-gray-500">
                  Pick a different master to see the source list.
                </div>
              ) : (
                sourceList.map((t) => {
                  const value = occupancy[t.name] || 'still_in_use';
                  return (
                    <div
                      key={t.name}
                      className="px-3 py-3 space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <div className="text-sm">
                          <span className="font-semibold text-gray-900">
                            {t.name}
                          </span>
                          <span className="text-gray-500">
                            {' '}
                            · {t.restaurant_room}
                          </span>
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <button
                          type="button"
                          onClick={() =>
                            setOccupancy((prev) => ({
                              ...prev,
                              [t.name]: 'still_in_use',
                            }))
                          }
                          className={`rounded-md border px-3 py-2 text-xs font-semibold transition-colors text-left ${
                            value === 'still_in_use'
                              ? 'border-amber-500 bg-amber-100 text-amber-900'
                              : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300'
                          }`}
                        >
                          <div>Still in use</div>
                          <div className="text-[10px] font-normal opacity-80 mt-0.5">
                            Hidden behind master until unmerged
                          </div>
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            setOccupancy((prev) => ({
                              ...prev,
                              [t.name]: 'now_empty',
                            }))
                          }
                          className={`rounded-md border px-3 py-2 text-xs font-semibold transition-colors text-left ${
                            value === 'now_empty'
                              ? 'border-emerald-500 bg-emerald-100 text-emerald-900'
                              : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300'
                          }`}
                        >
                          <div>Now empty</div>
                          <div className="text-[10px] font-normal opacity-80 mt-0.5">
                            Returns to the Available grid
                          </div>
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
            {freedSources.length > 0 && (
              <p className="text-[11px] text-emerald-700 mt-1.5 font-medium">
                {freedSources.length} table
                {freedSources.length === 1 ? '' : 's'} will be returned
                to the Available grid after the merge.
              </p>
            )}
          </div>

          {/* Cross-room warning */}
          {crossRoom && (
            <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
              <div className="text-xs text-amber-900">
                <div className="font-semibold">Cross-room merge</div>
                <div>
                  Selected tables span {roomsInvolved.length} rooms:{' '}
                  {roomsInvolved.join(', ')}. This is allowed but
                  reporting will group the combined order under the
                  master's room.
                </div>
              </div>
            </div>
          )}

          {/* Notes */}
          <div>
            <label className="block text-xs font-semibold text-gray-700 mb-1.5">
              Notes (optional)
            </label>
            <Input
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Reason / remarks"
              size="sm"
              disabled={loading}
            />
          </div>
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
          <Button
            onClick={() =>
              onConfirm({ master, freedSources, notes })
            }
            className="flex-1 bg-amber-600 hover:bg-amber-700 text-white"
            disabled={loading || !master || selectedTables.length < 2}
          >
            {loading ? 'Merging…' : `Merge ${selectedTables.length} Tables`}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default TableMergeDialog;
