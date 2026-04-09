import { call } from './frappe-sdk';

/**
 * Slim shape returned by `ury.ury_pos.api.preview_pos_closing_entry`.
 * Pre-built from ERPNext's `make_closing_entry_from_opening` so the
 * dialog can render the close form without recomputing expected
 * totals client-side.
 *
 * See CLAUDE.md "Fixes log" 2026-04-09.
 */
export interface POSClosingPaymentRow {
  mode_of_payment: string;
  /** Opening float per payment mode (carried over from the opening entry). */
  opening_amount: number;
  /** What ERPNext calculated should be in the drawer based on POS Invoices. */
  expected_amount: number;
  /** What the cashier counted. Defaults to expected_amount on first render. */
  closing_amount: number;
}

export interface POSClosingPreview {
  opening_entry: string;
  period_start_date: string;
  period_end_date: string;
  pos_profile: string;
  user: string;
  company: string;
  grand_total: number;
  net_total: number;
  total_quantity: number;
  total_taxes_and_charges: number;
  payments: POSClosingPaymentRow[];
  invoice_count: number;
}

/**
 * Build a preview of the POS Closing Entry for a given opening entry
 * without saving anything. Used to populate the in-POS closing dialog.
 */
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
 * mode_of_payment → cash counted by the cashier. Modes missing from
 * the map default to their expected amount on the backend.
 */
export const submitClosingEntry = async (
  openingEntry: string,
  closingAmounts: Record<string, number>
): Promise<{ name: string }> => {
  const res = await call.post<{ message: { name: string } }>(
    'ury.ury_pos.api.submit_pos_closing_entry',
    {
      opening_entry: openingEntry,
      closing_amounts: closingAmounts,
    }
  );
  return res.message;
};
