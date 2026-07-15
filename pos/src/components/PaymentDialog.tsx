import React, { useEffect, useMemo, useState } from 'react';
import {
  X,
  Percent,
  Coins,
  Users,
  User,
  Plus,
  Minus,
  Trash2,
  BedDouble,
  AlertCircle,
} from 'lucide-react';
import { usePOSStore } from '../store/pos-store';
import {
  cn,
  formatCurrency,
  extractFrappeServerError,
} from '../lib/utils';
import {
  Button,
  Input,
  Dialog,
  DialogContent,
  Select,
  SelectItem,
} from './ui';
import { showToast } from './ui/toast';
import { call } from '../lib/frappe-sdk';
import {
  displayPaymentOpen,
  displayPaymentUpdate,
  displayPaymentClose,
} from '../lib/pos-display';
import { DEFAULT_PAYMENT_MODE } from '../data/order-types';
import { chargeInvoiceToRoom } from '../lib/ihotel-api';
import { printSplitReceipts, printOrder } from '../lib/print';
import ItemSplitFlow from './ItemSplitFlow';

interface PaymentDialogProps {
  onClose: () => void;
  grandTotal: number;
  /** Passed from Orders.tsx but not currently used internally — kept
   *  for backward-compat with existing call sites. */
  roundedTotal?: number;
  invoice: string;
  customer: string;
  posProfile: string;
  table: string | null;
  cashier: string;
  owner: string;
  fetchOrders: () => Promise<void>;
  clearSelectedOrder: () => void;
  /**
   * iHotel: hotel room stamped on the draft (from Customer picker at
   * order-creation time). When set, the Payment dialog exposes a third
   * "Charge to Room" tab. When null, the tab is hidden entirely so
   * non-hotel orders stay unchanged.
   */
  hotelRoom?: string | null;
  /** Friendly label for the room's guest, rendered on the Charge tab. */
  hotelRoomLabel?: string | null;
}

type PaymentMode = 'single' | 'split' | 'room';

// Cent-safe equal distribution: floor to cents for N-1 payers, last
// payer absorbs the rounding remainder so the sum matches exactly.
const distributeEqually = (total: number, n: number): number[] => {
  if (n <= 0) return [];
  const totalCents = Math.round(total * 100);
  const baseCents = Math.floor(totalCents / n);
  const remainderCents = totalCents - baseCents * n;
  const out: number[] = [];
  for (let i = 0; i < n; i++) {
    // Distribute the extra cents across the first `remainderCents`
    // payers so no single payer gets >1c more than the rest.
    const cents = baseCents + (i < remainderCents ? 1 : 0);
    out.push(cents / 100);
  }
  return out;
};

// Sum with safe cent-math — never trust JS float addition for balance checks.
const sumAmounts = (xs: number[]): number =>
  Math.round(xs.reduce((s, x) => s + (x || 0), 0) * 100) / 100;

interface Payer {
  id: string; // stable key for React
  amount: string; // string so we can show empty state
  mode: string;
}

type SplitMode = 'equal' | 'custom';

const makePayer = (mode: string, amount: number): Payer => ({
  id: `p-${Math.random().toString(36).slice(2, 9)}`,
  amount: amount > 0 ? amount.toFixed(2) : '',
  mode,
});

