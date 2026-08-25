import { DOCTYPES } from '../data/doctypes';
import { call, db } from './frappe-sdk';

export interface Room {
  name: string;
  branch: string;
}

export interface Table {
  name: string;
  occupied: number;
  latest_invoice_time: string | null;
  is_take_away: number;
  restaurant_room: string;
  table_shape: 'Circle' | 'Square' | 'Rectangle';
  no_of_seats?: number;
  /** Set when this table has been merged into another — source tables
   *  are filtered out of the grid by the backend, but the field is
   *  still exposed for completeness. */
  merged_into?: string | null;
  /** Name of the Active URY Table Merge Log when this table is a
   *  merge master. Used to render the "Merged +N" badge. */
  merge_log_name?: string | null;
  /** Count of source tables in the active merge. */
  merge_source_count?: number;
  /** Full name of the waiter holding this table, from the active
   *  draft on it. Null when unoccupied or no waiter is assigned. */
  waiter_name?: string | null;
}

export interface TableMergeSource {
  source_table: string;
  original_room: string | null;
  original_occupied: number;
  had_active_order: number;
  original_invoice: string | null;
}

export interface TableMergePostMergeOrder {
  name: string;
  owner: string;
  customer: string;
  customer_name: string | null;
  grand_total: number;
  docstatus: number;
  status: string;
  creation: string;
}

export interface ActiveTableMergeLog {
  name: string;
  merged_at: string | null;
  merged_by: string;
  merged_by_full_name: string;
  merged_orders: number;
  order_merge_log: string | null;
  source_count: number;
  source_tables: TableMergeSource[];
  post_merge_orders: TableMergePostMergeOrder[];
  custom_allow_unmerge_after_new_orders: number;
}

export interface TableMergeResult {
  merge_log: string;
  master_table: string;
  merged_count: number;
  freed_count: number;
  order_merge_log: string | null;
  order_master: string | null;
}

export interface TableUnmergeResult {
  merge_log: string;
  master_table: string;
  unmerged_count: number;
  reassigned_orders: number;
}

export async function getRestaurantMenu(posProfile: string, room?: string | null) {
  const params: Record<string, string> = { pos_profile: posProfile };
  if (room) {
    params.room = room;
  }
  const res = await call.get('ury.ury_pos.api.getRestaurantMenu', params);
  return res.message;
}

export async function getRooms(branch: string): Promise<Room[]> {
  const rooms = await db.getDocList(DOCTYPES.URY_ROOM, {
    fields: ['name', 'branch'],
    filters: [['branch', 'like', branch]],
    limit: '*' as unknown as number,
    asDict: true,
  });
  return rooms as Room[];
}

export async function getTables(room: string): Promise<Table[]> {
  const res = await call.get('ury.ury_pos.api.getTable', { room });
  return res.message as Table[];
}

export async function getTableCount(
  room: string,
  branch?: string
): Promise<number> {
  // Frappe's newer query builder rejects raw SQL functions as strings
  // ("count(name) as count"). Use getCount via the whitelisted method
  // instead, or just fetch all names and count client-side. For a
  // table grid with typically <50 tables per room, fetching names is
  // cheaper than fighting the query builder's safety checks.
  const filters: any[] = [
    ['restaurant_room', '=', room],
    ...(branch ? [['branch', '=', branch]] : []),
  ];
  const rows = await db.getDocList(DOCTYPES.URY_TABLE, {
    fields: ['name'],
    filters: filters as any,
    limit: 0,  // no limit — fetch all
    asDict: true,
  });
  return (rows as any[]).length;
}

/**
 * Merge a list of URY Tables into one master. Every selected table
 * must currently have an active draft order — empty tables can't
 * participate (the backend rejects with "Empty Tables Selected").
 *
 * `master` optionally picks which table becomes the master; defaults
 * to the first entry. `notes` is an audit note.
 *
 * `freedSources` is a list of source table names whose customers have
 * physically vacated that table as part of the merge (e.g. two groups
 * combined onto one table). Those sources stay AVAILABLE in the grid
 * so the next customer can be seated there — their orders are still
 * combined onto the master. Sources NOT in the list stay hidden
 * behind the master via `merged_into` (i.e. the customers are still
 * sitting there and the cashier rings through the combined order on
 * the master).
 *
 * Same-branch only. Cross-room is allowed. Nested merges (merging a
 * master into another master) are supported — the backend resolves
 * the top-level master automatically.
 *
 * See CLAUDE.md "Fixes log" 2026-04-11.
 */
export async function mergeTables(
  tableNames: string[],
  master?: string,
  notes?: string,
  freedSources?: string[]
): Promise<TableMergeResult> {
  const res = await call.post<{ message: TableMergeResult }>(
    'ury.ury_pos.api.merge_tables',
    {
      tables: tableNames,
      // merge_orders is always forced ON now — empty-table merges are
      // blocked upstream, so every merge always has orders to merge.
      merge_orders: 1,
      master: master || null,
      notes: notes || null,
      freed_sources: freedSources || [],
    }
  );
  return res.message;
}

/**
 * Reverse a table merge. When the master has orders created AFTER
 * the merge AND the POS Profile's
 * `custom_allow_unmerge_after_new_orders` is on, pass
 * `orderAssignments` mapping each post-merge invoice to the table it
 * should live on after the unmerge (either the master or one of the
 * source tables).
 */
export async function unmergeTables(
  mergeLogName: string,
  orderAssignments?: Record<string, string>
): Promise<TableUnmergeResult> {
  const res = await call.post<{ message: TableUnmergeResult }>(
    'ury.ury_pos.api.unmerge_tables',
    {
      merge_log: mergeLogName,
      order_assignments: orderAssignments || null,
    }
  );
  return res.message;
}

/**
 * Look up the Active URY Table Merge Log where this table is the
 * master, plus the list of source tables and any post-merge orders
 * that would block a simple unmerge. Returns null when the table
 * isn't currently a merge master.
 */
export async function getActiveTableMergeLog(
  tableName: string | null
): Promise<ActiveTableMergeLog | null> {
  if (!tableName) return null;
  try {
    const res = await call.get<{ message: ActiveTableMergeLog | null }>(
      'ury.ury_pos.api.get_active_table_merge_log',
      { table: tableName }
    );
    return res.message || null;
  } catch (err) {
    console.error('Error fetching active table merge log:', err);
    return null;
  }
}
