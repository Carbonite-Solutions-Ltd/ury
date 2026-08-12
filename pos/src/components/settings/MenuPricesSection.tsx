import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Check,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from 'lucide-react';
import { Button } from '../ui/button';
import { showToast } from '../ui/toast';
import { extractFrappeServerError, formatCurrency } from '../../lib/utils';
import {
  addMenuItems,
  getItemGroupsForMenu,
  getMenuItemsForSettings,
  getMenusForSettings,
  removeMenuItems,
  saveMenuItemRates,
  searchItemsForMenu,
  type CandidateItem,
  type MenuItemRow,
  type MenuItemsResponse,
  type MenuSummary,
} from '../../lib/settings-api';

type PriceFilter = 'all' | 'unpriced' | 'priced';

/**
 * Menu & Prices — pick a menu, price its items, add or remove them.
 *
 * WHY EDITS ARE BATCHED. Saving a URY Menu rebuilds its ENTIRE price
 * list: every Item Price for that list is deleted and re-inserted, one
 * per row. On a 400-line menu, saving per edited row would mean 400
 * deletes and 400 inserts each time a price is typed. So rates are held
 * as pending edits and committed in a single call.
 *
 * THE OTHER THING WORTH KNOWING. `URY Menu.validate()` copies an Item's
 * `standard_rate` into any row whose rate is blank, on every save. So
 * clearing a price does not stick for an item that has a standard rate —
 * it comes straight back. The row shows that inline rather than letting
 * the edit appear to vanish.
 */
