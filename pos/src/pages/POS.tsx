import React, { useState, useRef } from 'react';
import { Star, TrendingUp, ShoppingCart, ChevronRight } from 'lucide-react';
import Sidebar from '../components/Sidebar';
import OrderPanel from '../components/OrderPanel';
import ProductDialog from '../components/ProductDialog';
import MenuList from '../components/MenuList';
import { usePOSStore } from '../store/pos-store';
import { cn, formatCurrency } from '../lib/utils';
import { Spinner } from '../components/ui/spinner';
import InitialLoader from '../components/InitialLoader';

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
  const cartSubtotal = activeOrders.reduce(
    (s, i) => s + (i.price || 0) * (i.quantity || 0),
    0
  );
  const clickTimerRef = useRef<NodeJS.Timeout | null>(null);
  const clickCountRef = useRef(0);

  const handleItemClick = (item: any) => {
    if (isMenuInteractionDisabled()) return;
    
    clickCountRef.current += 1;
    
    if (clickTimerRef.current) {
      clearTimeout(clickTimerRef.current);
    }

    clickTimerRef.current = setTimeout(() => {
      if (clickCountRef.current === 1) {
        // Single click - add to cart
        addToOrder({ ...item, quantity: 1 });
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

        {/* Floating cart bar — only when the cart is a drawer (< lg). Opens
            the OrderPanel slide-over. */}
        <button
          type="button"
          onClick={() => setCartOpen(true)}
          className="lg:hidden shrink-0 flex items-center justify-between gap-3 px-4 py-3 bg-blue-600 text-white shadow-lg active:bg-blue-700"
        >
          <span className="flex items-center gap-2 font-medium">
            <span className="relative">
              <ShoppingCart className="w-5 h-5" />
              {cartCount > 0 && (
                <span className="absolute -top-2 -right-2 bg-white text-blue-700 text-[10px] font-bold rounded-full h-4 min-w-[16px] px-1 flex items-center justify-center">
                  {cartCount > 99 ? '99+' : cartCount}
                </span>
              )}
            </span>
            {cartCount > 0
              ? `${cartCount} item${cartCount === 1 ? '' : 's'}`
              : 'View order'}
          </span>
          <span className="flex items-center gap-2 font-semibold">
            {cartCount > 0 && <span>{formatCurrency(cartSubtotal)}</span>}
            <ChevronRight className="w-5 h-5" />
          </span>
        </button>
      </div>

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
