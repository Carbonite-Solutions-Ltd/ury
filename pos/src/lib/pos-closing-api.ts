import { call } from './frappe-sdk';

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
}

export interface POSClosingSubmitResult {
  name: string;
  transferred: number;
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
