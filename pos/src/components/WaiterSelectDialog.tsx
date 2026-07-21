import React, { useEffect, useState } from 'react';
import { Search, UserRound, Plus, X, Loader2 } from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { showToast } from './ui/toast';
import { extractFrappeServerError } from '../lib/utils';
import { loadWaitersWithCache, createWaiter, type Waiter } from '../lib/waiter-api';

/**
 * Waiter picker shown when the cashier creates a NEW order on a POS
 * Profile with `custom_use_waiter` on. Picking (or quick-adding) a waiter
 * calls `onSelect`, which the OrderPanel uses to continue the submit.
 */
interface WaiterSelectDialogProps {
  onSelect: (waiter: Waiter) => void;
  onCancel: () => void;
}

const WaiterSelectDialog: React.FC<WaiterSelectDialogProps> = ({
  onSelect,
  onCancel,
}) => {
  const [query, setQuery] = useState('');
  const [allWaiters, setAllWaiters] = useState<Waiter[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState('');
  const [newMobile, setNewMobile] = useState('');
  const [saving, setSaving] = useState(false);

  // Load the full active-waiter list once (offline-first: a cached copy is
  // used when there's no internet). Filtering is client-side below so the
  // picker AND its search both work offline.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const list = await loadWaitersWithCache();
        if (!cancelled) setAllWaiters(list);
      } catch (e) {
        if (!cancelled) {
          showToast.error(
            extractFrappeServerError(e, 'Failed to load waiters').message
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const q = query.trim().toLowerCase();
  const waiters = q
    ? allWaiters.filter(
        (w) =>
          w.full_name.toLowerCase().includes(q) ||
          (w.mobile_number || '').toLowerCase().includes(q)
      )
    : allWaiters;

  const handleAdd = async () => {
    const name = newName.trim();
    if (!name) {
      showToast.error('Enter the waiter name');
      return;
    }
    setSaving(true);
    try {
      const w = await createWaiter(name, newMobile.trim() || undefined);
      showToast.success('Waiter added');
      onSelect(w);
    } catch (e) {
      const p = extractFrappeServerError(e, 'Failed to add waiter');
      showToast.error({ title: p.title || 'Add Failed', description: p.message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md bg-white rounded-xl shadow-xl flex flex-col max-h-[85vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-lg font-bold text-gray-900">Select Waiter</h2>
            <p className="text-xs text-gray-500">Assign a waiter to this order.</p>
          </div>
          <button
            onClick={onCancel}
            className="text-gray-400 hover:text-gray-700"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {!showAdd ? (
          <>
            <div className="px-5 pt-4">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                <Input
                  autoFocus
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search waiter…"
                  className="pl-9"
                />
              </div>
            </div>
            <div className="flex-1 overflow-y-auto overscroll-contain px-5 py-3 space-y-1.5 min-h-[140px]">
              {loading ? (
                <div className="flex items-center justify-center py-10 text-gray-400">
                  <Loader2 className="w-5 h-5 animate-spin" />
                </div>
              ) : waiters.length === 0 ? (
                <div className="text-center text-sm text-gray-500 py-10">
                  No waiters found.
                </div>
              ) : (
                waiters.map((w) => (
                  <button
                    key={w.name}
                    onClick={() => onSelect(w)}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-blue-50 text-left border border-transparent hover:border-blue-200 transition-colors"
                  >
                    <div className="w-9 h-9 rounded-full bg-gray-100 flex items-center justify-center shrink-0">
                      <UserRound className="w-4 h-4 text-gray-600" />
                    </div>
                    <div className="min-w-0">
                      <div className="font-medium text-gray-900 truncate">
                        {w.full_name}
                      </div>
                      {w.mobile_number && (
                        <div className="text-xs text-gray-500 truncate">
                          {w.mobile_number}
                        </div>
                      )}
                    </div>
                  </button>
                ))
              )}
            </div>
            <div className="px-5 py-3 border-t border-gray-100">
              <Button
                variant="outline"
                className="w-full"
                onClick={() => {
                  setNewName(query.trim());
                  setShowAdd(true);
                }}
              >
                <Plus className="w-4 h-4 mr-2" /> Add New Waiter
              </Button>
            </div>
          </>
        ) : (
          <div className="px-5 py-4 space-y-3">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Full Name
              </label>
              <Input
                autoFocus
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Waiter's full name"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Mobile Number
              </label>
              <Input
                value={newMobile}
                onChange={(e) => setNewMobile(e.target.value)}
                placeholder="Optional"
              />
            </div>
            <div className="flex gap-2 pt-1">
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => setShowAdd(false)}
                disabled={saving}
              >
                Back
              </Button>
              <Button
                className="flex-1"
                onClick={handleAdd}
                disabled={saving || !newName.trim()}
              >
                {saving ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  'Add & Select'
                )}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default WaiterSelectDialog;
