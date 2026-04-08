import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { storage } from './storage';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(amount: number): string {
  const symbol = storage.getItem('currencySymbol');
  return `${symbol} ${amount}`;
}

/** Parsed shape of a single Frappe server message. */
export interface FrappeServerMessage {
  message: string;
  title?: string;
  indicator?: 'blue' | 'green' | 'orange' | 'red' | 'yellow';
  raise_exception?: 0 | 1;
  as_table?: boolean;
}

/**
 * Parse Frappe's `_server_messages` envelope. It's a JSON-encoded array
 * of JSON-encoded objects. Returns [] on any parse failure.
 */
export function parseFrappeServerMessages(err: unknown): FrappeServerMessage[] {
  if (!err || typeof err !== 'object') return [];
  const anyErr = err as { _server_messages?: string };
  if (!anyErr._server_messages) return [];
  try {
    const arr = JSON.parse(anyErr._server_messages);
    if (!Array.isArray(arr)) return [];
    return arr
      .map((m) => {
        try {
          return typeof m === 'string' ? JSON.parse(m) : m;
        } catch {
          return null;
        }
      })
      .filter((m): m is FrappeServerMessage => !!m && typeof m.message === 'string');
  } catch {
    return [];
  }
}

/**
 * Pick the "real" error message from a Frappe error object. Prefers any
 * message flagged `raise_exception: 1` (Frappe's convention for "this is
 * the thrown error"); falls back to the last server message; then to
 * `err.message`; then to the fallback string. Handles the case where
 * multiple messages come back — e.g. a side-effect `msgprint(alert=True)`
 * from ERPNext's insert_item_price() stacked with the actual ValidationError.
 * Before this helper, consumers were reading `_server_messages[0]` which
 * could easily be the side-effect alert, not the thrown error.
 *
 * `stripHtml: true` (default) removes any `<a>…</a>` / `<br>` / etc. so
 * react-toastify renders it as plain text instead of raw markup.
 */
export function extractFrappeServerError(
  err: unknown,
  fallback: string = 'Something went wrong. Please try again.',
  stripHtml: boolean = true,
): { title?: string; message: string; raw?: FrappeServerMessage } {
  const messages = parseFrappeServerMessages(err);

  let picked: FrappeServerMessage | undefined;
  if (messages.length > 0) {
    picked = messages.find((m) => m.raise_exception === 1) || messages[messages.length - 1];
  }

  let text = picked?.message;
  if (!text && err && typeof err === 'object') {
    const anyErr = err as { message?: string };
    text = anyErr.message;
  }
  text = text || fallback;

  if (stripHtml) {
    // Strip tags + decode the handful of entities Frappe actually emits.
    text = text
      .replace(/<[^>]*>/g, '')
      .replace(/&amp;/g, '&')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .trim();
  }

  return {
    title: picked?.title,
    message: text,
    raw: picked,
  };
}
