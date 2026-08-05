import { useEffect, useState } from 'react';
import { Printer, CheckCircle2, X, Loader2, AlertTriangle, FileText } from 'lucide-react';
import { Button } from './ui';
import { getInvoicePrintHtml } from '../lib/invoice-api';

export type PrintChoice = 'printer' | 'mark';

interface PrintChoiceDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onChoose: (choice: PrintChoice) => void;
  /** Invoice being printed — shown so the admin can see what they're acting on. */
  orderName?: string | null;
  /** Disables both actions while the chosen flow runs. */
  busy?: boolean;
  /**
   * The print config actually in effect. Every field here is read from
   * the POS Profile the till resolved at boot, so what the dialog
   * reports IS what `printOrder` will use — not a re-derivation that
   * could drift from it.
   */
  printFormat?: string | null;
  /**
   * False when the named format does not exist. Resolved server-side
   * because the two failure modes are indistinguishable from the
   * output: a blank name and a deleted/renamed one both render Frappe's
   * Standard layout, byte for byte, with no exception.
   */
  printFormatExists?: boolean;
  printMode?: string | null;
  billPrinter?: string | null;
  qzHost?: string | null;
  posProfileName?: string | null;
}

/**
 * Asks an administrator whether to actually print a bill or just mark it
 * as printed — and shows exactly WHICH print format is about to be used,
 * with a live preview of the rendered result.
 *
 * Shown ONLY to users passing `canSkipPhysicalPrint` (Administrator /
 * System Manager). Everyone else keeps the unchanged one-click print —
 * a cashier should never be offered a "pretend I printed it" button.
 *
 * WHY THE PREVIEW EXISTS (2026-07-31). "The bill doesn't use the print
 * format set on the POS Profile" is a claim that is genuinely hard to
 * check from the outside: `frappe.www.printview.get_html_and_style`
 * falls back to Frappe's Standard format when it is handed a blank or
 * unknown format name, and it does so SILENTLY. The output looks like a
 * receipt either way, so nothing about the printed paper tells you which
 * format produced it.
 *
 * So the dialog states the format name, where it came from, and renders
 * the actual HTML that would be sent to the printer. A blank
 * `print_format` on the profile is called out explicitly rather than
 * quietly becoming "Standard".
 *
 * The preview is an IFRAME, not dangerouslySetInnerHTML: print formats
 * ship their own CSS, which would otherwise leak into the POS's own
 * styles (and vice versa — Tailwind's preflight would restyle the
 * receipt, making the preview a liar).
 */
