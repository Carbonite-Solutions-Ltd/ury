import { useEffect, useState } from 'react';
import { UserRound, Phone, X, Loader2 } from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';

export interface OrderContact {
  contact_name: string;
  contact_mobile: string;
}

interface Props {
  open: boolean;
  /** Order type being rung — shown in the copy so the prompt reads naturally. */
  orderType?: string | null;
  /** Prefilled values when editing an existing order's contact. */
  initialName?: string;
  initialMobile?: string;
  /**
   * 'prompt'  — asked while placing a new order. Primary action continues
   *             to placing the order, and Skip is offered prominently
   *             because the details are optional.
   * 'edit'    — editing an existing order from the Orders page. Primary
   *             action saves; no Skip (Cancel closes).
   */
  mode?: 'prompt' | 'edit';
  busy?: boolean;
  onClose: () => void;
  onSubmit: (contact: OrderContact) => void;
}

/**
 * Captures the name + phone number for a take-away or delivery order.
 *
 * Both fields are OPTIONAL, deliberately and visibly so: a walk-in
 * take-away often has neither, and forcing a cashier to invent values (or
 * to hunt for a Skip button) would slow the queue down for no benefit.
 * Enter blocks nothing, and Skip is a first-class action rather than a
 * quiet link.
 *
 * The same dialog serves the later edit from the Orders page — that's why
 * `mode` exists. Keeping one component means the field rules and phone
 * keypad behaviour can't drift between "capture" and "correct".
 */
const OrderContactDialog = ({
  open,
  orderType,
  initialName = '',
  initialMobile = '',
  mode = 'prompt',
  busy = false,
  onClose,
  onSubmit,
}: Props) => {
  const [name, setName] = useState(initialName);
  const [mobile, setMobile] = useState(initialMobile);

  // The dialog stays mounted (renders null when closed), so state would
  // otherwise persist between opens and show the previous order's
  // details. Re-seed on every open — same trap as CommentDialog.
  useEffect(() => {
    if (open) {
      setName(initialName);
      setMobile(initialMobile);
    }
  }, [open, initialName, initialMobile]);

  if (!open) return null;

  const submit = () =>
    onSubmit({ contact_name: name.trim(), contact_mobile: mobile.trim() });

  const isEdit = mode === 'edit';
  const label = (orderType || 'take-away').toLowerCase();

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center px-4">
      <div className="bg-white rounded-xl shadow-xl max-w-md w-full overflow-hidden">
        <div className="px-6 pt-5 pb-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-gray-900">
              {isEdit ? 'Contact Details' : 'Who is this order for?'}
            </h2>
            <p className="text-sm text-gray-500 mt-0.5">
              {isEdit
                ? 'Update the name or phone number for this order.'
                : `Optional — add a name and phone number for this ${label} order, or skip.`}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label="Close"
            className="text-gray-400 hover:text-gray-700 p-1 rounded-md hover:bg-gray-100 disabled:opacity-40"
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-6 pb-2 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Name <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <div className="relative">
              <UserRound
                size={16}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none"
              />
              <Input
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Customer name"
                className="pl-9"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') submit();
                }}
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Mobile Number{' '}
              <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <div className="relative">
              <Phone
                size={16}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none"
              />
              <Input
                // `tel` so a tablet shows the phone keypad rather than a
                // full keyboard. NOT `number` — that strips leading zeros
                // and rejects the +, spaces and dashes people actually type.
                type="tel"
                inputMode="tel"
                value={mobile}
                onChange={(e) => setMobile(e.target.value)}
                placeholder="e.g. 024 123 4567"
                className="pl-9"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') submit();
                }}
              />
            </div>
          </div>
        </div>

        <div className="px-6 pb-6 pt-4 flex items-center justify-end gap-2">
          {isEdit ? (
            <Button variant="outline" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
          ) : (
            <Button
              variant="outline"
              onClick={() => onSubmit({ contact_name: '', contact_mobile: '' })}
              disabled={busy}
            >
              Skip
            </Button>
          )}
          <Button
            onClick={submit}
            disabled={busy}
            className="bg-blue-600 hover:bg-blue-700 text-white"
          >
            {busy && <Loader2 size={14} className="mr-1.5 animate-spin" />}
            {isEdit ? 'Save' : 'Continue'}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default OrderContactDialog;
