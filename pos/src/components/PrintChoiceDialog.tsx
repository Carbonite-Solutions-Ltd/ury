import { Printer, CheckCircle2, X, Loader2 } from 'lucide-react';
import { Button } from './ui';

export type PrintChoice = 'printer' | 'mark';

interface PrintChoiceDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onChoose: (choice: PrintChoice) => void;
  /** Invoice being printed — shown so the admin can see what they're acting on. */
  orderName?: string | null;
  /** Disables both actions while the chosen flow runs. */
  busy?: boolean;
}

/**
 * Asks an administrator whether to actually print a bill or just mark it
 * as printed.
 *
 * Shown ONLY to users passing `canSkipPhysicalPrint` (Administrator /
 * System Manager). Everyone else keeps the unchanged one-click print —
 * a cashier should never be offered a "pretend I printed it" button.
 *
 * Why this exists: URY gates the Payment button behind `invoice_printed`,
 * so an admin testing orders and payments has to print a physical
 * receipt on every single test run just to unlock Payment. "Mark as
 * Printed" calls the very same backend endpoint a real print calls
 * (`qz_print_update`), so the invoice is flagged printed and Payment
 * unlocks — nothing is sent to a printer.
 */
const PrintChoiceDialog = ({
  isOpen,
  onClose,
  onChoose,
  orderName,
  busy = false,
}: PrintChoiceDialogProps) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-md w-full shadow-xl overflow-hidden">
        <div className="flex items-start justify-between px-6 pt-5 pb-3">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Print or Mark Printed?</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              {orderName
                ? `Order ${orderName}`
                : 'Choose how to handle this bill.'}
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

        <div className="px-6 pb-5 space-y-3">
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
                Send the bill to the printer as normal
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
