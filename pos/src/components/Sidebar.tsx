import { 
  Grid3X3,
  UtensilsCrossed,
} from 'lucide-react';
import { usePOSStore } from '../store/pos-store';
import { cn } from '../lib/utils';
import { Button, Badge } from './ui';
import CommentDialog from './CommentDialog';
import { useState } from 'react';

/**
 * One row of the category rail.
 *
 * ⚠ `h-auto` is load-bearing. The shared Button primitive's default size is
 * `h-10` — a FIXED 40px — so a name that wrapped to two or three lines
 * (text-sm is 20px a line, plus 20px of padding) overflowed its own box and
 * printed on top of the row beneath it. Branches with long course names
 * ("MENU - SOUPS NKWAN", "LOCAL & SOUP DISHES") hit this on every row.
 * `cn()` is tailwind-merge, so `h-auto` here correctly drops the base `h-10`
 * rather than fighting it.
 *
 * `min-h-[2.5rem]` keeps single-line rows exactly the height they were, so
 * nothing moves for the common case.
 */
const CATEGORY_ROW =
  'w-full flex items-center justify-between gap-2 px-3 py-2.5 h-auto min-h-[2.5rem] ' +
  'text-sm font-medium text-left transition-all duration-200 group relative';

interface SidebarProps {
  disabled?: boolean;
}

const Sidebar = ({ disabled }: SidebarProps) => {
  const { selectedCategory, setSelectedCategory, menuItems, categories, orderComment, setOrderComment } = usePOSStore();
  const [showCommentDialog, setShowCommentDialog] = useState(false);

  // Count items per category
  const getCategoryCount = (category: string) => {
    const count = menuItems.filter(item => item.course === category).length;
    return count;
  };

  const getAllItemsCount = () => {
    const count = menuItems.length;
    return count;
  };

  const handleCommentSave = (comment: string) => {
    setOrderComment(comment);
  };

  return (
    <div className={cn(
      // Desktop-only category rail. On narrower screens the categories
      // render as a horizontal chip row in the POS page (see POS.tsx).
      "hidden xl:flex w-64 bg-white border-r border-gray-200 h-full flex-col",
      disabled && "opacity-50 pointer-events-none"
    )}>
      {/* Categories List */}
      <nav className="flex-1 p-6 overflow-y-auto">
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
          {/* Section Title */}
          <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3 px-1">
            categories
          </h2>
          
          {/* All Items */}
          <Button
            onClick={() => setSelectedCategory('')}
            variant="ghost"
            className={cn(
              CATEGORY_ROW,
              'mb-1',
              selectedCategory === ''
                ? 'bg-white text-gray-900 shadow-sm font-semibold'
                : 'text-gray-700 hover:bg-white/60 hover:text-gray-900'
            )}
            disabled={disabled}
          >
            {/* Active indicator bar */}
            {selectedCategory === '' && (
              <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-blue-600 rounded-r-full" />
            )}
            
            <div className="flex items-center gap-3 ml-1 min-w-0">
              <Grid3X3 className="w-4 h-4 text-gray-500 flex-shrink-0" />
              <span>All Items</span>
            </div>

            <Badge variant="secondary" size="sm" className="shrink-0 text-xs text-gray-500 bg-gray-100 min-w-[24px] text-center">
              {getAllItemsCount()}
            </Badge>
          </Button>

          {/* Divider */}
          <div className="h-px bg-gray-200 my-3 mx-1" />

          {/* Category Items */}
          <div className="space-y-1">
            {categories.map((category) => {
              const count = getCategoryCount(category);
              return (
                <Button
                  key={category}
                  onClick={() => setSelectedCategory(category)}
                  variant="ghost"
                  className={cn(
                    CATEGORY_ROW,
                    selectedCategory === category
                      ? 'bg-white text-gray-900 shadow-sm font-semibold'
                      : 'text-gray-700 hover:bg-white/60 hover:text-gray-900'
                  )}
                  disabled={disabled}
                >
                  {/* Active indicator bar */}
                  {selectedCategory === category && (
                    <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-blue-600 rounded-r-full" />
                  )}
                  <div className="flex items-center gap-3 ml-1 min-w-0 flex-1">
                    <UtensilsCrossed className="w-4 h-4 text-gray-500 flex-shrink-0" />
                    {/* break-words so a long single token ("MENU ITEM - CHINESE
                        - SITOUT") wraps instead of running past the rail. */}
                    <span className="text-start leading-snug break-words">
                      {category}
                    </span>
                  </div>
                  <Badge variant="secondary" size="sm" className="shrink-0 text-xs text-gray-500 bg-gray-100 min-w-[24px] text-center">
                    {count}
                  </Badge>
                </Button>
              );
            })}
          </div>
        </div>
      </nav>

      {/* Comment Dialog is rendered from sidebar but triggered from order panel, to not mount it on every order panel render */}
      <CommentDialog
        isOpen={showCommentDialog}
        onClose={() => setShowCommentDialog(false)}
        onSave={handleCommentSave}
        initialComment={orderComment}
      />
    </div>
  );
};

export default Sidebar; 