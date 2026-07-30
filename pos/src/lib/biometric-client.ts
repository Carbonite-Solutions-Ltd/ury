/**
 * Client for the URY Finger Agent.
 *
 * The URY Finger Agent (ury-finger-agent) is a small local Java HTTP
 * service that runs on each cashier's Windows PC alongside QZ Tray.
 * It wraps the ZKFinger Java SDK and exposes a clean REST API
 * (default `http://127.0.0.1:9994`) that we own end-to-end.
 *
 * <p>This module replaced an earlier WebSocket-based client that
 * tried to talk directly to the vendor's ZKBioOnline / ISSOnline
 * services. Both turned out to be incompatible with modern browsers
 * on this hardware (ZKBioOnline crashes on the matching fingerprint
 * DLLs; ISSOnline's HTTP API is ActiveX-bound and IE-only). Owning
 * the agent let us pick a wire format that just works.
 *
 * <p>Surface mirrors the original WebSocket client so existing UI code
 * (`useFingerprintReader`, `BiometricDiagnosticPanel`,
 * `BiometricEnrollment`) stays identical.
 */

export type BiometricConnectionState =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'capturing'
  | 'enrolling'
  | 'error';

export interface BiometricDeviceInfo {
  serial?: string;
  vendor?: string;
  model?: string;
  driverVersion?: string;
  fpWidth?: number;
  fpHeight?: number;
  /** Raw status snapshot from /status — useful for diagnostics. */
  rawStatus?: Record<string, unknown>;
}

export interface CaptureResult {
  templateBase64: string;
  imageBase64?: string;
  quality?: number;
}

export interface EnrollProgress {
  scanIndex: number; // 1, 2, 3
  total: number; // 3
}

export interface EnrollResult {
  masterTemplateBase64: string;
  scans: CaptureResult[];
}

export interface MatchResult {
  score: number;
  matched: boolean;
}

export interface DebugMessage {
  direction: 'out' | 'in' | 'info' | 'error';
  at: number;
  payload: unknown;
}

export interface BiometricClientOptions {
  /**
   * Base URL of the URY Finger Agent. The agent listens on
   * `http://127.0.0.1:9994` by default. Override only for tests
   * or when an admin reconfigures the agent's port.
   */
  baseUrl: string;
  /** How long to wait for a single fingerprint capture before timing out. */
  captureTimeoutMs?: number;
  /** How long to wait for the 3-scan enrollment to complete. */
  enrollTimeoutMs?: number;
  /** How often to poll the agent during enrollment / capture. */
  pollIntervalMs?: number;
}

type StateListener = (s: BiometricConnectionState) => void;
type DebugListener = (m: DebugMessage) => void;
type DeviceInfoListener = (i: BiometricDeviceInfo) => void;
type EnrollProgressListener = (p: EnrollProgress) => void;

interface AgentEnrollSummary {
  session_id?: string;
  scans_captured?: number;
  scans_required?: number;
  done?: boolean;
  cancelled?: boolean;
  error?: string;
  template_base64?: string;
  template_length?: number;
}

interface AgentCaptureSummary {
  done?: boolean;
  cancelled?: boolean;
  error?: string;
  template_base64?: string;
  template_length?: number;
}

interface AgentStatus {
  opened?: boolean;
  device_handle?: number;
  db_handle?: number;
  fp_width?: number;
  fp_height?: number;
  session?: 'IDLE' | 'ENROLL' | 'CAPTURE';
  enroll?: AgentEnrollSummary;
  capture?: AgentCaptureSummary;
}

interface AgentErrorBody {
  error?: string;
  message?: string;
}

