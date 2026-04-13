import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type MouseEvent,
} from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  Eye,
  Loader2,
  Merge,
  Printer,
  Square,
  Undo2,
  Users,
  X,
} from 'lucide-react';
import { cn, extractFrappeServerError } from '../lib/utils';
import { usePOSStore } from '../store/pos-store';
import {
  getRooms,
  getTables,
  getTableCount,
  mergeTables,
  unmergeTables,
  getActiveTableMergeLog,
  type ActiveTableMergeLog,
  type Room,
  type Table,
} from '../lib/table-api';
import { Spinner } from '../components/ui/spinner';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { DINE_IN } from '../data/order-types';
import { TableShapeIcon } from '../components/TableShapeIcon';
import { getTableOrder } from '../lib/order-api';
import { printOrder } from '../lib/print';
import { showToast } from '../components/ui/toast';
import TableMergeDialog from '../components/TableMergeDialog';
import TableUnmergeDialog from '../components/TableUnmergeDialog';
import { useRootStore, type RootState } from '../store/root-store';
import { canMergeOrders } from '../lib/role-utils';
import '../components/ui/merge-mode.css';

const sortTables = (tables: Table[]) =>
  [...tables].sort((a, b) => a.name.localeCompare(b.name));

const TableView = () => {
  const navigate = useNavigate();
  const {
    posProfile,
    setSelectedTable,
    setSelectedOrderType,
  } = usePOSStore();
  const user = useRootStore((s: RootState) => s.user);
  const canMerge = useMemo(
    () => canMergeOrders(user, posProfile),
    [user, posProfile]
  );

  const branch = posProfile?.branch ?? null;
  const [rooms, setRooms] = useState<Room[]>([]);
  const [selectedRoom, setSelectedRoom] = useState<string | null>(null);
  const [tables, setTables] = useState<Table[]>([]);
  const [tablesCache, setTablesCache] = useState<Record<string, Table[]>>({});
  const [loadingRooms, setLoadingRooms] = useState(false);
  const [loadingTables, setLoadingTables] = useState(false);
  const [roomCounts, setRoomCounts] = useState<Record<string, number>>({});
  const [loadingRoomCounts, setLoadingRoomCounts] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [printingTable, setPrintingTable] = useState<string | null>(null);

  // Merge-mode state
  const [mergeMode, setMergeMode] = useState(false);
  const [mergeSelection, setMergeSelection] = useState<string[]>([]);
  const [mergeLoading, setMergeLoading] = useState(false);
  const [showMergeDialog, setShowMergeDialog] = useState(false);

  // Unmerge-mode state
  const [activeMergeLog, setActiveMergeLog] =
    useState<ActiveTableMergeLog | null>(null);
  const [unmergeTarget, setUnmergeTarget] = useState<string | null>(null);
  const [unmergeLoading, setUnmergeLoading] = useState(false);

  const persistRoomCounts = useCallback(
    (counts: Record<string, number>) => {
      if (!branch) return;
      sessionStorage.setItem(
        `ury_room_counts_${branch}`,
        JSON.stringify(counts)
      );
    },
    [branch]
  );

  useEffect(() => {
    async function fetchRooms() {
      if (!branch) return;
      setLoadingRooms(true);
      setError(null);

      try {
        const sessionKey = `ury_rooms_${branch}`;
        const cachedRooms = sessionStorage.getItem(sessionKey);

        if (cachedRooms) {
          const parsedRooms = JSON.parse(cachedRooms) as Room[];
          setRooms(parsedRooms);
          setSelectedRoom((prev) => prev ?? parsedRooms[0]?.name ?? null);
        } else {
          const fetchedRooms = await getRooms(branch);
          setRooms(fetchedRooms);
          setSelectedRoom(
            (prev) => prev ?? fetchedRooms[0]?.name ?? null
          );
          sessionStorage.setItem(sessionKey, JSON.stringify(fetchedRooms));
        }
      } catch (e) {
        console.error(e);
        setError('Failed to load rooms');
      } finally {
        setLoadingRooms(false);
      }
    }

    fetchRooms();
  }, [branch]);

  useEffect(() => {
    if (!branch || rooms.length === 0) return;
    const cacheKey = `ury_room_counts_${branch}`;
    const cachedCounts = sessionStorage.getItem(cacheKey);
    let shouldFetch = true;

    if (cachedCounts) {
      try {
        const parsedCounts = JSON.parse(cachedCounts) as Record<string, number>;
        setRoomCounts(parsedCounts);
        const hasAllRooms = rooms.every(
          (room) => typeof parsedCounts[room.name] === 'number'
        );
        if (hasAllRooms) {
          shouldFetch = false;
        }
      } catch {
        sessionStorage.removeItem(cacheKey);
      }
    }

    if (!shouldFetch) return;

    async function fetchRoomCounts() {
      setLoadingRoomCounts(true);
      try {
        const counts = await Promise.all(
          rooms.map((room) => getTableCount(room.name, room.branch))
        );
        const nextCounts = rooms.reduce(
          (acc, room, index) => {
            acc[room.name] = counts[index];
            return acc;
          },
          {} as Record<string, number>
        );
        setRoomCounts(nextCounts);
        persistRoomCounts(nextCounts);
      } catch (error) {
        console.error('Failed to load room counts', error);
      } finally {
        setLoadingRoomCounts(false);
      }
    }

    fetchRoomCounts();
  }, [branch, rooms, persistRoomCounts]);

  const loadTables = useCallback(
    async (roomName: string, options?: { useCache?: boolean }) => {
      if (!roomName) return;
      setError(null);

      const shouldUseCache = options?.useCache !== false;
      if (shouldUseCache && tablesCache[roomName]) {
        setTables(sortTables(tablesCache[roomName]));
        setLoadingTables(false);
        return;
      }

      setLoadingTables(true);
      try {
        const fetchedTables = await getTables(roomName);
        const sortedTables = sortTables(fetchedTables);
        setTables(sortedTables);
        setTablesCache((prev) => ({ ...prev, [roomName]: sortedTables }));
      } catch (e) {
        console.error(e);
        setError('Failed to load tables');
        setTables([]);
      } finally {
        setLoadingTables(false);
      }
    },
    [tablesCache]
  );

  const refreshRoomCount = useCallback(
    async (roomName: string) => {
      const roomMeta = rooms.find((room) => room.name === roomName);
      const branchName = roomMeta?.branch ?? branch;
      if (!roomName || !branchName) return;

      try {
        const count = await getTableCount(roomName, branchName);
        setRoomCounts((prev) => {
          const next = { ...prev, [roomName]: count };
          persistRoomCounts(next);
          return next;
        });
      } catch (error) {
        console.error(`Failed to refresh count for room ${roomName}`, error);
      }
    },
    [rooms, branch, persistRoomCounts]
  );

  useEffect(() => {
    if (!selectedRoom) return;
    loadTables(selectedRoom);
  }, [selectedRoom, loadTables]);

  const handleNavigateToPOS = (tableName: string) => {
    if (!selectedRoom) return;
    setSelectedOrderType(DINE_IN);
    setSelectedTable(tableName, selectedRoom);
    navigate('/');
  };

  const handlePreviewTable = (
    table: Table,
    event?: MouseEvent<HTMLButtonElement>
  ) => {
    event?.stopPropagation();
    handleNavigateToPOS(table.name);
  };

  const handlePrintTable = async (
    table: Table,
    event: MouseEvent<HTMLButtonElement>
  ) => {
    event.stopPropagation();

    if (!posProfile) {
      showToast.error('POS profile not loaded yet');
      return;
    }

    setPrintingTable(table.name);
    try {
      const orderResponse = await getTableOrder(table.name);
      const invoiceId = orderResponse.message?.name;

      if (!invoiceId) {
        showToast.error('No active order found for this table');
        return;
      }

      await printOrder({ orderId: invoiceId, posProfile });
      showToast.success('Printed successfully');
      await loadTables(table.restaurant_room, { useCache: false });
      await refreshRoomCount(table.restaurant_room);
    } catch (error) {
      showToast.error(
        error instanceof Error ? error.message : 'Failed to print order'
      );
    } finally {
      setPrintingTable(null);
    }
  };

  const formatInvoiceTime = (timestamp: string | null) => {
    if (!timestamp) return 'No bill activity yet';

    const parsedDate = new Date(timestamp);
    if (!Number.isNaN(parsedDate.getTime())) {
      return parsedDate.toLocaleTimeString(undefined, {
        hour: 'numeric',
        minute: 'numeric',
      });
    }

    const timeOnlyMatch = timestamp.match(
      /^(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d+))?$/
    );
    if (timeOnlyMatch) {
      const [, hours, minutes, seconds] = timeOnlyMatch;
      const date = new Date();
      date.setHours(Number(hours), Number(minutes), Number(seconds), 0);
      const formatted = date.toLocaleTimeString(undefined, {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      });
      if (/^\d{1,2}:\d{2}$/.test(formatted)) {
        return formatted;
      }
      return `${hours.padStart(2, '0')}:${minutes.padStart(2, '0')}`;
    }

    return timestamp;
  };

  // ---------- Merge mode ----------

  const enterMergeMode = () => {
    setMergeMode(true);
    setMergeSelection([]);
  };

  const exitMergeMode = () => {
    setMergeMode(false);
    setMergeSelection([]);
    setShowMergeDialog(false);
  };

  const toggleMergeSelection = (tableName: string) => {
    setMergeSelection((prev) =>
      prev.includes(tableName)
        ? prev.filter((n) => n !== tableName)
        : [...prev, tableName]
    );
  };

  const selectedTablesForMerge = useMemo(() => {
    // Merge selection can span rooms — collect across ALL cached rooms
    // plus the currently loaded list so cross-room merges survive a
    // room switch. We deduplicate by name.
    const byName: Record<string, Table> = {};
    for (const t of tables) byName[t.name] = t;
    for (const cached of Object.values(tablesCache)) {
      for (const t of cached) {
        if (!byName[t.name]) byName[t.name] = t;
      }
    }
    const ordered: Table[] = [];
    for (const name of mergeSelection) {
      if (byName[name]) ordered.push(byName[name]);
    }
    return ordered;
  }, [mergeSelection, tables, tablesCache]);

  const openMergeDialog = () => {
    if (mergeSelection.length < 2) {
      showToast.error('Pick at least two tables to merge.');
      return;
    }
    setShowMergeDialog(true);
  };

  const handleConfirmMerge = async ({
    master,
    freedSources,
    notes,
  }: {
    master: string;
    freedSources: string[];
    notes: string;
  }) => {
    setMergeLoading(true);
    try {
      const res = await mergeTables(
        mergeSelection,
        master,
        notes || undefined,
        freedSources
      );
      const freedMsg =
        res.freed_count > 0
          ? ` · ${res.freed_count} returned to Available`
          : '';
      showToast.success(
        `Merged ${res.merged_count + 1} tables into ${res.master_table}${freedMsg}`
      );
      setShowMergeDialog(false);
      setMergeMode(false);
      setMergeSelection([]);
      // Refresh every cached room we touched — sources may disappear,
      // masters may get a new badge.
      setTablesCache({});
      if (selectedRoom) await loadTables(selectedRoom, { useCache: false });
      if (branch) {
        for (const room of rooms) {
          refreshRoomCount(room.name);
        }
      }
    } catch (err) {
      const parsed = extractFrappeServerError(err, 'Failed to merge tables.');
      showToast.error({
        title: parsed.title || 'Merge Failed',
        description: parsed.message,
      });
    } finally {
      setMergeLoading(false);
    }
  };

  // ---------- Unmerge mode ----------

  const openUnmergeDialog = async (tableName: string) => {
    setUnmergeLoading(true);
    try {
      const log = await getActiveTableMergeLog(tableName);
      if (!log) {
        showToast.error('No active merge found on this table.');
        return;
      }
      setActiveMergeLog(log);
      setUnmergeTarget(tableName);
    } catch (err) {
      const parsed = extractFrappeServerError(
        err,
        'Failed to load merge details.'
      );
      showToast.error({
        title: parsed.title || 'Error',
        description: parsed.message,
      });
    } finally {
      setUnmergeLoading(false);
    }
  };

  const closeUnmergeDialog = () => {
    setActiveMergeLog(null);
    setUnmergeTarget(null);
  };

  const handleConfirmUnmerge = async ({
    orderAssignments,
  }: {
    orderAssignments: Record<string, string> | null;
  }) => {
    if (!activeMergeLog) return;
    setUnmergeLoading(true);
    try {
      await unmergeTables(
        activeMergeLog.name,
        orderAssignments || undefined
      );
      showToast.success('Tables unmerged successfully');
      closeUnmergeDialog();
      setTablesCache({});
      if (selectedRoom) await loadTables(selectedRoom, { useCache: false });
      if (branch) {
        for (const room of rooms) {
          refreshRoomCount(room.name);
        }
      }
    } catch (err) {
      const parsed = extractFrappeServerError(
        err,
        'Failed to unmerge tables.'
      );
      showToast.error({
        title: parsed.title || 'Unmerge Failed',
        description: parsed.message,
      });
    } finally {
      setUnmergeLoading(false);
    }
  };

  // ---------- Render ----------

  const tablesToDisplay = useMemo(() => sortTables(tables), [tables]);

  const hasRooms = rooms.length > 0;
  const showGridSkeleton = loadingTables || !selectedRoom;

  const handleRoomChange = (roomName: string) => {
    if (roomName === selectedRoom) {
      loadTables(roomName, { useCache: false });
      return;
    }

    setSelectedRoom(roomName);

    if (tablesCache[roomName]) {
      setTables(sortTables(tablesCache[roomName]));
      setLoadingTables(false);
    } else {
      setLoadingTables(true);
      setTables([]);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 bg-white border-b border-gray-200">
        <div className="max-w-screen-xl mx-auto">
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              {loadingRooms && (
                <div className="flex-1 min-w-[160px]">
                  <Spinner message="Loading rooms..." />
                </div>
              )}

              {!loadingRooms && !hasRooms && (
                <div className="flex items-center gap-2 text-gray-500 text-sm">
                  <AlertTriangle className="w-4 h-4" />
                  No rooms found for this branch
                </div>
              )}

              {rooms.map((room) => (
                <Button
                  key={room.name}
                  variant="tab"
                  data-selected={selectedRoom === room.name}
                  onClick={() => handleRoomChange(room.name)}
                  className="h-fit"
                >
                  {room.name}
                  {typeof roomCounts[room.name] === 'number' ? (
                    <Badge variant="outline" className="ml-2 bg-white/60">
                      {roomCounts[room.name]}
                    </Badge>
                  ) : loadingRoomCounts ? (
                    <Badge variant="outline" className="ml-2 bg-white/60">
                      --
                    </Badge>
                  ) : null}
                </Button>
              ))}

              {/* Merge Tables button / Merge mode bar */}
              <div className="ml-auto flex items-center gap-2">
                {canMerge && !mergeMode && (
                  <Button
                    variant="outline"
                    className="border-amber-300 text-amber-700 hover:bg-amber-50"
                    onClick={enterMergeMode}
                  >
                    <Merge className="w-4 h-4 mr-1.5" />
                    Merge Tables
                  </Button>
                )}
                {mergeMode && (
                  <div className="flex items-center gap-2 rounded-lg bg-amber-50 border border-amber-300 px-3 py-1.5">
                    <span className="text-sm font-semibold text-amber-900">
                      {mergeSelection.length} selected
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      className="border-amber-400 text-amber-800 hover:bg-amber-100"
                      onClick={exitMergeMode}
                    >
                      <X className="w-3.5 h-3.5 mr-1" />
                      Cancel
                    </Button>
                    <Button
                      size="sm"
                      className="bg-amber-600 hover:bg-amber-700 text-white"
                      onClick={openMergeDialog}
                      disabled={mergeSelection.length < 2 || mergeLoading}
                    >
                      <Merge className="w-3.5 h-3.5 mr-1" />
                      Merge
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-auto bg-gray-50 p-6">
        <div className="max-w-screen-xl mx-auto h-full">
          {error && !loadingTables ? (
            <div className="h-full flex flex-col items-center justify-center gap-3 text-red-500">
              <AlertTriangle className="w-10 h-10" />
              <p>{error}</p>
            </div>
          ) : showGridSkeleton ? (
            <Spinner message="Loading tables..." />
          ) : tablesToDisplay.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center gap-3 text-gray-500">
              <Square className="w-10 h-10" />
              <p>No tables found for this room</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
              {tablesToDisplay.map((table, idx) => {
                const isOccupied = table.occupied === 1;
                const isMerged =
                  !!table.merge_log_name &&
                  (table.merge_source_count ?? 0) > 0;
                const isSelectedForMerge = mergeSelection.includes(
                  table.name
                );
                // In merge mode, only occupied tables are selectable.
                // Available tables have no order to merge, so the
                // backend would reject them — we block the click up
                // front and dim the card.
                const mergeableInMergeMode = mergeMode && isOccupied;

                return (
                  <div
                    key={table.name}
                    role={
                      mergeMode
                        ? mergeableInMergeMode
                          ? 'button'
                          : 'group'
                        : !isOccupied
                        ? 'button'
                        : 'group'
                    }
                    tabIndex={
                      (mergeMode ? mergeableInMergeMode : !isOccupied)
                        ? 0
                        : -1
                    }
                    onClick={() => {
                      if (mergeMode) {
                        if (!mergeableInMergeMode) {
                          showToast.error(
                            'Only tables with active orders can be merged.'
                          );
                          return;
                        }
                        toggleMergeSelection(table.name);
                        return;
                      }
                      // Both available AND occupied tables navigate to
                      // the POS — available starts a new order, occupied
                      // opens the existing one so the cashier can add
                      // more items.
                      handleNavigateToPOS(table.name);
                    }}
                    className={cn(
                      'relative bg-white rounded-lg border-2 p-4 transition-all flex flex-col justify-between gap-y-4',
                      mergeMode &&
                        mergeableInMergeMode &&
                        `ury-wobble ury-wobble-d${idx % 6} cursor-pointer`,
                      mergeMode && !mergeableInMergeMode && 'opacity-40 cursor-not-allowed',
                      mergeMode && isSelectedForMerge
                        ? 'ring-2 ring-amber-500 ring-offset-2 border-amber-500 bg-amber-50'
                        : isOccupied
                        ? 'border-amber-400 bg-amber-50 text-amber-900 hover:border-amber-500 hover:shadow-md cursor-pointer'
                        : 'border-emerald-300 bg-emerald-50 text-emerald-900 hover:border-emerald-400 hover:shadow-md cursor-pointer'
                    )}
                  >
                    {/* Merge selection checkmark */}
                    {mergeMode && isSelectedForMerge && (
                      <div className="absolute top-2 right-2 z-10 flex items-center justify-center w-6 h-6 rounded-full bg-amber-600 text-white shadow">
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          className="w-4 h-4"
                          viewBox="0 0 20 20"
                          fill="currentColor"
                        >
                          <path
                            fillRule="evenodd"
                            d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                            clipRule="evenodd"
                          />
                        </svg>
                      </div>
                    )}
                    <div>
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <TableShapeIcon
                            shape={table.table_shape || 'Rectangle'}
                          />
                          <span className="font-semibold text-lg text-gray-900">
                            {table.name}
                          </span>
                        </div>
                        <div className="flex items-center gap-1">
                          {isMerged && (
                            <Badge
                              variant="default"
                              className="bg-amber-500 hover:bg-amber-600 text-white flex items-center gap-1 px-2 py-0.5"
                              title={`Merged from ${table.merge_source_count} table${table.merge_source_count === 1 ? '' : 's'}`}
                            >
                              <Merge className="w-3 h-3" />
                              <span className="text-xs">
                                +{table.merge_source_count}
                              </span>
                            </Badge>
                          )}
                          <Badge variant={isOccupied ? 'warning' : 'success'}>
                            {isOccupied ? 'Occupied' : 'Available'}
                          </Badge>
                        </div>
                      </div>

                      <div className="space-y-2 text-sm text-gray-700">
                        <div className="flex items-center justify-between">
                          <span className="font-medium">Room</span>
                          <span>{table.restaurant_room}</span>
                        </div>
                        {isOccupied && (
                          <div className="flex items-center justify-between">
                            <span className="font-medium">Started at</span>
                            <span>
                              {formatInvoiceTime(table.latest_invoice_time)}
                            </span>
                          </div>
                        )}
                        {typeof table.no_of_seats === 'number' && (
                          <div className="flex items-center justify-between">
                            <span className="font-medium">Seats</span>
                            <span className="flex items-center gap-1">
                              <Users className="w-3 h-3" />
                              {table.no_of_seats}
                            </span>
                          </div>
                        )}
                        {table.is_take_away === 1 && (
                          <Badge variant="pending" className="mt-2">
                            Take away
                          </Badge>
                        )}
                      </div>
                    </div>

                    {!mergeMode && isOccupied ? (
                      <div className="flex gap-2 pt-3 mt-3 border-t border-amber-200 flex-wrap">
                        <button
                          onClick={(event) => handlePreviewTable(table, event)}
                          className="flex-1 flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded bg-white hover:bg-amber-100 transition"
                        >
                          <Eye className="w-3 h-3" />
                          Preview
                        </button>
                        <button
                          onClick={(event) => handlePrintTable(table, event)}
                          disabled={printingTable === table.name}
                          className="flex-1 flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded bg-white hover:bg-amber-100 transition disabled:opacity-60 disabled:cursor-not-allowed"
                        >
                          {printingTable === table.name ? (
                            <>
                              <Loader2 className="w-3 h-3 animate-spin" />
                              Printing...
                            </>
                          ) : (
                            <>
                              <Printer className="w-3 h-3" />
                              Print
                            </>
                          )}
                        </button>
                        {isMerged && canMerge && (
                          <button
                            onClick={(event) => {
                              event.stopPropagation();
                              openUnmergeDialog(table.name);
                            }}
                            disabled={unmergeLoading}
                            className="w-full flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded bg-white hover:bg-amber-100 transition"
                          >
                            <Undo2 className="w-3 h-3" />
                            Unmerge
                          </button>
                        )}
                      </div>
                    ) : !mergeMode ? (
                      <>
                        {isMerged && canMerge ? (
                          <button
                            onClick={(event) => {
                              event.stopPropagation();
                              openUnmergeDialog(table.name);
                            }}
                            disabled={unmergeLoading}
                            className="w-full flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded bg-white hover:bg-amber-100 transition border border-amber-300"
                          >
                            <Undo2 className="w-3 h-3" />
                            Unmerge
                          </button>
                        ) : (
                          <p className="text-sm text-gray-500">
                            Tap to start a new dine-in order
                          </p>
                        )}
                      </>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Status Legend */}
      <div className="fixed bottom-[4.5rem] w-full p-4 bg-white border-t border-gray-200">
        <div className="max-w-screen-xl mx-auto">
          <div className="flex items-center justify-center gap-6 text-sm">
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 bg-green-100 border border-green-300 rounded"></div>
              <span>Available</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 bg-red-100 border border-red-300 rounded"></div>
              <span>Occupied</span>
            </div>
          </div>
        </div>
      </div>

      {/* Merge confirm dialog */}
      {showMergeDialog && (
        <TableMergeDialog
          selectedTables={selectedTablesForMerge}
          onCancel={() => setShowMergeDialog(false)}
          onConfirm={handleConfirmMerge}
          loading={mergeLoading}
        />
      )}

      {/* Unmerge dialog */}
      {activeMergeLog && unmergeTarget && (
        <TableUnmergeDialog
          mergeLog={activeMergeLog}
          masterTable={unmergeTarget}
          onCancel={closeUnmergeDialog}
          onConfirm={handleConfirmUnmerge}
          loading={unmergeLoading}
        />
      )}
    </div>
  );
};

export default TableView;
