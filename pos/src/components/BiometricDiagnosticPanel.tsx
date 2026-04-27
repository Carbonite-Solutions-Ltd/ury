/**
 * BiometricDiagnosticPanel
 *
 * Collapsible debug view that mirrors every WebSocket message between
 * the React POS and the ISSOnline driver. Shown on the enrollment page
 * (opt-in via a "Show diagnostic console" toggle) so during first-run
 * setup we can inspect the raw wire format of the specific driver
 * version installed on the cashier PC, and adapt the protocol adapter
 * if the defaults don't match.
 *
 * Once the protocol is confirmed, admins can leave it collapsed — but
 * keeping the panel available in production is useful for support
 * triage ("reader stopped working" → open the console, see what the
 * driver is actually sending).
 */

import React, { useMemo } from 'react';
import { Trash2, ChevronDown, ChevronUp, Radio, AlertCircle, ArrowRight, ArrowLeft } from 'lucide-react';
import type { DebugMessage, BiometricConnectionState, BiometricDeviceInfo } from '../lib/biometric-client';
import { Button } from './ui/button';
import { cn } from '../lib/utils';

interface Props {
  state: BiometricConnectionState;
  deviceInfo: BiometricDeviceInfo;
  wsUrl: string;
  debugMessages: DebugMessage[];
  error: string | null;
  expanded: boolean;
  onToggleExpanded: () => void;
  onClearDebug: () => void;
  onReconnect: () => void;
}

const STATE_META: Record<BiometricConnectionState, { label: string; tone: string }> = {
  disconnected: { label: 'Disconnected', tone: 'bg-gray-100 text-gray-700 border-gray-300' },
  connecting: { label: 'Connecting…', tone: 'bg-blue-50 text-blue-700 border-blue-300' },
  connected: { label: 'Connected', tone: 'bg-emerald-50 text-emerald-700 border-emerald-300' },
  capturing: { label: 'Capturing…', tone: 'bg-amber-50 text-amber-700 border-amber-300' },
  enrolling: { label: 'Enrolling…', tone: 'bg-amber-50 text-amber-700 border-amber-300' },
  error: { label: 'Error', tone: 'bg-red-50 text-red-700 border-red-300' },
};

function shortTime(ms: number): string {
  const d = new Date(ms);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  const mmm = String(d.getMilliseconds()).padStart(3, '0');
  return `${hh}:${mm}:${ss}.${mmm}`;
}

function MessageRow({ msg }: { msg: DebugMessage }) {
  const directionMeta = {
    out: { icon: ArrowRight, color: 'text-blue-600', bg: 'bg-blue-50' },
    in: { icon: ArrowLeft, color: 'text-emerald-700', bg: 'bg-emerald-50' },
    info: { icon: Radio, color: 'text-gray-600', bg: 'bg-gray-50' },
    error: { icon: AlertCircle, color: 'text-red-700', bg: 'bg-red-50' },
  }[msg.direction];
  const Icon = directionMeta.icon;
  const formatted = useMemo(() => {
    try {
      return typeof msg.payload === 'string' ? msg.payload : JSON.stringify(msg.payload, null, 2);
    } catch {
      return String(msg.payload);
    }
  }, [msg.payload]);
  return (
    <div
      className={cn(
        'px-3 py-2 font-mono text-xs border-l-2 border-gray-200',
        directionMeta.bg
      )}
    >
      <div className={cn('flex items-center gap-2 mb-1', directionMeta.color)}>
        <Icon size={12} />
        <span className="font-semibold uppercase">{msg.direction}</span>
        <span className="text-gray-500">{shortTime(msg.at)}</span>
      </div>
      <pre className="whitespace-pre-wrap break-words text-gray-800 leading-relaxed">{formatted}</pre>
    </div>
  );
}

export default function BiometricDiagnosticPanel({
  state,
  deviceInfo,
  wsUrl,
  debugMessages,
  error,
  expanded,
  onToggleExpanded,
  onClearDebug,
  onReconnect,
}: Props) {
  const stateMeta = STATE_META[state];

  return (
    <div className="border border-gray-200 rounded-lg bg-white overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 bg-gray-50 border-b border-gray-200">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onToggleExpanded}
            className="flex items-center gap-2 text-sm font-medium text-gray-700 hover:text-gray-900"
            title={expanded ? 'Collapse diagnostic console' : 'Expand diagnostic console'}
          >
            {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            <span>Fingerprint Diagnostic Console</span>
          </button>
          <span
            className={cn(
              'inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs font-medium',
              stateMeta.tone
            )}
          >
            <span
              className={cn(
                'w-1.5 h-1.5 rounded-full',
                state === 'connected'
                  ? 'bg-emerald-500 animate-pulse'
                  : state === 'error'
                  ? 'bg-red-500'
                  : 'bg-gray-400'
              )}
            />
            {stateMeta.label}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {state !== 'connected' && state !== 'connecting' && (
            <Button variant="outline" size="sm" onClick={onReconnect}>
              Reconnect
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={onClearDebug} title="Clear messages">
            <Trash2 size={14} />
          </Button>
        </div>
      </div>

      {expanded && (
        <div className="divide-y divide-gray-100">
          <div className="px-4 py-2 bg-gray-50 text-xs text-gray-600 grid grid-cols-1 md:grid-cols-3 gap-2">
            <div>
              <span className="font-semibold text-gray-700">WebSocket:</span>{' '}
              <code className="font-mono text-gray-800">{wsUrl || '(not configured)'}</code>
            </div>
            <div>
              <span className="font-semibold text-gray-700">Device:</span>{' '}
              <code className="font-mono text-gray-800">
                {deviceInfo.model || deviceInfo.serial || '—'}
              </code>
            </div>
            <div>
              <span className="font-semibold text-gray-700">Driver:</span>{' '}
              <code className="font-mono text-gray-800">{deviceInfo.driverVersion || '—'}</code>
            </div>
          </div>
          {error && (
            <div className="px-4 py-2 bg-red-50 text-sm text-red-800 flex items-start gap-2">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <div>
                <div className="font-semibold">Connection error</div>
                <div className="text-xs opacity-80">{error}</div>
              </div>
            </div>
          )}
          <div className="max-h-80 overflow-y-auto">
            {debugMessages.length === 0 ? (
              <div className="px-4 py-6 text-center text-sm text-gray-500">
                No messages yet. Connect the reader + trigger a capture to see traffic.
              </div>
            ) : (
              debugMessages
                .slice()
                .reverse()
                .map((m, idx) => <MessageRow key={`${m.at}-${idx}`} msg={m} />)
            )}
          </div>
        </div>
      )}
    </div>
  );
}
