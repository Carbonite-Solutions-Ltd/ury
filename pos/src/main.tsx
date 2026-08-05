import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import AppErrorBoundary from './components/AppErrorBoundary'
import './lib/qz-init';
import { registerServiceWorker } from './lib/register-sw';
import { initConnectivityWatch } from './lib/connectivity';
import { initOutbox } from './lib/outbox';

// Offline PWA (Phase A): cache the app shell + boot data so the POS loads
// with no internet, and watch connectivity so the offline banner/alert
// can fire. Both are safe no-ops in dev / non-secure contexts.
registerServiceWorker();
initConnectivityWatch();
// Offline order outbox (Phase B): drain queued orders when connectivity
// returns. Must run after the connectivity watcher is wired.
initOutbox();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/*
      Outside <App /> on purpose: a crash in App's own boot path (terminal
      resolve, geofence gate, POS-opening provider) is exactly the case
      that produced a blank screen, so the boundary has to sit above all
      of it. Anything inside App could go down with it.
    */}
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </StrictMode>,
)