import { NavLink } from 'react-router-dom';
import {
  LayoutGrid,
  ClipboardList,
  Table,
  Bell,
  Users,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useEffect, useRef, useState } from 'react';
import { call } from '../lib/frappe-sdk';
import NotificationToast from './NotificationToast';
import { BarChart3 } from 'lucide-react';
import { getWaiterPendingOrderCount } from '../lib/waiter-api';
import { usePOSStore } from '../store/pos-store';
import { useRootStore } from '../store/root-store';
import type { RootState } from '../store/root-store';
import { isWaiterOnly } from '../lib/role-utils';
import { primeAlertAudio, playAlertSound, vibrateAlert } from '../lib/alert-feedback';

// @ts-ignore
const socket = window.frappe?.socketio || null;

const Footer = () => {
  const [notificationCount, setNotificationCount] = useState(0);
  const [waiterPendingCount, setWaiterPendingCount] = useState(0);
  const [currentNotification, setCurrentNotification] = useState<any>(null);
  // The Waiters tab only exists when the POS Profile uses waiters.
  const useWaiter = usePOSStore((s) => s.posProfile?.custom_use_waiter === 1);
  // A waiter-only user gets a trimmed nav (no Reports / Waiters).
  const user = useRootStore((state: RootState) => state.user);
  const waiterMode = isWaiterOnly(user);

  // Poll-based served-order detection. The KDS triggers its sound off a
  // poll like this; we do the same so the alert doesn't depend on the
  // realtime socket (which can be flaky in the PWA). Tracks the served
  // invoices seen so far; a genuinely NEW one (after the first poll) fires
  // sound + vibration. The realtime handler shares this set so the two
  // paths don't double-alert. 2026-07-15.
  const seenServedRef = useRef<Set<string>>(new Set());
  const notifInitRef = useRef(false);

  const alertServed = (data: any) => {
    setCurrentNotification(data);
    playAlertSound();
    vibrateAlert();
  };

  const fetchWaiterPendingCount = async () => {
    setWaiterPendingCount(await getWaiterPendingOrderCount());
  };

  useEffect(() => {
    // Fetch notification count on mount
    fetchNotificationCount();

    // Poll every 15s. Doubles as the served-order sound trigger (KDS-style)
    // so the alert survives a flaky realtime socket. 2026-07-15.
    const interval = setInterval(fetchNotificationCount, 15000);

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

  // Unlock the audio alert on the first user interaction. Browsers block
  // audio until the user has gestured; priming here means the served-order
  // beep actually plays when it fires later. 2026-07-15.
  useEffect(() => {
    const prime = () => primeAlertAudio();
    window.addEventListener('pointerdown', prime, { once: true });
    window.addEventListener('keydown', prime, { once: true });
    return () => {
      window.removeEventListener('pointerdown', prime);
      window.removeEventListener('keydown', prime);
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
    // Dedup with the poll: skip if we've already alerted for this order.
    if (data?.invoice && seenServedRef.current.has(data.invoice)) return;
    if (data?.invoice) seenServedRef.current.add(data.invoice);
    setNotificationCount(prev => prev + 1);
    alertServed(data);
  };

  const fetchNotificationCount = async () => {
    try {
      const response = await call.get('ury.ury_pos.api.get_kitchen_notifications');
      const notifications = (response.message || []) as any[];
      setNotificationCount(notifications.length);

      // Fallback trigger (KDS-style): if a served order appears that we
      // hadn't seen on the previous poll, alert. Skipped on the very first
      // poll so we don't blast for every pre-existing served order at load.
      const currentIds = new Set(notifications.map((n) => n.invoice));
      if (notifInitRef.current) {
        const fresh = notifications.find(
          (n) => n.invoice && !seenServedRef.current.has(n.invoice)
        );
        if (fresh) alertServed(fresh);
      }
      seenServedRef.current = currentIds;
      notifInitRef.current = true;
    } catch (error) {
      console.error('Failed to fetch notification count:', error);
    }
  };

  const closeToast = () => {
    setCurrentNotification(null);
  };

  // Waiter-only users get a focused 4-tab nav: place orders, tables, their
  // own orders, and kitchen alerts. Everyone else sees the full cashier nav.
  const navItems = waiterMode
    ? [
        { icon: LayoutGrid, label: 'POS', path: '/' },
        { icon: Table, label: 'Tables', path: '/table' },
        { icon: ClipboardList, label: 'My Orders', path: '/orders' },
        { icon: Bell, label: 'Alerts', path: '/notifications', badge: notificationCount },
      ]
    : [
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
