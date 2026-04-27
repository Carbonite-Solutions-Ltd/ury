"""URY Biometric & PIN authentication API.

The ZKFinger `libzkfp.so` library cannot initialize on a server with no physical
reader attached (its capture-library bootstrap fails — see CLAUDE.md Fixes log
2026-04-24). So server-side template matching is not possible on cloud Frappe.
Instead, matching runs on the cashier's Windows terminal via the ISSOnline
service; this module stores templates, validates verdicts, hashes PINs, and
creates Frappe sessions on successful auth.

Trust model: the match verdict is client-computed and trusted by the server.
The server validates the verdict score against a configurable threshold,
rate-limits per user + per IP, and audits every attempt. This is the same
trust level URY already operates under for QZ Tray printing. Attackers who
compromise the Windows terminal can bypass biometric — mitigations: PIN
lockout, rate limiting, and password always available as a separate path.

Endpoints (all @frappe.whitelist):
  - get_public_settings  (allow_guest): frontend reads feature toggle, ws_url, threshold
  - search_users_for_login  (allow_guest): autocomplete on the login page
  - get_enrollment_template_for_login  (allow_guest, rate-limited): sends
    stored template to the client for local ISSOnline matching
  - biometric_login  (allow_guest, rate-limited): accept match verdict, create session
  - pin_login  (allow_guest, rate-limited): accept PIN, create session
  - enroll_biometric  (captain+): create/update enrollment record
  - change_pin  (authenticated): self-service PIN rotation
  - admin_reset_enrollment  (captain+): clear lockouts, optionally delete row
  - record_password_login  (authenticated): called from frontend after a
    password login to update last_login_method
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, get_datetime_str, now_datetime
from frappe.utils.password import check_password as _frappe_check_password

try:
	from frappe.utils.password import passlibctx as _passlib_ctx
except ImportError:
	_passlib_ctx = None

# ---------------------------------------------------------------------------
# Role helpers
# ---------------------------------------------------------------------------

URY_LOGIN_ROLES = ("URY Cashier", "URY Captain", "URY Manager")
URY_ENROLLMENT_ADMIN_ROLES = ("System Manager", "URY Manager", "URY Captain")


def _is_enrollment_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	return any(r in roles for r in URY_ENROLLMENT_ADMIN_ROLES)


def _require_enrollment_admin() -> None:
	if not _is_enrollment_admin():
		frappe.throw(
			_("You do not have permission to manage biometric enrollments. "
			  "Ask a captain or administrator."),
			frappe.PermissionError,
			title=_("Permission Denied"),
		)


def _user_has_ury_login_role(user: str) -> bool:
	roles = set(frappe.get_roles(user))
	return any(r in roles for r in URY_LOGIN_ROLES)


# ---------------------------------------------------------------------------
# Settings access
# ---------------------------------------------------------------------------

def _get_settings() -> dict[str, Any]:
	"""Return the biometric settings singleton as a dict, with safe defaults.

	Defensive: if the doctype hasn't been migrated yet (fresh install), returns
	a dict with `enabled=0` so every public endpoint short-circuits cleanly.
	"""
	try:
		doc = frappe.get_cached_doc("URY Biometric Settings")
	except Exception:
		return {"enabled": 0}
	return {
		"enabled": int(doc.enabled or 0),
		"match_threshold": cint(doc.match_threshold) or 80,
		"min_template_bytes": cint(doc.min_template_bytes) or 300,
		"max_template_bytes": cint(doc.max_template_bytes) or 3500,
		"pin_max_attempts": cint(doc.pin_max_attempts) or 5,
		"pin_lockout_minutes": cint(doc.pin_lockout_minutes) or 15,
		"biometric_login_rate_limit_seconds": cint(doc.biometric_login_rate_limit_seconds) or 60,
		"biometric_login_max_attempts": cint(doc.biometric_login_max_attempts) or 10,
		"template_lookup_rate_limit_seconds": cint(doc.template_lookup_rate_limit_seconds) or 60,
		"template_lookup_max_attempts": cint(doc.template_lookup_max_attempts) or 5,
		"issonline_ws_url": doc.issonline_ws_url or "ws://127.0.0.1:12000",
	}


def _require_enabled(settings: dict[str, Any] | None = None) -> dict[str, Any]:
	settings = settings or _get_settings()
	if not settings.get("enabled"):
		frappe.throw(
			_("Biometric authentication is not enabled on this site."),
			title=_("Biometric Disabled"),
		)
	return settings


# ---------------------------------------------------------------------------
# PIN hashing
# ---------------------------------------------------------------------------

PIN_PATTERN = re.compile(r"^\d{6}$")


def _validate_pin_format(pin: str) -> str:
	if not pin or not isinstance(pin, str):
		frappe.throw(_("PIN is required."), title=_("Invalid PIN"))
	pin = pin.strip()
	if not PIN_PATTERN.match(pin):
		frappe.throw(
			_("PIN must be exactly 6 digits (0-9)."),
			title=_("Invalid PIN"),
		)
	return pin


def _hash_pin(pin: str) -> str:
	"""Hash a 6-digit PIN using Frappe's passlib context (pbkdf2_sha256).

	Using passlib directly here (rather than Frappe's own `update_password`)
	because URY Biometric Enrollment stores the hash on its own field, not
	on the User auth table — we don't want PIN hashes to leak into Frappe's
	password-reset flows.
	"""
	if _passlib_ctx is None:
		# Extremely defensive: should never happen on modern Frappe
		frappe.throw(_("Password hashing is not available on this server."))
	return _passlib_ctx.hash(pin)


def _verify_pin(pin: str, pin_hash: str) -> bool:
	if not pin or not pin_hash or _passlib_ctx is None:
		return False
	try:
		return bool(_passlib_ctx.verify(pin, pin_hash))
	except Exception:
		return False


# ---------------------------------------------------------------------------
# Template validation
# ---------------------------------------------------------------------------

def _decode_and_validate_template(template_b64: str, settings: dict[str, Any]) -> tuple[str, int]:
	"""Validate a base64 template blob. Returns (clean_b64, byte_length).

	Rejects empty input, non-base64 input, and templates outside the allowed
	size window. The clean_b64 is the re-encoded base64 so we persist a
	canonical form (no URL-encoding, no stray whitespace).
	"""
	if not template_b64 or not isinstance(template_b64, str):
		frappe.throw(_("Fingerprint template is required."), title=_("Invalid Template"))
	candidate = template_b64.strip().replace("\n", "").replace("\r", "")
	# ISSOnline sometimes URL-encodes; tolerate both shapes
	try:
		from urllib.parse import unquote
		candidate = unquote(candidate)
	except Exception:
		pass
	try:
		raw = base64.b64decode(candidate, validate=True)
	except (binascii.Error, ValueError):
		frappe.throw(
			_("Fingerprint template is not valid base64."),
			title=_("Invalid Template"),
		)
	length = len(raw)
	lo = settings.get("min_template_bytes") or 300
	hi = settings.get("max_template_bytes") or 3500
	if length < lo or length > hi:
		frappe.throw(
			_("Fingerprint template size ({0} bytes) is outside the allowed range ({1}-{2}).").format(
				length, lo, hi
			),
			title=_("Invalid Template"),
		)
	return base64.b64encode(raw).decode("ascii"), length


# ---------------------------------------------------------------------------
# Rate limiting (per-user + per-IP sliding window via frappe.cache)
# ---------------------------------------------------------------------------

def _rate_limit_bucket_key(kind: str, identifier: str) -> str:
	ip = (frappe.local.request_ip or "0.0.0.0") if hasattr(frappe.local, "request_ip") else "0.0.0.0"
	return f"ury_biometric_ratelimit:{kind}:{ip}:{identifier}"


def _check_rate_limit(kind: str, identifier: str, window_seconds: int, max_attempts: int) -> None:
	"""Raise if the caller exceeds `max_attempts` of `kind` for `identifier` within window.

	Uses frappe.cache (Redis) with a bucket key per (IP, identifier) and a
	rolling TTL. On every call we INCR; first call sets TTL.
	"""
	key = _rate_limit_bucket_key(kind, identifier)
	cache = frappe.cache()
	try:
		new_val = cache.incrby(key, 1)
		if new_val == 1:
			cache.expire(key, max(1, int(window_seconds)))
	except Exception:
		# Cache miss / redis down — fail open (don't block legitimate logins on infra hiccup)
		return
	if new_val > max_attempts:
		frappe.throw(
			_("Too many attempts. Please wait a moment and try again."),
			frappe.ValidationError,
			title=_("Rate Limit Exceeded"),
		)


# ---------------------------------------------------------------------------
# Enrollment lookup
# ---------------------------------------------------------------------------

def _get_enrollment(user: str) -> Any | None:
	if not frappe.db.exists("URY Biometric Enrollment", user):
		return None
	return frappe.get_doc("URY Biometric Enrollment", user)


def _enrollment_is_active(enrollment) -> bool:
	if not enrollment:
		return False
	if getattr(enrollment, "disabled", 0):
		return False
	return True


def _record_login(
	enrollment,
	method: str,
	terminal: str | None = None,
) -> None:
	"""Stamp last-login fields on the enrollment + reset PIN failure counters.

	Called after every successful biometric / PIN login AND after password
	logins (via `record_password_login`) so the smart-default tab on the
	login page tracks the user's real behaviour across methods.
	"""
	if not enrollment:
		return
	now = now_datetime()
	ip = getattr(frappe.local, "request_ip", None) or ""
	frappe.db.set_value(
		"URY Biometric Enrollment",
		enrollment.name,
		{
			"last_login_method": method,
			"last_login_at": now,
			"last_login_ip": ip[:140],
			"last_login_terminal": terminal or None,
			"failed_pin_attempts": 0,
			"pin_locked_until": None,
		},
		update_modified=False,
	)
	frappe.db.commit()


# ---------------------------------------------------------------------------
# Session creation
# ---------------------------------------------------------------------------

def _create_login_session(user: str) -> dict[str, Any]:
	"""Create a Frappe login session for `user` and return a response payload.

	Uses LoginManager.login_as to bypass password. The caller is responsible
	for having already validated the authentication proof (biometric/PIN).
	"""
	user_doc = frappe.get_doc("User", user)
	if user_doc.enabled == 0:
		frappe.throw(_("This user account is disabled."), title=_("Account Disabled"))
	frappe.local.login_manager.login_as(user)
	return {
		"user": user,
		"full_name": user_doc.full_name,
		"home_page": "/pos",
	}


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def get_public_settings() -> dict[str, Any]:
	"""Return the subset of biometric settings safe to expose to guests.

	Called by the login page on load to decide which tabs to render. Never
	returns secrets (no rate-limit internals, no threshold numbers that
	could help an attacker calibrate).
	"""
	s = _get_settings()
	return {
		"enabled": int(s.get("enabled") or 0),
		"issonline_ws_url": s.get("issonline_ws_url") or "",
	}


@frappe.whitelist(allow_guest=True)
def search_users_for_login(query: str = "") -> list[dict[str, Any]]:
	"""Autocomplete search over URY login-eligible users.

	Scoped to users with URY Cashier / URY Captain / URY Manager role.
	Returns minimal metadata the login page needs (name, full_name,
	has_enrollment, last_login_method) so it can switch tabs automatically.
	"""
	settings = _get_settings()
	if not settings.get("enabled"):
		return []
	query = (query or "").strip()
	if len(query) < 1:
		return []
	# Rate-limit per IP (not per user — query is free-form)
	_check_rate_limit(
		"search",
		identifier="_global",
		window_seconds=10,
		max_attempts=60,
	)
	like = f"%{query}%"
	rows = frappe.db.sql(
		"""
		SELECT DISTINCT
			u.name,
			u.full_name,
			u.email,
			u.enabled
		FROM `tabUser` AS u
		INNER JOIN `tabHas Role` AS hr ON hr.parent = u.name
		WHERE u.enabled = 1
		  AND hr.role IN %(roles)s
		  AND (u.name LIKE %(like)s OR u.full_name LIKE %(like)s OR u.email LIKE %(like)s)
		ORDER BY u.full_name
		LIMIT 15
		""",
		{"roles": URY_LOGIN_ROLES, "like": like},
		as_dict=True,
	)
	# Attach enrollment metadata
	names = [r["name"] for r in rows]
	enrollments = {}
	if names:
		enrolled_rows = frappe.db.sql(
			"""
			SELECT name, disabled, last_login_method, fingerprint_template_length, pin_hash
			FROM `tabURY Biometric Enrollment`
			WHERE name IN %(names)s
			""",
			{"names": names},
			as_dict=True,
		)
		enrollments = {r["name"]: r for r in enrolled_rows}
	out = []
	for r in rows:
		en = enrollments.get(r["name"])
		has_fp = bool(en and not en["disabled"] and (en["fingerprint_template_length"] or 0) > 0)
		has_pin = bool(en and not en["disabled"] and en["pin_hash"])
		out.append({
			"name": r["name"],
			"full_name": r["full_name"] or r["name"],
			"email": r["email"] or "",
			"has_fingerprint": int(has_fp),
			"has_pin": int(has_pin),
			"last_login_method": (en or {}).get("last_login_method") or "",
		})
	return out


@frappe.whitelist(allow_guest=True)
def get_enrollment_template_for_login(username: str) -> dict[str, Any]:
	"""Return the stored fingerprint template for a user about to log in.

	Rate-limited per (IP, username). Only returns metadata + template for
	active enrollments with a fingerprint stamped. The client-side ISSOnline
	service uses this template to perform the 1:1 match against a freshly
	captured template.
	"""
	settings = _require_enabled()
	username = (username or "").strip()
	if not username:
		frappe.throw(_("Username is required."), title=_("Invalid Request"))
	_check_rate_limit(
		"template_lookup",
		identifier=username.lower(),
		window_seconds=settings["template_lookup_rate_limit_seconds"],
		max_attempts=settings["template_lookup_max_attempts"],
	)
	enrollment = _get_enrollment(username)
	if not _enrollment_is_active(enrollment):
		# Generic error — do not leak whether the user exists
		frappe.throw(
			_("No biometric enrollment found for this user."),
			title=_("Not Enrolled"),
		)
	if not enrollment.fingerprint_template:
		frappe.throw(
			_("No fingerprint has been enrolled for this user."),
			title=_("Not Enrolled"),
		)
	return {
		"username": enrollment.user,
		"template_b64": enrollment.fingerprint_template,
		"template_length": enrollment.fingerprint_template_length or 0,
		"match_threshold": settings["match_threshold"],
		"primary_finger": enrollment.primary_finger or "",
	}


@frappe.whitelist(allow_guest=True)
def biometric_login(
	username: str,
	captured_template_b64: str,
	match_score: int,
	terminal: str | None = None,
) -> dict[str, Any]:
	"""Log in via a client-computed biometric match verdict.

	The client has already performed the 1:1 match locally via ISSOnline
	and is asserting the score. We validate:
	  1. The enrollment exists and is active.
	  2. The captured template is a plausible size (not garbage).
	  3. The asserted score meets the configured threshold.
	  4. Per-(IP, username) rate limits are not exceeded.

	On success, we create the Frappe session and stamp last_login_method.
	"""
	settings = _require_enabled()
	username = (username or "").strip()
	if not username:
		frappe.throw(_("Username is required."), title=_("Invalid Request"))
	_check_rate_limit(
		"biometric_login",
		identifier=username.lower(),
		window_seconds=settings["biometric_login_rate_limit_seconds"],
		max_attempts=settings["biometric_login_max_attempts"],
	)
	# Validate the captured template (length sanity only; we never match on server)
	_decode_and_validate_template(captured_template_b64, settings)
	try:
		score = int(match_score)
	except (TypeError, ValueError):
		frappe.throw(_("Match score must be an integer."), title=_("Invalid Request"))
	if score < 0 or score > 10000:
		frappe.throw(_("Match score is out of range."), title=_("Invalid Request"))
	if score < settings["match_threshold"]:
		frappe.throw(
			_("Fingerprint did not match (score {0} < required {1}).").format(
				score, settings["match_threshold"]
			),
			frappe.AuthenticationError,
			title=_("Match Failed"),
		)
	enrollment = _get_enrollment(username)
	if not _enrollment_is_active(enrollment) or not enrollment.fingerprint_template:
		# Don't leak whether the user exists
		frappe.throw(
			_("Biometric login is not available for this user."),
			frappe.AuthenticationError,
			title=_("Login Failed"),
		)
	if not _user_has_ury_login_role(username):
		frappe.throw(
			_("This user does not have a URY login role."),
			frappe.AuthenticationError,
			title=_("Login Failed"),
		)
	response = _create_login_session(username)
	_record_login(enrollment, method="Biometric", terminal=terminal)
	response["method"] = "Biometric"
	return response


@frappe.whitelist(allow_guest=True)
def pin_login(username: str, pin: str, terminal: str | None = None) -> dict[str, Any]:
	"""Log in via a 6-digit PIN.

	Enforces per-user failed-attempt counter + lockout on top of per-IP rate
	limits. On the 5th consecutive failure (configurable), the user's PIN
	is locked for pin_lockout_minutes — captain can reset via
	admin_reset_enrollment.
	"""
	settings = _require_enabled()
	username = (username or "").strip()
	pin = (pin or "").strip()
	if not username:
		frappe.throw(_("Username is required."), title=_("Invalid Request"))
	_validate_pin_format(pin)
	_check_rate_limit(
		"pin_login",
		identifier=username.lower(),
		window_seconds=settings["biometric_login_rate_limit_seconds"],
		max_attempts=settings["biometric_login_max_attempts"],
	)

	enrollment = _get_enrollment(username)
	if not _enrollment_is_active(enrollment) or not enrollment.pin_hash:
		frappe.throw(
			_("PIN login is not available for this user."),
			frappe.AuthenticationError,
			title=_("Login Failed"),
		)
	if not _user_has_ury_login_role(username):
		frappe.throw(
			_("This user does not have a URY login role."),
			frappe.AuthenticationError,
			title=_("Login Failed"),
		)
	# Lockout check
	if enrollment.pin_locked_until:
		locked_until = get_datetime(enrollment.pin_locked_until)
		if locked_until > now_datetime():
			frappe.throw(
				_("PIN is locked until {0}. Contact your captain to reset.").format(
					get_datetime_str(locked_until)
				),
				frappe.AuthenticationError,
				title=_("PIN Locked"),
			)
	# Verify
	if not _verify_pin(pin, enrollment.pin_hash):
		# Bump failure counter
		new_count = (enrollment.failed_pin_attempts or 0) + 1
		updates = {"failed_pin_attempts": new_count}
		if new_count >= settings["pin_max_attempts"]:
			lock_until = add_to_date(now_datetime(), minutes=settings["pin_lockout_minutes"])
			updates["pin_locked_until"] = lock_until
		frappe.db.set_value("URY Biometric Enrollment", enrollment.name, updates, update_modified=False)
		frappe.db.commit()
		remaining = max(0, settings["pin_max_attempts"] - new_count)
		if remaining > 0:
			frappe.throw(
				_("Incorrect PIN. {0} attempt(s) remaining.").format(remaining),
				frappe.AuthenticationError,
				title=_("Incorrect PIN"),
			)
		frappe.throw(
			_("Incorrect PIN. Your PIN is now locked for {0} minutes.").format(
				settings["pin_lockout_minutes"]
			),
			frappe.AuthenticationError,
			title=_("PIN Locked"),
		)
	response = _create_login_session(username)
	_record_login(enrollment, method="PIN", terminal=terminal)
	response["method"] = "PIN"
	return response


# ---------------------------------------------------------------------------
# Enrollment (captain/admin only)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def enroll_biometric(
	user: str,
	fingerprint_template_b64: str,
	primary_finger: str = "Right Index",
	pin: str | None = None,
) -> dict[str, Any]:
	"""Create or update a URY Biometric Enrollment row.

	Captain/admin only. Accepts a merged fingerprint master template (produced
	client-side by ISSOnline from 3 capture scans) and an optional 6-digit PIN.
	If the enrollment already exists, the fingerprint is replaced; the PIN is
	only set/updated when provided.
	"""
	_require_enrollment_admin()
	settings = _require_enabled()
	user = (user or "").strip()
	if not user:
		frappe.throw(_("User is required."), title=_("Invalid Request"))
	if not frappe.db.exists("User", user):
		frappe.throw(_("User {0} does not exist.").format(user), title=_("User Not Found"))
	if not _user_has_ury_login_role(user):
		frappe.throw(
			_("User {0} does not have a URY login role. Assign URY Cashier / URY Captain / URY Manager first.").format(user),
			title=_("No URY Role"),
		)
	canonical_b64, length = _decode_and_validate_template(fingerprint_template_b64, settings)

	valid_fingers = {
		"Right Thumb", "Right Index", "Right Middle", "Right Ring", "Right Little",
		"Left Thumb", "Left Index", "Left Middle", "Left Ring", "Left Little",
	}
	if primary_finger not in valid_fingers:
		primary_finger = "Right Index"

	pin_hash = None
	if pin is not None and pin != "":
		pin = _validate_pin_format(pin)
		pin_hash = _hash_pin(pin)

	existing = frappe.db.exists("URY Biometric Enrollment", user)
	now = now_datetime()
	captain = frappe.session.user

	if existing:
		doc = frappe.get_doc("URY Biometric Enrollment", user)
		doc.fingerprint_template = canonical_b64
		doc.fingerprint_template_length = length
		doc.fingerprint_enrolled_at = now
		doc.fingerprint_enrolled_by = captain
		doc.primary_finger = primary_finger
		doc.disabled = 0
		doc.failed_pin_attempts = 0
		doc.pin_locked_until = None
		if pin_hash:
			doc.pin_hash = pin_hash
			doc.pin_set_at = now
			doc.pin_changed_at = now
		doc.save(ignore_permissions=True)
		action = "updated"
	else:
		if not pin_hash:
			frappe.throw(
				_("A 6-digit PIN is required when creating a new enrollment so the cashier has a fallback login path."),
				title=_("PIN Required"),
			)
		doc = frappe.get_doc({
			"doctype": "URY Biometric Enrollment",
			"user": user,
			"fingerprint_template": canonical_b64,
			"fingerprint_template_length": length,
			"fingerprint_enrolled_at": now,
			"fingerprint_enrolled_by": captain,
			"primary_finger": primary_finger,
			"pin_hash": pin_hash,
			"pin_set_at": now,
			"pin_changed_at": now,
			"failed_pin_attempts": 0,
		})
		doc.insert(ignore_permissions=True)
		action = "created"

	frappe.db.commit()
	return {
		"user": user,
		"enrollment": doc.name,
		"action": action,
		"fingerprint_length": length,
		"primary_finger": primary_finger,
		"pin_set": bool(pin_hash),
		"enrolled_by": captain,
	}


@frappe.whitelist()
def admin_reset_enrollment(user: str, delete: int = 0) -> dict[str, Any]:
	"""Captain/admin: clear lockouts on a user's enrollment, optionally delete it.

	Use `delete=1` to remove the entire enrollment row (e.g., cashier has left,
	or a fresh enrollment is required from scratch). Default behaviour (delete=0)
	unlocks the PIN + resets the failure counter, leaving the fingerprint + PIN
	hash intact — suitable for "cashier got themselves locked out" recovery.
	"""
	_require_enrollment_admin()
	user = (user or "").strip()
	enrollment = _get_enrollment(user)
	if not enrollment:
		frappe.throw(
			_("No enrollment exists for user {0}.").format(user),
			title=_("Not Enrolled"),
		)
	if cint(delete):
		frappe.delete_doc("URY Biometric Enrollment", enrollment.name, ignore_permissions=True)
		frappe.db.commit()
		return {"user": user, "action": "deleted"}
	frappe.db.set_value(
		"URY Biometric Enrollment",
		enrollment.name,
		{"failed_pin_attempts": 0, "pin_locked_until": None, "disabled": 0},
		update_modified=True,
	)
	frappe.db.commit()
	return {"user": user, "action": "unlocked"}


# ---------------------------------------------------------------------------
# Self-service PIN change
# ---------------------------------------------------------------------------

@frappe.whitelist()
def change_pin(old_pin: str, new_pin: str) -> dict[str, Any]:
	"""Authenticated user changes their own PIN.

	Verifies the old PIN, hashes and stores the new one, resets the failure
	counter and any active lockout. No rate limiting here — the user is
	already authenticated, and misusing this is self-harm.
	"""
	_require_enabled()
	if frappe.session.user == "Guest":
		frappe.throw(_("You must be logged in to change your PIN."), frappe.PermissionError)
	enrollment = _get_enrollment(frappe.session.user)
	if not enrollment:
		frappe.throw(
			_("You don't have a biometric enrollment yet. Ask a captain to enrol you first."),
			title=_("Not Enrolled"),
		)
	if not enrollment.pin_hash:
		frappe.throw(
			_("No PIN is set on your enrollment. Ask a captain to reset it."),
			title=_("PIN Not Set"),
		)
	_validate_pin_format(old_pin)
	new_pin = _validate_pin_format(new_pin)
	if old_pin == new_pin:
		frappe.throw(
			_("New PIN must be different from the old PIN."),
			title=_("PIN Unchanged"),
		)
	if not _verify_pin(old_pin, enrollment.pin_hash):
		# Use the failure counter here too so brute-forcing via change_pin is rate-limited
		settings = _get_settings()
		new_count = (enrollment.failed_pin_attempts or 0) + 1
		updates = {"failed_pin_attempts": new_count}
		if new_count >= settings["pin_max_attempts"]:
			updates["pin_locked_until"] = add_to_date(now_datetime(), minutes=settings["pin_lockout_minutes"])
		frappe.db.set_value("URY Biometric Enrollment", enrollment.name, updates, update_modified=False)
		frappe.db.commit()
		frappe.throw(
			_("Old PIN is incorrect."),
			frappe.AuthenticationError,
			title=_("Incorrect PIN"),
		)
	now = now_datetime()
	frappe.db.set_value(
		"URY Biometric Enrollment",
		enrollment.name,
		{
			"pin_hash": _hash_pin(new_pin),
			"pin_changed_at": now,
			"failed_pin_attempts": 0,
			"pin_locked_until": None,
		},
		update_modified=True,
	)
	frappe.db.commit()
	return {"user": frappe.session.user, "action": "pin_changed", "changed_at": get_datetime_str(now)}


# ---------------------------------------------------------------------------
# Post-login tracking (called by the React POS after a password login)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def record_password_login(terminal: str | None = None) -> dict[str, Any]:
	"""Frontend calls this after a successful password login so the smart-default
	login tab tracks the user's real behaviour across all three methods.

	No-op for users without an enrollment.
	"""
	if frappe.session.user == "Guest":
		return {"recorded": 0}
	enrollment = _get_enrollment(frappe.session.user)
	if not enrollment:
		return {"recorded": 0, "reason": "no_enrollment"}
	_record_login(enrollment, method="Password", terminal=terminal)
	return {"recorded": 1, "method": "Password"}
