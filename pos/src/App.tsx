import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Footer from './components/Footer';
import Header from './components/Header';
import Orders from './pages/Orders';
import POS from './pages/POS';
import Table from './pages/Table';
import Reports from './pages/Reports';
import Notifications from './pages/Notifications';
import AuthGuard from './components/AuthGuard';
import POSOpeningProvider from './components/POSOpeningProvider';
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
import { Monitor, MapPin } from 'lucide-react';
import { extractFrappeServerError } from './lib/utils';


function App() {
  const { initializeApp, setTerminalConfig } = usePOSStore();
  const [terminal, setTerminal] = useState<TerminalConfig | null>(null);
  const [terminalError, setTerminalError] = useState<string | null>(null);
  const [terminalLoading, setTerminalLoading] = useState(true);
  const [needsSetup, setNeedsSetup] = useState(false);

  // Resolve terminal: check localStorage first, then validate with server
  useEffect(() => {
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
  }, [setTerminalConfig]);

  // Initialize app once terminal is resolved
  useEffect(() => {
    if (terminal) {
      initializeApp();
      setupKotListener();
      initPosDisplay();
      return () => {
        destroyPosDisplay();
      };
    }
  }, [initializeApp, terminal]);

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

  return (
    <>
      <ToastProvider />
      <ScreenSizeProvider>
        <AuthGuard>
          <POSOpeningProvider>
            <Router basename="/pos">
              <div className="flex flex-col h-screen bg-gray-100 font-inter">
                <Header />
                <div className="flex-1 overflow-hidden">
                  <Routes>
                    <Route path="/" element={<POS />} />
                    <Route path="/orders" element={<Orders />} />
                    <Route path="/table" element={<Table />} />
                    <Route path="/reports" element={<Reports />} />
                    <Route path="/notifications" element={<Notifications />} />
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

export default App;
