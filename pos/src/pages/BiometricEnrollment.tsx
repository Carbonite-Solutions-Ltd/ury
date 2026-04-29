/**
 * BiometricEnrollment page (captain/admin only).
 *
 * Three-step wizard:
 *   1. Pick user (autocomplete over URY-role users)
 *   2. Place finger 3 times (with live per-scan feedback)
 *   3. Set 6-digit PIN (with confirm + show/hide)
 * → Success summary with "Enroll another" CTA.
 *
 * Reader traffic mirrors into a collapsible diagnostic panel so the
 * first time the captain sets up a new cashier PC we can verify the
 * WebSocket wire format matches the ProtocolAdapter expectations.
 *
 * Security notes:
 *   - Enrollment requires the captain/admin to already be authenticated.
 *     Unauthorized users hit the `_require_enrollment_admin` guard on
 *     the backend with a PermissionError.
 *   - Every enrollment is stamped with `fingerprint_enrolled_by =
 *     current session user`.
 *   - PIN is never logged or sent in the diagnostic panel (we strip
 *     pin fields before logging).
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  User as UserIcon,
  Fingerprint,
  KeyRound,
  CheckCircle2,
  ArrowLeft,
  ArrowRight,
  RefreshCw,
  AlertTriangle,
  Search,
  UserCheck,
  Loader2,
  Trash2,
} from 'lucide-react';
import { Card, CardContent } from '../components/ui';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { showToast } from '../components/ui/toast';
import { cn } from '../lib/utils';
import { useFingerprintReader } from '../lib/use-fingerprint-reader';
import { useRootStore } from '../store/root-store';
import { canAccessDeskAndTerminalSwitch } from '../lib/role-utils';
import { extractFrappeServerError } from '../lib/utils';
import {
  searchUsersForLogin,
  enrollBiometric,
  adminResetEnrollment,
  type LoginUserCandidate,
} from '../lib/biometric-api';
import BiometricDiagnosticPanel from '../components/BiometricDiagnosticPanel';

type WizardStep = 'pick' | 'fingerprint' | 'pin' | 'done';

const FINGER_OPTIONS = [
  'Right Thumb',
  'Right Index',
  'Right Middle',
  'Right Ring',
  'Right Little',
  'Left Thumb',
  'Left Index',
  'Left Middle',
  'Left Ring',
  'Left Little',
];

// ---------------------------------------------------------------------------
// User picker
// ---------------------------------------------------------------------------

interface UserPickerProps {
  onPicked: (u: LoginUserCandidate) => void;
}

function UserPicker({ onPicked }: UserPickerProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<LoginUserCandidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!query.trim()) {
      setResults([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    debounceRef.current = setTimeout(async () => {
      try {
        const r = await searchUsersForLogin(query);
        setResults(r);
      } catch (err) {
        setResults([]);
        setError(extractFrappeServerError(err, 'Could not search users.').message);
      } finally {
        setLoading(false);
      }
    }, 220);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  return (
    <Card className="border-gray-200">
      <CardContent className="p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center">
            <UserIcon className="text-blue-700" size={22} />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Pick a user</h2>
            <p className="text-sm text-gray-600">
              Search by name, email, or username. Only URY cashiers, captains, and managers are shown.
            </p>
          </div>
        </div>
        <div className="relative">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none"
          />
          <Input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Start typing a name or email…"
            className="pl-9"
          />
          {loading && (
            <Loader2
              size={14}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 animate-spin"
            />
          )}
        </div>
        {error && (
          <div className="mt-3 p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">
            {error}
          </div>
        )}
        <div className="mt-4 divide-y divide-gray-100 border border-gray-200 rounded-lg overflow-hidden min-h-[100px]">
          {results.length === 0 && !loading && query.trim() && (
            <div className="px-4 py-6 text-center text-sm text-gray-500">
              No users found matching <span className="font-medium">"{query}"</span>.
            </div>
          )}
          {results.length === 0 && !query.trim() && (
            <div className="px-4 py-6 text-center text-sm text-gray-400">
              Start typing to search…
            </div>
          )}
          {results.map((u) => (
            <button
              key={u.name}
              type="button"
              onClick={() => onPicked(u)}
              className="w-full text-left px-4 py-3 hover:bg-blue-50 focus:bg-blue-50 focus:outline-none transition-colors flex items-center justify-between gap-3"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-9 h-9 rounded-full bg-gray-100 flex items-center justify-center shrink-0">
                  <UserIcon size={16} className="text-gray-600" />
                </div>
                <div className="min-w-0">
                  <div className="font-medium text-gray-900 truncate">{u.full_name}</div>
                  <div className="text-xs text-gray-500 truncate">{u.email || u.name}</div>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {u.has_fingerprint === 1 && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 text-xs font-medium">
                    <Fingerprint size={10} /> Enrolled
                  </span>
                )}
                {u.has_pin === 1 && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200 text-xs font-medium">
                    <KeyRound size={10} /> PIN
                  </span>
                )}
                <ArrowRight size={14} className="text-gray-400" />
              </div>
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Fingerprint 3-scan wizard
// ---------------------------------------------------------------------------

type ScanState = 'idle' | 'scanning' | 'captured' | 'rejected';

interface ScanCardProps {
  idx: number;
  state: ScanState;
}

function ScanCard({ idx, state }: ScanCardProps) {
  const meta = {
    idle: {
      ring: 'border-gray-200 bg-gray-50',
      iconBg: 'bg-gray-200',
      iconColor: 'text-gray-400',
      label: 'Waiting',
    },
    scanning: {
      ring: 'border-blue-400 bg-blue-50 animate-pulse',
      iconBg: 'bg-blue-200',
      iconColor: 'text-blue-700',
      label: 'Place finger…',
    },
    captured: {
      ring: 'border-emerald-400 bg-emerald-50',
      iconBg: 'bg-emerald-200',
      iconColor: 'text-emerald-700',
      label: 'Captured',
    },
    rejected: {
      ring: 'border-red-400 bg-red-50',
      iconBg: 'bg-red-200',
      iconColor: 'text-red-700',
      label: 'Try again',
    },
  }[state];
  return (
    <div
      className={cn(
        'rounded-xl border-2 p-5 flex flex-col items-center gap-3 transition-all',
        meta.ring
      )}
    >
      <div
        className={cn(
          'w-16 h-16 rounded-full flex items-center justify-center',
          meta.iconBg
        )}
      >
        {state === 'captured' ? (
          <CheckCircle2 className={meta.iconColor} size={30} />
        ) : state === 'rejected' ? (
          <AlertTriangle className={meta.iconColor} size={28} />
        ) : (
          <Fingerprint className={meta.iconColor} size={30} />
        )}
      </div>
      <div className="text-center">
        <div className="text-xs uppercase tracking-wide text-gray-500">Scan {idx}</div>
        <div className="text-sm font-medium text-gray-800">{meta.label}</div>
      </div>
    </div>
  );
}

interface FingerprintStepProps {
  pickedUser: LoginUserCandidate;
  primaryFinger: string;
  onFingerChange: (f: string) => void;
  onBack: () => void;
  onCaptured: (templateBase64: string) => void;
}

function FingerprintStep({
  pickedUser,
  primaryFinger,
  onFingerChange,
  onBack,
  onCaptured,
}: FingerprintStepProps) {
  const {
    state,
    isReady,
    settings,
    error,
    deviceInfo,
    enrollProgress,
    debugMessages,
    connect,
    enroll,
    cancel,
    clearError,
    clearDebug,
  } = useFingerprintReader({ autoConnect: true });

  const [scans, setScans] = useState<ScanState[]>(['idle', 'idle', 'idle']);
  const [running, setRunning] = useState(false);
  const [resultTemplate, setResultTemplate] = useState<string | null>(null);
  const [debugOpen, setDebugOpen] = useState(false);

  // Translate progress events into per-card state
  useEffect(() => {
    if (!enrollProgress) return;
    setScans((prev) => {
      const next = [...prev];
      for (let i = 0; i < next.length; i++) {
        if (i < enrollProgress.scanIndex) next[i] = 'captured';
        else if (i === enrollProgress.scanIndex) next[i] = 'scanning';
        else next[i] = 'idle';
      }
      return next;
    });
  }, [enrollProgress]);

  const handleStart = useCallback(async () => {
    clearError();
    setResultTemplate(null);
    setScans(['scanning', 'idle', 'idle']);
    setRunning(true);
    try {
      const result = await enroll();
      setScans(['captured', 'captured', 'captured']);
      setResultTemplate(result.masterTemplateBase64);
      setRunning(false);
    } catch (err) {
      setRunning(false);
      setScans(['rejected', 'rejected', 'rejected']);
      const msg = err instanceof Error ? err.message : String(err);
      showToast.error({
        title: 'Enrollment failed',
        description: msg,
      });
    }
  }, [enroll, clearError]);

  const handleReset = useCallback(() => {
    cancel();
    clearError();
    setScans(['idle', 'idle', 'idle']);
    setResultTemplate(null);
    setRunning(false);
  }, [cancel, clearError]);

  return (
    <Card className="border-gray-200">
      <CardContent className="p-6">
        <div className="flex items-start justify-between gap-4 mb-5">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-full bg-emerald-100 flex items-center justify-center">
              <Fingerprint className="text-emerald-700" size={22} />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900">
                Scan {pickedUser.full_name}'s fingerprint
              </h2>
              <p className="text-sm text-gray-600">
                Ask the cashier to place their finger on the reader <strong>three times</strong>. The
                driver will merge the three scans into one enrolment template.
              </p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={onBack}>
            <ArrowLeft size={14} /> Change user
          </Button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-[1fr,220px] gap-4 mb-4">
          <div className="flex flex-col gap-2">
            <label className="text-xs font-semibold text-gray-700 uppercase tracking-wide">
              Primary finger
            </label>
            <select
              value={primaryFinger}
              onChange={(e) => onFingerChange(e.target.value)}
              disabled={running}
              className="h-10 rounded-md border border-gray-200 px-3 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200 focus:outline-none disabled:bg-gray-50"
            >
              {FINGER_OPTIONS.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-2">
            <label className="text-xs font-semibold text-gray-700 uppercase tracking-wide">
              Reader status
            </label>
            <div className="h-10 px-3 flex items-center gap-2 rounded-md border border-gray-200 bg-gray-50 text-sm text-gray-700">
              <span
                className={cn(
                  'w-2 h-2 rounded-full',
                  state === 'connected' && 'bg-emerald-500',
                  state === 'connecting' && 'bg-blue-500 animate-pulse',
                  state === 'error' && 'bg-red-500',
                  state === 'disconnected' && 'bg-gray-400',
                  (state === 'capturing' || state === 'enrolling') && 'bg-amber-500 animate-pulse'
                )}
              />
              <span className="truncate">
                {state === 'connected' && (deviceInfo.model || 'Connected')}
                {state === 'connecting' && 'Connecting…'}
                {state === 'capturing' && 'Capturing…'}
                {state === 'enrolling' && 'Enrolling…'}
                {state === 'disconnected' && 'Not connected'}
                {state === 'error' && 'Error'}
              </span>
            </div>
          </div>
        </div>

        {/* Reader not available → show hint + reconnect button */}
        {!isReady && state !== 'enrolling' && (
          <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-md text-sm text-amber-900 flex items-start justify-between gap-3">
            <div className="flex items-start gap-2">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <div>
                <div className="font-medium">Reader not connected.</div>
                <div className="text-xs opacity-80">
                  {error ||
                    'The ISSOnline driver must be running on this Windows machine. Check the system tray icon, then click Reconnect.'}
                </div>
              </div>
            </div>
            <Button size="sm" variant="outline" onClick={() => connect().catch(() => {})}>
              <RefreshCw size={14} /> Reconnect
            </Button>
          </div>
        )}

        {/* 3-scan cards */}
        <div className="grid grid-cols-3 gap-3 mb-5">
          {scans.map((s, i) => (
            <ScanCard key={i} idx={i + 1} state={s} />
          ))}
        </div>

        {/* Progress banner */}
        {running && (
          <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-md text-sm text-blue-900 flex items-center gap-2">
            <Loader2 size={16} className="animate-spin" />
            {enrollProgress
              ? `Captured ${enrollProgress.scanIndex} of ${enrollProgress.total}. Please lift and place finger again.`
              : 'Waiting for first scan…'}
          </div>
        )}

        {/* Action row */}
        <div className="flex items-center justify-between gap-3">
          <div className="text-xs text-gray-500">
            The cashier's fingerprint template stays on this Frappe site only. It is never shared
            with third parties.
          </div>
          <div className="flex items-center gap-2">
            {(resultTemplate || scans.some((s) => s === 'rejected')) && (
              <Button variant="outline" onClick={handleReset} disabled={running}>
                <RefreshCw size={14} /> Redo
              </Button>
            )}
            {!resultTemplate ? (
              <Button
                onClick={handleStart}
                disabled={!isReady || running}
                className="bg-emerald-600 hover:bg-emerald-700"
              >
                {running ? (
                  <>
                    <Loader2 size={14} className="animate-spin" /> Scanning…
                  </>
                ) : (
                  <>
                    <Fingerprint size={14} /> Start 3-scan enrollment
                  </>
                )}
              </Button>
            ) : (
              <Button
                onClick={() => onCaptured(resultTemplate)}
                className="bg-emerald-600 hover:bg-emerald-700"
              >
                Continue to PIN <ArrowRight size={14} />
              </Button>
            )}
          </div>
        </div>

        {/* Diagnostic panel — collapsed by default */}
        <div className="mt-6">
          <BiometricDiagnosticPanel
            state={state}
            deviceInfo={deviceInfo}
            wsUrl={settings?.issonline_ws_url ?? ''}
            debugMessages={debugMessages}
            error={error}
            expanded={debugOpen}
            onToggleExpanded={() => setDebugOpen((v) => !v)}
            onClearDebug={clearDebug}
            onReconnect={() => connect().catch(() => {})}
          />
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// PIN step
// ---------------------------------------------------------------------------

