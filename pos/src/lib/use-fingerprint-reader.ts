/**
 * React hook + utilities for the BiometricClient singleton.
 *
 * Usage:
 *   const { state, deviceInfo, capture, enroll, match, debugMessages } =
 *     useFingerprintReader();
 *
 * The hook auto-connects (once enabled) when the client is first
 * instantiated. Pages that don't need the reader (e.g. password-only
 * login screens) can render without the hook — the agent connection
 * is only opened when a component mounts the hook.
 *
 * Underlying transport: HTTP REST against the local URY Finger Agent
 * (default `http://127.0.0.1:9994`). See {@link BiometricClient} for
 * details. The agent must be running on the cashier's PC.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  BiometricClient,
  BiometricConnectionState,
  CaptureResult,
  DebugMessage,
  EnrollProgress,
  EnrollResult,
  MatchResult,
  BiometricDeviceInfo,
  getBiometricClient,
  resetBiometricClient,
} from './biometric-client';
import { getPublicBiometricSettings, PublicBiometricSettings } from './biometric-api';

const MAX_DEBUG_BUFFER = 200;
const DEFAULT_AGENT_URL = 'http://127.0.0.1:9994';

// Module-scoped cache so the public settings endpoint is only called once
// per page load, regardless of how many components mount the hook.
let cachedSettings: PublicBiometricSettings | null = null;
let settingsPromise: Promise<PublicBiometricSettings> | null = null;
function loadPublicSettingsOnce(): Promise<PublicBiometricSettings> {
  if (cachedSettings) return Promise.resolve(cachedSettings);
  if (!settingsPromise) {
    settingsPromise = getPublicBiometricSettings()
      .then((s) => {
        cachedSettings = s;
        return s;
      })
      .catch((err) => {
        settingsPromise = null;
        throw err;
      });
  }
  return settingsPromise;
}

/**
 * Resolves the agent URL to use, with a sensible default.
 *
 * Existing sites may have `issonline_ws_url` set to a `ws://` URL from
 * the previous WebSocket-based architecture. The agent is HTTP, so we
 * silently translate any leftover `ws://` to `http://` and `wss://` to
 * `https://`. If the value is empty or starts with `ws://127.0.0.1:12000`
 * (the old default), we substitute the new default.
 */
function resolveAgentUrl(raw: string | undefined, override: string | undefined): string {
  if (override) return override;
  const value = (raw ?? '').trim();
  if (!value) return DEFAULT_AGENT_URL;
  // Old WebSocket defaults that no longer apply
  if (value === 'ws://127.0.0.1:12000' || value === 'wss://127.0.0.1:12000') {
    return DEFAULT_AGENT_URL;
  }
  if (value.startsWith('ws://')) return 'http://' + value.slice('ws://'.length);
  if (value.startsWith('wss://')) return 'https://' + value.slice('wss://'.length);
  return value;
}

interface UseFingerprintReaderOptions {
  /** When false, the hook will NOT auto-connect. Useful on pages where
   * the reader is only activated after the user picks a username. */
  autoConnect?: boolean;
  /** Override the agent URL (rarely needed — defaults to the URL fetched
   * from URY Biometric Settings, which itself defaults to
   * `http://127.0.0.1:9994`). */
  agentUrlOverride?: string;
  /** Persistent buffer of recent agent messages for the diagnostic panel. */
  debugBufferSize?: number;
}

export interface UseFingerprintReaderResult {
  /** Lifecycle state: disconnected / connecting / connected / capturing / enrolling / error */
  state: BiometricConnectionState;
  /** Site-wide settings (feature toggle + agent URL). */
  settings: PublicBiometricSettings | null;
  /** Is the reader available AND connected? Convenient for gating UI. */
  isReady: boolean;
  /** Last error surfaced (from connect, capture, enroll, or match). */
  error: string | null;
  /** Basic device info populated after handshake. */
  deviceInfo: BiometricDeviceInfo;
  /** Latest enroll progress event (null until enrollment starts). */
  enrollProgress: EnrollProgress | null;
  /** Rolling buffer of agent request/response messages for diagnostic panel. */
  debugMessages: DebugMessage[];
  /** Connect / reconnect manually. Safe to call even if already connected. */
  connect: () => Promise<void>;
  /** Disconnect from the agent + close the device. */
  disconnect: () => void;
  /** Capture a single fingerprint. */
  capture: () => Promise<CaptureResult>;
  /** 3-scan enroll (driver-side merge). */
  enroll: () => Promise<EnrollResult>;
  /** 1:1 match of two templates. */
  match: (args: {
    storedTemplateBase64: string;
    capturedTemplateBase64: string;
  }) => Promise<MatchResult>;
  /** Cancel the current capture/enroll. */
  cancel: () => void;
  /** Clear the current error state. */
  clearError: () => void;
  /** Clear the debug buffer. */
  clearDebug: () => void;
}