const PrintChoiceDialog = ({
  isOpen,
  onClose,
  onChoose,
  orderName,
  busy = false,
  printFormat,
  printFormatExists,
  printMode,
  billPrinter,
  qzHost,
  posProfileName,
}: PrintChoiceDialogProps) => {
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const formatIsSet = Boolean(printFormat && String(printFormat).trim());
  // Only trust an explicit false. `undefined` means an older backend
  // that predates the flag, and treating that as "missing" would cry
  // wolf on every print.
  const formatMissing = formatIsSet && printFormatExists === false;
  const formatOk = formatIsSet && !formatMissing;

  useEffect(() => {
    // Re-fetch on every open. The dialog stays mounted, so without this
    // it would show the PREVIOUS order's receipt — the same trap already
    // fixed in CommentDialog and OrderContactDialog.
    if (!isOpen || !orderName) {
      setPreviewHtml(null);
      setPreviewError(null);
      return;
    }
    let cancelled = false;
    setPreviewLoading(true);
    setPreviewError(null);
    setPreviewHtml(null);

    // Deliberately passes the format through exactly as printOrder does,
    // blank included. Substituting a default here would hide the very
    // misconfiguration this dialog exists to expose.
    getInvoicePrintHtml(orderName, (printFormat ?? '') as string)
      .then((html) => {
        if (!cancelled) setPreviewHtml(html);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setPreviewError(
            err instanceof Error ? err.message : 'Could not render the preview.'
          );
        }
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isOpen, orderName, printFormat]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-start sm:items-center justify-center z-50 p-4 overflow-y-auto">
      <div className="bg-white rounded-lg max-w-3xl w-full shadow-xl overflow-hidden my-4">
        <div className="flex items-start justify-between px-6 pt-5 pb-3 border-b border-gray-200">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Print or Mark Printed?</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              {orderName ? `Order ${orderName}` : 'Choose how to handle this bill.'}
            </p>
          </div>
          <button
            onClick={onClose}
            disabled={busy}
            aria-label="Close"
            className="text-gray-400 hover:text-gray-600 disabled:opacity-40"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* ── what is actually about to be used ── */}
        <div className="px-6 py-4 bg-gray-50 border-b border-gray-200">
          <div className="flex items-center gap-2 mb-2">
            <FileText className="w-4 h-4 text-gray-500" />
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
              Print configuration
            </span>
          </div>

          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
            <div className="flex justify-between sm:block">
              <dt className="text-gray-500 sm:text-xs">Print format</dt>
              <dd
                className={
                  formatOk
                    ? 'font-semibold text-gray-900 break-all'
                    : 'font-semibold text-red-600 break-all'
                }
              >
                {formatIsSet ? printFormat : 'Not set'}
                {formatMissing && (
                  <span className="block text-xs font-normal">
                    — this format does not exist
                  </span>
                )}
              </dd>
            </div>
            <div className="flex justify-between sm:block">
              <dt className="text-gray-500 sm:text-xs">From POS Profile</dt>
              <dd className="font-medium text-gray-900 break-all">
                {posProfileName || '—'}
              </dd>
            </div>
            <div className="flex justify-between sm:block">
              <dt className="text-gray-500 sm:text-xs">Mode</dt>
              <dd className="font-medium text-gray-900">{printMode || 'Legacy'}</dd>
            </div>
            <div className="flex justify-between sm:block">
              <dt className="text-gray-500 sm:text-xs">Printer</dt>
              <dd className="font-medium text-gray-900 break-all">
                {billPrinter || 'Default'}
                {qzHost && qzHost !== 'localhost' ? ` · ${qzHost}` : ''}
              </dd>
            </div>
          </dl>

          {!formatOk && (
            <div className="mt-3 flex gap-2 rounded-md border border-red-200 bg-red-50 p-3">
              <AlertTriangle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
              <p className="text-xs text-red-800 leading-relaxed">
                {formatMissing ? (
                  <>
                    POS Profile <strong>{posProfileName || 'this profile'}</strong>{' '}
                    names the print format <strong>{printFormat}</strong>, but no
                    such format exists — it was renamed or deleted. Frappe falls
                    back to its Standard layout <em>silently</em>, so the receipt
                    below is NOT your format. Repoint{' '}
                    <strong>Print Format</strong> on that profile in the desk.
                  </>
                ) : (
                  <>
                    This POS Profile has <strong>no Print Format set</strong>, so
                    Frappe falls back to its Standard layout without warning —
                    which is exactly what "it isn't using my print format" looks
                    like. Set <strong>Print Format</strong> on POS Profile{' '}
                    <strong>{posProfileName || 'this profile'}</strong> in the desk.
                  </>
                )}
              </p>
            </div>
          )}
        </div>

        {/* ── the actual rendered receipt ── */}
        <div className="px-6 py-4">
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Preview
          </span>
          <div className="mt-2 border border-gray-200 rounded-md bg-white overflow-hidden">
            {previewLoading && (
              <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-500">
                <Loader2 className="w-4 h-4 animate-spin" />
                Rendering the receipt…
              </div>
            )}
            {previewError && (
              <div className="px-4 py-6 text-sm text-red-700 bg-red-50">
                <p className="font-medium">Preview failed</p>
                <p className="mt-1 text-xs">{previewError}</p>
                <p className="mt-2 text-xs text-red-600">
                  A format that can't render here won't print either — this is
                  likely the real fault.
                </p>
              </div>
            )}
            {previewHtml !== null && !previewLoading && (
              // srcDoc, not dangerouslySetInnerHTML: keeps the receipt's own
              // CSS out of the POS and Tailwind's preflight out of the
              // receipt, so what is shown matches what prints.
              <iframe
                title="Receipt preview"
                srcDoc={previewHtml}
                className="w-full h-[45vh] bg-white"
                sandbox=""
              />
            )}
          </div>
        </div>

        <div className="px-6 pb-5 space-y-3 border-t border-gray-200 pt-4">
          <Button
            onClick={() => onChoose('printer')}
            disabled={busy}
            className="w-full justify-start bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 px-4 rounded-lg h-auto"
          >
            {busy ? (
              <Loader2 className="w-5 h-5 mr-3 animate-spin shrink-0" />
            ) : (
              <Printer className="w-5 h-5 mr-3 shrink-0" />
            )}
            <span className="text-left">
              <span className="block">Print to Printer</span>
              <span className="block text-xs font-normal opacity-90">
                Sends exactly what's previewed above
                {billPrinter ? ` to ${billPrinter}` : ''}
              </span>
            </span>
          </Button>

          <Button
            onClick={() => onChoose('mark')}
            disabled={busy}
            variant="outline"
            className="w-full justify-start border-gray-300 text-gray-700 hover:bg-gray-50 font-medium py-3 px-4 rounded-lg h-auto"
          >
            <CheckCircle2 className="w-5 h-5 mr-3 shrink-0 text-green-600" />
            <span className="text-left">
              <span className="block">Mark as Printed</span>
              <span className="block text-xs font-normal text-gray-500">
                Nothing is sent to a printer. Unlocks Payment.
              </span>
            </span>
          </Button>

          <p className="text-xs text-gray-400 pt-1">
            You're seeing this because you're signed in as an administrator.
            Cashiers always print normally.
          </p>
        </div>
      </div>
    </div>
  );
};

export default PrintChoiceDialog;
