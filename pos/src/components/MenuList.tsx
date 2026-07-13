import { useEffect, useMemo } from 'react';
import { usePOSStore } from '../store/pos-store';
import MenuCard from './MenuCard';
import { Spinner } from './ui/spinner';
import { cn } from '../lib/utils';

interface MenuListProps {
  onItemClick: (item: any) => void;
}

const MenuList: React.FC<MenuListProps> = ({ onItemClick }) => {
  const {
    menuItems,
    menuLoading,
    error,
    selectedCategory,
    searchQuery,
    quickFilter,
    fetchMenuItems,
    isMenuInteractionDisabled,
    isOrderInteractionDisabled
  } = usePOSStore();

  useEffect(() => {
    fetchMenuItems();
  }, [fetchMenuItems]);

  const filteredItems = useMemo(() => {
    return menuItems.filter(item => {
      const searchTerm = searchQuery.toLowerCase();
      const matchesCategory = !selectedCategory || item.course === selectedCategory;
      const matchesSearch = !searchQuery || 
        item.name.toLowerCase().includes(searchTerm) ||
        item.item.toLowerCase().includes(searchTerm);
      const matchesFilter = quickFilter === 'all' || 
        (quickFilter === 'special' && item.special_dish === 1);
      
      return matchesCategory && matchesSearch && matchesFilter;
    });
  }, [menuItems, selectedCategory, searchQuery, quickFilter]);

  const isInteractionDisabled = isMenuInteractionDisabled() || isOrderInteractionDisabled();

  return (
    <div className="flex-1 overflow-auto bg-gray-50">
      <div className="max-w-screen-xl mx-auto p-3 sm:p-4 pb-8">
        {menuLoading ? (
          <div className="h-96">
            <Spinner message="Loading menu items..." />
          </div>
        ) : error ? (
          <div className="flex items-center justify-center h-96">
            <div className="text-red-600 text-center">
              <p className="text-lg font-medium">Error loading menu items</p>
              <p className="text-sm mt-2">{error}</p>
            </div>
          </div>
        ) : menuItems.length === 0 ? (
          // Underlying menu is genuinely empty — a fresh install or an
          // admin who hasn't added any items yet. Deep-link to the desk
          // so they can add items instead of just staring at a blank screen.
          // See CLAUDE.md "Fixes log" 2026-04-08.
          <div className="flex items-center justify-center h-96">
            <div className="text-center max-w-md">
              <p className="text-lg font-medium text-gray-700">No menu items yet</p>
              <p className="text-sm mt-2 text-gray-500">
                This menu has no items. Add some under{' '}
                <strong>ExPOS Menu Item</strong> in the desk to see them here.
              </p>
              <button
                onClick={() =>
                  window.open(
                    `${window.location.origin}/app/ury-menu-item/new?disabled=0`,
                    '_blank'
                  )
                }
                className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 text-sm font-medium"
              >
                Add Menu Items
              </button>
            </div>
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="flex items-center justify-center h-96">
            <div className="text-gray-500 text-center">
              <p className="text-lg font-medium">No items found</p>
              <p className="text-sm mt-2">Try adjusting your filters or search term</p>
            </div>
          </div>
        ) : (
          <div className={cn(
            "grid grid-cols-3 sm:grid-cols-4 xl:grid-cols-5 gap-2 sm:gap-3",
            isInteractionDisabled && "opacity-50 pointer-events-none"
          )}>
            {filteredItems.map((item) => (
              <MenuCard
                key={item.id}
                id={item.id}
                name={item.name}
                price={item.price}
                item_image={item.image}
                course={item.course}
                item={item.item}
                onClick={() => onItemClick(item)}
                disabled={isInteractionDisabled}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default MenuList; 