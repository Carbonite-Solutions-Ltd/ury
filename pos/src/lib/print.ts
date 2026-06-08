import { printWithQz } from './print-qz';
import {
  getInvoicePrintHtml,
  networkPrint,
  selectNetworkPrinter,
  updatePrintStatus
} from './invoice-api';
import { PosProfileCombined } from './pos-profile-api';
import { formatCurrency } from './utils';

interface PrintOrderParams {
  orderId: string;
  posProfile: PosProfileCombined
}

/** One value-split payment portion to print as its own receipt. */
export interface SplitReceipt {
  /** 1-based receipt number. */
  index: number;
  /** Order grand total (same on every receipt). */
  total: number;
  /** This receipt's payment portion. */
  amount: number;
  /** Mode of payment for this portion. */
  mode: string;
}

interface PrintSplitReceiptsParams {
  orderId: string;
  posProfile: PosProfileCombined;
  receipts: SplitReceipt[];
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

/** Banner prepended to each value-split receipt copy. */
function buildSplitBanner(receipt: SplitReceipt, count: number): string {
  return (
    `<div style="text-align:center;font-family:monospace;` +
    `border-bottom:1px dashed #000;padding:6px 0;margin-bottom:8px;">` +
    `<div style="font-size:15px;font-weight:bold;">RECEIPT ${receipt.index} OF ${count}</div>` +
    `<div style="font-size:12px;">Grand Total: ${formatCurrency(receipt.total)}</div>` +
    `<div style="font-size:14px;font-weight:bold;margin-top:2px;">` +
    `This receipt: ${formatCurrency(receipt.amount)} (${receipt.mode})</div>` +
    `</div>`
  );
}

/**
 * Print one itemized receipt per value-split payer. Each receipt is the
 * full invoice HTML with a banner injected at the top showing the grand
 * total and that receipt's payment portion ("Receipt 1 of 2").
 *
 * QZ Tray mode (the default for cloud-hosted URY) fetches the base HTML
 * once and prints N annotated copies. In CUPS / socket modes — where the
 * receipt is rendered server-side and we can't inject the banner without
 * a print-format change — it falls back to printing the bill once.
 */
export async function printSplitReceipts({
  orderId,
  posProfile,
  receipts,
}: PrintSplitReceiptsParams): Promise<'qz' | 'network' | 'socket'> {
  if (!receipts || receipts.length <= 1) {
    return printOrder({ orderId, posProfile });
  }

  const {
    qz_print,
    qz_host,
    print_format,
    printer,
    custom_print_mode,
    custom_bill_printer,
  } = posProfile;

  const newQz = custom_print_mode === 'QZ Tray';
  const newDisabled = custom_print_mode === 'Disabled';

  if (newQz || (!newDisabled && qz_print === 1)) {
    const qzHost = qz_host || 'localhost';
    const html = await getInvoicePrintHtml(orderId, print_format as string);
    const billPrinter = (custom_bill_printer || printer || null) as string | null;
    for (const receipt of receipts) {
      const banner = buildSplitBanner(receipt, receipts.length);
      // eslint-disable-next-line no-await-in-loop -- jobs must not interleave
      await printWithQz(qzHost, banner + html, billPrinter);
    }
    await updatePrintStatus(orderId);
    return 'qz';
  }

  // Non-QZ: banner injection isn't available server-side, so just print
  // the bill once. The on-screen Split Breakdown still shows the portions.
  return printOrder({ orderId, posProfile });
}
