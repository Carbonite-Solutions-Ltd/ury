import { call, db } from './frappe-sdk';

/**
 * Slim shape returned by `ury.ury_pos.api.preview_pos_closing_entry`.
 * URY computes totals itself (not via ERPNext's
 * `make_closing_entry_from_opening`) so backdated invoices still count
 * and the preview can expose a paid/draft split for the
 * transfer-before-close flow. See CLAUDE.md "Fixes log" 2026-04-10.
 */
export interface POSClosingPaymentRow {
  mode_of_payment: string;
  /** Opening float per payment mode (carried over from the opening entry). */
  opening_amount: number;
  /** What the backend computed should be in the drawer from paid POS Invoices. */
  expected_amount: number;
  /** What the cashier counted. Defaults to expected_amount on first render. */
  closing_amount: number;
}

export interface POSClosingDraftInvoice {
  name: string;
  customer: string | null;
  customer_name: string | null;
  grand_total: number;
  restaurant_table: string | null;
  invoice_printed: number;
}

export interface POSClosingTransferCandidate {
  user: string;
  full_name: string;
}

export interface POSClosingPreview {
  opening_entry: string;
  period_start_date: string;
  period_end_date: string;
  pos_profile: string;
  user: string;
  company: string;
  /** Totals below are PAID-SIDE ONLY — draft invoices are not counted. */
  grand_total: number;
  net_total: number;
  total_quantity: number;
  total_taxes_and_charges: number;
  /** Paid invoice count (what the closing entry will actually record). */
  invoice_count: number;
  payments: POSClosingPaymentRow[];
  /** Draft (unpaid) invoices that are blocking the close. */
  draft_count: number;
  draft_grand_total: number;
  draft_invoices: POSClosingDraftInvoice[];
  /** Other cashiers on this branch who can inherit the unpaid drafts. */
  transfer_candidates: POSClosingTransferCandidate[];
  /** 1 when the current user is a captain (can transfer drafts). */
  is_captain?: number;
  /** 1 when transfers are possible (captain AND max_invoice_transfers > 0). */
  can_transfer?: number;
  /** Per-invoice transfer hop cap from the POS Profile. */
  max_invoice_transfers?: number;
}

export interface POSClosingSubmitResult {
  name: string;
  /** Number of Pending transfer requests created at close. */
  transfers_created: number;
  transfer_to: string | null;
}

export const previewClosingEntry = async (
  openingEntry: string
): Promise<POSClosingPreview> => {
  const res = await call.get<{ message: POSClosingPreview }>(
    'ury.ury_pos.api.preview_pos_closing_entry',
    { opening_entry: openingEntry }
  );
  return res.message;
};

/**
 * Create + submit the POS Closing Entry. `closingAmounts` is a map of
 * mode_of_payment → cash counted by the cashier.
 *
 * `transferTo` is REQUIRED when the shift has any draft (unpaid)
 * invoices — the backend rejects the close otherwise. Pass the target
 * cashier's user id (e.g. "alice@example.com"). When there are no
 * drafts, leave it undefined.
 */
export const submitClosingEntry = async (
  openingEntry: string,
  closingAmounts: Record<string, number>,
  transferTo?: string
): Promise<POSClosingSubmitResult> => {
  const res = await call.post<{ message: POSClosingSubmitResult }>(
    'ury.ury_pos.api.submit_pos_closing_entry',
    {
      opening_entry: openingEntry,
      closing_amounts: closingAmounts,
      transfer_to: transferTo || null,
    }
  );
  return res.message;
};


