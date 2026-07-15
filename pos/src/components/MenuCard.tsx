import { FC } from 'react';
import { formatCurrency, cn } from '../lib/utils';

interface MenuCardProps {
  id: string;
  name: string;
  price: number;
  item_image: string | null;
  course?: string;
  item: string;
  onClick?: (el: HTMLElement) => void;
  disabled?: boolean;
}

const MenuCard: FC<MenuCardProps> = ({ 
  id, 
  name, 
  price, 
  item_image, 
  course, 
  item, 
  onClick,
  disabled 
}) => {
  return (
    <div
      className={cn(
        // Compact so more fit per row (4 on phones, 5 on tablets, 6 on
        // landscape/desktop — see MenuList grid). active:scale gives a
        // tactile press feel alongside the fly-to-cart animation.
        "bg-white rounded-lg shadow-sm overflow-hidden hover:shadow-md transition-transform cursor-pointer flex flex-col h-36 sm:h-44 xl:h-48 active:scale-95",
        disabled && "opacity-50 cursor-not-allowed pointer-events-none"
      )}
      onClick={disabled ? undefined : (e) => onClick?.(e.currentTarget as HTMLElement)}
    >
      {/* Image section - fixed height */}
      <div className="h-14 sm:h-20 shrink-0">
        {item_image ? (
          <img
            src={item_image}
            alt={name}
            className="w-full h-full object-cover filter saturate-75 brightness-95"
            style={{ filter: 'saturate(0.7) brightness(0.95)' }}
            onError={(e) => {
              const target = e.target as HTMLImageElement;
              target.style.display = 'none';
              const parent = target.parentElement;
              if (parent) {
                const placeholder = document.createElement('div');
                placeholder.className = 'w-full h-full bg-gray-200 flex items-center justify-center text-2xl text-gray-400 font-medium';
                placeholder.textContent = name.slice(0, 2).toUpperCase();
                parent.insertBefore(placeholder, target);
              }
            }}
          />
        ) : (
          <div className="w-full h-full bg-gray-200 flex items-center justify-center text-2xl text-gray-400 font-medium">
            {name.slice(0, 2).toUpperCase()}
          </div>
        )}
      </div>

      {/* Content section - flex grow with fixed padding */}
      <div className="flex-1 min-h-0 p-2 sm:p-3 flex flex-col">
        {/* Name section - up to 2 lines */}
        <div>
          <h3 className="font-medium text-gray-900 text-xs sm:text-sm leading-4 sm:leading-5 line-clamp-2" title={name}>
            {name}
          </h3>
        </div>

        {/* Course section - fixed height for 1 line (hidden on very small cards) */}
        <div className="hidden sm:block h-5 mt-1">
          <p className="text-xs text-gray-500 truncate" title={course}>
            {course || ' '}
          </p>
        </div>

        {/* Price section - pushed to bottom */}
        <div className="mt-auto pt-1 sm:pt-2">
          <span className="text-xs sm:text-sm font-semibold text-gray-900 tabular-nums">
            {formatCurrency(price)}
          </span>
        </div>
      </div>
    </div>
  );
};

export default MenuCard; 