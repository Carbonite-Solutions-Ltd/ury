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
import { getKitchenChangeRequests } from '../lib/kitchen-change-api';

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
  // Mirror of notificationCount for the recurring-reminder interval (avoids
  // a stale closure). 2026-07-16.
  const notifCountRef = useRef(0);

  /** Sound + haptic only (used for held-order alerts, which have no toast). */
  const ring = () => {
    playAlertSound();
    vibrateAlert();
  };

  const alertServed = (data: any) => {
    setCurrentNotification(data);
    ring();
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

    // The kitchen un-served an order (reinstate). Clearing the invoice's
    // status server-side is only half of it — without this the waiter's
    // Orders list keeps its "Served" badge until she happens to refetch.
    // Refresh the count AND the orders list so the badge goes with it.
    // 2026-08-24.
    const handleUnserved = () => {
      fetchNotificationCount();
      // Refetches with whatever filters are currently set; harmless when
      // the Orders page isn't mounted.
      useRootStore.getState().fetchOrders().catch(() => {
        /* transient — the 15s poll and the next visit will catch up */
      });
    };

    // Listen for realtime notifications
    if (socket) {
      socket.on('order_served_notification', handleNewNotification);
      socket.on('order_unserved_notification', handleUnserved);
    }

    return () => {
      clearInterval(interval);
      if (socket) {
        socket.off('order_served_notification', handleNewNotification);
        socket.off('order_unserved_notification', handleUnserved);
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

  // Keep the ref in sync so the recurring reminder reads the live count.
  useEffect(() => {
    notifCountRef.current = notificationCount;
  }, [notificationCount]);

  // Recurring reminder: while there are un-served kitchen notifications,
  // re-ring the sound + vibration every 30s until the user clears them
  // (taps "Served" on the Alerts page → the count drops to 0 and this
  // stops on the next tick). Runs globally so the reminder follows the
  // user wherever they are in the POS. 2026-07-16; shortened from 60s to
  // 30s on 2026-08-24 — a minute is long enough for a waiter to miss the
  // chime over a noisy floor and leave the food sitting under the pass.
  //
  // The 15s notification poll is what raises the count in the first
  // place; this only nags about a count that is already known, so the
  // two intervals are deliberately different and must not be merged.
  useEffect(() => {
    const id = setInterval(() => {
      if (notifCountRef.current > 0) {
        playAlertSound();
        vibrateAlert();
      }
    }, 30000);
    return () => clearInterval(id);
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
      // Kitchen change requests count as alerts too — the order is ON HOLD
      // until the waiter answers, so it must nag like a served order.
      const changes = await getKitchenChangeRequests();
      setNotificationCount(notifications.length + changes.length);

      // Fallback trigger (KDS-style): if a served order or a change request
      // appears that we hadn't seen on the previous poll, alert. Skipped on
      // the very first poll so we don't blast for pre-existing ones at load.
      const currentIds = new Set<string>([
        ...notifications.map((n) => n.invoice),
        ...changes.map((c) => `chg:${c.kot}`),
      ]);
      if (notifInitRef.current) {
        const freshChange = changes.find(
          (c) => !seenServedRef.current.has(`chg:${c.kot}`)
        );
        const freshServed = notifications.find(
          (n) => n.invoice && !seenServedRef.current.has(n.invoice)
        );
        // A held order is the more urgent of the two.
        if (freshChange) ring();
        else if (freshServed) alertServed(freshServed);
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
        { icon: BarChart3, label: 'My Sales', path: '/my-sales' },
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