interface PinDigitInputProps {
  value: string;
  onChange: (v: string) => void;
  label: string;
  autoFocus?: boolean;
}

function PinDigitInput({ value, onChange, label, autoFocus }: PinDigitInputProps) {
  // 6 cells, each a single-digit input that auto-advances
  const refs = useRef<Array<HTMLInputElement | null>>([]);
  const digits = useMemo(() => {
    const arr = Array(6).fill('');
    for (let i = 0; i < Math.min(value.length, 6); i++) arr[i] = value[i];
    return arr;
  }, [value]);

  const handleChange = (idx: number, raw: string) => {
    const clean = raw.replace(/\D/g, '').slice(-1);
    const next = digits.slice();
    next[idx] = clean;
    const assembled = next.join('').slice(0, 6);
    onChange(assembled);
    if (clean && idx < 5) refs.current[idx + 1]?.focus();
  };
  const handleKeyDown = (idx: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace' && !digits[idx] && idx > 0) {
      refs.current[idx - 1]?.focus();
    }
  };
  const handlePaste = (idx: number, e: React.ClipboardEvent<HTMLInputElement>) => {
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
    if (pasted.length > 1) {
      e.preventDefault();
      onChange(pasted);
      refs.current[Math.min(pasted.length, 5)]?.focus();
    }
  };

  return (
    <div>
      <label className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2 block">
        {label}
      </label>
      <div className="flex gap-2">
        {digits.map((d, i) => (
          <input
            key={i}
            ref={(el) => {
              refs.current[i] = el;
            }}
            autoFocus={autoFocus && i === 0}
            type="password"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={1}
            value={d}
            onChange={(e) => handleChange(i, e.target.value)}
            onKeyDown={(e) => handleKeyDown(i, e)}
            onPaste={(e) => handlePaste(i, e)}
            className="w-12 h-14 text-center text-2xl font-bold rounded-lg border-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
        ))}
      </div>
    </div>
  );
}

