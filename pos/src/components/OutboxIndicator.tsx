/*
 * Outbox indicator (Phase B).
 *
 * Shows the waiter their offline-queued orders: how many are waiting to
 * sync, which are sending, and which failed (with retry/discard). It's a
 * compact banner in App.tsx's flex column (next to OfflineBanner). Hidden
 * when the queue is empty.
 *
 * A PENDING order is NOT in the kitchen yet — it only reaches the kitchen
 * once it drains successfully on reconnect. The copy makes that explicit.
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  CloudUpload,
  Loader2,
  AlertTriangle,
  RefreshCw,
  Pencil,
  Trash2,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { useOutbox, type OutboxEntry } from '../lib/outbox';
import { useConnectivity } from '../lib/connectivity';
import { usePOSStore } from '../store/pos-store';

const OutboxIndicator = () => {
  const entries = useOutbox((s) => s.entries);
  const draining = useOutbox((s) => s.draining);
  const retry = useOutbox((s) => s.retry);
  const discard = useOutbox((s) => s.discard);
  const drain = useOutbox((s) => s.drain);
  const online = useConnectivity((s) => s.online);
  const loadFromOutboxPayload = usePOSStore((s) => s.loadFromOutboxPayload);
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(false);

  // Load a failed order back into the cart so the waiter can fix what was
  // wrong (e.g. pick a valid customer) and re-send. Removes it from the
  // queue — the fixed order is re-submitted as a fresh new order.
  const handleFix = (entry: OutboxEntry) => {
    loadFromOutboxPayload(entry.payload);
    discard(entry.id);
    setExpanded(false);
    navigate('/');
  };

  if (entries.length === 0) return null;

  const failed = entries.filter((e) => e.status === 'failed').length;
  const active = entries.length - failed; // pending + sending

  // Red when something failed, otherwise amber (waiting) / blue (sending).
  const tone = failed > 0 ? 'bg-red-600' : draining ? 'bg-blue-600' : 'bg-amber-500';

  return (
    <div role="status" className={`shrink-0 w-full ${tone} text-white shadow z-30`}>
      <div className="mx-auto max-w-screen-xl px-4 py-2 text-sm">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="w-full flex items-center gap-3 text-left"
        >
          {draining ? (
            <Loader2 className="w-4 h-4 shrink-0 animate-spin" />
          ) : failed > 0 ? (
            <AlertTriangle className="w-4 h-4 shrink-0" />
          ) : (
            <CloudUpload className="w-4 h-4 shrink-0" />
          )}
          <div className="flex-1 min-w-0">
            <span className="font-semibold">
              {active > 0 && `${active} order${active === 1 ? '' : 's'} waiting to send`}
              {active > 0 && failed > 0 && ' · '}
              {failed > 0 && `${failed} failed`}
            </span>{' '}
            <span className="opacity-90">
              {online
                ? 'Sending to the kitchen…'
                : "will send automatically when you're back online"}
            </span>
          </div>
          {expanded ? (
            <ChevronUp className="w-4 h-4 shrink-0" />
          ) : (
            <ChevronDown className="w-4 h-4 shrink-0" />
          )}
        </button>

        {expanded && (
          <ul className="mt-2 space-y-1.5">
            {entries.map((e) => (
              <li
                key={e.id}
                className="flex items-center gap-2 rounded-md bg-white/15 px-2.5 py-1.5"
              >
                <div className="flex-1 min-w-0">
                  <div className="truncate font-medium">{e.label}</div>
                  <div className="text-xs opacity-90">
                    {e.status === 'sending' && 'Sending…'}
                    {e.status === 'pending' &&
                      (online ? 'Waiting to send…' : 'Queued (offline)')}
                    {e.status === 'failed' && (e.error || 'Send failed')}
                  </div>
                </div>
                {e.status === 'failed' ? (
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      type="button"
                      onClick={() => handleFix(e)}
                      title="Open in the cart to fix and re-send"
                      className="inline-flex items-center gap-1 rounded bg-white/20 hover:bg-white/30 px-2 py-1 text-xs font-semibold"
                    >
                      <Pencil className="w-3.5 h-3.5" />
                      Fix
                    </button>
                    <button
                      type="button"
                      onClick={() => retry(e.id)}
                      title="Try sending again as-is"
                      className="inline-flex items-center rounded bg-white/20 hover:bg-white/30 p-1"
                    >
                      <RefreshCw className="w-3.5 h-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => discard(e.id)}
                      title="Discard"
                      className="inline-flex items-center rounded bg-white/20 hover:bg-white/30 p-1"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ) : (
                  <Loader2
                    className={`w-3.5 h-3.5 shrink-0 ${
                      e.status === 'sending' ? 'animate-spin' : 'opacity-40'
                    }`}
                  />
                )}
              </li>
            ))}
            {online && (active > 0 || failed > 0) && (
              <li>
                <button
                  type="button"
                  onClick={() => drain()}
                  className="mt-1 inline-flex items-center gap-1.5 rounded-md bg-white/20 hover:bg-white/30 px-2.5 py-1 text-xs font-semibold"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  Try to send all now
                </button>
              </li>
            )}
          </ul>
        )}
      </div>
    </div>
  );
};

export default OutboxIndicator;
