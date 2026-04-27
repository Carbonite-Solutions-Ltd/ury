/**
 * BiometricLogin page — `/pos/login`.
 *
 * Replaces the old "Sign in to continue → /login" landing for guests
 * hitting `/pos`. Cashiers pick their account from an autocomplete,
 * then sign in with one of three methods:
 *
 *  - **Biometric**: place finger on the local ZK reader (via the URY
 *    Finger Agent). The browser captures, asks the agent to match
 *    against the stored template, posts the score to the server.
 *  - **PIN**: 6-digit fallback. Works without the agent / reader.
 *  - **Password**: standard Frappe email/password login. Works for
 *    everyone, with or without an enrollment.
 *
 * Smart default: when a user is selected, the page auto-picks the tab
 * matching their `last_login_method` (so a cashier who usually uses
 * biometric sees biometric pre-selected). If they have no enrollment
 * at all, the biometric + PIN tabs hide and only password remains.
 *
 * Backend endpoints used (all already shipped in Phase 1):
 *  - search_users_for_login (allow_guest)
 *  - get_enrollment_template_for_login (allow_guest, rate-limited)
 *  - biometric_login (allow_guest, rate-limited)
 *  - pin_login (allow_guest, rate-limited)
 *  - record_password_login (authenticated, called after Frappe login)
 *  - Frappe's standard /api/method/login (for password)
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Fingerprint, KeyRound, Mail, ArrowRight, ArrowLeft, Search, User as UserIcon,
  Loader2, AlertTriangle, CheckCircle2, RefreshCw, ShieldAlert, Lock,
} from 'lucide-react';
import { Card, CardContent } from '../components/ui';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { showToast } from '../components/ui/toast';
import { cn } from '../lib/utils';
import { extractFrappeServerError } from '../lib/utils';
import {
  searchUsersForLogin,
  getEnrollmentTemplateForLogin,
  biometricLogin,
  pinLogin,
  recordPasswordLogin,
  type LoginUserCandidate,
} from '../lib/biometric-api';
import { useFingerprintReader } from '../lib/use-fingerprint-reader';
import { auth } from '../lib/frappe-sdk';

type LoginMethod = 'biometric' | 'pin' | 'password';

// ---------------------------------------------------------------------------
// Username picker
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
    <div className="space-y-3">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1.5">
          Sign in as
        </label>
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          <Input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type your name or email…"
            className="pl-9"
          />
          {loading && (
            <Loader2 size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 animate-spin" />
          )}
        </div>
      </div>
      {error && (
        <div className="p-2 bg-red-50 border border-red-200 rounded-md text-sm text-red-700">{error}</div>
      )}
      {results.length > 0 && (
        <div className="divide-y divide-gray-100 border border-gray-200 rounded-lg overflow-hidden bg-white">
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
              <div className="flex items-center gap-1.5 shrink-0">
                {u.has_fingerprint === 1 && (
                  <span title="Biometric enrolled" className="inline-flex w-6 h-6 rounded-full bg-emerald-100 items-center justify-center">
                    <Fingerprint size={12} className="text-emerald-700" />
                  </span>
                )}
                {u.has_pin === 1 && (
                  <span title="PIN set" className="inline-flex w-6 h-6 rounded-full bg-blue-100 items-center justify-center">
                    <KeyRound size={12} className="text-blue-700" />
                  </span>
                )}
                <ArrowRight size={14} className="text-gray-400 ml-1" />
              </div>
            </button>
          ))}
        </div>
      )}
      {!loading && query.trim() && results.length === 0 && !error && (
        <div className="p-3 text-center text-sm text-gray-500 bg-gray-50 rounded-md">
          No users matching "<span className="font-medium">{query}</span>".
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 6-digit PIN input (re-uses the pattern from the enrollment wizard)
// ---------------------------------------------------------------------------

function PinDigits({
  value, onChange, autoFocus,
}: { value: string; onChange: (v: string) => void; autoFocus?: boolean }) {
  const refs = useRef<Array<HTMLInputElement | null>>([]);
  const digits = useMemo(() => {
    const arr = Array(6).fill('');
    for (let i = 0; i < Math.min(value.length, 6); i++) arr[i] = value[i];
    return arr;
  }, [value]);

  const onCellChange = (idx: number, raw: string) => {
    const clean = raw.replace(/\D/g, '').slice(-1);
    const next = digits.slice();
    next[idx] = clean;
    onChange(next.join('').slice(0, 6));
    if (clean && idx < 5) refs.current[idx + 1]?.focus();
  };
  const onCellKey = (idx: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace' && !digits[idx] && idx > 0) refs.current[idx - 1]?.focus();
  };
  const onPaste = (idx: number, e: React.ClipboardEvent<HTMLInputElement>) => {
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
    if (pasted.length > 1) {
      e.preventDefault();
      onChange(pasted);
      refs.current[Math.min(pasted.length, 5)]?.focus();
    }
  };
  return (
    <div className="flex gap-2 justify-center">
      {digits.map((d, i) => (
        <input
          key={i}
          ref={(el) => { refs.current[i] = el; }}
          autoFocus={autoFocus && i === 0}
          type="tel"
          inputMode="numeric"
          maxLength={1}
          value={d}
          onChange={(e) => onCellChange(i, e.target.value)}
          onKeyDown={(e) => onCellKey(i, e)}
          onPaste={(e) => onPaste(i, e)}
          className="w-11 h-14 text-center text-2xl font-bold rounded-lg border-2 border-gray-200 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Method tabs
// ---------------------------------------------------------------------------

interface MethodTabsProps {
  user: LoginUserCandidate;
  selected: LoginMethod;
  available: LoginMethod[];
  onSelect: (m: LoginMethod) => void;
}

function MethodTabs({ user, selected, available, onSelect }: MethodTabsProps) {
  const allMethods: { id: LoginMethod; label: string; icon: typeof Fingerprint }[] = [
    { id: 'biometric', label: 'Biometric', icon: Fingerprint },
    { id: 'pin', label: 'PIN', icon: KeyRound },
    { id: 'password', label: 'Password', icon: Lock },
  ];
  return (
    <div className="flex gap-1 bg-gray-100 p-1 rounded-lg">
      {allMethods.map(({ id, label, icon: Icon }) => {
        const isAvailable = available.includes(id);
        const isActive = selected === id;
        return (
          <button
            key={id}
            type="button"
            disabled={!isAvailable}
            onClick={() => onSelect(id)}
            className={cn(
              'flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-colors',
              isActive && 'bg-white text-blue-700 shadow-sm',
              !isActive && isAvailable && 'text-gray-700 hover:bg-gray-50',
              !isAvailable && 'text-gray-400 cursor-not-allowed',
            )}
            title={
              isAvailable
                ? label
                : id === 'biometric'
                ? `${user.full_name} doesn't have a fingerprint enrolled.`
                : id === 'pin'
                ? `${user.full_name} doesn't have a PIN set.`
                : ''
            }
          >
            <Icon size={14} />
            <span>{label}</span>
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Biometric tab
// ---------------------------------------------------------------------------

function BiometricTab({ user, terminalName }: { user: LoginUserCandidate; terminalName?: string | null }) {
  const {
    state, isReady, deviceInfo, connect, capture, match, error: readerError,
  } = useFingerprintReader({ autoConnect: true });
  const [phase, setPhase] = useState<'idle' | 'capturing' | 'matching' | 'authenticating' | 'success'>('idle');
  const [phaseError, setPhaseError] = useState<string | null>(null);
  // Tracks whether the user has explicitly requested a retry after an
  // error. Auto-arm fires automatically when the tab is shown + reader
  // is ready, but pauses after an error so the user can read it; the
  // retry button clears phaseError which re-arms via the auto-fire effect.
  const autoArmAttemptRef = useRef(0);

  const handleStart = useCallback(async () => {
    setPhaseError(null);
    setPhase('capturing');
    try {
      // 1. Server-side: stored template + per-user threshold
      const stored = await getEnrollmentTemplateForLogin(user.name);
      // 2. Local capture via the agent (matches the user's freshly placed finger)
      const captureResult = await capture();
      const capturedB64 = captureResult.templateBase64;
      setPhase('matching');
      // 3. Local 1:1 match through the agent
      const result = await match({
        storedTemplateBase64: stored.template_b64,
        capturedTemplateBase64: capturedB64,
      });
      const required = stored.match_threshold || 80;
      if (!result.matched || result.score < required) {
        throw new Error(`Fingerprint did not match (score ${result.score}, required ${required}).`);
      }
      // 4. Server creates the Frappe session
      setPhase('authenticating');
      const session = await biometricLogin({
        username: user.name,
        captured_template_b64: capturedB64,
        match_score: result.score,
        terminal: terminalName ?? null,
      });
      setPhase('success');
      showToast.success({
        title: 'Welcome back',
        description: `Signed in as ${session.full_name}.`,
      });
      window.location.replace('/pos');
    } catch (err) {
      setPhase('idle');
      const parsed = extractFrappeServerError(err, 'Could not sign you in.');
      setPhaseError(parsed.message);
    }
  }, [user, terminalName, capture, match]);

  // Auto-arm: as soon as the tab is shown AND the reader is ready AND
  // we're idle without a prior error, start capturing. This means the
  // cashier just places their finger — no extra button click.
  // After an error, this stays paused until the user clicks Try Again
  // (which clears phaseError, re-arming this effect).
  useEffect(() => {
    if (phase !== 'idle' || !isReady || phaseError) return;
    // Bump a counter so concurrent renders can't double-fire
    autoArmAttemptRef.current += 1;
    const myAttempt = autoArmAttemptRef.current;
    // Tiny delay so the user sees the "Place your finger" message
    // animate in before the agent starts the capture loop.
    const t = setTimeout(() => {
      if (myAttempt === autoArmAttemptRef.current && phase === 'idle' && !phaseError) {
        handleStart();
      }
    }, 200);
    return () => clearTimeout(t);
  }, [phase, isReady, phaseError, handleStart]);

  if (state === 'disconnected' || state === 'error') {
    return (
      <div className="text-center space-y-3 py-2">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-amber-100">
          <AlertTriangle className="text-amber-700" size={28} />
        </div>
        <div className="text-base font-semibold text-gray-900">Reader not connected</div>
        <div className="text-sm text-gray-600 max-w-xs mx-auto">
          {readerError || 'The local URY Finger Agent isn\'t running on this PC. Switch to PIN or password to sign in now.'}
        </div>
        <Button variant="outline" size="sm" onClick={() => connect().catch(() => {})}>
          <RefreshCw size={14} /> Reconnect
        </Button>
      </div>
    );
  }

  return (
    <div className="text-center space-y-4 py-2">
      <div
        className={cn(
          'inline-flex items-center justify-center w-24 h-24 rounded-full transition-all',
          phase === 'capturing' && 'bg-blue-100 animate-pulse',
          phase === 'matching' && 'bg-blue-100',
          phase === 'authenticating' && 'bg-emerald-100',
          phase === 'success' && 'bg-emerald-200',
          phase === 'idle' && 'bg-gray-100',
        )}
      >
        {phase === 'success' ? (
          <CheckCircle2 className="text-emerald-700" size={48} />
        ) : phase === 'matching' || phase === 'authenticating' ? (
          <Loader2 className="text-blue-700 animate-spin" size={44} />
        ) : (
          <Fingerprint
            className={cn(
              phase === 'capturing' ? 'text-blue-700' : 'text-gray-500',
            )}
            size={48}
          />
        )}
      </div>
      <div>
        <div className="text-base font-semibold text-gray-900">
          {phase === 'idle' && 'Place your finger on the reader'}
          {phase === 'capturing' && 'Hold still…'}
          {phase === 'matching' && 'Matching…'}
          {phase === 'authenticating' && 'Signing you in…'}
          {phase === 'success' && 'Signed in!'}
        </div>
        <div className="text-xs text-gray-500 mt-1">
          {state === 'connected' && (deviceInfo.model || 'Reader connected')}
          {state === 'connecting' && 'Reader connecting…'}
          {(state === 'capturing' || state === 'enrolling') && 'Reader busy'}
        </div>
      </div>
      {phaseError && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700 text-left">
          {phaseError}
        </div>
      )}
      {phase === 'idle' && phaseError && (
        <Button
          onClick={() => setPhaseError(null)}
          disabled={!isReady}
          className="w-full bg-blue-600 hover:bg-blue-700"
        >
          <Fingerprint size={14} /> Try again
        </Button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PIN tab
// ---------------------------------------------------------------------------

function PinTab({ user, terminalName }: { user: LoginUserCandidate; terminalName?: string | null }) {
  const [pin, setPin] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = useCallback(async () => {
    if (pin.length !== 6) return;
    setSubmitting(true);
    setError(null);
    try {
      const session = await pinLogin({
        username: user.name,
        pin,
        terminal: terminalName ?? null,
      });
      showToast.success({
        title: 'Welcome back',
        description: `Signed in as ${session.full_name}.`,
      });
      window.location.replace('/pos');
    } catch (err) {
      const parsed = extractFrappeServerError(err, 'Could not sign you in.');
      setError(parsed.message);
      setPin('');
    } finally {
      setSubmitting(false);
    }
  }, [user, pin, terminalName]);

  // Auto-submit on 6 digits
  useEffect(() => {
    if (pin.length === 6 && !submitting) {
      handleSubmit();
    }
  }, [pin, submitting, handleSubmit]);

  return (
    <div className="space-y-4 py-2">
      <div className="text-center">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-blue-100 mb-2">
          <KeyRound className="text-blue-700" size={26} />
        </div>
        <div className="text-base font-semibold text-gray-900">Enter your 6-digit PIN</div>
        <div className="text-xs text-gray-500 mt-1">
          The one your captain set up during enrollment.
        </div>
      </div>
      <PinDigits value={pin} onChange={setPin} autoFocus />
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700">
          {error}
        </div>
      )}
      <Button
        onClick={handleSubmit}
        disabled={pin.length !== 6 || submitting}
        className="w-full bg-blue-600 hover:bg-blue-700"
      >
        {submitting ? (
          <>
            <Loader2 size={14} className="animate-spin" /> Signing in…
          </>
        ) : (
          <>
            <ArrowRight size={14} /> Sign in
          </>
        )}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Password tab
// ---------------------------------------------------------------------------

function PasswordTab({ user, terminalName }: { user: LoginUserCandidate; terminalName?: string | null }) {
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = useCallback(async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!password) return;
    setSubmitting(true);
    setError(null);
    try {
      // Frappe's standard /api/method/login. We use frappe-js-sdk's auth.loginWithUsernamePassword.
      await auth.loginWithUsernamePassword({ username: user.name, password });
      // Track that this user just used password so smart-default works next time
      await recordPasswordLogin(terminalName ?? null);
      showToast.success({ title: 'Welcome back' });
      window.location.replace('/pos');
    } catch (err) {
      const parsed = extractFrappeServerError(err, 'Incorrect email or password.');
      setError(parsed.message);
    } finally {
      setSubmitting(false);
    }
  }, [user, password, terminalName]);

  return (
    <form onSubmit={handleSubmit} className="space-y-4 py-2">
      <div className="text-center">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-gray-100 mb-2">
          <Lock className="text-gray-700" size={26} />
        </div>
        <div className="text-base font-semibold text-gray-900">Enter your password</div>
        <div className="text-xs text-gray-500 mt-1">
          {user.email || user.name}
        </div>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1.5">Password</label>
        <Input
          autoFocus
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Your password"
          autoComplete="current-password"
        />
      </div>
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700">
          {error}
        </div>
      )}
      <Button
        type="submit"
        disabled={!password || submitting}
        className="w-full bg-blue-600 hover:bg-blue-700"
      >
        {submitting ? (
          <>
            <Loader2 size={14} className="animate-spin" /> Signing in…
          </>
        ) : (
          <>
            <ArrowRight size={14} /> Sign in
          </>
        )}
      </Button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Page shell
// ---------------------------------------------------------------------------

export default function BiometricLogin({ terminalName }: { terminalName?: string | null }) {
  const [pickedUser, setPickedUser] = useState<LoginUserCandidate | null>(null);
  const [method, setMethod] = useState<LoginMethod>('password');

  const availableMethods = useMemo<LoginMethod[]>(() => {
    if (!pickedUser) return ['password'];
    const out: LoginMethod[] = [];
    if (pickedUser.has_fingerprint === 1) out.push('biometric');
    if (pickedUser.has_pin === 1) out.push('pin');
    out.push('password'); // always available
    return out;
  }, [pickedUser]);

  // Smart default whenever a user is picked
  useEffect(() => {
    if (!pickedUser) return;
    const last = pickedUser.last_login_method;
    if (last === 'Biometric' && pickedUser.has_fingerprint === 1) setMethod('biometric');
    else if (last === 'PIN' && pickedUser.has_pin === 1) setMethod('pin');
    else if (last === 'Password') setMethod('password');
    else if (pickedUser.has_fingerprint === 1) setMethod('biometric');
    else if (pickedUser.has_pin === 1) setMethod('pin');
    else setMethod('password');
  }, [pickedUser]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-blue-50 flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-md">
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-blue-600 shadow-lg mb-3">
            <Fingerprint className="text-white" size={28} />
          </div>
          <h1 className="text-2xl font-bold text-gray-900">ExPOS Sign In</h1>
          <p className="text-sm text-gray-500 mt-1">
            Sign in to your terminal to start serving customers.
          </p>
        </div>

        <Card className="border-gray-200 shadow-lg">
          <CardContent className="p-6">
            {!pickedUser ? (
              <UserPicker onPicked={setPickedUser} />
            ) : (
              <div className="space-y-5">
                {/* Selected user header */}
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center shrink-0">
                      <UserIcon size={18} className="text-blue-700" />
                    </div>
                    <div className="min-w-0">
                      <div className="font-semibold text-gray-900 truncate">{pickedUser.full_name}</div>
                      <div className="text-xs text-gray-500 truncate">{pickedUser.email || pickedUser.name}</div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setPickedUser(null)}
                    className="text-xs text-gray-500 hover:text-gray-900 flex items-center gap-1 shrink-0"
                  >
                    <ArrowLeft size={12} /> Change
                  </button>
                </div>

                {/* Tabs */}
                <MethodTabs
                  user={pickedUser}
                  selected={method}
                  available={availableMethods}
                  onSelect={setMethod}
                />

                {/* Active tab content */}
                <div className="pt-1">
                  {method === 'biometric' && <BiometricTab user={pickedUser} terminalName={terminalName} />}
                  {method === 'pin' && <PinTab user={pickedUser} terminalName={terminalName} />}
                  {method === 'password' && <PasswordTab user={pickedUser} terminalName={terminalName} />}
                </div>

                {/* No-enrollment hint */}
                {pickedUser.has_fingerprint === 0 && pickedUser.has_pin === 0 && (
                  <div className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-md p-3 flex items-start gap-2">
                    <ShieldAlert size={14} className="mt-0.5 shrink-0" />
                    <div>
                      No biometric enrollment yet. Ask your captain to enrol your fingerprint
                      so you can sign in with one touch next time.
                    </div>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        <div className="text-center mt-4">
          <a
            href="/login?redirect-to=%2Fpos"
            className="text-xs text-gray-500 hover:text-gray-700 inline-flex items-center gap-1"
          >
            <Mail size={11} /> Use the standard login page instead
          </a>
        </div>
      </div>
    </div>
  );
}
