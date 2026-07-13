import { useEffect, useState } from 'react';
import { Download, X, Share, Plus } from 'lucide-react';

/**
 * Smart PWA install prompt. Shows ONLY on mobile / tablet, only when the app
 * isn't already installed, and only once (dismissal is remembered).
 *
 *  - Android / Chromium: captures the `beforeinstallprompt` event and offers
 *    a one-tap "Install app" button that fires the native install dialog.
 *  - iOS Safari: no `beforeinstallprompt`, so we show a short "Add to Home
 *    Screen" hint (Share → Add to Home Screen) instead.
 */

const DISMISS_KEY = 'ury_pwa_install_dismissed';

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
};

function isStandalone(): boolean {
  return (
    window.matchMedia?.('(display-mode: standalone)').matches ||
    // iOS Safari
    (window.navigator as unknown as { standalone?: boolean }).standalone === true
  );
}

function isIos(): boolean {
  const ua = navigator.userAgent;
  return (
    /iPhone|iPad|iPod/.test(ua) ||
    // iPadOS 13+ reports as Macintosh but is touch-capable.
    (navigator.maxTouchPoints > 1 && /Macintosh/.test(ua))
  );
}

function isMobileOrTablet(): boolean {
  const ua = navigator.userAgent;
  return (
    /Android|iPhone|iPad|iPod|Mobile|Tablet|Silk|Kindle|PlayBook/i.test(ua) ||
    isIos() ||
    // Coarse pointer (touch) + smaller viewport → treat as tablet/mobile.
    (window.matchMedia?.('(pointer: coarse)').matches && window.innerWidth < 1280)
  );
}

const InstallPrompt = () => {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [visible, setVisible] = useState(false);
  const [iosHint, setIosHint] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (isStandalone() || !isMobileOrTablet()) return;
    try {
      if (localStorage.getItem(DISMISS_KEY)) return;
    } catch {
      /* ignore */
    }

    const onBeforeInstall = (e: Event) => {
      e.preventDefault();
      setDeferred(e as BeforeInstallPromptEvent);
      setIosHint(false);
      setVisible(true);
    };
    const onInstalled = () => {
      setVisible(false);
      try {
        localStorage.setItem(DISMISS_KEY, '1');
      } catch {
        /* ignore */
      }
    };
    window.addEventListener('beforeinstallprompt', onBeforeInstall);
    window.addEventListener('appinstalled', onInstalled);

    // iOS has no beforeinstallprompt — show the manual hint after a beat so
    // it doesn't flash on first paint.
    let iosTimer: ReturnType<typeof setTimeout> | undefined;
    if (isIos()) {
      iosTimer = setTimeout(() => {
        setIosHint(true);
        setVisible(true);
      }, 1800);
    }

    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstall);
      window.removeEventListener('appinstalled', onInstalled);
      if (iosTimer) clearTimeout(iosTimer);
    };
  }, []);

  const remember = () => {
    try {
      localStorage.setItem(DISMISS_KEY, '1');
    } catch {
      /* ignore */
    }
  };

  const dismiss = () => {
    setVisible(false);
    remember();
  };

  const install = async () => {
    if (!deferred) return;
    await deferred.prompt();
    await deferred.userChoice.catch(() => undefined);
    setDeferred(null);
    setVisible(false);
    remember();
  };

  if (!visible) return null;

  return (
    <div className="fixed inset-x-0 bottom-0 z-[60] p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pointer-events-none">
      <div className="mx-auto max-w-sm rounded-2xl bg-white shadow-2xl border border-gray-200 p-3 flex items-center gap-3 pointer-events-auto">
        <div className="h-10 w-10 shrink-0 rounded-xl bg-blue-600 text-white flex items-center justify-center">
          <Download className="w-5 h-5" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-gray-900">Install ExPOS</p>
          {iosHint ? (
            <p className="text-xs text-gray-500 leading-snug mt-0.5 flex items-center flex-wrap gap-x-1">
              Tap <Share className="inline w-3.5 h-3.5 text-blue-600" /> then
              <span className="inline-flex items-center gap-0.5">
                <Plus className="w-3 h-3" /> Add to Home Screen
              </span>
            </p>
          ) : (
            <p className="text-xs text-gray-500 leading-snug mt-0.5">
              Add it to your home screen for a faster, full-screen experience.
            </p>
          )}
        </div>
        {!iosHint && (
          <button
            type="button"
            onClick={install}
            className="shrink-0 px-3 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold active:bg-blue-700"
          >
            Install
          </button>
        )}
        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss"
          className="shrink-0 h-8 w-8 rounded-md text-gray-400 hover:bg-gray-100 flex items-center justify-center"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};

export default InstallPrompt;
