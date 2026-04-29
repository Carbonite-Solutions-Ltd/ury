import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Footer from './components/Footer';
import Header from './components/Header';
import Orders from './pages/Orders';
import POS from './pages/POS';
import Table from './pages/Table';
import Reports from './pages/Reports';
import Notifications from './pages/Notifications';
import BiometricEnrollment from './pages/BiometricEnrollment';
import BiometricLogin from './pages/BiometricLogin';
import AuthGuard from './components/AuthGuard';
import POSOpeningProvider from './components/POSOpeningProvider';
import ShiftHoursBanner from './components/ShiftHoursBanner';
import ScreenSizeProvider from './components/ScreenSizeProvider';
import { ToastProvider } from './components/ui/toast';
import { usePOSStore } from './store/pos-store';
import { useEffect, useState } from 'react';
import { setupKotListener } from './lib/kot-listener';
import { initPosDisplay, destroyPosDisplay } from './lib/pos-display';
import {
  getSavedTerminal,
  saveTerminal,
  getTerminalConfig,
  getTerminals,
  TerminalConfig,
} from './lib/terminal-api';
import { getLoggedUser, logout } from './lib/auth-api';
import {
  getBrowserPosition,
  getGeofenceConfig,
  validateGeofence,
} from './lib/geofence-api';
import { Monitor, MapPin, LogIn, MapPinOff, ShieldAlert } from 'lucide-react';
import { extractFrappeServerError } from './lib/utils';


