import { call, db } from './frappe-sdk';

export interface POSOpeningResponse {
  message: number;
}

/**
 * validate_pos_close now returns either "Success" or an object describing
 * the unclosed entry so the dialog can deep-link to its form.
 * Older clients that read `.message === "Failed"` still work because the
 * backend returns `status: "Failed"` inside the message object.
 */
export interface POSCloseValidationResponse {
  message:
    | string
    | {
        status: 'Success' | 'Failed';
        unclosed_entry?: string;
      };
}

export interface OpeningBalanceRow {
  mode_of_payment: string;
  opening_amount: number;
}

export interface CreatePOSOpeningPayload {
  period_start_date: string; // "YYYY-MM-DD HH:mm:ss"
  posting_date: string; // "YYYY-MM-DD"
  company: string;
  pos_profile: string;
  branch: string;
  user: string;
  balance_details: OpeningBalanceRow[];
  /**
   * URY POS Terminal name. Stamped on the entry so subsequent
   * `posOpening` checks scope to this physical till. Required when
   * the device has a registered terminal (always true in the React POS).
   */
  custom_terminal?: string;
}

export const checkPOSOpening = async (
  terminal?: string | null
): Promise<POSOpeningResponse> => {
  try {
    const params: Record<string, string> = {};
    if (terminal) params.terminal = terminal;
    const response = await call.get<POSOpeningResponse>(
      'ury.ury_pos.api.posOpening',
      params
    );

    return response;
  } catch (error) {
    console.error('Error checking POS opening status:', error);
    throw error;
  }
};

export const validatePOSClose = async (
  posProfile: string,
  terminal?: string | null
): Promise<POSCloseValidationResponse> => {
  try {
    const params: Record<string, string> = { pos_profile: posProfile };
    if (terminal) params.terminal = terminal;
    const response = await call.get<POSCloseValidationResponse>(
      'ury.ury_pos.api.validate_pos_close',
      params
    );

    return response;
  } catch (error) {
    console.error('Error validating POS close status:', error);
    throw error;
  }
};

/**
 * Fetch the Mode of Payment list from the POS Profile so the dialog can
 * seed one opening-balance row per payment mode with amount = 0.
 * Wraps the existing `ury.ury_pos.api.getModeOfPayment` whitelisted method.
 */
export const getOpeningBalanceDetails = async (): Promise<OpeningBalanceRow[]> => {
  const response = await call.get<{ message: OpeningBalanceRow[] }>(
    'ury.ury_pos.api.getModeOfPayment'
  );
  return response.message || [];
};

/**
 * Create and submit a POS Opening Entry in one round-trip.
 * Mirrors the legacy Vue POS pattern: createDoc (docstatus 0) then
 * updateDoc (docstatus 1). The backend `validate_terminal_branch` hook
 * verifies that `custom_terminal`'s branch matches the entry's branch
 * before insert, so a malformed payload will throw cleanly.
 *
 * The captain-must-be-open gate (`main_pos_open_check`) was removed
 * on 2026-04-08 — opening entries are now per-terminal (and per-user
 * in multi_cashier strict mode), so cross-user ordering checks are
 * gone. See CLAUDE.md "Fixes log".
 */
export const createAndSubmitPOSOpening = async (
  payload: CreatePOSOpeningPayload
): Promise<string> => {
  const created = await db.createDoc('POS Opening Entry', payload);
  await db.updateDoc('POS Opening Entry', created.name, { docstatus: 1 });
  return created.name as string;
};

/**
 * Lightweight metadata about the currently-open POS Opening Entry that
 * `posOpening()` would consider "this user's session" — including a
 * fallback to the same-profile entry that ERPNext's standard
 * check_open_pos_exists would block on (used by the dialog's
 * "Existing Open Entry" branch to deep-link to whatever's blocking).
 *
 * Returns null when there's no matching entry. Used by:
 *   - The Existing-Entry branch of POSOpeningDialog (Fix A).
 *   - The ShiftHoursBanner (Fix B) to compute shift age.
 *
 * See CLAUDE.md "Fixes log" 2026-04-09.
 */
export interface CurrentPOSOpenEntry {
  name: string;
  period_start_date: string;
  posting_date: string;
  pos_profile: string;
  user: string;
  custom_terminal?: string | null;
  /** 1 when the entry belongs to the session user. */
  is_mine?: 0 | 1;
  /** Full name of whoever opened it (falls back to the user id). */
  opened_by?: string | null;
  /** 1 when it was opened on the terminal we asked about. */
  same_terminal?: 0 | 1;
}

export const getCurrentPosOpenEntry = async (
  terminal?: string | null
): Promise<CurrentPOSOpenEntry | null> => {
  try {
    const params: Record<string, string> = {};
    if (terminal) params.terminal = terminal;
    const res = await call.get<{ message: CurrentPOSOpenEntry | null }>(
      'ury.ury_pos.api.get_pos_open_entry',
      params
    );
    return res.message || null;
  } catch (error) {
    console.error('Error fetching current POS open entry:', error);
    return null;
  }
};

// `hasMainCashierOpened` was deleted on 2026-07-28 along with the
// "Join Session" / "Waiting for Main Cashier" dialog branches it fed.
// Do not reintroduce it. It existed to decide whether a sub-cashier
// could create their own opening entry alongside the captain's — an
// operation ERPNext's `check_open_pos_exists` has never permitted, so
// the answer it produced could only ever lead to a guaranteed error.
// Whether someone has already opened the POS is now answered by
// `checkPOSOpening()` (backend `posOpening`), which scopes by POS
// Profile and simply returns 0 — no dialog, straight into the POS.
