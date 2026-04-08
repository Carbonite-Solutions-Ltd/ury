import { call } from './frappe-sdk';

const TERMINAL_KEY = 'ury_pos_terminal';

export interface TerminalConfig {
  terminal: string;
  room: string;
  branch: string;
  description?: string;
  /**
   * Name of the POS Profile bound to this terminal.
   * Always present on responses from `get_terminal_config`. On responses
   * from `get_terminals` (the list endpoint used by the setup screen) it
   * may be empty for terminals that haven't been fully configured yet —
   * those should be visually flagged as "not configured" and not
   * selectable.
   */
  pos_profile?: string;
}

interface TerminalConfigResponse {
  message: TerminalConfig;
}

interface TerminalListResponse {
  message: TerminalConfig[];
}

/** Fetch a single terminal's config from the server. */
export async function getTerminalConfig(terminal: string): Promise<TerminalConfig> {
  const res = await call.get<TerminalConfigResponse>(
    'ury.ury_pos.api.get_terminal_config',
    { terminal }
  );
  return res.message;
}

/** List all active terminals for the current user's branch. */
export async function getTerminals(): Promise<TerminalConfig[]> {
  const res = await call.get<TerminalListResponse>(
    'ury.ury_pos.api.get_terminals'
  );
  return res.message;
}

/** Get saved terminal name from this device's localStorage. */
export function getSavedTerminal(): string | null {
  return localStorage.getItem(TERMINAL_KEY);
}

/** Save terminal name to this device's localStorage. */
export function saveTerminal(terminalName: string): void {
  localStorage.setItem(TERMINAL_KEY, terminalName);
}

/** Clear saved terminal from this device. */
export function clearSavedTerminal(): void {
  localStorage.removeItem(TERMINAL_KEY);
}
