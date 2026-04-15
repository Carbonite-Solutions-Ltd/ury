import { printWithQz } from './print-qz';
import {
  getInvoicePrintHtml,
  networkPrint,
  selectNetworkPrinter,
  updatePrintStatus
} from './invoice-api';
import { PosProfileCombined } from './pos-profile-api';

interface PrintOrderParams {
  orderId: string;
  posProfile: PosProfileCombined
}

/**
 * Print an invoice.
 *
 * Reads the NEW unified `custom_print_mode` config first (set by
 * the 2026-04-16 print revamp), falling back to the legacy
 * `qz_print` flag for profiles that haven't been re-saved since
 * migration. For QZ Tray mode, passes the `custom_bill_printer`
 * string to QZ so the print goes to the ADMIN-configured bill
 * printer, not `qz.printers.getDefault()` (the old bug).
 */
export async function printOrder({ orderId, posProfile }: PrintOrderParams): Promise<'qz' | 'network' | 'socket'> {
  const {
    qz_print,
    qz_host,
    print_format,
    printer,
    name,
    cashier,
    multiple_cashier,
    custom_print_mode,
    custom_bill_printer,
  } = posProfile;

  // Decide the print mode. Prefer the new config; fall back to the
  // legacy qz_print flag. Treat "Disabled" as falling through to
  // legacy so admins can explicitly opt out by setting it.
  const newQz = custom_print_mode === 'QZ Tray';
  const newCups = custom_print_mode === 'CUPS (Direct)';
  const newDisabled = custom_print_mode === 'Disabled';

  if (newQz || (!newDisabled && qz_print === 1)) {
    // Fall back to 'localhost' when qz_host is empty. QZ Tray
    // almost always runs on the cashier's local machine and the
    // browser connects to localhost. Historical installs that
    // were never touched may have a null qz_host — the schema now
    // ships with default 'localhost' but we default in code too
    // as a belt-and-braces for sites that haven't re-migrated yet.
    const qzHost = qz_host || 'localhost';
    const html = await getInvoicePrintHtml(orderId, print_format as string);
    // Prefer the new bill printer field; fall back to the legacy
    // single `printer` field for backwards compat.
    const billPrinter = (custom_bill_printer || printer || null) as string | null;
    await printWithQz(qzHost, html, billPrinter);
    await updatePrintStatus(orderId);
    return 'qz';
  } else if (newCups || printer) {
    // Network printing — unchanged legacy path. CUPS Direct mode
    // falls here; its backend resolver handles per-department routing.
    if (cashier && !multiple_cashier) {
      await networkPrint(
        orderId,
        (custom_bill_printer || printer) as string,
        print_format as string,
      );
    } else {
      await selectNetworkPrinter(orderId, name, print_format);
    }
    await updatePrintStatus(orderId);
    return 'network';
  } else {
    // Last-resort fallback: open the printview page in a new tab.
    // This is the UX pain point the user flagged — Round 2 will
    // replace this with an inline print modal + hidden iframe.
    const url = `/printview?doctype=POS Invoice&name=${orderId}&format=${print_format}&no_letterhead=1&settings={}&letterhead=No Letterhead&trigger_print=1&_lang=en`;
    window.open(url, '_blank', 'noopener,noreferrer');
    await updatePrintStatus(orderId);
    return 'socket';
  }
}