function App() {
  const { initializeApp, setTerminalConfig } = usePOSStore();
  const [terminal, setTerminal] = useState<TerminalConfig | null>(null);
  const [terminalError, setTerminalError] = useState<string | null>(null);
  const [terminalLoading, setTerminalLoading] = useState(true);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [isGuest, setIsGuest] = useState(false);
  const [geofenceChecking, setGeofenceChecking] = useState(false);
  const [geofenceError, setGeofenceError] = useState<string | null>(null);
  const [geofencePassed, setGeofencePassed] = useState(false);
  const [geofenceAttempt, setGeofenceAttempt] = useState(0);

  // Pre-flight auth check. Before touching any whitelisted endpoint
  // we ask Frappe "who am I?" via the guest-safe
  // `frappe.auth.get_logged_user`. If the answer is "Guest" we short-
  // circuit the whole app into the unauthenticated landing screen so
  // the cashier sees a clean "Sign in to continue" button instead of
  // the raw "Function ury.ury_pos.api.get_terminals is not whitelisted"
  // error that used to surface when Guest hit the terminal-setup
  // screen. The redirect brings the user back to /pos after login.
  useEffect(() => {
    (async () => {
      try {
        const u = await getLoggedUser();
        setIsGuest(!u || u === 'Guest');
      } catch {
        setIsGuest(true);
      } finally {
        setAuthChecked(true);
      }
    })();
  }, []);

  // Resolve terminal: check localStorage first, then validate with server
  useEffect(() => {
    if (!authChecked || isGuest) return;
    const resolve = async () => {
      const saved = getSavedTerminal();

      if (saved) {
        try {
          const config = await getTerminalConfig(saved);
          setTerminal(config);
          setTerminalConfig(config);
          sessionStorage.removeItem('posProfile');
          sessionStorage.removeItem('menuCategories');
        } catch {
          // Saved terminal no longer valid — show setup
          setNeedsSetup(true);
        }
      } else {
        // No saved terminal — show setup
        setNeedsSetup(true);
      }

      setTerminalLoading(false);
    };

    resolve();
  }, [authChecked, isGuest, setTerminalConfig]);

  // Geofence check — runs once, right after the terminal resolves
  // and before we boot the rest of the app. When the POS Profile has
  // `custom_geofence_enabled = 0` the backend returns `{enabled: 0}`
  // and we skip the whole flow (no browser permission prompt shown).
  // When enabled, we ask the browser for a GPS fix, POST it to the
  // backend, and block the POS if the user is too far from the
  // allowed coordinates. See CLAUDE.md "Fixes log" 2026-04-10.
  useEffect(() => {
    if (!terminal || geofencePassed) return;
    let cancelled = false;
    setGeofenceChecking(true);
    setGeofenceError(null);
    (async () => {
      try {
        const cfg = await getGeofenceConfig(terminal.terminal);
        if (cancelled) return;
        if (!cfg.enabled) {
          setGeofencePassed(true);
          return;
        }
        // Feature is on — ask the browser for a position.
        const pos = await getBrowserPosition();
        if (cancelled) return;
        await validateGeofence(
          pos.coords.latitude,
          pos.coords.longitude,
          terminal.terminal
        );
        if (cancelled) return;
        setGeofencePassed(true);
      } catch (err) {
        if (cancelled) return;
        // ValidationError from the backend flows through the standard
        // frappe-js-sdk error pipeline; native browser errors come
        // through getBrowserPosition with plain-string messages.
        const parsed = extractFrappeServerError(
          err,
          (err as Error)?.message || 'Failed to verify your location.'
        );
        setGeofenceError(parsed.message);
      } finally {
        if (!cancelled) setGeofenceChecking(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [terminal, geofencePassed, geofenceAttempt]);

  // Initialize app once terminal is resolved AND geofence passed.
  useEffect(() => {
    if (terminal && geofencePassed) {
      initializeApp();
      setupKotListener();
      initPosDisplay();
      return () => {
        destroyPosDisplay();
      };
    }
  }, [initializeApp, terminal, geofencePassed]);

  const handleTerminalSelected = async (terminalName: string) => {
    try {
      const config = await getTerminalConfig(terminalName);
      saveTerminal(terminalName);
      setTerminal(config);
      setTerminalConfig(config);
      setNeedsSetup(false);
      sessionStorage.clear();
    } catch (err: any) {
      let msg = 'Failed to load terminal.';
      if (err?._server_messages) {
        try {
          const messages = JSON.parse(err._server_messages);
          const parsed = JSON.parse(messages[0]);
          msg = parsed.message;
        } catch { /* use default */ }
      }
      setTerminalError(msg);
    }
  };

  if (!authChecked) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="text-gray-400 animate-pulse">Checking session…</div>
      </div>
    );
  }

  if (isGuest) {
    return <BiometricLogin terminalName={terminal?.terminal ?? null} />;
  }

  if (terminalLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="text-gray-400 animate-pulse">Loading terminal...</div>
      </div>
    );
  }

  if (terminalError) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="max-w-md w-full mx-4 bg-white rounded-2xl shadow-lg p-8 text-center">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-red-50 mb-4">
            <Monitor className="w-8 h-8 text-red-500" />
          </div>
          <h2 className="text-xl font-bold text-gray-900 mb-2">Terminal Error</h2>
          <p className="text-gray-600">{terminalError}</p>
        </div>
      </div>
    );
  }

  if (needsSetup) {
    return <TerminalSetupScreen onSelect={handleTerminalSelected} />;
  }

  if (terminal && geofenceChecking && !geofencePassed) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="max-w-md w-full mx-4 bg-white rounded-2xl shadow-lg p-8 text-center">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-blue-50 mb-4">
            <MapPin className="w-8 h-8 text-blue-600 animate-pulse" />
          </div>
          <h2 className="text-xl font-bold text-gray-900 mb-2">
            Verifying Your Location
          </h2>
          <p className="text-gray-600 text-sm">
            Please allow location access in your browser so we can confirm
            you're on site. This only happens once per session.
          </p>
        </div>
      </div>
    );
  }

  if (terminal && geofenceError && !geofencePassed) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="max-w-md w-full mx-4 bg-white rounded-2xl shadow-lg p-8 text-center">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-red-50 mb-4">
            <ShieldAlert className="w-8 h-8 text-red-600" />
          </div>
          <h2 className="text-xl font-bold text-gray-900 mb-2">
            Location Check Failed
          </h2>
          <p className="text-gray-600 text-sm mb-6">{geofenceError}</p>
          <div className="flex items-center gap-3 justify-center">
            <button
              onClick={() => setGeofenceAttempt((n) => n + 1)}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-lg transition-colors flex items-center gap-2"
            >
              <MapPinOff className="w-4 h-4" />
              Try Again
            </button>
            <button
              onClick={async () => {
                try {
                  await logout();
                } finally {
                  // Land on /pos as guest → App.tsx renders BiometricLogin
                  window.location.href = '/pos';
                }
              }}
              className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-semibold rounded-lg transition-colors"
            >
              Sign Out
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      <ToastProvider />
      <ScreenSizeProvider>
        <AuthGuard>
          <POSOpeningProvider>
            <Router basename="/pos">
              <div className="flex flex-col h-screen bg-gray-100 font-inter">
                {/* Shift banner sits inside the flex column so it
                    takes its natural height and the rest of the
                    layout shrinks to fit. Mounting it at the
                    POSOpeningProvider level used to drop it
                    OUTSIDE the h-screen container, pushing the
                    Footer below the viewport. */}
                <ShiftHoursBanner />
                <Header />
                <div className="flex-1 overflow-hidden">
                  <Routes>
                    <Route path="/" element={<POS />} />
                    <Route path="/orders" element={<Orders />} />
                    <Route path="/table" element={<Table />} />
                    <Route path="/reports" element={<Reports />} />
                    <Route path="/notifications" element={<Notifications />} />
                    <Route path="/biometric-enrollment" element={<BiometricEnrollment />} />
                  </Routes>
                </div>
                <Footer />
              </div>
            </Router>
          </POSOpeningProvider>
        </AuthGuard>
      </ScreenSizeProvider>
    </>
  );
}


/**
 * One-time device registration screen.
 * Fetches available terminals from the server and lets admin pick one.
 */