export function useFingerprintReader(
  options: UseFingerprintReaderOptions = {}
): UseFingerprintReaderResult {
  const { autoConnect = true, agentUrlOverride, debugBufferSize = MAX_DEBUG_BUFFER } = options;

  const [settings, setSettings] = useState<PublicBiometricSettings | null>(cachedSettings);
  useEffect(() => {
    if (settings) return;
    let alive = true;
    loadPublicSettingsOnce().then(
      (s) => { if (alive) setSettings(s); },
      () => { if (alive) setSettings({ enabled: 0, issonline_ws_url: '' }); }
    );
    return () => { alive = false; };
  }, [settings]);

  const agentUrl = resolveAgentUrl(settings?.issonline_ws_url, agentUrlOverride);
  const enabled = settings?.enabled === 1;

  const clientRef = useRef<BiometricClient | null>(null);
  const [state, setState] = useState<BiometricConnectionState>('disconnected');
  const [error, setError] = useState<string | null>(null);
  const [deviceInfo, setDeviceInfo] = useState<BiometricDeviceInfo>({});
  const [enrollProgress, setEnrollProgress] = useState<EnrollProgress | null>(null);
  const [debugMessages, setDebugMessages] = useState<DebugMessage[]>([]);

  const getClient = useCallback((): BiometricClient | null => {
    if (!enabled) return null;
    if (!clientRef.current) {
      clientRef.current = getBiometricClient(agentUrl);
    }
    return clientRef.current;
  }, [enabled, agentUrl]);

  // Subscribe to client events
  useEffect(() => {
    const client = getClient();
    if (!client) return;
    setState(client.getState());
    setDeviceInfo(client.getDeviceInfo());
    const unsubState = client.onStateChange(setState);
    const unsubDeviceInfo = client.onDeviceInfo(setDeviceInfo);
    const unsubDebug = client.onDebugMessage((msg) => {
      setDebugMessages((prev) => {
        const next = [...prev, msg];
        if (next.length > debugBufferSize) return next.slice(-debugBufferSize);
        return next;
      });
    });
    const unsubProgress = client.onEnrollProgress(setEnrollProgress);
    return () => {
      unsubState();
      unsubDeviceInfo();
      unsubDebug();
      unsubProgress();
    };
  }, [getClient, debugBufferSize]);

  // Auto-connect
  useEffect(() => {
    if (!autoConnect) return;
    const client = getClient();
    if (!client) return;
    client.connect().catch((err) => {
      setError(err instanceof Error ? err.message : String(err));
    });
  }, [autoConnect, getClient]);

  const connect = useCallback(async () => {
    const client = getClient();
    if (!client) {
      throw new Error(
        'Fingerprint reader is not configured. Ask an administrator to enable biometric authentication in URY Biometric Settings.'
      );
    }
    setError(null);
    try {
      await client.connect();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      throw err;
    }
  }, [getClient]);

  const disconnect = useCallback(() => {
    void clientRef.current?.disconnect();
    resetBiometricClient();
    clientRef.current = null;
  }, []);

  const capture = useCallback(async (): Promise<CaptureResult> => {
    const client = getClient();
    if (!client) throw new Error('Fingerprint reader is not configured.');
    setError(null);
    try {
      return await client.capture();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      throw err;
    }
  }, [getClient]);

  const enroll = useCallback(async (): Promise<EnrollResult> => {
    const client = getClient();
    if (!client) throw new Error('Fingerprint reader is not configured.');
    setError(null);
    setEnrollProgress(null);
    try {
      return await client.enroll();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      throw err;
    }
  }, [getClient]);

  const match = useCallback(
    async (args: {
      storedTemplateBase64: string;
      capturedTemplateBase64: string;
    }): Promise<MatchResult> => {
      const client = getClient();
      if (!client) throw new Error('Fingerprint reader is not configured.');
      setError(null);
      try {
        return await client.match(args);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
        throw err;
      }
    },
    [getClient]
  );

  const cancel = useCallback(() => {
    clientRef.current?.cancel();
  }, []);

  const clearError = useCallback(() => setError(null), []);
  const clearDebug = useCallback(() => setDebugMessages([]), []);

  return {
    state,
    settings: settings ?? null,
    isReady: state === 'connected',
    error,
    deviceInfo,
    enrollProgress,
    debugMessages,
    connect,
    disconnect,
    capture,
    enroll,
    match,
    cancel,
    clearError,
    clearDebug,
  };
}