/* ------------------------------------------------------------------ *
 * Surviving a gateway timeout on the close.
 *
 * URY runs invoice consolidation INLINE on purpose (see CLAUDE.md
 * 2026-06-11): an enqueued close returned success while silently
 * marking the entry Failed, so cashiers were told the day was closed
 * when it wasn't. The cost of that choice is wall-clock — a busy shift
 * can take longer to consolidate than the edge will hold the request
 * open.
 *
 * On landing.erpxpand.com the first ceiling is CLOUDFLARE at 100s, not
 * gunicorn at 120s. When Cloudflare gives up it returns a 504 to the
 * BROWSER and drops its connection — but gunicorn does not abort a
 * request because the client went away. The close keeps running and, if
 * it finishes inside gunicorn's own timeout, COMMITS NORMALLY.
 *
 * So a 504 here is not "the close failed". It is "we stopped
 * listening". Treating it as failure is what makes a cashier retry a
 * close that already succeeded. These helpers let the dialog go and ask
 * the database what actually happened instead of guessing.
 * ------------------------------------------------------------------ */

// The predicate lives in its own dependency-free module so it can be
// unit-tested without a DOM or the SDK (see close-timeout-rule.test.mjs).
// Re-exported here so callers have one import for the whole close flow.
export { closeMayStillBeRunning } from './close-timeout-rule';

export interface ShiftCloseOutcome {
  /** The shift really is closed — safe to report success. */
  closed: boolean;
  /** Name of the submitted POS Closing Entry, when we could read it. */
  closingEntryName: string | null;
}

interface OpeningEntryStatusRow {
  name: string;
  status: string;
}

/** Current `status` of a POS Opening Entry, or null if unreadable. */
async function readOpeningEntryStatus(
  openingEntry: string
): Promise<string | null> {
  const rows = await db.getDocList<OpeningEntryStatusRow>('POS Opening Entry', {
    fields: ['name', 'status'],
    filters: [['name', '=', openingEntry]],
    limit: 1,
    asDict: true,
  });
  return rows[0]?.status ?? null;
}

interface ClosingEntryRow {
  name: string;
  docstatus: number;
}

/** Name of the submitted closing entry for this shift, if one exists. */
async function readSubmittedClosingEntry(
  openingEntry: string
): Promise<string | null> {
  const rows = await db.getDocList<ClosingEntryRow>('POS Closing Entry', {
    fields: ['name', 'docstatus'],
    filters: [
      ['pos_opening_entry', '=', openingEntry],
      ['docstatus', '=', 1],
    ],
    orderBy: { field: 'creation', order: 'desc' },
    limit: 1,
    asDict: true,
  });
  return rows[0]?.name ?? null;
}

/**
 * Poll until the shift is actually closed, or the window runs out.
 *
 * The POS Opening Entry's own `status` is the authoritative signal —
 * it is what decides whether the cashier can start a new shift, and it
 * only flips once the whole close transaction has COMMITTED. A close
 * that is still mid-flight is invisible here (uncommitted), and one
 * that rolled back never flips it at all, so neither can be mistaken
 * for success.
 *
 * A failed probe is never treated as a verdict — the same flaky link
 * that killed the submit can kill a poll. We just keep asking.
 */
export async function waitForShiftClosed(
  openingEntry: string,
  opts: {
    timeoutMs?: number;
    intervalMs?: number;
    onProgress?: (elapsedMs: number) => void;
  } = {}
): Promise<ShiftCloseOutcome> {
  const timeoutMs = opts.timeoutMs ?? 240_000;
  const intervalMs = opts.intervalMs ?? 5_000;
  const startedAt = Date.now();

  for (;;) {
    try {
      const status = await readOpeningEntryStatus(openingEntry);
      if (status === 'Closed') {
        let closingEntryName: string | null = null;
        try {
          closingEntryName = await readSubmittedClosingEntry(openingEntry);
        } catch {
          // The shift is closed either way — the name is cosmetic.
        }
        return { closed: true, closingEntryName };
      }
    } catch {
      // Probe failed; not a verdict. Keep polling.
    }

    const elapsed = Date.now() - startedAt;
    opts.onProgress?.(elapsed);
    if (elapsed >= timeoutMs) return { closed: false, closingEntryName: null };
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}