interface PinStepProps {
  pickedUser: LoginUserCandidate;
  fingerprintTemplate: string;
  primaryFinger: string;
  onBack: () => void;
  onEnrolled: () => void;
}

function PinStep({
  pickedUser,
  fingerprintTemplate,
  primaryFinger,
  onBack,
  onEnrolled,
}: PinStepProps) {
  const [pin1, setPin1] = useState('');
  const [pin2, setPin2] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [skipPin, setSkipPin] = useState(pickedUser.has_pin === 1);

  const mismatch = pin1.length === 6 && pin2.length === 6 && pin1 !== pin2;
  const canSubmit = skipPin
    ? true
    : pin1.length === 6 && pin2.length === 6 && pin1 === pin2 && !submitting;

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const result = await enrollBiometric({
        user: pickedUser.name,
        fingerprint_template_b64: fingerprintTemplate,
        primary_finger: primaryFinger,
        pin: skipPin ? undefined : pin1,
      });
      showToast.success({
        title: 'Enrollment saved',
        description:
          result.action === 'created'
            ? `${pickedUser.full_name} can now log in with biometric${result.pin_set ? ' or PIN' : ''}.`
            : `Updated ${pickedUser.full_name}'s enrollment.`,
      });
      onEnrolled();
    } catch (err) {
      const parsed = extractFrappeServerError(err, 'Could not save enrollment.');
      showToast.error({ title: parsed.title || 'Enrollment failed', description: parsed.message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card className="border-gray-200">
      <CardContent className="p-6">
        <div className="flex items-start justify-between gap-4 mb-5">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center">
              <KeyRound className="text-blue-700" size={22} />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Set fallback PIN</h2>
              <p className="text-sm text-gray-600">
                Ask {pickedUser.full_name} to enter a private 6-digit PIN they'll remember. This is
                the fallback when the reader isn't available or their finger won't scan.
              </p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={onBack}>
            <ArrowLeft size={14} /> Back
          </Button>
        </div>

        {pickedUser.has_pin === 1 && (
          <div className="mb-4 p-3 bg-gray-50 border border-gray-200 rounded-md">
            <label className="flex items-start gap-2 text-sm text-gray-700 cursor-pointer">
              <input
                type="checkbox"
                checked={skipPin}
                onChange={(e) => setSkipPin(e.target.checked)}
                className="mt-0.5"
              />
              <span>
                <strong>Keep existing PIN.</strong> Only re-enrolling the fingerprint. Uncheck to
                also set a new PIN.
              </span>
            </label>
          </div>
        )}

        {!skipPin && (
          <div className="space-y-5">
            <PinDigitInput value={pin1} onChange={setPin1} label="New PIN (6 digits)" autoFocus />
            <PinDigitInput value={pin2} onChange={setPin2} label="Confirm PIN" />
            {mismatch && (
              <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">
                PINs don't match. Please try again.
              </div>
            )}
          </div>
        )}

        <div className="mt-6 flex items-center justify-between gap-3">
          <div className="text-xs text-gray-500">
            PINs are hashed with pbkdf2-sha256 before storage. They're never shown anywhere in the
            system after this step.
          </div>
          <Button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="bg-emerald-600 hover:bg-emerald-700"
          >
            {submitting ? (
              <>
                <Loader2 size={14} className="animate-spin" /> Saving…
              </>
            ) : (
              <>
                <CheckCircle2 size={14} /> Complete enrollment
              </>
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Done step
// ---------------------------------------------------------------------------

interface DoneStepProps {
  pickedUser: LoginUserCandidate;
  onEnrollAnother: () => void;
  onExit: () => void;
}

function DoneStep({ pickedUser, onEnrollAnother, onExit }: DoneStepProps) {
  return (
    <Card className="border-gray-200">
      <CardContent className="p-10 flex flex-col items-center text-center">
        <div className="w-20 h-20 rounded-full bg-emerald-100 flex items-center justify-center mb-4">
          <CheckCircle2 className="text-emerald-600" size={44} />
        </div>
        <h2 className="text-xl font-semibold text-gray-900 mb-2">Enrollment complete</h2>
        <p className="text-sm text-gray-600 max-w-md mb-6">
          <strong>{pickedUser.full_name}</strong> can now sign in to URY POS using their fingerprint
          or 6-digit PIN. They can change their PIN anytime from the avatar menu.
        </p>
        <div className="flex gap-2">
          <Button variant="outline" onClick={onExit}>
            Done
          </Button>
          <Button onClick={onEnrollAnother} className="bg-emerald-600 hover:bg-emerald-700">
            Enroll another user
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page shell + wizard orchestration
// ---------------------------------------------------------------------------

export default function BiometricEnrollment() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const user = useRootStore((s) => s.user);
  const canEnroll = canAccessDeskAndTerminalSwitch(user);

  const [step, setStep] = useState<WizardStep>('pick');
  const [pickedUser, setPickedUser] = useState<LoginUserCandidate | null>(null);
  const [primaryFinger, setPrimaryFinger] = useState('Right Index');
  const [fingerprintTemplate, setFingerprintTemplate] = useState<string | null>(null);
  const [resetPending, setResetPending] = useState(false);

  // Deep-link support: when the desk-side "Enrol Fingerprint + PIN" button
  // opens /pos/biometric-enrollment?user=<name>, pre-pick that user by
  // running a single search + matching by name. If no match, fall back
  // to the normal picker.
  useEffect(() => {
    const deepLink = searchParams.get('user');
    if (!deepLink || pickedUser || !canEnroll) return;
    (async () => {
      try {
        const rows = await searchUsersForLogin(deepLink);
        const hit = rows.find((r) => r.name === deepLink);
        if (hit) {
          setPickedUser(hit);
          setStep('fingerprint');
          // Strip the param so refresh doesn't re-trigger the deep-link
          const next = new URLSearchParams(searchParams);
          next.delete('user');
          setSearchParams(next, { replace: true });
        }
      } catch {
        /* ignore - user will see the normal picker */
      }
    })();
  }, [searchParams, pickedUser, canEnroll, setSearchParams]);

  const handleExit = useCallback(() => navigate('/'), [navigate]);
  const handleReset = useCallback(() => {
    setStep('pick');
    setPickedUser(null);
    setFingerprintTemplate(null);
    setPrimaryFinger('Right Index');
  }, []);

  const handleUserPicked = useCallback((u: LoginUserCandidate) => {
    setPickedUser(u);
    setStep('fingerprint');
  }, []);

  const handleCaptured = useCallback((template: string) => {
    setFingerprintTemplate(template);
    setStep('pin');
  }, []);

  const handleDelete = useCallback(async () => {
    if (!pickedUser) return;
    if (!window.confirm(`Delete ${pickedUser.full_name}'s enrollment entirely? This cannot be undone.`)) {
      return;
    }
    setResetPending(true);
    try {
      await adminResetEnrollment(pickedUser.name, { delete: true });
      showToast.success({
        title: 'Enrollment deleted',
        description: `${pickedUser.full_name} has been removed from biometric authentication.`,
      });
      handleReset();
    } catch (err) {
      const parsed = extractFrappeServerError(err, 'Could not delete enrollment.');
      showToast.error({ title: parsed.title || 'Delete failed', description: parsed.message });
    } finally {
      setResetPending(false);
    }
  }, [pickedUser, handleReset]);

  if (!canEnroll) {
    return (
      <div className="max-w-2xl mx-auto my-8 px-4">
        <Card className="border-red-200">
          <CardContent className="p-6 text-center">
            <AlertTriangle className="mx-auto mb-3 text-red-600" size={40} />
            <h2 className="text-lg font-semibold text-gray-900 mb-2">Permission required</h2>
            <p className="text-sm text-gray-600 mb-4">
              Only captains, managers, and administrators can enroll cashiers' biometrics.
            </p>
            <Button variant="outline" onClick={handleExit}>
              Back to POS
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto my-6 px-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900 flex items-center gap-2">
            <Fingerprint className="text-emerald-600" size={24} /> Biometric Enrollment
          </h1>
          <p className="text-sm text-gray-600">
            Register a cashier's fingerprint + PIN so they can log in without typing a password.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={handleExit}>
          <ArrowLeft size={14} /> Back to POS
        </Button>
      </div>

      {/* Stepper */}
      <div className="flex items-center justify-center gap-2 mb-6 text-xs">
        {(
          [
            { key: 'pick', label: '1. User', icon: UserIcon },
            { key: 'fingerprint', label: '2. Fingerprint', icon: Fingerprint },
            { key: 'pin', label: '3. PIN', icon: KeyRound },
            { key: 'done', label: 'Done', icon: UserCheck },
          ] as Array<{ key: WizardStep; label: string; icon: typeof UserIcon }>
        ).map((s, i, arr) => {
          const currentIdx = arr.findIndex((a) => a.key === step);
          const sIdx = i;
          const active = sIdx === currentIdx;
          const done = sIdx < currentIdx;
          const Icon = s.icon;
          return (
            <React.Fragment key={s.key}>
              <div
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-full border',
                  active && 'bg-emerald-50 border-emerald-300 text-emerald-800',
                  done && 'bg-emerald-600 border-emerald-600 text-white',
                  !active && !done && 'bg-gray-50 border-gray-200 text-gray-500'
                )}
              >
                <Icon size={12} />
                <span className="font-medium">{s.label}</span>
              </div>
              {i < arr.length - 1 && (
                <div
                  className={cn('w-8 h-[2px]', done ? 'bg-emerald-600' : 'bg-gray-200')}
                />
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Step body */}
      {step === 'pick' && <UserPicker onPicked={handleUserPicked} />}
      {step === 'fingerprint' && pickedUser && (
        <FingerprintStep
          pickedUser={pickedUser}
          primaryFinger={primaryFinger}
          onFingerChange={setPrimaryFinger}
          onBack={() => setStep('pick')}
          onCaptured={handleCaptured}
        />
      )}
      {step === 'pin' && pickedUser && fingerprintTemplate && (
        <PinStep
          pickedUser={pickedUser}
          fingerprintTemplate={fingerprintTemplate}
          primaryFinger={primaryFinger}
          onBack={() => setStep('fingerprint')}
          onEnrolled={() => setStep('done')}
        />
      )}
      {step === 'done' && pickedUser && (
        <DoneStep pickedUser={pickedUser} onEnrollAnother={handleReset} onExit={handleExit} />
      )}

      {/* Danger zone — only shown on fingerprint/pin steps */}
      {(step === 'fingerprint' || step === 'pin') && pickedUser?.has_fingerprint === 1 && (
        <div className="mt-6 p-4 border border-red-200 bg-red-50 rounded-lg flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Trash2 size={16} className="text-red-600 shrink-0" />
            <div className="text-sm">
              <div className="font-medium text-red-900">Delete existing enrollment</div>
              <div className="text-xs text-red-700">
                Removes {pickedUser.full_name}'s fingerprint and PIN entirely. They'll need
                password login until re-enrolled.
              </div>
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleDelete}
            disabled={resetPending}
            className="border-red-300 text-red-700 hover:bg-red-100"
          >
            {resetPending ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />} Delete
          </Button>
        </div>
      )}
    </div>
  );
}
