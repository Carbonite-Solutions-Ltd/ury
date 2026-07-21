import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import './lib/qz-init';
import { setupKotListener } from './lib/kot-listener';
import { registerServiceWorker } from './lib/register-sw';
import { initConnectivityWatch } from './lib/connectivity';

// Offline PWA (Phase A): cache the app shell + boot data so the POS loads
// with no internet, and watch connectivity so the offline banner/alert
// can fire. Both are safe no-ops in dev / non-secure contexts.
registerServiceWorker();
initConnectivityWatch();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)