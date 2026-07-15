import React, { useState, useRef } from 'react';
import { Star, TrendingUp, ShoppingCart } from 'lucide-react';
import Sidebar from '../components/Sidebar';
import OrderPanel from '../components/OrderPanel';
import ProductDialog from '../components/ProductDialog';
import MenuList from '../components/MenuList';
import { usePOSStore } from '../store/pos-store';
import { cn } from '../lib/utils';
import { Spinner } from '../components/ui/spinner';
import InitialLoader from '../components/InitialLoader';
import { flyToCart } from '../lib/fly-to-cart';

export default function POS() {
  const {
    quickFilter,
    setQuickFilter,
    setSelectedItem,
    addToOrder,
    loading,
    error,
    isMenuInteractionDisabled,
    isInitializing,
    categories,
    selectedCategory,
    setSelectedCategory,
    activeOrders,
  } = usePOSStore();

  const [isDialogOpen, setIsDialogOpen] = useState(false);
  // < lg the cart is a slide-over drawer opened from the floating bar.
  const [cartOpen, setCartOpen] = useState(false);
  const cartCount = activeOrders.reduce((s, i) => s + (i.quantity || 0), 0);
  const clickTimerRef = useRef<NodeJS.Timeout | null>(null);
  const clickCountRef = useRef(0);
  // The tapped card element, used as the fly-to-cart animation source.
  const lastCardElRef = useRef<HTMLElement | null>(null);

  const handleItemClick = (item: any, el?: HTMLElement) => {
    if (isMenuInteractionDisabled()) return;

    if (el) lastCardElRef.current = el;
    clickCountRef.current += 1;

    if (clickTimerRef.current) {
      clearTimeout(clickTimerRef.current);
    }

    clickTimerRef.current = setTimeout(() => {
      if (clickCountRef.current === 1) {
        // Single click - add to cart, with a fly-to-cart swish + haptic tap.
        addToOrder({ ...item, quantity: 1 });
        flyToCart(lastCardElRef.current);
      } else if (clickCountRef.current === 2) {
        // Double click - open dialog
        setSelectedItem(item);
        setIsDialogOpen(true);
      }
      clickCountRef.current = 0;
    }, 250); // 250ms threshold for double click
  };

  const QuickFilterButton = ({ filter, icon: Icon, label }: { 
    filter: 'all' | 'special';
    icon: React.ElementType;
    label: string;
  }) => (
    <button
      onClick={() => setQuickFilter(filter)}
      className={cn(
        'flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium transition-colors',
        quickFilter === filter
          ? 'bg-blue-100 text-blue-700'
          : 'bg-gray-100 text-gray-700 hover:bg-gray-200',
        isMenuInteractionDisabled() && 'opacity-50 cursor-not-allowed pointer-events-none'
      )}
      disabled={isMenuInteractionDisabled()}
    >
      <Icon className="w-4 h-4" />
      {label}
    </button>
  );

  // Horizontal category chips shown when the category rail (Sidebar) is
  // hidden (< xl). Keeps categories one tap away on tablet/mobile.
  const CategoryChip = ({ value, label }: { value: string; label: string }) => (
    <button
      onClick={() => setSelectedCategory(value)}
      className={cn(
        'shrink-0 px-3 py-1.5 rounded-full text-sm font-medium transition-colors whitespace-nowrap',
        selectedCategory === value
          ? 'bg-blue-600 text-white'
          : 'bg-gray-100 text-gray-700 hover:bg-gray-200',
        isMenuInteractionDisabled() && 'opacity-50 cursor-not-allowed pointer-events-none'
      )}
      disabled={isMenuInteractionDisabled()}
    >
      {label}
    </button>
  );

  if (isInitializing) {
    return <InitialLoader />;
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <p className="text-xl font-semibold text-red-600 mb-2">Failed to load POS</p>
          <p className="text-gray-600">{error}</p>
          <button 
            onClick={() => window.location.reload()}
            className="mt-4 px-4 py-2 bg-primary-600 text-white rounded-md hover:bg-primary-700"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Spinner message="Loading menu items..." />
      </div>
    );
  }

  return (
    <div className="flex flex-1 overflow-hidden h-full">
      <Sidebar disabled={isMenuInteractionDisabled()} />
      <div className="flex-1 flex flex-col h-full overflow-hidden min-w-0">
        <div className="p-3 sm:p-4 bg-white border-b border-gray-200">
          <div className="max-w-screen-xl mx-auto space-y-2.5">
            <div className="flex items-center gap-2 overflow-x-auto overflow-y-hidden">
              <QuickFilterButton filter="all" icon={Star} label="All" />
              <QuickFilterButton filter="special" icon={TrendingUp} label="Special Items" />
            </div>
            {/* Category chips — visible when the Sidebar rail is hidden (< xl). */}
            {categories.length > 0 && (
              <div className="xl:hidden flex items-center gap-2 overflow-x-auto overflow-y-hidden pb-0.5">
                <CategoryChip value="" label="All Items" />
                {categories.map((c) => (
                  <CategoryChip key={c} value={c} label={c} />
                ))}
              </div>
            )}
          </div>
        </div>

        <MenuList onItemClick={handleItemClick} />
      </div>

      {/* Floating cart button (FAB) — only when the cart is a drawer (< lg).
          Sits above the bottom nav; the badge flags the item count. */}
      {!cartOpen && (
        <button
          type="button"
          data-cart-target
          onClick={() => setCartOpen(true)}
          aria-label={cartCount > 0 ? `View order, ${cartCount} items` : 'View order'}
          className="lg:hidden fixed bottom-20 right-4 z-30 h-14 w-14 rounded-full bg-blue-600 text-white shadow-xl flex items-center justify-center active:bg-blue-700 active:scale-95 transition-transform"
        >
          <ShoppingCart className="w-6 h-6" />
          {cartCount > 0 && (
            <span className="absolute -top-1 -right-1 min-w-[20px] h-5 px-1 rounded-full bg-red-500 text-white text-xs font-bold flex items-center justify-center border-2 border-white">
              {cartCount > 99 ? '99+' : cartCount}
            </span>
          )}
        </button>
      )}

      {/* Backdrop for the mobile cart drawer. */}
      {cartOpen && (
        <div
          className="lg:hidden fixed inset-0 bg-black/40 z-30"
          onClick={() => setCartOpen(false)}
        />
      )}

      <OrderPanel mobileOpen={cartOpen} onCloseMobile={() => setCartOpen(false)} />
      {isDialogOpen && <ProductDialog onClose={() => setIsDialogOpen(false)} />}
    </div>
  );
}
