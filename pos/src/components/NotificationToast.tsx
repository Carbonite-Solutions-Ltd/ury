import { useEffect, useState } from 'react';
import { CheckCircle, X } from 'lucide-react';
import { formatCurrency } from '../lib/utils';

interface NotificationToastProps {
  notification: {
    invoice: string;
    customer_name: string;
    restaurant_table: string | null;
    grand_total: number;
    items_list: string;
    items_count: number;
  } | null;
  onClose: () => void;
}

export default function NotificationToast({ notification, onClose }: NotificationToastProps) {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    if (notification) {
      setIsVisible(true);
      
      // Auto-hide after 5 seconds
      const timer = setTimeout(() => {
        setIsVisible(false);
        setTimeout(onClose, 300); // Wait for fade animation
      }, 5000);

      return () => clearTimeout(timer);
    }
  }, [notification, onClose]);

  if (!notification) return null;

  return (
    <div
      className={`fixed top-20 right-6 z-50 transition-all duration-300 ${
        isVisible ? 'translate-x-0 opacity-100' : 'translate-x-full opacity-0'
      }`}
    >
      <div className="bg-white rounded-lg shadow-2xl border-2 border-green-500 p-4 w-80">
        <div className="flex items-start gap-3">
          {/* Icon */}
          <div className="flex-shrink-0 w-10 h-10 rounded-full bg-green-100 flex items-center justify-center">
            <CheckCircle className="w-6 h-6 text-green-600" />
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between mb-1">
              <h3 className="text-sm font-bold text-gray-900">Order Ready!</h3>
              <button
                onClick={() => {
                  setIsVisible(false);
                  setTimeout(onClose, 300);
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <p className="text-xs text-gray-600 mb-2">
              {notification.invoice}
              {notification.restaurant_table && ` • Table ${notification.restaurant_table}`}
            </p>

            <div className="bg-gray-50 rounded p-2 mb-2">
              <p className="text-xs text-gray-700 font-medium mb-1">
                {notification.items_count} item(s):
              </p>
              <p className="text-xs text-gray-600 line-clamp-2">
                {notification.items_list}
              </p>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-500">{notification.customer_name}</span>
              <span className="text-sm font-bold text-gray-900">
                {formatCurrency(notification.grand_total)}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