export class AgentError extends Error {
  readonly code: string;
  readonly status: number;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export class BiometricClient {
  private baseUrl: string;
  private captureTimeoutMs: number;
  private enrollTimeoutMs: number;
  private pollIntervalMs: number;

  private state: BiometricConnectionState = 'disconnected';
  private stateListeners = new Set<StateListener>();
  private debugListeners = new Set<DebugListener>();
  private deviceInfoListeners = new Set<DeviceInfoListener>();
  private enrollProgressListeners = new Set<EnrollProgressListener>();
  private deviceInfo: BiometricDeviceInfo = {};

  private currentEnrollAbort: AbortController | null = null;
  private currentCaptureAbort: AbortController | null = null;

  constructor(options: BiometricClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.captureTimeoutMs = options.captureTimeoutMs ?? 25_000;
    this.enrollTimeoutMs = options.enrollTimeoutMs ?? 90_000;
    this.pollIntervalMs = options.pollIntervalMs ?? 350;
  }

  // ------------------------------------------------------------------
  // Subscription API
  // ------------------------------------------------------------------

  onStateChange(fn: StateListener): () => void {
    this.stateListeners.add(fn);
    return () => this.stateListeners.delete(fn);
  }
  onDebugMessage(fn: DebugListener): () => void {
    this.debugListeners.add(fn);
    return () => this.debugListeners.delete(fn);
  }
  onDeviceInfo(fn: DeviceInfoListener): () => void {
    this.deviceInfoListeners.add(fn);
    return () => this.deviceInfoListeners.delete(fn);
  }
  onEnrollProgress(fn: EnrollProgressListener): () => void {
    this.enrollProgressListeners.add(fn);
    return () => this.enrollProgressListeners.delete(fn);
  }

  getState(): BiometricConnectionState { return this.state; }
  getDeviceInfo(): BiometricDeviceInfo { return { ...this.deviceInfo }; }
  getBaseUrl(): string { return this.baseUrl; }

  // ------------------------------------------------------------------
  // Lifecycle: connect = ping agent + open device
  // ------------------------------------------------------------------

  async connect(): Promise<void> {
    if (this.state === 'connected' || this.state === 'capturing' || this.state === 'enrolling') {
      return;
    }
    this.setState('connecting');
    try {
      // Step 1: confirm agent is reachable
      const info = await this.req<Record<string, unknown>>('GET', '/');
      this.log('info', { event: 'agent', detail: info });
      if (typeof info?.version === 'string') {
        this.deviceInfo = {
          ...this.deviceInfo,
          driverVersion: `Agent ${info.version} • Java ${info.java_version ?? '?'}`,
        };
        this.fireDeviceInfo();
      }
      // Step 2: ensure the device is open. If already open this is a no-op.
      const openResp = await this.req<AgentStatus>('POST', '/open');
      this.applyStatus(openResp);
      if (!openResp.opened) {
        throw new AgentError(
          'open_failed',
          'Agent reports the reader is not opened.',
          503
        );
      }
      this.setState('connected');
    } catch (err) {
      this.setState('error');
      this.log('error', { event: 'connect-failed', detail: errorToObject(err) });
      throw err;
    }
  }

  async disconnect(): Promise<void> {
    this.cancel();
    try {
      await this.req('POST', '/close');
    } catch (err) {
      // best-effort
      this.log('error', { event: 'close-failed', detail: errorToObject(err) });
    }
    this.setState('disconnected');
  }

  // ------------------------------------------------------------------
  // Enroll (3-scan)
  // ------------------------------------------------------------------

  async enroll(): Promise<EnrollResult> {
    await this.requireConnected();
    if (this.currentEnrollAbort) {
      throw new Error('An enrollment is already in progress.');
    }
    this.setState('enrolling');
    const abort = new AbortController();
    this.currentEnrollAbort = abort;
    try {
      const start = await this.req<AgentEnrollSummary>('POST', '/enroll/start');
      this.log('info', { event: 'enroll-start', detail: start });
      const sessionId = start.session_id;
      if (!sessionId) throw new Error('Agent did not return an enrollment session_id.');

      const startedAt = Date.now();
      let lastScansCaptured = -1;

      while (!abort.signal.aborted) {
        if (Date.now() - startedAt > this.enrollTimeoutMs) {
          throw new AgentError('timeout', 'Enrollment timed out. Please start over.', 408);
        }
        const summary = await this.req<AgentEnrollSummary>('POST', '/enroll/poll', { session_id: sessionId });
        this.log('info', { event: 'enroll-poll', detail: summary });

        if (summary.cancelled) {
          throw new AgentError('cancelled', summary.error || 'Enrollment cancelled.', 499);
        }
        if (summary.error && !summary.done) {
          // Soft error (different finger, retake) — surface progress but keep polling
          this.log('error', { event: 'enroll-warn', detail: summary.error });
        }
        if (typeof summary.scans_captured === 'number' && summary.scans_captured !== lastScansCaptured) {
          lastScansCaptured = summary.scans_captured;
          this.fireEnrollProgress({
            scanIndex: summary.scans_captured,
            total: summary.scans_required ?? 3,
          });
        }
        if (summary.done && summary.template_base64) {
          return {
            masterTemplateBase64: summary.template_base64,
            scans: [], // agent doesn't expose per-scan templates
          };
        }
        if (summary.done && summary.error) {
          throw new AgentError('enroll_failed', summary.error, 500);
        }
        await sleep(this.pollIntervalMs);
      }
      throw new AgentError('cancelled', 'Enrollment cancelled.', 499);
    } finally {
      this.currentEnrollAbort = null;
      if (this.state === 'enrolling') this.setState('connected');
    }
  }

  // ------------------------------------------------------------------
  // Single capture (verify flow)
  // ------------------------------------------------------------------

  async capture(): Promise<CaptureResult> {
    await this.requireConnected();
    if (this.currentCaptureAbort) {
      throw new Error('A capture is already in progress.');
    }
    this.setState('capturing');
    const abort = new AbortController();
    this.currentCaptureAbort = abort;
    try {
      const start = await this.req<AgentCaptureSummary>('POST', '/capture/start');
      this.log('info', { event: 'capture-start', detail: start });
      const startedAt = Date.now();
      while (!abort.signal.aborted) {
        if (Date.now() - startedAt > this.captureTimeoutMs) {
          throw new AgentError('timeout', 'Capture timed out. Please try again.', 408);
        }
        const summary = await this.req<AgentCaptureSummary>('POST', '/capture/poll');
        if (summary.cancelled) {
          throw new AgentError('cancelled', summary.error || 'Capture cancelled.', 499);
        }
        if (summary.done && summary.template_base64) {
          return {
            templateBase64: summary.template_base64,
          };
        }
        if (summary.done && summary.error) {
          throw new AgentError('capture_failed', summary.error, 500);
        }
        await sleep(this.pollIntervalMs);
      }
      throw new AgentError('cancelled', 'Capture cancelled.', 499);
    } finally {
      this.currentCaptureAbort = null;
      if (this.state === 'capturing') this.setState('connected');
    }
  }

  // ------------------------------------------------------------------
  // 1:1 match
  // ------------------------------------------------------------------

  async match(args: {
    storedTemplateBase64: string;
    capturedTemplateBase64: string;
  }): Promise<MatchResult> {
    await this.requireConnected();
    const r = await this.req<{ score: number; matched: boolean }>('POST', '/verify', {
      template1: args.storedTemplateBase64,
      template2: args.capturedTemplateBase64,
    });
    return { score: r.score, matched: r.matched };
  }

  cancel(): void {
    if (this.currentEnrollAbort) {
      this.currentEnrollAbort.abort();
      this.req('POST', '/enroll/cancel').catch(() => {});
    }
    if (this.currentCaptureAbort) {
      this.currentCaptureAbort.abort();
      this.req('POST', '/capture/cancel').catch(() => {});
    }
  }

  // ------------------------------------------------------------------
  // Internals
  // ------------------------------------------------------------------

  private async requireConnected(): Promise<void> {
    if (
      this.state === 'connected' ||
      this.state === 'capturing' ||
      this.state === 'enrolling'
    ) return;
    await this.connect();
  }

  private async req<T = unknown>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
    const url = this.baseUrl + path;
    const init: RequestInit = { method };
    if (body !== undefined) {
      init.headers = { 'Content-Type': 'application/json' };
      init.body = JSON.stringify(body);
    }
    this.log('out', { method, path, body });
    let resp: Response;
    try {
      resp = await fetch(url, init);
    } catch {
      // Network failure — agent isn't running, port closed, etc.
      throw new AgentError(
        'agent_unreachable',
        `Could not reach URY Finger Agent at ${this.baseUrl}. ` +
          `Make sure ury-finger-agent is running on this PC.`,
        0
      );
    }
    let parsed: unknown = null;
    try {
      const text = await resp.text();
      parsed = text ? JSON.parse(text) : null;
    } catch {
      // non-JSON body — keep as null
    }
    this.log('in', { status: resp.status, path, body: parsed });
    if (!resp.ok) {
      const eb = (parsed as AgentErrorBody) || {};
      throw new AgentError(
        eb.error || `http_${resp.status}`,
        eb.message || `Agent returned HTTP ${resp.status}.`,
        resp.status
      );
    }
    return parsed as T;
  }

