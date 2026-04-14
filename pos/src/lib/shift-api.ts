/**
 * URY Shift system helpers.
 *
 * Calls the whitelisted `get_shift_status` endpoint on the URY backend
 * to read the cashier's current shift state for the supplied terminal.
 * Powers the ShiftHoursBanner and the POS Opening Entry gate when the
 * profile's `custom_shift_system_mode` is set to "URY Shift" or "HRMS
 * Shift Type". When the mode is "Disabled", the banner falls back to
 * the legacy `custom_shift_hours` math and this endpoint is unused.
 *
 * See CLAUDE.md "Fixes log" 2026-04-14 for the full design.
 */
import { call } from './frappe-sdk';

export type ShiftSystemMode = 'Disabled' | 'URY Shift' | 'HRMS Shift Type';

export type ShiftGateStatus =
  | 'before_window'
  | 'in_window'
  | 'running'
  | 'after_end'
  | 'outside'
  | 'no_shift'
  | 'disabled'
  | 'bypass';

export interface ShiftStatus {
  mode: ShiftSystemMode;
  bypass: boolean;
  has_shift: boolean;
  shift_name: string | null;
  branch: string | null;
  /** "HH:MM" 24h, or null. */
  start_time: string | null;
  end_time: string | null;
  /** "HH:MM" 24h. */
  now: string;
  /** Is the cashier allowed to open a POS Opening Entry right now. */
  can_open: boolean;
  status: ShiftGateStatus;
  reason: string | null;
  tolerance_minutes_before?: number;
  tolerance_minutes_after_start?: number;
  tolerance_minutes_after_end?: number;
}

/**
 * Fetch the current shift status for the logged-in user on the
 * supplied terminal. Throws on network / server error so callers can
 * surface a friendly message via extractFrappeServerError.
 */
export async function getShiftStatus(
  terminal?: string | null
): Promise<ShiftStatus> {
  const params: Record<string, string> = {};
  if (terminal) params.terminal = terminal;
  const res = await call.get<{ message: ShiftStatus }>(
    'ury.ury_pos.api.get_shift_status',
    params
  );
  return res.message;
}
