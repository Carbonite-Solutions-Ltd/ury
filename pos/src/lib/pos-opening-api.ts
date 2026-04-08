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
}

export const checkPOSOpening = async (): Promise<POSOpeningResponse> => {
  try {
    const response = await call.get<POSOpeningResponse>(
      'ury.ury_pos.api.posOpening'
    );

    return response;
  } catch (error) {
    console.error('Error checking POS opening status:', error);
    throw error;
  }
};

export const validatePOSClose = async (
  posProfile: string
): Promise<POSCloseValidationResponse> => {
  try {
    const response = await call.get<POSCloseValidationResponse>(
      'ury.ury_pos.api.validate_pos_close',
      {
        pos_profile: posProfile,
      }
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
 * updateDoc (docstatus 1). All validation hooks run on both steps,
 * including the multi-cashier "main cashier must be open" check — so
 * the caller will surface the friendly sub-cashier waiting state based
 * on the error this throws if the main cashier hasn't opened yet.
 */
export const createAndSubmitPOSOpening = async (
  payload: CreatePOSOpeningPayload
): Promise<string> => {
  const created = await db.createDoc('POS Opening Entry', payload);
  await db.updateDoc('POS Opening Entry', created.name, { docstatus: 1 });
  return created.name as string;
};

/**
 * Check whether the main cashier (`mainCashierUser`) currently has
 * an open + submitted POS Opening Entry for a given POS Profile.
 * Used by the sub-cashier branch of the opening dialog to decide
 * between "Join Session" and "Waiting for main cashier".
 */
export const hasMainCashierOpened = async (
  mainCashierUser: string,
  posProfile: string
): Promise<boolean> => {
  const rows = (await db.getDocList('POS Opening Entry', {
    fields: ['name'],
    filters: [
      ['user', '=', mainCashierUser],
      ['pos_profile', '=', posProfile],
      ['status', '=', 'Open'],
      ['docstatus', '=', 1],
    ],
    limit: 1,
  })) as Array<{ name: string }>;
  return rows.length > 0;
};
