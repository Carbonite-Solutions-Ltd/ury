"""HTTP delivery of a sale payload to the remote (cloud) URY site.

Kept separate from `worker.py` so the delivery mechanics and the queue
mechanics can be reasoned about — and failed — independently.

── The classification rule, which is the important part ────────────────
`classify_failure` decides whether a failure is TRANSIENT (retry forever)
or PERMANENT (stop, tell a human). Getting this backwards is expensive in
both directions: a transient failure marked permanent silently loses a
sale from head office's books, and a permanent one marked transient
retries a payload that can never succeed until the end of time.

So the rule is deliberately lopsided: **only an explicit application-level
rejection from the receiver is permanent.** Everything else — timeouts,
DNS failures, 5xx, and even 401/403 — is transient. Bad credentials are
worth retrying because they are a configuration mistake that someone will
fix, and retrying then succeeds on its own; marking those rows Failed
would mean re-queueing every one of them by hand afterwards.
"""

import json

import frappe
from frappe.utils import now_datetime

RECEIVER_METHOD = "ury.ury.sync.receiver.receive_sale"
PING_METHOD = "ury.ury.sync.receiver.ping"

# A core method every Frappe site has, used to test credentials on their
# own — separately from whether ExPOS is installed. That separation is what
# lets the connection test say "the key is wrong" instead of "something is
# wrong", which is the whole point of having a test button.
AUTH_PROBE_METHOD = "frappe.auth.get_logged_user"


class PermanentRejection(Exception):
	"""The receiver understood the payload and refused it. Do not retry."""


def classify_failure(status_code=None, body=None, exception=None):
	"""Return (is_permanent, message).

	Pure enough to test directly — no network, no site.
	"""
	if exception is not None:
		return False, f"{type(exception).__name__}: {exception}"

	# An explicit, understood refusal is the ONLY permanent outcome.
	if status_code == 200 and isinstance(body, dict):
		message = body.get("message") if isinstance(body.get("message"), dict) else body
		if isinstance(message, dict) and message.get("status") == "rejected":
			return True, f"Rejected by remote: {message.get('reason') or 'no reason given'}"

	if status_code and 400 <= status_code < 500:
		# Includes 401/403 (fix the key and the retries succeed) and 417
		# (Frappe's ValidationError). Transient on purpose — see above.
		return False, f"HTTP {status_code}: {_short(body)}"

	if status_code and status_code >= 500:
		return False, f"HTTP {status_code}: {_short(body)}"

	return False, f"Unexpected response (HTTP {status_code}): {_short(body)}"


def _short(body, limit=400):
	if body is None:
		return ""
	text = body if isinstance(body, str) else json.dumps(body, default=str)
	return text[:limit]


def remote_base(settings):
	"""The remote site root, with any trailing slash removed."""
	return (settings.remote_url or "").rstrip("/")


def remote_method_url(settings, method):
	return f"{remote_base(settings)}/api/method/{method}"


def auth_headers(settings):
	"""Frappe token auth for the configured key pair.

	⚠ Shared with the connection test on purpose. If the test built its own
	header it could pass while a real push failed (or the reverse), which
	would make the test worse than having none.
	"""
	secret = settings.get_password("remote_api_secret", raise_exception=False)
	return {
		"Authorization": f"token {settings.remote_api_key}:{secret}",
		"Content-Type": "application/json",
		"Accept": "application/json",
	}


def request_timeout(settings):
	return int(settings.connection_timeout_seconds or 30)


def push_sale(payload, settings):
	"""Deliver one sale payload. Raises PermanentRejection, or any other
	Exception for a transient failure.

	Returns the remote's parsed `message` on success.
	"""
	import requests

	url = remote_method_url(settings, RECEIVER_METHOD)
	headers = auth_headers(settings)
	timeout = request_timeout(settings)

	try:
		response = requests.post(
			url,
			headers=headers,
			data=json.dumps({"payload": payload}, default=str),
			timeout=timeout,
		)
	except Exception as exc:  # network-level: DNS, timeout, reset
		permanent, message = classify_failure(exception=exc)
		raise RuntimeError(message) from exc

	try:
		body = response.json()
	except ValueError:
		body = response.text

	if response.status_code == 200 and isinstance(body, dict):
		message = body.get("message")
		if isinstance(message, dict) and message.get("status") == "accepted":
			return message

	permanent, message = classify_failure(
		status_code=response.status_code, body=body
	)
	if permanent:
		raise PermanentRejection(message)
	raise RuntimeError(message)


def record_outcome(settings, error=None):
	"""Keep a breadcrumb on the settings doc so someone can see at a glance
	whether sync is actually working, without reading the queue."""
	values = {}
	if error:
		values["last_error"] = str(error)[:1000]
		values["last_error_at"] = now_datetime()
	else:
		values["last_success_at"] = now_datetime()
		values["last_error"] = None
	frappe.db.set_value(
		"URY Sync Settings", "URY Sync Settings", values, update_modified=False
	)