function TerminalSetupScreen({ onSelect }: { onSelect: (terminal: string) => void }) {
  const [terminals, setTerminals] = useState<TerminalConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    getTerminals()
      .then((list) => {
        // Normalize: frappe.get_all returns 'name' for the terminal ID, and
        // also carries pos_profile so the setup screen can show which
        // profile each terminal is bound to and flag unconfigured ones.
        const normalized = list.map((t: any) => ({
          terminal: t.terminal || t.name,
          room: t.room,
          branch: t.branch,
          description: t.description,
          pos_profile: t.pos_profile,
        }));
        setTerminals(normalized);
        setLoading(false);
      })
      .catch((err) => {
        // Surface the actual server message (e.g. "Your user is not
        // linked to any Branch...") instead of a generic catchall.
        // See CLAUDE.md "Fixes log" 2026-04-09.
        const parsed = extractFrappeServerError(
          err,
          'Failed to load terminals. Check your connection and user permissions.'
        );
        setError(parsed.message);
        setLoading(false);
      });
  }, []);

  const handleConfirm = async () => {
    if (!selected) return;
    setConfirming(true);
    await onSelect(selected);
    setConfirming(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="text-gray-400 animate-pulse">Loading terminals...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="max-w-md w-full mx-4 bg-white rounded-2xl shadow-lg p-8 text-center">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-red-50 mb-4">
            <Monitor className="w-8 h-8 text-red-500" />
          </div>
          <h2 className="text-xl font-bold text-gray-900 mb-2">Setup Error</h2>
          <p className="text-gray-600">{error}</p>
        </div>
      </div>
    );
  }

  if (terminals.length === 0) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="max-w-md w-full mx-4 bg-white rounded-2xl shadow-lg p-8 text-center">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-amber-50 mb-4">
            <Monitor className="w-8 h-8 text-amber-500" />
          </div>
          <h2 className="text-xl font-bold text-gray-900 mb-2">No Terminals Available</h2>
          <p className="text-gray-600">
            No POS Terminals have been created yet. Ask your administrator to create terminals in the back office under <strong>ExPOS POS Terminal</strong>.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50">
      <div className="max-w-lg w-full mx-4">
        <div className="bg-white rounded-2xl shadow-lg p-8">
          {/* Header */}
          <div className="text-center mb-8">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-blue-50 mb-4">
              <Monitor className="w-8 h-8 text-blue-600" />
            </div>
            <h1 className="text-2xl font-bold text-gray-900">Register This Device</h1>
            <p className="text-gray-500 mt-2">
              Select which POS terminal this device will be. This is a one-time setup.
            </p>
          </div>

          {/* Terminal list */}
          <div className="space-y-3 mb-8">
            {terminals.map((t) => {
              const unconfigured = !t.pos_profile;
              const isSelected = selected === t.terminal;
              return (
                <button
                  key={t.terminal}
                  onClick={() => !unconfigured && setSelected(t.terminal)}
                  disabled={unconfigured}
                  title={
                    unconfigured
                      ? 'This terminal has no POS Profile set. Open it in the desk and link a POS Profile before using it.'
                      : undefined
                  }
                  className={`w-full flex items-center gap-4 p-4 rounded-xl border-2 transition-all text-left ${
                    unconfigured
                      ? 'border-gray-200 bg-gray-50 opacity-60 cursor-not-allowed'
                      : isSelected
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                  }`}
                >
                  <div
                    className={`flex items-center justify-center w-10 h-10 rounded-lg shrink-0 ${
                      isSelected
                        ? 'bg-blue-500 text-white'
                        : 'bg-gray-100 text-gray-500'
                    }`}
                  >
                    <MapPin className="w-5 h-5" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div
                      className={`font-semibold truncate ${
                        isSelected ? 'text-blue-700' : 'text-gray-900'
                      }`}
                    >
                      {t.terminal}
                    </div>
                    <div className="text-sm text-gray-500 truncate">
                      {t.room}
                      {t.branch && ` · ${t.branch}`}
                    </div>
                    {t.pos_profile ? (
                      <div className="text-xs text-gray-400 truncate mt-0.5">
                        POS Profile: {t.pos_profile}
                      </div>
                    ) : (
                      <div className="text-xs text-red-500 truncate mt-0.5">
                        Not configured — no POS Profile linked
                      </div>
                    )}
                    {t.description && (
                      <div className="text-xs text-gray-400 italic truncate mt-0.5">
                        {t.description}
                      </div>
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Confirm */}
          <button
            onClick={handleConfirm}
            disabled={!selected || confirming}
            className={`w-full py-3 text-base font-medium rounded-lg transition-colors ${
              selected && !confirming
                ? 'bg-blue-600 text-white hover:bg-blue-700'
                : 'bg-gray-200 text-gray-400 cursor-not-allowed'
            }`}
          >
            {confirming ? 'Setting up...' : 'Register Terminal'}
          </button>

          <p className="text-xs text-gray-400 text-center mt-4">
            This setting is saved on this device. To change it, use "Change Terminal" from the user menu.
          </p>
        </div>
      </div>
    </div>
  );
}

/* UnauthenticatedLanding was the old "Sign in to continue" card that
 * deep-linked to Frappe's /login. Replaced by `<BiometricLogin>` in
 * the isGuest branch above (Phase 3 of the biometric rollout). */

export default App;