const PaymentDialog: React.FC<PaymentDialogProps> = ({
  onClose,
  grandTotal,
  invoice,
  customer,
  posProfile,
  table,
  cashier,
  owner,
  fetchOrders,
  clearSelectedOrder,
  hotelRoom,
  hotelRoomLabel,
}) => {
  const {
    paymentModes,
    fetchPaymentModes,
    posProfile: storePosProfile,
  } = usePOSStore();
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [discountValue, setDiscountValue] = useState<string>('');
  const [appliedDiscount, setAppliedDiscount] = useState<number>(0);

  // iHotel: the "Charge to Room" tab is only available when the draft
  // already carries a hotel room and the POS Profile has iHotel enabled.
  // Picking the room happens in the CustomerSelect component, not here.
  const ihotelEnabled = storePosProfile?.custom_ihotel_enabled === 1;
  const canChargeToRoom = Boolean(ihotelEnabled && hotelRoom);

  // Which of the three payment paths is currently active. Default to
  // Charge to Room when it's available (cashier explicitly chose a
  // hotel guest in the picker — that's a strong intent signal) and to
  // Single otherwise.
  const [paymentMode, setPaymentMode] = useState<PaymentMode>(
    canChargeToRoom ? 'room' : 'single'
  );

  // Derived flags used by the existing render branches. Keep these
  // names so the JSX below stays the same.
  const splitEnabled = paymentMode === 'split';

  // Optional transaction / reference id for non-cash payments (card, MOMO,
  // bank transfer, etc.). Shown only when a non-cash mode is being paid.
  // 2026-07-16.
  const [transactionId, setTransactionId] = useState('');

  // Single-payer state (existing behavior, driven by mode-keyed inputs).
  const [paymentInputs, setPaymentInputs] = useState<{ [mode: string]: string }>({});

  // Split-payer state.
  const [splitMode, setSplitMode] = useState<SplitMode>('equal');
  const [payers, setPayers] = useState<Payer[]>([]);
  // Custom split: payer ids the cashier has typed into. Those keep their
  // entered amount; every UNTOUCHED payer auto-splits the remainder equally.
  const [touchedIds, setTouchedIds] = useState<Set<string>>(new Set());

  // Split STYLE: by value (per-payer amounts, one invoice) or by item
  // (separate invoices, sequential pay). 2026-06-05.
  const [splitStyle, setSplitStyle] = useState<'value' | 'item'>('value');

  // Normalize payment modes to plain string ids for child components.
  const paymentModeIds = useMemo(
    () =>
      (paymentModes as any[]).map((m) => (typeof m === 'string' ? m : m.id)),
    [paymentModes]
  );

  const setSplitEnabled = (enabled: boolean) => {
    setPaymentMode(enabled ? 'split' : 'single');
  };

  const handleSplitComplete = async () => {
    onClose();
    clearSelectedOrder();
    await fetchOrders();
  };

  useEffect(() => {
    fetchPaymentModes();
  }, [fetchPaymentModes]);

  const subtotal = grandTotal;
  const totalDiscount = appliedDiscount;
  const finalTotal = useMemo(
    () => Math.max(0, Math.round((subtotal - totalDiscount) * 100) / 100),
    [subtotal, totalDiscount]
  );

  const defaultMode = useMemo(() => {
    if (paymentModes.includes(DEFAULT_PAYMENT_MODE)) return DEFAULT_PAYMENT_MODE;
    return paymentModes[0] || DEFAULT_PAYMENT_MODE;
  }, [paymentModes]);

  // Initialize / re-balance equal-split amounts whenever the trigger inputs change.
  useEffect(() => {
    if (!splitEnabled || splitMode !== 'equal') return;
    if (payers.length === 0) return;
    const amounts = distributeEqually(finalTotal, payers.length);
    setPayers((prev) =>
      prev.map((p, i) => ({ ...p, amount: amounts[i].toFixed(2) }))
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [splitEnabled, splitMode, payers.length, finalTotal]);

  // When the cashier first enables split, seed with 2 payers and equal amounts.
  useEffect(() => {
    if (splitEnabled && payers.length === 0) {
      const amounts = distributeEqually(finalTotal, 2);
      setPayers([
        makePayer(defaultMode, amounts[0]),
        makePayer(defaultMode, amounts[1]),
      ]);
      setSplitMode('equal');
      setTouchedIds(new Set());
    }
    if (!splitEnabled && payers.length > 0) {
      setPayers([]);
      setTouchedIds(new Set());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [splitEnabled]);

  // Auto-fill the default mode for single-payer flow (existing behavior).
  useEffect(() => {
    if (splitEnabled) return;
    const defaultPresent = paymentModes.find((m) => m === DEFAULT_PAYMENT_MODE);
    const otherEntered = Object.keys(paymentInputs).length <= 1;
    if (finalTotal && paymentModes && DEFAULT_PAYMENT_MODE && defaultPresent && otherEntered) {
      setPaymentInputs((prev) => ({
        ...prev,
        [DEFAULT_PAYMENT_MODE]: String(finalTotal),
      }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finalTotal, paymentModes, splitEnabled]);

  // ------ Single-payer helpers (kept intact) ------
  const singlePayerPayments = useMemo(
    () =>
      paymentModes
        .map((mode: any) => {
          const id = typeof mode === 'string' ? mode : mode.id;
          const amount = parseFloat(paymentInputs[id] || '');
          return amount > 0 ? { mode_of_payment: id, amount } : null;
        })
        .filter(Boolean) as Array<{ mode_of_payment: string; amount: number }>,
    [paymentModes, paymentInputs]
  );
  const singlePayerTotal = useMemo(
    () => sumAmounts(singlePayerPayments.map((p) => p.amount)),
    [singlePayerPayments]
  );

  const getRemainingBalance = (currentId: string) => {
    const totalEntered = Object.entries(paymentInputs)
      .filter(([id]) => id !== currentId)
      .reduce((sum, [, val]) => sum + (parseFloat(val) || 0), 0);
    return Math.max(0, finalTotal - totalEntered);
  };

  const handlePaymentInputFocus = (id: string) => {
    setPaymentInputs((inputs) => {
      if (!inputs[id] || parseFloat(inputs[id]) === 0) {
        const remaining = getRemainingBalance(id);
        return { ...inputs, [id]: remaining > 0 ? String(remaining) : '' };
      }
      return inputs;
    });
  };

  // ------ Split-payer helpers ------
  const payerAmounts = useMemo(
    () => payers.map((p) => parseFloat(p.amount) || 0),
    [payers]
  );
  const splitPaidTotal = useMemo(() => sumAmounts(payerAmounts), [payerAmounts]);
  const splitRemaining = useMemo(
    () => Math.round((finalTotal - splitPaidTotal) * 100) / 100,
    [finalTotal, splitPaidTotal]
  );
  // Tolerance of 1 cent to avoid float-comparison pain.
  const splitBalanced = Math.abs(splitRemaining) < 0.01;

  // Custom-split redistribution: every UNTOUCHED payer shares the remainder
  // (total − sum of touched amounts) equally, cent-safe. So when the cashier
  // types into one bill, the others auto-fill: with 2 bills the second gets
  // the remainder; with 3+ the rest split it equally.
  const redistributeUntouched = (
    list: Payer[],
    touched: Set<string>
  ): Payer[] => {
    const untouched = list.filter((p) => !touched.has(p.id));
    if (untouched.length === 0) return list;
    const sumTouched = list
      .filter((p) => touched.has(p.id))
      .reduce((s, p) => s + (parseFloat(p.amount) || 0), 0);
    const remainder = Math.max(
      0,
      Math.round((finalTotal - sumTouched) * 100) / 100
    );
    const amounts = distributeEqually(remainder, untouched.length);
    let i = 0;
    return list.map((p) =>
      touched.has(p.id) ? p : { ...p, amount: amounts[i++].toFixed(2) }
    );
  };

  const setPayerAmount = (id: string, value: string) => {
    if (splitMode !== 'custom') {
      setPayers((prev) =>
        prev.map((p) => (p.id === id ? { ...p, amount: value } : p))
      );
      return;
    }
    // Lock this bill to the typed value; the rest auto-split the remainder.
    const touched = new Set(touchedIds);
    touched.add(id);
    setTouchedIds(touched);
    setPayers((prev) => {
      const updated = prev.map((p) =>
        p.id === id ? { ...p, amount: value } : p
      );
      return redistributeUntouched(updated, touched);
    });
  };
  const setPayerMode = (id: string, mode: string) => {
    setPayers((prev) => prev.map((p) => (p.id === id ? { ...p, mode } : p)));
  };
  const addPayer = () => {
    if (payers.length >= 10) return;
    setPayers((prev) => {
      const next = [...prev, makePayer(defaultMode, 0)];
      if (splitMode === 'equal') {
        const amounts = distributeEqually(finalTotal, next.length);
        return next.map((p, i) => ({ ...p, amount: amounts[i].toFixed(2) }));
      }
      // Custom: the new bill is untouched — re-split the remainder.
      return redistributeUntouched(next, touchedIds);
    });
  };
  const removePayer = (id: string) => {
    if (payers.length <= 2) return;
    const touched = new Set(touchedIds);
    touched.delete(id);
    setTouchedIds(touched);
    setPayers((prev) => {
      const next = prev.filter((p) => p.id !== id);
      if (splitMode === 'equal') {
        const amounts = distributeEqually(finalTotal, next.length);
        return next.map((p, i) => ({ ...p, amount: amounts[i].toFixed(2) }));
      }
      return redistributeUntouched(next, touched);
    });
  };
  const evenSplitFromCustom = () => {
    // Clear all locks and split evenly again.
    setTouchedIds(new Set());
    const amounts = distributeEqually(finalTotal, payers.length);
    setPayers((prev) =>
      prev.map((p, i) => ({ ...p, amount: amounts[i].toFixed(2) }))
    );
  };

  // ------ Final payload builder ------
  // The split UI is a cashier convenience. On the backend we collapse
  // every payer row that shares a mode into one POS Invoice payment row
  // (cleaner on the desk side). The cashier still "sees" the split
  // in the receipt's payment breakdown by mode.
  const collapsePayers = (
    raw: Array<{ mode: string; amount: number }>
  ): Array<{ mode_of_payment: string; amount: number }> => {
    const grouped = new Map<string, number>();
    for (const row of raw) {
      if (!row.amount) continue;
      grouped.set(row.mode, (grouped.get(row.mode) || 0) + row.amount);
    }
    return Array.from(grouped.entries()).map(([mode_of_payment, amount]) => ({
      mode_of_payment,
      amount: Math.round(amount * 100) / 100,
    }));
  };

  const outgoingPayments = useMemo(() => {
    if (splitEnabled) {
      return collapsePayers(
        payers.map((p) => ({ mode: p.mode, amount: parseFloat(p.amount) || 0 }))
      );
    }
    return singlePayerPayments;
  }, [splitEnabled, payers, singlePayerPayments]);

  const outgoingTotal = useMemo(
    () => sumAmounts(outgoingPayments.map((p) => p.amount)),
    [outgoingPayments]
  );

  // Any non-cash payment in the current tender? Drives the optional
  // Transaction ID field (single + value-split both flow through
  // make_invoice). 2026-07-16.
  const hasNonCashPayment = useMemo(
    () =>
      outgoingPayments.some(
        (p) => (p.mode_of_payment || '').trim().toLowerCase() !== 'cash'
      ),
    [outgoingPayments]
  );

  // Customer dual-screen: push amount due / collected / change to the display
  // bridge while this dialog is open (no DOM scraping). 2026-06-11.
  const changeDue = Math.max(0, Math.round((outgoingTotal - finalTotal) * 100) / 100);
  useEffect(() => {
    displayPaymentOpen(finalTotal);
    return () => displayPaymentClose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    displayPaymentUpdate(finalTotal, outgoingTotal, changeDue);
  }, [finalTotal, outgoingTotal, changeDue]);

  const canSubmit =
    paymentMode === 'room'
      ? canChargeToRoom && !isProcessing
      : splitEnabled
      ? splitBalanced && payers.every((p) => (parseFloat(p.amount) || 0) > 0)
      : outgoingPayments.length > 0;

  const handleApplyDiscount = () => {
    const value = parseFloat(discountValue);
    if (isNaN(value) || value <= 0) {
      setError('Please enter a valid discount value');
      return;
    }
    if (value > 100) {
      setError('Percentage discount cannot exceed 100%');
      return;
    }
    const calculatedDiscount = (grandTotal * value) / 100;
    setAppliedDiscount(calculatedDiscount);
    setError(null);
  };

  const handlePayment = async () => {
    setIsProcessing(true);
    setError(null);
    try {
      if (paymentMode === 'room') {
        // iHotel path: writes a Folio Charge on the guest's open
        // iHotel Profile + marks the POS Invoice as a charged draft
        // (docstatus stays 0 forever — GL entries come from iHotel's
        // checkout flow when the guest settles). See CLAUDE.md.
        if (!hotelRoom) {
          throw new Error('No hotel room is selected for this order.');
        }
        const result = await chargeInvoiceToRoom(invoice, hotelRoom);
        showToast.success(
          `Order charged to Room ${hotelRoom} · ${formatCurrency(result.amount)}`
        );
        onClose();
        clearSelectedOrder();
        await fetchOrders();
        return;
      }
      await call.post('ury.ury.doctype.ury_order.ury_order.make_invoice', {
        additionalDiscount: discountValue ? parseInt(discountValue) : null,
        cashier,
        customer,
        invoice,
        owner,
        payments: outgoingPayments,
        pos_profile: posProfile,
        table,
        // Only meaningful for non-cash tenders; blank/null otherwise.
        transaction_id: hasNonCashPayment ? transactionId.trim() || null : null,
      });
      showToast.success('Payment successful');

      // Value split (2026-06-05): print one itemized receipt per payer,
      // each headed with the grand total + that receipt's portion. A
      // print failure must not undo the (already submitted) payment.
      if (
        splitEnabled &&
        splitStyle === 'value' &&
        payers.length > 1 &&
        storePosProfile
      ) {
        try {
          const receipts = payers.map((p, i) => ({
            index: i + 1,
            total: finalTotal,
            amount: parseFloat(p.amount) || 0,
            mode: p.mode,
          }));
          await printSplitReceipts({
            orderId: invoice,
            posProfile: storePosProfile,
            receipts,
          });
        } catch (printErr) {
          console.error('Split receipt print failed:', printErr);
          showToast.error({
            title: 'Receipts not printed',
            description:
              'Payment went through, but the split receipts could not be printed. Reprint from the Orders page.',
          });
        }
      } else if (storePosProfile) {
        // Auto-print the bill on payment (single payer). A print failure
        // must NOT undo the already-submitted payment.
        try {
          await printOrder({ orderId: invoice, posProfile: storePosProfile });
        } catch (printErr) {
          console.error('Bill print failed:', printErr);
          showToast.error({
            title: 'Bill not printed',
            description:
              'Payment went through, but the bill could not be printed. Reprint it from the Orders page.',
          });
        }
      }

      onClose();
      clearSelectedOrder();
      await fetchOrders();
    } catch (err) {
      // frappe-js-sdk throws a plain Error whose `.message` is just
      // the HTTP status phrase ("There was an error."). The real
      // ValidationError lives in `_server_messages`. See CLAUDE.md
      // "Fixes log" 2026-04-10.
      const parsed = extractFrappeServerError(err, 'Payment failed.');
      setError(parsed.message);
      showToast.error({
        title: parsed.title || 'Payment Failed',
        description: parsed.message,
      });
    } finally {
      setIsProcessing(false);
    }
  };

  // Item split takes over the whole dialog with its own allocator +
  // sequential pay flow. "Cancel" inside returns to the value view.
  if (paymentMode === 'split' && splitStyle === 'item') {
    return (
      <Dialog open={true} onOpenChange={onClose}>
        <DialogContent
          variant="xlarge"
          className="bg-white w-full max-w-4xl p-0"
          showCloseButton={false}
        >
          <ItemSplitFlow
            sourceInvoice={invoice}
            table={table}
            defaultCustomer={customer}
            defaultCustomerName=""
            posProfile={storePosProfile}
            paymentModes={paymentModeIds}
            defaultMode={defaultMode}
            onCancel={() => setSplitStyle('value')}
            onComplete={handleSplitComplete}
          />
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent
        variant="xlarge"
        className="bg-white w-full max-w-4xl max-h-[92vh] flex flex-col md:flex-row p-0"
        showCloseButton={false}
      >
        {/* Left Column */}
        <div className="md:w-1/2 p-6 border-b md:border-b-0 md:border-r border-gray-200 overflow-y-auto">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-2xl font-bold text-gray-900">Payment</h2>
            <Button onClick={onClose} variant="ghost" size="icon" className="p-2">
              <X className="w-5 h-5" />
            </Button>
          </div>

          {/* Mode selector: 2-way toggle when iHotel is off, 3-way
              segmented control when the draft has a hotel room tagged. */}
          {canChargeToRoom ? (
            <div className="mb-5 grid grid-cols-3 gap-1 rounded-lg border border-gray-200 p-1 bg-gray-50 text-xs font-semibold">
              <button
                type="button"
                onClick={() => setPaymentMode('single')}
                className={cn(
                  'flex items-center justify-center gap-1.5 py-2 rounded-md transition-colors',
                  paymentMode === 'single'
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                )}
              >
                <User className="w-3.5 h-3.5" /> Single
              </button>
              <button
                type="button"
                onClick={() => setPaymentMode('split')}
                className={cn(
                  'flex items-center justify-center gap-1.5 py-2 rounded-md transition-colors',
                  paymentMode === 'split'
                    ? 'bg-white text-blue-700 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                )}
              >
                <Users className="w-3.5 h-3.5" /> Split
              </button>
              <button
                type="button"
                onClick={() => setPaymentMode('room')}
                className={cn(
                  'flex items-center justify-center gap-1.5 py-2 rounded-md transition-colors',
                  paymentMode === 'room'
                    ? 'bg-white text-amber-700 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                )}
              >
                <BedDouble className="w-3.5 h-3.5" /> Room
              </button>
            </div>
          ) : (
            <div className="mb-5 flex items-center justify-between rounded-lg border border-gray-200 p-3 bg-gray-50">
              <div className="flex items-center gap-2">
                {splitEnabled ? (
                  <Users className="w-4 h-4 text-blue-600" />
                ) : (
                  <User className="w-4 h-4 text-gray-500" />
                )}
                <div>
                  <div className="text-sm font-semibold text-gray-900">
                    {splitEnabled ? 'Split Bill' : 'Single Payer'}
                  </div>
                  <div className="text-xs text-gray-500">
                    {splitEnabled
                      ? 'Each payer pays their own share.'
                      : 'One bill, one or more payment methods.'}
                  </div>
                </div>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={splitEnabled}
                onClick={() => setSplitEnabled(!splitEnabled)}
                className={cn(
                  'relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2',
                  splitEnabled ? 'bg-blue-600' : 'bg-gray-300'
                )}
              >
                <span
                  className={cn(
                    'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition-transform',
                    splitEnabled ? 'translate-x-5' : 'translate-x-0'
                  )}
                />
              </button>
            </div>
          )}

          {/* Charge to Room panel: replaces the payment inputs entirely
              when the cashier is charging this order to the guest's folio. */}
          {paymentMode === 'room' && (
            <div className="space-y-4">
              <div className="rounded-lg border-2 border-amber-200 bg-amber-50 p-4">
                <div className="flex items-start gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-amber-200">
                    <BedDouble className="w-5 h-5 text-amber-800" />
                  </div>
                  <div className="flex-1">
                    <div className="text-sm font-bold text-amber-900 mb-1">
                      Charge to Room {hotelRoom}
                    </div>
                    {hotelRoomLabel && (
                      <div className="text-xs text-amber-800 mb-2">
                        {hotelRoomLabel}
                      </div>
                    )}
                    <div className="text-2xl font-bold text-amber-900 mb-2">
                      {formatCurrency(finalTotal)}
                    </div>
                    <p className="text-xs text-amber-800 leading-relaxed">
                      The full order total will be added to the guest's open
                      iHotel folio as a single Folio Charge row. The POS
                      Invoice stays in draft status — iHotel posts the
                      accounting entries when the guest settles at checkout.
                    </p>
                  </div>
                </div>
              </div>
              <div className="flex items-start gap-2 text-xs text-gray-600 rounded-lg bg-gray-50 border border-gray-200 p-3">
                <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0 text-gray-400" />
                <span>
                  To split, apply a discount, or take cash/card instead, switch
                  back to the <b>Single</b> or <b>Split</b> tab above.
                </span>
              </div>
            </div>
          )}

          {/* Discount Section (hidden when charging to room). */}
          {paymentMode !== 'room' && storePosProfile?.enable_discount === 1 && (
            <div className="space-y-4 mb-6">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <Percent className="w-5 h-5" />
                Apply Discount
              </h3>
              <div className="flex gap-2">
                <Input
                  type="number"
                  value={discountValue}
                  onChange={(e) => setDiscountValue(e.target.value)}
                  placeholder="Enter %"
                  size="sm"
                  className="flex-1"
                />
                <Button onClick={handleApplyDiscount} variant="default" size="sm">
                  Apply
                </Button>
              </div>
            </div>
          )}

          {/* Single-payer mode: existing behavior */}
          {paymentMode === 'single' && (
            <div className="space-y-4">
              <h3 className="text-lg font-semibold">Payment Methods</h3>
              <div className="grid grid-cols-1 gap-3">
                {paymentModes.map((mode: any) => {
                  const id = typeof mode === 'string' ? mode : mode.id;
                  return (
                    <div key={id} className="flex items-center gap-3">
                      <span className="w-24 font-medium">
                        {typeof mode === 'string' ? mode : mode.name}
                      </span>
                      <Input
                        type="number"
                        min="0"
                        step="0.01"
                        value={paymentInputs[id] || ''}
                        onChange={(e) =>
                          setPaymentInputs((inputs) => ({
                            ...inputs,
                            [id]: e.target.value,
                          }))
                        }
                        onFocus={() => handlePaymentInputFocus(id)}
                        placeholder="Amount"
                        className="flex-1"
                        size="sm"
                        disabled={isProcessing}
                      />
                    </div>
                  );
                })}
              </div>
              <div className="flex justify-between mt-2 text-sm">
                <span className="font-medium">Total Entered</span>
                <span className="text-green-600 font-semibold flex items-center gap-1">
                  {formatCurrency(singlePayerTotal)} / {formatCurrency(finalTotal)}
                  {singlePayerTotal > finalTotal && (
                    <span className="text-yellow-700 font-semibold">
                      <Coins className="inline w-4 h-4 ml-1 text-yellow-500" />
                      <span className="text-yellow-500 font-bold ml-1">
                        {formatCurrency(singlePayerTotal - finalTotal)}
                      </span>
                    </span>
                  )}
                </span>
              </div>
            </div>
          )}

          {/* Split-payer mode: per-payer cards */}
          {splitEnabled && (
            <div className="space-y-4">
              {/* Split style: by value (this view) or by item (separate
                  bills, opens the item allocator). */}
              <div className="grid grid-cols-2 gap-1 rounded-lg border border-gray-200 p-1 bg-gray-50 text-xs font-semibold">
                <button
                  type="button"
                  onClick={() => setSplitStyle('value')}
                  className={cn(
                    'py-2 rounded-md transition-colors',
                    splitStyle === 'value'
                      ? 'bg-white text-blue-700 shadow-sm'
                      : 'text-gray-500 hover:text-gray-700'
                  )}
                >
                  By Value
                </button>
                <button
                  type="button"
                  onClick={() => setSplitStyle('item')}
                  className={cn(
                    'py-2 rounded-md transition-colors',
                    splitStyle === 'item'
                      ? 'bg-white text-blue-700 shadow-sm'
                      : 'text-gray-500 hover:text-gray-700'
                  )}
                >
                  By Item
                </button>
              </div>

              {/* Mode + payer-count controls */}
              <div className="flex items-center justify-between gap-2">
                <div className="inline-flex rounded-md border border-gray-200 bg-white p-0.5 text-xs">
                  <button
                    type="button"
                    onClick={() => {
                      setSplitMode('equal');
                      setTouchedIds(new Set());
                    }}
                    className={cn(
                      'px-3 py-1.5 rounded font-semibold transition-colors',
                      splitMode === 'equal'
                        ? 'bg-blue-600 text-white shadow-sm'
                        : 'text-gray-600 hover:text-gray-900'
                    )}
                  >
                    Equal
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setSplitMode('custom');
                      setTouchedIds(new Set());
                    }}
                    className={cn(
                      'px-3 py-1.5 rounded font-semibold transition-colors',
                      splitMode === 'custom'
                        ? 'bg-blue-600 text-white shadow-sm'
                        : 'text-gray-600 hover:text-gray-900'
                    )}
                  >
                    Custom
                  </button>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    size="icon"
                    onClick={() => removePayer(payers[payers.length - 1]?.id)}
                    disabled={payers.length <= 2}
                    className="h-8 w-8"
                    title="Remove payer"
                  >
                    <Minus className="w-4 h-4" />
                  </Button>
                  <span className="text-sm font-semibold min-w-[3rem] text-center">
                    {payers.length} {payers.length === 1 ? 'payer' : 'payers'}
                  </span>
                  <Button
                    type="button"
                    variant="secondary"
                    size="icon"
                    onClick={addPayer}
                    disabled={payers.length >= 10}
                    className="h-8 w-8"
                    title="Add payer"
                  >
                    <Plus className="w-4 h-4" />
                  </Button>
                </div>
              </div>

              {/* Custom-mode shortcut */}
              {splitMode === 'custom' && (
                <button
                  type="button"
                  onClick={evenSplitFromCustom}
                  className="text-xs text-blue-600 hover:text-blue-800 font-semibold underline-offset-2 hover:underline"
                >
                  Reset to even split
                </button>
              )}

              {/* Payer cards */}
              <div className="space-y-2.5 max-h-[280px] overflow-y-auto pr-1">
                {payers.map((p, idx) => {
                  const amt = parseFloat(p.amount) || 0;
                  return (
                    <div
                      key={p.id}
                      className={cn(
                        'rounded-lg border p-3 transition-colors',
                        amt > 0
                          ? 'border-blue-200 bg-blue-50/40'
                          : 'border-gray-200 bg-white'
                      )}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-600 text-xs font-bold text-white">
                            {idx + 1}
                          </div>
                          <span className="text-sm font-semibold text-gray-900">
                            Payer {idx + 1}
                          </span>
                        </div>
                        {payers.length > 2 && (
                          <button
                            type="button"
                            onClick={() => removePayer(p.id)}
                            className="text-gray-400 hover:text-red-600 transition-colors"
                            title="Remove payer"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="flex-1 relative">
                          <Input
                            type="number"
                            min="0"
                            step="0.01"
                            value={p.amount}
                            onChange={(e) => setPayerAmount(p.id, e.target.value)}
                            placeholder="Amount"
                            size="sm"
                            disabled={splitMode === 'equal' || isProcessing}
                            className={cn(
                              splitMode === 'equal' &&
                                'bg-gray-50 cursor-not-allowed'
                            )}
                          />
                        </div>
                        <div className="w-32">
                          <Select
                            value={p.mode}
                            onValueChange={(v) => setPayerMode(p.id, v)}
                            disabled={isProcessing}
                            size="sm"
                          >
                            {paymentModes.map((m: any) => {
                              const mid = typeof m === 'string' ? m : m.id;
                              const label = typeof m === 'string' ? m : m.name;
                              return (
                                <SelectItem key={mid} value={mid}>
                                  {label}
                                </SelectItem>
                              );
                            })}
                          </Select>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Balance bar */}
              <div
                className={cn(
                  'rounded-lg border p-3',
                  splitBalanced && payers.length > 0
                    ? 'border-green-300 bg-green-50'
                    : splitPaidTotal > finalTotal
                    ? 'border-yellow-300 bg-yellow-50'
                    : 'border-gray-200 bg-gray-50'
                )}
              >
                <div className="flex justify-between text-xs text-gray-600 mb-1.5">
                  <span>Collected</span>
                  <span>Total</span>
                </div>
                <div className="flex justify-between items-end mb-2">
                  <span className="text-lg font-bold text-gray-900">
                    {formatCurrency(splitPaidTotal)}
                  </span>
                  <span className="text-sm font-semibold text-gray-600">
                    {formatCurrency(finalTotal)}
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-gray-200 overflow-hidden">
                  <div
                    className={cn(
                      'h-full transition-all',
                      splitBalanced
                        ? 'bg-green-500'
                        : splitPaidTotal > finalTotal
                        ? 'bg-yellow-500'
                        : 'bg-blue-500'
                    )}
                    style={{
                      width: `${
                        finalTotal > 0
                          ? Math.min(
                              100,
                              Math.round((splitPaidTotal / finalTotal) * 100)
                            )
                          : 0
                      }%`,
                    }}
                  />
                </div>
                <div className="mt-2 text-xs font-semibold">
                  {splitBalanced ? (
                    <span className="text-green-700">Balanced — ready to charge.</span>
                  ) : splitRemaining > 0 ? (
                    <span className="text-gray-700">
                      {formatCurrency(splitRemaining)} remaining
                    </span>
                  ) : (
                    <span className="text-yellow-700">
                      Over by {formatCurrency(Math.abs(splitRemaining))}
                    </span>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Optional transaction / reference id — shown only when a
              non-cash mode is being paid. 2026-07-16. */}
          {paymentMode !== 'room' && hasNonCashPayment && (
            <div className="mt-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Transaction ID{' '}
                <span className="text-gray-400 font-normal">(optional)</span>
              </label>
              <Input
                type="text"
                value={transactionId}
                onChange={(e) => setTransactionId(e.target.value)}
                placeholder="e.g. MoMo / card / transfer reference"
                disabled={isProcessing}
              />
              <p className="mt-1 text-xs text-gray-500">
                Reference for the non-cash payment (card, mobile money, transfer…).
              </p>
            </div>
          )}
        </div>

        {/* Right Column */}
        <div className="md:w-1/2 p-6 overflow-y-auto">
          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-red-700 text-sm">{error}</p>
            </div>
          )}

          <div className="space-y-3 mb-6">
            <h3 className="text-lg font-semibold">Order Summary</h3>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-600">Subtotal</span>
                <span>{formatCurrency(subtotal)}</span>
              </div>
              {appliedDiscount > 0 && (
                <div className="flex justify-between text-green-600">
                  <span>Discount</span>
                  <span>-{formatCurrency(appliedDiscount)}</span>
                </div>
              )}
              <div className="border-t pt-2">
                <div className="flex justify-between font-semibold text-lg">
                  <span>Total</span>
                  <span>{formatCurrency(finalTotal)}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Split summary in the right column so the receipt preview feels honest */}
          {splitEnabled && payers.length > 0 && (
            <div className="mb-6 rounded-lg bg-gray-50 border border-gray-200 p-3">
              <h4 className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5" />
                Split Breakdown
              </h4>
              <ul className="space-y-1 text-xs">
                {payers.map((p, i) => (
                  <li key={p.id} className="flex justify-between">
                    <span className="text-gray-600">
                      Receipt {i + 1} · <span className="font-medium">{p.mode}</span>
                    </span>
                    <span className="font-semibold text-gray-900">
                      {formatCurrency(parseFloat(p.amount) || 0)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <Button
            onClick={handlePayment}
            disabled={isProcessing || !canSubmit}
            variant={isProcessing || !canSubmit ? 'secondary' : 'default'}
            className={cn(
              'w-full',
              paymentMode === 'room' &&
                !isProcessing &&
                canSubmit &&
                'bg-amber-600 hover:bg-amber-700 text-white'
            )}
          >
            {isProcessing
              ? 'Processing...'
              : paymentMode === 'room'
              ? `Charge ${formatCurrency(finalTotal)} to Room ${hotelRoom}`
              : `Pay ${formatCurrency(
                  splitEnabled ? splitPaidTotal : outgoingTotal || finalTotal
                )}`}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default PaymentDialog;
