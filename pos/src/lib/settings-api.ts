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
