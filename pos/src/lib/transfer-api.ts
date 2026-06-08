import { call } from './frappe-sdk';
import type { POSInvoice } from './invoice-api';

/**
 * Invoice-transfer API client (2026-06-05).
 *
 * Captains offer unpaid drafts to another cashier at shift close; the
 * receiving cashier approves/rejects them from the Orders page "Incoming
 * Transfers" filter. Backend lives in `ury.ury_pos.api`.
 */

export interface TransferMeta {
  transfer: string;
  from_user: string;
  from_full_name: string;
  requested_at: string;
  hop_number: number;
}

export type IncomingTransferInvoice = POSInvoice & {
  transfer_meta?: TransferMeta;
};

export interface TransferResolveResult {
  transfer: string;
  invoice: string;
  status: string;
  queued_to?: string;
}

/** Pending transfers addressed to the current user (Orders list). */
export async function getIncomingTransfers(
  terminal?: string | null,
  posting_date?: string | null
): Promise<{ data: IncomingTransferInvoice[]; next: boolean }> {
  const res = await call.get<{
    message: { data: IncomingTransferInvoice[]; next: boolean };
  }>('ury.ury_pos.api.get_incoming_transfers', {
    terminal: terminal || null,
    posting_date: posting_date || null,
  });
  return res.message;
}

/** Count of pending incoming transfers (sidebar badge). Never throws. */
export async function getIncomingTransferCount(): Promise<number> {
  try {
    const res = await call.get<{ message: { count: number } }>(
      'ury.ury_pos.api.get_incoming_transfer_count'
    );
    return res.message?.count || 0;
  } catch {
    return 0;
  }
}

/** Accept an incoming transfer — re-homes the draft to the current user. */
export async function approveTransfer(
  transfer: string
): Promise<TransferResolveResult> {
  const res = await call.post<{ message: TransferResolveResult }>(
    'ury.ury_pos.api.approve_transfer',
    { transfer }
  );
  return res.message;
}

/** Reject an incoming transfer — routes the draft to a branch captain. */
export async function rejectTransfer(
  transfer: string,
  reason?: string
): Promise<TransferResolveResult> {
  const res = await call.post<{ message: TransferResolveResult }>(
    'ury.ury_pos.api.reject_transfer',
    { transfer, reason: reason || null }
  );
  return res.message;
}