  private applyStatus(status: AgentStatus): void {
    if (!status) return;
    this.deviceInfo = {
      ...this.deviceInfo,
      fpWidth: status.fp_width,
      fpHeight: status.fp_height,
      model: this.deviceInfo.model || 'ZK Fingerprint Reader',
      rawStatus: status as unknown as Record<string, unknown>,
    };
    this.fireDeviceInfo();
  }

  private setState(s: BiometricConnectionState): void {
    if (this.state === s) return;
    this.state = s;
    for (const fn of this.stateListeners) fn(s);
  }

  private log(direction: DebugMessage['direction'], payload: unknown): void {
    const m: DebugMessage = { direction, at: Date.now(), payload };
    for (const fn of this.debugListeners) fn(m);
  }

  private fireDeviceInfo(): void {
    for (const fn of this.deviceInfoListeners) fn(this.getDeviceInfo());
  }

  private fireEnrollProgress(p: EnrollProgress): void {
    for (const fn of this.enrollProgressListeners) fn(p);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function errorToObject(err: unknown): Record<string, unknown> {
  if (err instanceof AgentError) {
    return { type: 'AgentError', code: err.code, status: err.status, message: err.message };
  }
  if (err instanceof Error) {
    return { type: err.name, message: err.message };
  }
  return { value: String(err) };
}

// ---------------------------------------------------------------------------
// Singleton + helpers (kept for backwards-compat with existing imports)
// ---------------------------------------------------------------------------

let singleton: BiometricClient | null = null;

export function getBiometricClient(baseUrl?: string): BiometricClient {
  if (!singleton) {
    if (!baseUrl) {
      throw new Error('BiometricClient must be initialised with a base URL first.');
    }
    singleton = new BiometricClient({ baseUrl });
  } else if (baseUrl && (singleton as unknown as { baseUrl: string }).baseUrl !== baseUrl) {
    singleton.disconnect().catch(() => {});
    singleton = new BiometricClient({ baseUrl });
  }
  return singleton;
}

export function resetBiometricClient(): void {
  if (singleton) {
    singleton.disconnect().catch(() => {});
    singleton = null;
  }
}

// Legacy WebSocket-based protocol adapter API — kept as exports so any
// stray imports still type-check, but they're deprecated and no-op.
export interface ProtocolAdapter {
  handshake(send: (msg: object) => void): void;
  dispatch(raw: unknown, ctx: unknown): boolean;
  requestCapture(send: (msg: object) => void): void;
  requestEnroll(send: (msg: object) => void): boolean;
  requestMatch(send: (msg: object) => void, args: unknown): boolean;
  cancel(send: (msg: object) => void): void;
}

/** @deprecated The agent-based client doesn't use protocol adapters. */
export class ZKBioOnlineProtocol implements ProtocolAdapter {
  handshake() {}
  dispatch() { return false; }
  requestCapture() {}
  requestEnroll() { return false; }
  requestMatch() { return false; }
  cancel() {}
}

/** @deprecated Use ZKBioOnlineProtocol. */
export const ZKIssoDefaultProtocol = ZKBioOnlineProtocol;
