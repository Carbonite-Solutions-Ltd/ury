import { NavLink } from 'react-router-dom';
import {
  LayoutGrid,
  ClipboardList,
  Table,
  Bell,
  Users,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useEffect, useState } from 'react';
import { call } from '../lib/frappe-sdk';
import NotificationToast from './NotificationToast';
import { BarChart3 } from 'lucide-react';
import { getWaiterPendingOrderCount } from '../lib/waiter-api';
import { usePOSStore } from '../store/pos-store';

// @ts-ignore
const socket = window.frappe?.socketio || null;

const Footer = () => {
  const [notificationCount, setNotificationCount] = useState(0);
  const [waiterPendingCount, setWaiterPendingCount] = useState(0);
  const [currentNotification, setCurrentNotification] = useState<any>(null);
  // The Waiters tab only exists when the POS Profile uses waiters.
  const useWaiter = usePOSStore((s) => s.posProfile?.custom_use_waiter === 1);

  const fetchWaiterPendingCount = async () => {
    setWaiterPendingCount(await getWaiterPendingOrderCount());
  };

  useEffect(() => {
    // Fetch notification count on mount
    fetchNotificationCount();

    // Poll for updates every 30 seconds as backup
    const interval = setInterval(fetchNotificationCount, 30000);

    // Listen for realtime notifications
    if (socket) {
      socket.on('order_served_notification', handleNewNotification);
    }

    return () => {
      clearInterval(interval);
      if (socket) {
        socket.off('order_served_notification', handleNewNotification);
      }
    };
  }, []);

  // Waiter pending-order badge — only when the profile uses waiters.
  useEffect(() => {
    if (!useWaiter) {
      setWaiterPendingCount(0);
      return;
    }
    fetchWaiterPendingCount();
    const interval = setInterval(fetchWaiterPendingCount, 30000);
    return () => clearInterval(interval);
  }, [useWaiter]);

  const handleNewNotification = (data: any) => {
    console.log('🔔 New order served notification:', data);
    
    // Show toast notification
    setCurrentNotification(data);
    
    // Increment count
    setNotificationCount(prev => prev + 1);
    
    // Play notification sound (optional)
    playNotificationSound();
  };

  const playNotificationSound = () => {
    const audio = new Audio('/assets/frappe/sounds/notification.mp3');
    audio.play().catch(err => console.log('Audio play failed:', err));
  };

  const fetchNotificationCount = async () => {
    try {
      const response = await call.get('ury.ury_pos.api.get_kitchen_notifications');
      const notifications = response.message || [];
      setNotificationCount(notifications.length);
    } catch (error) {
      console.error('Failed to fetch notification count:', error);
    }
  };

  const closeToast = () => {
    setCurrentNotification(null);
  };

  const navItems = [
  { icon: LayoutGrid, label: 'POS', path: '/' },
  { icon: Table, label: 'Table', path: '/table' },
  { icon: ClipboardList, label: 'Orders', path: '/orders' },
  ...(useWaiter
    ? [{ icon: Users, label: 'Waiters', path: '/waiters', badge: waiterPendingCount }]
    : []),
  { icon: BarChart3, label: 'Reports', path: '/reports' },
  { icon: Bell, label: 'Alerts', path: '/notifications', badge: notificationCount },

];

  return (
    <>
      <NotificationToast notification={currentNotification} onClose={closeToast} />
      
      <div className="bg-white border-t border-gray-200 py-2 relative">
        <nav className="max-w-screen-xl mx-auto px-1 sm:px-4">
          <div className="flex justify-around sm:justify-center items-center gap-1 sm:gap-4">
            {navItems.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                onClick={() => {
                  // Refresh the relevant badge count on tab change.
                  if (item.path === '/notifications') {
                    fetchNotificationCount();
                  } else if (item.path === '/waiters') {
                    fetchWaiterPendingCount();
                  }
                }}
                className={({ isActive }) =>
                  cn(
                    'flex flex-col items-center px-2 py-1.5 sm:p-2 rounded-lg text-gray-700 hover:bg-gray-100 transition-colors relative min-w-0',
                    isActive && 'text-blue-600'
                  )
                }
              >
                <div className="relative">
                  <item.icon className="w-5 h-5" />
                  {item.badge !== undefined && item.badge > 0 && (
                    <span className="absolute -top-2 -right-2 bg-red-500 text-white text-xs font-bold rounded-full h-5 w-5 flex items-center justify-center animate-pulse">
                      {item.badge > 9 ? '9+' : item.badge}
                    </span>
                  )}
                </div>
                <span className="text-xs mt-1">{item.label}</span>
              </NavLink>
            ))}
          </div>
        </nav>
      </div>
    </>
  );
};

export default Footer;
