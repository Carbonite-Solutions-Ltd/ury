import { call } from './frappe-sdk';

/**
 * Client for the Frappe-side URY Biometric API. Thin wrappers over the
 * whitelisted methods in ury/ury/biometric/api.py. All network/session
 * errors propagate; callers should use extractFrappeServerError() for
 * user-visible messages.
 */

export interface PublicBiometricSettings {
  enabled: 0 | 1;
  issonline_ws_url: string;
}

export interface LoginUserCandidate {
  name: string;
  full_name: string;
  email: string;
  has_fingerprint: 0 | 1;
  has_pin: 0 | 1;
  last_login_method: '' | 'Biometric' | 'PIN' | 'Password';
}

export interface EnrollmentTemplateLookup {
  username: string;
  template_b64: string;
  template_length: number;
  match_threshold: number;
  primary_finger: string;
}

export interface LoginResult {
  user: string;
  full_name: string;
  home_page: string;
  method: 'Biometric' | 'PIN' | 'Password';
  /**
   * PIN expiry (2026-06-05). Set by pin_login when the PIN is past its
   * expiry window. The session IS created (the user authenticated with
   * the correct PIN), but the login page must force a reset before
   * reaching the POS.
   */
  pin_change_required?: boolean;
  pin_expired?: boolean;
}

export interface EnrollResult {
  user: string;
  enrollment: string;
  action: 'created' | 'updated';
  fingerprint_length: number;
  primary_finger: string;
  pin_set: boolean;
  enrolled_by: string;
}

export interface AdminResetResult {
  user: string;
  action: 'unlocked' | 'deleted';
}

export interface PinChangeResult {
  user: string;
  /** `pin_set` when this was a first PIN, `pin_changed` when replacing one. */
  action: 'pin_changed' | 'pin_set' | 'pin_set_by_admin';
  changed_at: string;
}

export interface MyPinStatus {
  user: string;
  has_enrollment: 0 | 1;
  /** 0 when the user has never set a PIN — the dialog then skips the "current PIN" field. */
  has_pin: 0 | 1;
  /** 1 for captains / managers / admins, who may set a PIN for someone else. */
  can_set_for_others: 0 | 1;
}

const MODULE = 'ury.ury.biometric.api';

export async function getPublicBiometricSettings(): Promise<PublicBiometricSettings> {
  const res = await call.get<{ message: PublicBiometricSettings }>(
    `${MODULE}.get_public_settings`
  );
  return res.message ?? { enabled: 0, issonline_ws_url: '' };
}

export async function searchUsersForLogin(query: string): Promise<LoginUserCandidate[]> {
  if (!query || !query.trim()) return [];
  const res = await call.get<{ message: LoginUserCandidate[] }>(
    `${MODULE}.search_users_for_login`,
    { query }
  );
  return res.message ?? [];
}

export async function getEnrollmentTemplateForLogin(
  username: string
): Promise<EnrollmentTemplateLookup> {
  const res = await call.get<{ message: EnrollmentTemplateLookup }>(
    `${MODULE}.get_enrollment_template_for_login`,
    { username }
  );
  return res.message;
}

export async function biometricLogin(args: {
  username: string;
  captured_template_b64: string;
  match_score: number;
  terminal?: string | null;
}): Promise<LoginResult> {
  const res = await call.post<{ message: LoginResult }>(`${MODULE}.biometric_login`, {
    username: args.username,
    captured_template_b64: args.captured_template_b64,
    match_score: args.match_score,
    terminal: args.terminal ?? null,
  });
  return res.message;
}

export async function pinLogin(args: {
  username: string;
  pin: string;
  terminal?: string | null;
}): Promise<LoginResult> {
  const res = await call.post<{ message: LoginResult }>(`${MODULE}.pin_login`, {
    username: args.username,
    pin: args.pin,
    terminal: args.terminal ?? null,
  });
  return res.message;
}

export async function enrollBiometric(args: {
  user: string;
  fingerprint_template_b64: string;
  primary_finger?: string;
  pin?: string;
}): Promise<EnrollResult> {
  const res = await call.post<{ message: EnrollResult }>(`${MODULE}.enroll_biometric`, {
    user: args.user,
    fingerprint_template_b64: args.fingerprint_template_b64,
    primary_finger: args.primary_finger ?? 'Right Index',
    pin: args.pin ?? null,
  });
  return res.message;
}

export async function adminResetEnrollment(
  user: string,
  options: { delete?: boolean } = {}
): Promise<AdminResetResult> {
  const res = await call.post<{ message: AdminResetResult }>(
    `${MODULE}.admin_reset_enrollment`,
    { user, delete: options.delete ? 1 : 0 }
  );
  return res.message;
}

/**
 * Set or change the signed-in user's own PIN.
 *
 * `old_pin` is optional: omit it when the user has no PIN yet (check
 * `getMyPinStatus().has_pin` first). The backend still REQUIRES it
 * whenever a PIN already exists, so leaving it out is not a bypass.
 */
export async function changePin(args: {
  old_pin?: string;
  new_pin: string;
  terminal?: string | null;
}): Promise<PinChangeResult> {
  const res = await call.post<{ message: PinChangeResult }>(`${MODULE}.change_pin`, args);
  return res.message;
}

/** Whether the signed-in user already has a PIN, and may set others'. */
export async function getMyPinStatus(): Promise<MyPinStatus> {
  const res = await call.get<{ message: MyPinStatus }>(`${MODULE}.get_my_pin_status`);
  return res.message;
}

/**
 * Captain / administrator sets another user's PIN. No old PIN needed —
 * this is the recovery path for a forgotten or never-set PIN. Every call
 * is recorded in the URY PIN Change Log.
 */
export async function adminSetUserPin(args: {
  user: string;
  new_pin: string;
  terminal?: string | null;
}): Promise<PinChangeResult> {
  const res = await call.post<{ message: PinChangeResult }>(
    `${MODULE}.admin_set_user_pin`,
    args
  );
  return res.message;
}

export async function recordPasswordLogin(terminal?: string | null): Promise<void> {
  try {
    await call.post(`${MODULE}.record_password_login`, { terminal: terminal ?? null });
  } catch {
    /* non-fatal — tracking only */
  }
}