const MenuPricesSection = () => {
  const [menus, setMenus] = useState<MenuSummary[]>([]);
  const [selected, setSelected] = useState<string>('');
  const [data, setData] = useState<MenuItemsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<PriceFilter>('all');
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [showAdd, setShowAdd] = useState(false);

  const loadMenus = useCallback(async () => {
    try {
      const list = await getMenusForSettings();
      setMenus(list);
      setSelected((cur) => cur || list[0]?.name || '');
    } catch (err) {
      setError(extractFrappeServerError(err, 'Could not load menus.').message);
    }
  }, []);

  const loadItems = useCallback(async (menu: string) => {
    if (!menu) return;
    setLoading(true);
    setError(null);
    setEdits({});
    try {
      setData(await getMenuItemsForSettings(menu));
    } catch (err) {
      setError(extractFrappeServerError(err, 'Could not load this menu.').message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMenus();
  }, [loadMenus]);
  useEffect(() => {
    if (selected) loadItems(selected);
  }, [selected, loadItems]);

  const rows = useMemo(() => {
    const all = data?.items ?? [];
    const q = search.trim().toLowerCase();
    return all.filter((r) => {
      if (filter === 'unpriced' && r.rate) return false;
      if (filter === 'priced' && !r.rate) return false;
      if (!q) return true;
      return (
        r.item.toLowerCase().includes(q) ||
        (r.item_name || '').toLowerCase().includes(q) ||
        (r.course || '').toLowerCase().includes(q)
      );
    });
  }, [data, search, filter]);

  const unpricedCount = useMemo(
    () => (data?.items ?? []).filter((r) => !r.rate).length,
    [data]
  );
  const pendingCount = Object.keys(edits).length;

  const handleSave = async () => {
    if (!selected || !pendingCount) return;
    const payload: Record<string, number> = {};
    for (const [item, raw] of Object.entries(edits)) {
      const n = Number(raw);
      if (Number.isFinite(n) && n >= 0) payload[item] = n;
    }
    setSaving(true);
    try {
      const res = await saveMenuItemRates(selected, payload);
      showToast.success(`Saved ${res.updated} price${res.updated === 1 ? '' : 's'}`);
      if (res.blocked_by_standard_rate?.length) {
        showToast.info({
          title: "Some prices didn't clear",
          description:
            `${res.blocked_by_standard_rate.length} item(s) have a standard rate on ` +
            `the Item record, which is copied back in automatically. Clear it there ` +
            `to leave them unpriced.`,
        });
      }
      await loadItems(selected);
      loadMenus();
    } catch (err) {
      const p = extractFrappeServerError(err, 'Could not save prices.');
      showToast.error({ title: p.title || 'Save failed', description: p.message });
    } finally {
      setSaving(false);
    }
  };

  const handleRemove = async (item: string, label: string) => {
    if (!selected) return;
    try {
      await removeMenuItems(selected, [item]);
      showToast.success(`Removed ${label}`);
      await loadItems(selected);
      loadMenus();
    } catch (err) {
      const p = extractFrappeServerError(err, 'Could not remove the item.');
      showToast.error({ title: p.title || 'Remove failed', description: p.message });
    }
  };

  return (
    <section className="bg-white border border-gray-200 rounded-lg">
      {/* header */}
      <div className="px-4 sm:px-5 py-4 border-b border-gray-200">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-gray-900">Menu &amp; Prices</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Price the items on a menu, or add and remove them.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={() => selected && loadItems(selected)}
              disabled={loading || !selected}
              className="border-gray-300 text-gray-700"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </Button>
            <Button
              onClick={() => setShowAdd(true)}
              disabled={!selected}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              <Plus className="w-4 h-4 mr-1.5" />
              Add items
            </Button>
          </div>
        </div>

        {/* menu picker */}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm min-w-[12rem]"
          >
            {menus.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name} · {m.item_count} items
                {m.unpriced_count ? ` · ${m.unpriced_count} unpriced` : ''}
              </option>
            ))}
          </select>
          {data?.price_list && (
            <span className="text-xs text-gray-500">
              Price list: <span className="font-medium">{data.price_list}</span>
            </span>
          )}
        </div>
      </div>

      {/* toolbar */}
      <div className="px-4 sm:px-5 py-3 border-b border-gray-200 bg-gray-50 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[10rem]">
          <Search className="w-4 h-4 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search item, name or course"
            className="w-full border border-gray-300 rounded-lg pl-8 pr-3 py-2 text-sm"
          />
        </div>
        <div className="flex rounded-lg border border-gray-300 overflow-hidden shrink-0">
          {(
            [
              ['all', `All (${data?.items.length ?? 0})`],
              ['unpriced', `No price (${unpricedCount})`],
              ['priced', 'Priced'],
            ] as [PriceFilter, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              className={`px-3 py-2 text-xs font-medium ${
                filter === key
                  ? 'bg-blue-600 text-white'
                  : 'bg-white text-gray-700 hover:bg-gray-50'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* pending-changes bar */}
      {pendingCount > 0 && (
        <div className="px-4 sm:px-5 py-2.5 bg-amber-50 border-b border-amber-200 flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm text-amber-900">
            {pendingCount} unsaved price{pendingCount === 1 ? '' : 's'}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={() => setEdits({})}
              disabled={saving}
              className="border-amber-300 text-amber-800"
            >
              Discard
            </Button>
            <Button
              onClick={handleSave}
              disabled={saving}
              className="bg-amber-600 hover:bg-amber-700 text-white"
            >
              {saving ? (
                <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
              ) : (
                <Check className="w-4 h-4 mr-1.5" />
              )}
              Save prices
            </Button>
          </div>
        </div>
      )}

      {/* body */}
      <div className="p-4 sm:p-5">
        {error && (
          <div className="flex gap-2 rounded-lg border border-red-200 bg-red-50 p-3 mb-3">
            <AlertTriangle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
            <p className="text-sm text-red-800">{error}</p>
          </div>
        )}
        {loading && (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-500">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading menu…
          </div>
        )}
        {!loading && !error && rows.length === 0 && (
          <p className="py-10 text-center text-sm text-gray-500">
            {filter === 'unpriced'
              ? 'Every item on this menu has a price.'
              : 'Nothing matches.'}
          </p>
        )}
        {!loading && rows.length > 0 && (
          <div className="overflow-x-auto -mx-2 sm:mx-0">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-white">
                <tr className="text-left text-xs uppercase tracking-wide text-gray-500 border-b border-gray-200">
                  <th className="py-2 px-2 sm:px-3 font-medium">Item</th>
                  <th className="py-2 px-3 font-medium hidden sm:table-cell">Course</th>
                  <th className="py-2 px-2 sm:px-3 font-medium w-24 sm:w-32">Price</th>
                  <th className="py-2 px-1 sm:px-3 font-medium w-9"></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <PriceRow
                    key={r.row}
                    row={r}
                    value={edits[r.item]}
                    onChange={(v) =>
                      setEdits((cur) => {
                        const next = { ...cur };
                        if (v === '' || Number(v) === r.rate) delete next[r.item];
                        else next[r.item] = v;
                        return next;
                      })
                    }
                    onRemove={() => handleRemove(r.item, r.item_name || r.item)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showAdd && selected && (
        <AddItemsDialog
          menu={selected}
          courses={data?.courses ?? []}
          onClose={() => setShowAdd(false)}
          onAdded={() => {
            setShowAdd(false);
            loadItems(selected);
            loadMenus();
          }}
        />
      )}
    </section>
  );
};

const PriceRow = ({
  row,
  value,
  onChange,
  onRemove,
}: {
  row: MenuItemRow;
  value: string | undefined;
  onChange: (v: string) => void;
  onRemove: () => void;
}) => {
  const dirty = value !== undefined;
  // Clearing a price is futile while the Item carries a standard rate:
  // URY Menu.validate() writes it straight back on save.
  const clearBlocked = dirty && Number(value) === 0 && row.standard_rate > 0;

  return (
    <tr className="border-b border-gray-100 last:border-0 hover:bg-gray-50">
      <td className="py-2 px-2 sm:px-3">
        <div className="font-medium text-gray-900 break-words">{row.item_name || row.item}</div>
        <div className="text-xs text-gray-500">
          {row.item}
          {row.course ? <span className="sm:hidden"> · {row.course}</span> : null}
        </div>
        {clearBlocked && (
          <div className="text-xs text-amber-700 mt-0.5">
            Won't clear — item has a standard rate of{' '}
            {formatCurrency(row.standard_rate)}
          </div>
        )}
      </td>
      <td className="py-2 px-3 hidden sm:table-cell text-gray-600">
        {row.course || <span className="text-gray-400">—</span>}
      </td>
      <td className="py-2 px-2 sm:px-3">
        <input
          type="number"
          inputMode="decimal"
          min={0}
          step="0.01"
          value={value ?? (row.rate || '')}
          placeholder="0.00"
          onChange={(e) => onChange(e.target.value)}
          className={`w-full border rounded-lg px-2 py-1.5 text-sm text-right ${
            dirty
              ? 'border-amber-400 bg-amber-50'
              : row.rate
              ? 'border-gray-300'
              : 'border-red-300 bg-red-50'
          }`}
        />
      </td>
      <td className="py-2 px-1 sm:px-3 text-right">
        <button
          onClick={onRemove}
          title="Remove from this menu"
          className="text-gray-400 hover:text-red-600 p-1"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </td>
    </tr>
  );
};

const AddItemsDialog = ({
  menu,
  courses,
  onClose,
  onAdded,
}: {
  menu: string;
  courses: string[];
  onClose: () => void;
  onAdded: () => void;
}) => {
  const [query, setQuery] = useState('');
  const [group, setGroup] = useState('');
  const [groups, setGroups] = useState<string[]>([]);
  const [results, setResults] = useState<CandidateItem[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [course, setCourse] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getItemGroupsForMenu().then(setGroups).catch(() => setGroups([]));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const t = window.setTimeout(() => {
      searchItemsForMenu(menu, query, group || null)
        .then((r) => !cancelled && setResults(r))
        .catch(() => !cancelled && setResults([]))
        .finally(() => !cancelled && setLoading(false));
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [menu, query, group]);

  const submit = async () => {
    if (!picked.size) return;
    setBusy(true);
    try {
      const res = await addMenuItems(menu, [...picked], course || null);
      showToast.success(
        `Added ${res.added} item${res.added === 1 ? '' : 's'}` +
          (res.skipped ? ` · ${res.skipped} skipped` : '')
      );
      onAdded();
    } catch (err) {
      const p = extractFrappeServerError(err, 'Could not add the items.');
      showToast.error({ title: p.title || 'Add failed', description: p.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-start sm:items-center justify-center z-50 p-4 overflow-y-auto">
      <div className="bg-white rounded-lg w-full max-w-2xl shadow-xl my-4 flex flex-col max-h-[90vh]">
        <div className="flex items-start justify-between px-5 py-4 border-b border-gray-200">
          <div>
            <h3 className="text-base font-semibold text-gray-900">Add items to {menu}</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              Only items not already on this menu are listed.
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-5 py-3 border-b border-gray-200 bg-gray-50 flex flex-wrap gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search items"
            className="flex-1 min-w-[9rem] border border-gray-300 rounded-lg px-3 py-2 text-sm"
          />
          <select
            value={group}
            onChange={(e) => setGroup(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
          >
            <option value="">All groups</option>
            {groups.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-3">
          {loading && (
            <div className="flex items-center gap-2 py-6 text-sm text-gray-500">
              <Loader2 className="w-4 h-4 animate-spin" /> Searching…
            </div>
          )}
          {!loading && results.length === 0 && (
            <p className="py-6 text-sm text-gray-500 text-center">No matching items.</p>
          )}
          {!loading &&
            results.map((it) => {
              const on = picked.has(it.name);
              return (
                <button
                  key={it.name}
                  onClick={() =>
                    setPicked((cur) => {
                      const next = new Set(cur);
                      if (next.has(it.name)) next.delete(it.name);
                      else next.add(it.name);
                      return next;
                    })
                  }
                  className={`w-full text-left flex items-center gap-3 px-3 py-2 rounded-lg border mb-1.5 ${
                    on ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:bg-gray-50'
                  }`}
                >
                  <span
                    className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                      on ? 'bg-blue-600 border-blue-600' : 'border-gray-300'
                    }`}
                  >
                    {on && <Check className="w-3 h-3 text-white" />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-gray-900 truncate">
                      {it.item_name || it.name}
                    </span>
                    <span className="block text-xs text-gray-500 truncate">
                      {it.name} · {it.item_group}
                    </span>
                  </span>
                </button>
              );
            })}
        </div>

        <div className="px-5 py-4 border-t border-gray-200 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500">Course</label>
            <select
              value={course}
              onChange={(e) => setCourse(e.target.value)}
              className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
            >
              <option value="">None</option>
              {courses.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-600">{picked.size} selected</span>
            <Button
              onClick={submit}
              disabled={!picked.size || busy}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              {busy ? (
                <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
              ) : (
                <Plus className="w-4 h-4 mr-1.5" />
              )}
              Add
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MenuPricesSection;
