import { useState } from 'react';
import { Trash2, Edit, FrownIcon, Plus, Loader2, MessageSquare, Users, X } from 'lucide-react';
import { usePOSStore } from '../store/pos-store';
import { formatCurrency, cn, extractFrappeServerError } from '../lib/utils';
import { canManageMenuPrices, isCaptainOrAbove } from '../lib/role-utils';
import { CustomerSelect } from './CustomerSelect';
import ProductDialog from './ProductDialog';
import OrderTypeSelect from './OrderTypeSelect';
import CommentDialog from './CommentDialog';
import { Button } from './ui/button';
import { Spinner } from './ui/spinner';
import { syncOrder } from '../lib/order-api';
import { useRootStore } from '../store/root-store';
import type { RootState } from '../store/root-store';
import { showToast } from './ui/toast';
import { DINE_IN } from '../data/order-types';
import WaiterSelectDialog from './WaiterSelectDialog';
import type { Waiter } from '../lib/waiter-api';

interface OrderPanelProps {
  /** < lg: whether the cart drawer is open. Ignored on lg+ (static column). */
  mobileOpen?: boolean;
  /** < lg: close the cart drawer. */
  onCloseMobile?: () => void;
}

const OrderPanel = ({ mobileOpen = false, onCloseMobile }: OrderPanelProps = {}) => {
  const {
    activeOrders,
    removeFromOrder,
    updateQuantity,
    updateItemComment,
    clearOrder,
    setSelectedItem,
    orderLoading,
    isOrderInteractionDisabled,
    isUpdatingOrder,
    posProfile,
    selectedOrderType,
    selectedTable,
    selectedRoom,
    selectedCustomer,
    selectedAggregator,
    resetOrderState,
    paymentModes,
    orderId,
    orderComment,
    setOrderComment,
    terminalName,
    shiftBlocked,
    hotelRoom,
    selectedWaiter,
    setSelectedWaiter,
    lockedItemQtys,
  } = usePOSStore();
  const user = useRootStore((state: RootState) => state.user);
  // On an EXISTING order, a plain cashier can only INCREASE the original
  // items — never reduce them below what was ordered or remove them (that
  // previously let them delete the whole order by emptying it). Captains /
  // managers / admins keep full control. New items added this session stay
  // freely editable for everyone.
  const restrictExistingItems = isUpdatingOrder && !isCaptainOrAbove(user);
  const [editingItem, setEditingItem] = useState<typeof activeOrders[0] | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showCommentDialog, setShowCommentDialog] = useState(false);
  // Cart line whose per-item note is being edited (null = dialog closed).
  const [noteItem, setNoteItem] = useState<any | null>(null);
  const [showWaiterDialog, setShowWaiterDialog] = useState(false);
  const [numberOfPeople, setNumberOfPeople] = useState<number>(1);

  // Waiter feature: pop a waiter picker when CREATING a new order on a
  // profile that uses waiters. Not on updates (the order already has one).
  const useWaiter = posProfile?.custom_use_waiter === 1;

  const calculateItemTotal = (item: typeof activeOrders[0]) => {
    const basePrice = item.selectedVariant?.price || item.price;
    const addonsTotal = item.selectedAddons?.reduce((sum, addon) => sum + addon.price, 0) || 0;
    return (basePrice + addonsTotal) * item.quantity;
  };

  const total = activeOrders.reduce(
    (sum, item) => sum + calculateItemTotal(item),
    0
  );

  const handleEdit = (item: typeof activeOrders[0]) => {
    const menuItem = {
      ...item,
      variants: item.variants,
      addons: item.addons,
    };
    setSelectedItem(menuItem);
    setEditingItem(item);
  };

  const handleCommentSave = (comment: string) => {
    setOrderComment(comment);
  };

  const handleNumberOfPeopleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = parseInt(e.target.value) || 0;
    if (value >= 0 && value <= 100) {
      setNumberOfPeople(value);
    }
  };

  const handleSubmit = async (waiterOverride?: Waiter) => {
    try {
      if (!posProfile) {
        throw new Error('POS Profile not found');
      }

      if (!user?.name) {
        throw new Error('User not logged in');
      }

      // Hard block when the POS Profile has
      // `custom_block_orders_after_shift_end` enabled and the shift
      // has run past its `custom_shift_hours` limit. The
      // ShiftHoursBanner already shows a red banner explaining why.
      // See CLAUDE.md "Fixes log" 2026-04-09.
      if (shiftBlocked) {
        showToast.error(
          'Your shift is over. Close the POS Opening Entry before starting a new one.'
        );
        return;
      }

      // Validate customer/aggregator details
      if (selectedOrderType === 'Aggregators') {
        if (!selectedAggregator?.customer) {
          showToast.error('Please select an aggregator before proceeding');
          return;
        }
      } else if (!selectedCustomer?.name) {
        showToast.error('Please select a customer before proceeding');
        return;
      }

      // Validate table selection for dine-in orders
      if (selectedOrderType === DINE_IN && !selectedTable) {
        showToast.error(`Please select a table for ${DINE_IN} orders`);
        return;
      }

      // Validate number of people for dine-in orders
      if (selectedOrderType === DINE_IN && numberOfPeople < 1) {
        showToast.error('Please enter the number of people (at least 1)');
        return;
      }

      // Waiter gate: when the profile uses waiters, a NEW order must have a
      // waiter. Self-serve waiters (URY Waiter role + linked) are auto-
      // assigned their own waiter (posProfile.self_waiter) — the picker
      // never opens for them. Everyone else (cashier/captain/manager/admin)
      // picks; if none is chosen yet, pop the picker and stop here — the
      // dialog re-calls handleSubmit with the chosen waiter. Updates skip
      // this (the order already carries its waiter). The backend also
      // FORCES the self-waiter in sync_order, so this can't be spoofed.
      const orderWaiter =
        waiterOverride || selectedWaiter || posProfile.self_waiter || undefined;
      if (useWaiter && !isUpdatingOrder && !orderWaiter?.name) {
        setShowWaiterDialog(true);
        return;
      }

      setIsSubmitting(true);
      
      const orderData = {
        items: activeOrders.map((item) => ({
          item: item.id,
          item_name: item.name,
          rate: item.selectedVariant?.price || item.price,
          qty: item.quantity,
          comment: item.comment || undefined,
        })),
        no_of_pax: selectedOrderType === DINE_IN ? numberOfPeople : 1,
        pos_profile: posProfile.name,
        order_type: selectedOrderType,
        table: selectedTable || undefined,
        room: selectedRoom || undefined,
        customer:
          selectedOrderType === "Aggregators"
            ? selectedAggregator?.customer
            : selectedCustomer?.name,
        aggregator_id:
          selectedOrderType === "Aggregators"
            ? selectedAggregator?.customer
            : undefined,
        cashier: posProfile.cashier,
        owner: isUpdatingOrder ? undefined : user.name,
        mode_of_payment: paymentModes[0],
        last_invoice: isUpdatingOrder ? orderId : null,
        invoice: isUpdatingOrder ? orderId : null,
        waiter: user.name,
        selected_waiter: orderWaiter?.name || undefined,
        comments: orderComment || undefined,
        terminal: terminalName || undefined,
        hotel_room: hotelRoom || undefined,
      };

      await syncOrder(orderData);
      
      // Reset all states after successful order submission
      resetOrderState();
      setNumberOfPeople(1);
      showToast.success(isUpdatingOrder ? 'Order updated successfully' : 'Order created successfully');
      // On mobile the panel is a drawer — close it so the cashier lands
      // back on the menu after ringing an order.
      onCloseMobile?.();
    } catch (error) {
      console.error('Failed to sync order:', error);

      // Parse Frappe's _server_messages envelope. Prefers raise_exception=1
      // so we surface the actual ValidationError, not any side-effect
      // msgprint(alert=True) that piggybacked on the response. Strips
      // HTML so links like <a href="...">Fanta</a> don't render as raw
      // markup. See CLAUDE.md "Fixes log" 2026-04-08.
      const parsed = extractFrappeServerError(error, 'Failed to process order');

      // Special case: Price Not Set. sync_order throws with
      // title="Price Not Set" when a menu item has no price or rate 0.
      // Show a rich toast with a "Set Price in Menu" deep-link — but
      // only to users who can actually edit the menu. Cashiers see the
      // message without the button so they know to ask a manager.
      if (parsed.title === 'Price Not Set') {
        const canEdit = canManageMenuPrices(user);
        showToast.error({
          title: 'Price Not Set',
          description: parsed.message,
          action: canEdit
            ? {
                label: 'Set Price in Menu',
                onClick: () =>
                  window.open(
                    `${window.location.origin}/app/ury-menu`,
                    '_blank',
                  ),
              }
            : undefined,
        });
      } else {
        showToast.error(parsed.message);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const EmptyCartUI = () => (
    <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
      <div className="w-24 h-24 bg-gray-100 rounded-full flex items-center justify-center mb-6">
        <FrownIcon className="w-12 h-12 text-gray-400" />
      </div>
      
      <h3 className="text-lg font-semibold text-gray-900 mb-2">
        Your cart is empty
      </h3>
      
      <p className="text-gray-500 text-sm mb-6 max-w-xs leading-relaxed">
        Add items to get started with your order
      </p>
      
      <div className="flex items-center gap-2 text-blue-600 bg-blue-50 px-4 py-2 rounded-lg">
        <Plus className="w-4 h-4" />
        <span className="text-sm font-medium">Click items to add them</span>
      </div>
      
      <div className="mt-4 text-xs text-gray-400">
        Double-click for customization options
      </div>
    </div>
  );

  const LoadingOrderUI = () => (
    <div className="h-96">
      <Spinner message="Loading order details..." />
    </div>
  );

  const isInteractionDisabled =
    isOrderInteractionDisabled() || isSubmitting || shiftBlocked;

  return (
    <div
      data-cart-target
      className={cn(
        'bg-white flex flex-col z-40',
        // Desktop (lg+): static right column.
        'lg:relative lg:w-96 lg:border-l lg:border-gray-200 lg:h-full lg:shrink-0 lg:z-10 lg:shadow-none lg:translate-x-0',
        // Mobile / tablet-portrait (< lg): fixed slide-over drawer from the
        // right, opened via the floating cart bar in POS.tsx.
        'fixed inset-y-0 right-0 h-full w-full max-w-md shadow-2xl transition-transform duration-300 ease-in-out',
        mobileOpen ? 'translate-x-0' : 'translate-x-full lg:translate-x-0'
      )}
    >
      {/* Mobile drawer header with a close button (hidden on lg+). */}
      <div className="lg:hidden flex items-center justify-between px-4 py-3 border-b border-gray-200 flex-shrink-0">
        <span className="text-base font-semibold text-gray-900">Order</span>
        <button
          type="button"
          onClick={onCloseMobile}
          aria-label="Close order panel"
          className="inline-flex items-center justify-center h-9 w-9 rounded-md text-gray-500 hover:bg-gray-100"
        >
          <X className="w-5 h-5" />
        </button>
      </div>
      <div className="p-4 border-b border-gray-200 flex-shrink-0">
        <OrderTypeSelect disabled={isInteractionDisabled} />
        <div className="mt-3"><CustomerSelect disabled={isInteractionDisabled} /></div>

        {/* Self-serve waiter: locked to herself, no picker. */}
        {useWaiter && posProfile?.self_waiter && (
          <div className="mt-3 flex items-center gap-2 text-sm bg-blue-50 border border-blue-200 rounded-md px-3 py-2 text-blue-800">
            <Users className="w-4 h-4 shrink-0" />
            <span className="truncate">
              Serving as <strong>{posProfile.self_waiter.full_name}</strong>
            </span>
          </div>
        )}

        {/* Number of People Input - Only show for Dine In */}
        {selectedOrderType === DINE_IN && (
          <div className="mt-3">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Number of People
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <Users className="h-4 w-4 text-gray-400" />
              </div>
              <input
                type="number"
                min="1"
                max="100"
                value={numberOfPeople}
                onChange={handleNumberOfPeopleChange}
                className={cn(
                  "block w-full pl-10 pr-3 py-2 border border-gray-300 rounded-md",
                  "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500",
                  "text-sm",
                  isInteractionDisabled && "bg-gray-100 cursor-not-allowed"
                )}
                disabled={isInteractionDisabled}
                placeholder="Enter number of people"
              />
            </div>
            {numberOfPeople < 1 && (
              <p className="mt-1 text-xs text-red-600">
                Please enter at least 1 person
              </p>
            )}
          </div>
        )}
      </div>
      
      {orderLoading ? (
        <LoadingOrderUI />
      ) : activeOrders.length === 0 ? (
        <EmptyCartUI />
      ) : (
        <>
          <div className="flex-1 overflow-y-auto px-6">
            {activeOrders.map((item) => (
              <div
                key={item.uniqueId}
                className={cn(
                  "flex flex-col py-4 border-b border-gray-100",
                  isInteractionDisabled && "opacity-50"
                )}
              >
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <div className="flex items-center justify-between">
                      <h3 className="font-medium text-gray-900 text-sm">{item.name}</h3>
                    </div>
                    {item.selectedVariant && (
                      <p className="text-sm text-gray-600">{item.selectedVariant.name}</p>
                    )}
                    {item.selectedAddons && item.selectedAddons.length > 0 && (
                      <p className="text-sm text-gray-500">
                        {item.selectedAddons.map(addon => addon.name).join(', ')}
                      </p>
                    )}
                    <p className="text-gray-600 text-sm">{formatCurrency(calculateItemTotal(item))}</p>
                    {/* Special instruction for this line — shown so the
                        cashier/waiter can see it without opening a dialog. */}
                    {item.comment && (
                      <p className="mt-1 inline-flex items-start gap-1 rounded bg-amber-50 border border-amber-300 px-2 py-0.5 text-xs font-medium text-amber-900">
                        <MessageSquare className="w-3 h-3 mt-0.5 shrink-0" />
                        <span className="break-words">{item.comment}</span>
                      </p>
                    )}
                  </div>

                  <div className="flex items-center space-x-2">
                    {/* One-tap per-item note (2026-07-16). Previously the only
                        way in was double-tapping the menu card to open the
                        product dialog, which nobody discovered. Allowed even
                        on already-ordered lines — a note changes no qty or
                        price, so the cashier item-restriction doesn't apply. */}
                    <Button
                      onClick={() => setNoteItem(item)}
                      variant="ghost"
                      size="icon"
                      className={cn(
                        item.comment
                          ? 'text-amber-600 hover:text-amber-700'
                          : 'text-gray-400 hover:text-gray-600'
                      )}
                      title={item.comment ? 'Edit note' : 'Add note'}
                      disabled={isInteractionDisabled}
                    >
                      <MessageSquare className="w-5 h-5" />
                    </Button>
                    <Button
                      onClick={() => handleEdit(item)}
                      variant="ghost"
                      size="icon"
                      className="text-blue-600 hover:text-blue-700"
                      title={
                        restrictExistingItems &&
                        (lockedItemQtys[item.uniqueId!] || 0) > 0
                          ? 'Only a captain can edit an item already ordered'
                          : 'Edit item'
                      }
                      // Editing re-opens the product dialog (qty/add-ons); a
                      // cashier mustn't use it to reduce an original item.
                      disabled={
                        isInteractionDisabled ||
                        (restrictExistingItems &&
                          (lockedItemQtys[item.uniqueId!] || 0) > 0)
                      }
                    >
                      <Edit className="w-4 h-4" />
                    </Button>
                    <div className="flex items-center space-x-2">
                      <Button
                        onClick={() => {
                          const newQuantity = Math.max(0, item.quantity - 1);
                          if (newQuantity === 0) {
                            removeFromOrder(item.uniqueId!);
                          } else {
                            updateQuantity(item.uniqueId!, newQuantity);
                          }
                        }}
                        variant="outline"
                        size="icon"
                        className="w-8 h-8 rounded-full"
                        // Cashiers can't reduce an original item below the
                        // quantity already ordered.
                        disabled={
                          isInteractionDisabled ||
                          (restrictExistingItems &&
                            item.quantity <=
                              (lockedItemQtys[item.uniqueId!] || 0))
                        }
                        title={
                          restrictExistingItems &&
                          item.quantity <= (lockedItemQtys[item.uniqueId!] || 0)
                            ? 'Only a captain can reduce an item already ordered'
                            : undefined
                        }
                      >
                        -
                      </Button>
                      <span className="w-6 text-center">{item.quantity}</span>
                      <Button
                        onClick={() => updateQuantity(item.uniqueId!, item.quantity + 1)}
                        variant="outline"
                        size="icon"
                        className="w-8 h-8 rounded-full"
                        disabled={isInteractionDisabled}
                      >
                        +
                      </Button>
                    </div>

                    {/* Remove (trash) — hidden for a cashier on an original
                        item; only a captain can remove what's already
                        ordered (new items this session stay removable). */}
                    {!(
                      restrictExistingItems &&
                      (lockedItemQtys[item.uniqueId!] || 0) > 0
                    ) && (
                      <Button
                        onClick={() => removeFromOrder(item.uniqueId!)}
                        variant="ghost"
                        size="icon"
                        className="text-red-500 hover:text-red-600"
                        disabled={isInteractionDisabled}
                      >
                        <Trash2 className="w-5 h-5" />
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            ))}
            {/* Clear cart wipes every line — hidden for a cashier editing an
                existing order (it would empty the original items, the very
                loophole we're closing). Captains keep it. */}
            {activeOrders.length > 0 && !restrictExistingItems && (
              <Button
                onClick={clearOrder}
                variant="ghost"
                size="sm"
                className="w-full text-gray-600 hover:text-gray-800 mt-4"
                disabled={isInteractionDisabled}
              >
                Clear cart
              </Button>
            )}
          </div>
          
          <div className="p-4 border-t border-gray-200 flex-shrink-0 bg-white">
            <div className="flex justify-between items-center mb-4">
              <div className="flex items-center gap-2">
                <Button
                  onClick={() => setShowCommentDialog(true)}
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "h-8 w-8 p-0",
                    orderComment ? "text-blue-600" : "text-gray-500 hover:text-gray-700"
                  )}
                  disabled={isInteractionDisabled}
                  title={orderComment ? "Edit comment" : "Add comment"}
                >
                  <MessageSquare className="w-4 h-4" />
                </Button>
                <span className="text-lg font-semibold">Total</span>
              </div>
              <span className="text-lg font-semibold">{formatCurrency(total)}</span>
            </div>
            <Button
              onClick={() => handleSubmit()}
              variant="default"
              size="default"
              className="w-full"
              disabled={isInteractionDisabled}
            >
              {isSubmitting ? (
                <div className="flex items-center">
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  {isUpdatingOrder ? 'Updating Order...' : 'Processing Order...'}
                </div>
              ) : isUpdatingOrder ? (
                'Update Order'
              ) : (
                'Add New Order'
              )}
            </Button>
          </div>
        </>
      )}

      {editingItem && (
        <ProductDialog
          onClose={() => {
            setEditingItem(null);
            setSelectedItem(null);
          }}
          editMode
          initialVariant={editingItem.selectedVariant}
          initialAddons={editingItem.selectedAddons}
          initialQuantity={editingItem.quantity}
          itemToReplace={editingItem}
        />
      )}

      <CommentDialog
        isOpen={showCommentDialog}
        onClose={() => setShowCommentDialog(false)}
        onSave={handleCommentSave}
        initialComment={orderComment}
      />
      {/* Per-item special instruction (reuses CommentDialog with item wording). */}
      <CommentDialog
        isOpen={!!noteItem}
        onClose={() => setNoteItem(null)}
        onSave={(c) => {
          if (noteItem?.uniqueId) updateItemComment(noteItem.uniqueId, c);
        }}
        initialComment={noteItem?.comment || ''}
        title={noteItem?.name ? `Note — ${noteItem.name}` : 'Item Note'}
        label="Special instructions for this item"
        placeholder="e.g. no onions, extra spicy, well done…"
      />
      {showWaiterDialog && (
        <WaiterSelectDialog
          onSelect={(w) => {
            setSelectedWaiter(w);
            setShowWaiterDialog(false);
            // Continue the submit with the just-picked waiter (passed
            // directly to avoid the stale-closure on selectedWaiter).
            handleSubmit(w);
          }}
          onCancel={() => setShowWaiterDialog(false)}
        />
      )}
    </div>
  );
};

export default OrderPanel;