import { call } from './frappe-sdk';

/** One item group on the branch's menus, and where its KOTs would route. */
export interface KotCoverageGroup {
  item_group: string;
  item_count: number;
  /** 0 when no production unit claims this group. */
  covered: 0 | 1;
  /** Production unit(s) this group routes to. Empty when uncovered. */
  productions: string[];
  /** A few item names so the admin can recognise the group. */
  sample_items: string[];
}

export interface KotCoverageProduction {
  production: string;
  item_groups: string[];
}

export interface KotCoverageAudit {
  branch: string;
  pos_profile: string | null;
  restaurant: string | null;
  kds_routing_mode: string;
  /**
   * 1 in URY Production Unit mode, where an unmatched item gets NO KOT at
   * all. 0 in Menu Course mode, where unmatched items land in a fallback
   * KOT — a gap there is harmless.
   */
  drops_unmatched_items: 0 | 1;
  menus_checked: string[];
  productions: KotCoverageProduction[];
  item_groups: KotCoverageGroup[];
  uncovered_count: number;
  uncovered_item_total: number;
  total_item_groups: number;
  total_items: number;
}

/**
 * Audit which menu item groups will never produce a KOT.
 *
 * Catches the silent failure this was built for: in Production Unit mode
 * an item group attached to no production unit bills fine and never
 * reaches any kitchen or bar screen, with no error anywhere.
 */
export async function getKotCoverageAudit(
  terminal?: string | null
): Promise<KotCoverageAudit> {
  const res = await call.get<{ message: KotCoverageAudit }>(
    'ury.ury_pos.api.get_kot_coverage_audit',
    terminal ? { terminal } : {}
  );
  return res.message;
}

// ── Settings › Menu & Prices (2026-08-06) ──────────────────────────
//
// All admin/manager-only; the backend re-checks on every call.
//
// The write helpers are deliberately BULK. `URY Menu.on_update` rebuilds
// the entire price list on every save — deleting and re-inserting one
// Item Price per row — so saving per edited row would rebuild a 400-line
// price list once per keystroke. Collect edits, commit once.

export interface MenuSummary {
  name: string;
  branch: string | null;
  enabled: number;
  price_list: string | null;
  item_count: number;
  unpriced_count: number;
}

export interface MenuItemRow {
  row: string;
  item: string;
  item_name: string;
  course: string | null;
  rate: number;
  disabled: number;
  special_dish: number;
  /** What URY Menu.validate() will write into a blank rate. */
  standard_rate: number;
}

export interface MenuItemsResponse {
  menu: string;
  branch: string | null;
  price_list: string | null;
  items: MenuItemRow[];
  courses: string[];
}

export interface CandidateItem {
  name: string;
  item_name: string;
  item_group: string;
  standard_rate: number;
}

export async function getMenusForSettings(): Promise<MenuSummary[]> {
  const r = await call.get<{ message: MenuSummary[] }>(
    'ury.ury_pos.api.get_menus_for_settings'
  );
  return r.message || [];
}

export async function getMenuItemsForSettings(
  menu: string
): Promise<MenuItemsResponse> {
  const r = await call.get<{ message: MenuItemsResponse }>(
    'ury.ury_pos.api.get_menu_items_for_settings',
    { menu }
  );
  return r.message;
}

export async function saveMenuItemRates(
  menu: string,
  updates: Record<string, number>
): Promise<{
  updated: number;
  blocked_by_standard_rate: { item: string; standard_rate: number }[];
}> {
  const r = await call.post<{
    message: {
      updated: number;
      blocked_by_standard_rate: { item: string; standard_rate: number }[];
    };
  }>('ury.ury_pos.api.save_menu_item_rates', {
    menu,
    updates: JSON.stringify(updates),
  });
  return r.message;
}

export async function removeMenuItems(
  menu: string,
  items: string[]
): Promise<{ removed: number; remaining?: number }> {
  const r = await call.post<{ message: { removed: number; remaining?: number } }>(
    'ury.ury_pos.api.remove_menu_items',
    { menu, items: JSON.stringify(items) }
  );
  return r.message;
}

export async function addMenuItems(
  menu: string,
  items: string[],
  course?: string | null
): Promise<{ added: number; skipped: number; total: number }> {
  const r = await call.post<{
    message: { added: number; skipped: number; total: number };
  }>('ury.ury_pos.api.add_menu_items', {
    menu,
    items: JSON.stringify(items),
    ...(course ? { course } : {}),
  });
  return r.message;
}

export async function searchItemsForMenu(
  menu: string,
  query?: string,
  itemGroup?: string | null
): Promise<CandidateItem[]> {
  const r = await call.get<{ message: CandidateItem[] }>(
    'ury.ury_pos.api.search_items_for_menu',
    { menu, ...(query ? { query } : {}), ...(itemGroup ? { item_group: itemGroup } : {}) }
  );
  return r.message || [];
}

export async function getItemGroupsForMenu(): Promise<string[]> {
  const r = await call.get<{ message: string[] }>(
    'ury.ury_pos.api.get_item_groups_for_menu'
  );
  return r.message || [];
}
