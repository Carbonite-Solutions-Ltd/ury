/*
 * Offline banner (Phase A offline support).
 *
 * A persistent bar shown whenever the connectivity watcher reports the
 * device is offline, plus a toast on each online/offline transition so
 * the waiter gets an unmissable heads-up. It lives as a flex child in
 * App.tsx's h-[100dvh] column (next to ShiftHoursBanner) so it takes its
 * natural height and the rest of the layout shrinks around it — the same
 * pattern as ShiftHoursBanner.
 *
 * Phase A is read-only offline: the copy makes clear that orders can't
 * reach the kitchen until the connection is back. Placing/queueing an
 * order offline is Phase B.
 */
import { useEffect, useRef } from 'react';
import { WifiOff } from 'lucide-react';
import { useConnectivity } from '../lib/connectivity';
import { showToast } from './ui/toast';

const OfflineBanner = () => {
  const online = useConnectivity((s) => s.online);
  const prevOnline = useRef(online);

  useEffect(() => {
    if (prevOnline.current === online) return;
    if (online) {
      showToast.success('Back online — orders can be sent again.');
    } else {
      showToast.error({
        title: "You're offline",
        description:
          "Orders can't be sent to the kitchen until the connection is back. You can still browse.",
      });
    }
    prevOnline.current = online;
  }, [online]);

  if (online) return null;

  return (
    <div
      role="alert"
      className="shrink-0 w-full bg-gray-800 text-white shadow z-30"
    >
      <div className="mx-auto max-w-screen-xl flex items-center gap-3 px-4 py-2 text-sm">
        <WifiOff className="w-4 h-4 shrink-0" />
        <div className="flex-1 min-w-0">
          <span className="font-semibold">You're offline.</span>{' '}
          <span className="opacity-90">
            Orders can't be sent to the kitchen until the connection is back —
            you can still browse the menu and open orders.
          </span>
        </div>
      </div>
    </div>
  );
};

export default OfflineBanner;
