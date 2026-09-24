"""Pre-flight connection test for branch → cloud sync.

Answers, in one click, the questions that are otherwise only answerable by
enabling sync on a live site and watching the queue fail:

  1. Is the remote configured at all, and is it not this same site?
  2. Is the remote reachable?
  3. Are the API credentials accepted?
  4. Is ExPOS installed there, and new enough to contain the sync module?
  5. Has it been migrated (does `URY Remote Sale` exist)?
  6. Is it a CLOUD site, or is it itself a branch that will refuse sales?
  7. Do both sides agree on the payload version?

── Why each check is separate ───────────────────────────────────────────
Every one of these fails with the same symptom through the delivery path:
a queue row sitting in `Retrying` with a one-line error. Collapsing them
into a single "connection failed" would leave the operator guessing which
of seven things to fix. So the report is per-check, and each failure
carries the specific remedy.

The credentials check and the ExPOS check are deliberately TWO separate
HTTP calls, against a core Frappe method and then the ExPOS ping. Without
that split, a 403 is ambiguous — bad key, or the method not existing? With
it, "core method OK but ping 404" says precisely: credentials are fine,
ExPOS is missing.

⚠ This test builds its URL and auth headers with `transport.remote_method_url`
and `transport.auth_headers` — the same helpers the real push uses. It must
stay that way. A test that authenticates differently from the delivery path
can pass while every sale fails, which is worse than having no test.
"""

import json

import frappe
from frappe import _

from ury.ury.sync import payload as payload_builder
from ury.ury.sync import transport

SETTINGS_DOCTYPE = "URY Sync Settings"

PASS = "pass"
FAIL = "fail"
WARN = "warn"
SKIP = "skip"


def _require_sync_admin():
	"""Reading this test implies reading the remote's identity and whether
	the credentials work. Keep it with the people who own the settings."""
	user = frappe.session.user
	if user == "Administrator":
		return
	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "URY Manager"}:
		return
	frappe.throw(
		_("Only an ExPOS Manager or System Manager can test the sync connection."),
		frappe.PermissionError,
		title=_("Not Permitted"),
	)


def _check(key, label, status, detail, remedy=None):
	return {
		"key": key,
		"label": label,
		"status": status,
		"detail": detail,
		"remedy": remedy or "",
	}


def _call_remote(settings, method):
	"""POST a no-argument whitelisted method on the remote.

	Returns (status_code, body, exception). POST rather than GET because the
	delivery path posts, and token auth on a POST is already proven to work
	here — no reason for the test to exercise a different shape.
	"""
	import requests

	try:
		response = requests.post(
			transport.remote_method_url(settings, method),
			headers=transport.auth_headers(settings),
			data=json.dumps({}),
			timeout=transport.request_timeout(settings),
		)
	except Exception as exc:  # DNS, TLS, timeout, connection refused
		return None, None, exc

	try:
		body = response.json()
	except ValueError:
		body = response.text
	return response.status_code, body, None


def _describe_transport_error(exc):
	"""Turn a requests exception into something an operator can act on."""
	name = type(exc).__name__
	text = str(exc)
	if "Name or service not known" in text or "nodename nor servname" in text:
		return "The hostname could not be resolved (DNS)."
	if "Connection refused" in text:
		return "The host answered but refused the connection on that port."
	if "SSLError" in name or "CERTIFICATE" in text.upper():
		return f"TLS/certificate problem: {text[:200]}"
	if "Timeout" in name:
		return "The request timed out before the site answered."
	return f"{name}: {text[:200]}"


def _missing_method_reason(status, body):
	"""Detect "the remote has no such method", and say WHY.

	⚠ Verified against a real site rather than assumed, and the assumption
	was wrong: a missing whitelisted method does NOT reliably come back as
	404. Frappe wraps the import failure and returns **HTTP 417
	ValidationError** with "Failed to get method for command ... No module
	named ...". Classifying that as a generic unexpected response produced a
	useless "check the error log" remedy for what is by far the most common
	setup mistake — a cloud site running an ExPOS build older than sync.

	Returns (detail, remedy) or None.
	"""
	blob = body if isinstance(body, str) else json.dumps(body, default=str)

	deploy_remedy = (
		"That site's ExPOS predates branch→cloud sync. Deploy the ExPOS build "
		"that contains ury/ury/sync to the cloud site, then run "
		"bench --site <cloud> migrate and bench restart."
	)

	if "No module named 'ury.ury.sync'" in blob or 'No module named "ury.ury.sync"' in blob:
		return (
			"ExPOS IS installed on the remote, but that version has no sync module.",
			deploy_remedy,
		)
	if "No module named 'ury'" in blob or 'No module named "ury"' in blob:
		return (
			"ExPOS (ury) is not installed on the remote site at all.",
			"Install ExPOS there: bench --site <cloud> install-app ury, then migrate.",
		)
	if "has no attribute 'ping'" in blob or 'has no attribute "ping"' in blob:
		return (
			"The remote has the sync module but no ping endpoint, so it is older "
			"than the connection test.",
			deploy_remedy,
		)
	if status == 404 or "Failed to get method" in blob or "Method Not Found" in blob:
		return (
			f"The remote has no {transport.PING_METHOD} method (HTTP {status}).",
			deploy_remedy,
		)
	return None


@frappe.whitelist()
def test_connection():
	"""Run every pre-flight check and return a per-check report.

	Returns `{ok, remote_site, checks: [...]}`. `ok` is 1 only when nothing
	failed; warnings do not block it.

	Safe to run on a live site: it only reads. It never sends a sale, and it
	never writes to the remote.
	"""
	_require_sync_admin()

	# Deliberately NOT get_cached_doc — the operator has usually just edited
	# these values, and testing a cached copy would test the wrong thing.
	settings = frappe.get_doc(SETTINGS_DOCTYPE)
	checks = []
	remote_site = None

	# ── 1. Configuration ────────────────────────────────────────────────
	url = (settings.remote_url or "").strip()
	missing = []
	if not url:
		missing.append("Remote Site URL")
	if not (settings.remote_api_key or "").strip():
		missing.append("API Key")
	if not settings.get_password("remote_api_secret", raise_exception=False):
		missing.append("API Secret")

	if missing:
		checks.append(
			_check(
				"config",
				"Settings complete",
				FAIL,
				"Missing: " + ", ".join(missing),
				"Fill these in and save before testing.",
			)
		)
		return {"ok": 0, "remote_site": None, "checks": checks}

	if not url.lower().startswith(("http://", "https://")):
		checks.append(
			_check(
				"config",
				"Settings complete",
				FAIL,
				f"Remote Site URL has no scheme: {url}",
				"Write it in full, e.g. https://cloud.example.com",
			)
		)
		return {"ok": 0, "remote_site": None, "checks": checks}

	this_site = frappe.local.site or ""
	if this_site and this_site in url:
		checks.append(
			_check(
				"config",
				"Remote is a different site",
				FAIL,
				f"The remote URL points at this same site ({this_site}).",
				"A site cannot sync to itself. Point this at the cloud site.",
			)
		)
		return {"ok": 0, "remote_site": None, "checks": checks}

	checks.append(
		_check("config", "Settings complete", PASS, f"Remote: {url}")
	)

	# ── 2. Reachable + credentials (core Frappe method) ─────────────────
	status, body, exc = _call_remote(settings, transport.AUTH_PROBE_METHOD)

	if exc is not None:
		checks.append(
			_check(
				"reachable",
				"Site reachable",
				FAIL,
				_describe_transport_error(exc),
				"Check the URL, DNS, and that the site is up and allows this server.",
			)
		)
		return {"ok": 0, "remote_site": None, "checks": checks}

	checks.append(_check("reachable", "Site reachable", PASS, f"HTTP {status}"))

	if status in (401, 403):
		checks.append(
			_check(
				"credentials",
				"API credentials accepted",
				FAIL,
				f"The remote rejected the key pair (HTTP {status}).",
				"Regenerate the API key/secret on the cloud site's User and paste both again.",
			)
		)
		return {"ok": 0, "remote_site": None, "checks": checks}

	if status != 200:
		checks.append(
			_check(
				"credentials",
				"API credentials accepted",
				FAIL,
				f"Unexpected HTTP {status} from {transport.AUTH_PROBE_METHOD}: {transport._short(body, 200)}",
				"That URL may not be a Frappe site, or a proxy is in the way.",
			)
		)
		return {"ok": 0, "remote_site": None, "checks": checks}

	remote_user = body.get("message") if isinstance(body, dict) else None
	checks.append(
		_check(
			"credentials",
			"API credentials accepted",
			PASS,
			f"Authenticated as {remote_user or 'unknown user'}",
		)
	)

	# ── 3. ExPOS installed there, new enough to have the sync module ────
	status, body, exc = _call_remote(settings, transport.PING_METHOD)

	if exc is not None:
		checks.append(
			_check(
				"expos",
				"ExPOS installed on remote",
				FAIL,
				_describe_transport_error(exc),
				"The site answered the first call but not this one — retry, then check its logs.",
			)
		)
		return {"ok": 0, "remote_site": None, "checks": checks}

	absence = _missing_method_reason(status, body)
	if absence:
		detail, remedy = absence
		checks.append(
			_check("expos", "ExPOS installed on remote", FAIL, detail, remedy)
		)
		return {"ok": 0, "remote_site": None, "checks": checks}

	if status != 200 or not isinstance(body, dict) or not isinstance(body.get("message"), dict):
		checks.append(
			_check(
				"expos",
				"ExPOS installed on remote",
				FAIL,
				f"HTTP {status}: {transport._short(body, 200)}",
				"ExPOS answered unexpectedly. Check the cloud site's error log.",
			)
		)
		return {"ok": 0, "remote_site": None, "checks": checks}

	info = body["message"]
	remote_site = info.get("site")
	checks.append(
		_check(
			"expos",
			"ExPOS installed on remote",
			PASS,
			f"Confirmed on site '{remote_site or 'unknown'}'",
		)
	)

	# ── 4. Migrated (the mirror doctype has to exist to store anything) ─
	if info.get("mirror_doctype_ready"):
		checks.append(
			_check("migrated", "Remote is migrated", PASS, "URY Remote Sale exists.")
		)
	else:
		checks.append(
			_check(
				"migrated",
				"Remote is migrated",
				FAIL,
				"ExPOS is installed but URY Remote Sale does not exist.",
				"Run bench --site <cloud> migrate, then test again.",
			)
		)

	# ── 5. Is it actually a CLOUD site? ─────────────────────────────────
	if info.get("sync_enabled"):
		checks.append(
			_check(
				"role",
				"Remote is a cloud site",
				FAIL,
				"That site has outbound sync ENABLED, so it is itself a branch.",
				"A branch cannot receive. Untick Sync Enabled there, or point this "
				"at the real cloud site.",
			)
		)
	else:
		checks.append(
			_check(
				"role",
				"Remote is a cloud site",
				PASS,
				"Outbound sync is off there, so it can receive.",
			)
		)

	# ── 6. Payload version agreement ────────────────────────────────────
	local_version = payload_builder.PAYLOAD_VERSION
	remote_version = info.get("payload_version")
	if remote_version == local_version:
		checks.append(
			_check(
				"version",
				"Payload version matches",
				PASS,
				f"Both sides on v{local_version}.",
			)
		)
	else:
		checks.append(
			_check(
				"version",
				"Payload version matches",
				WARN,
				f"This site sends v{local_version}; the remote expects v{remote_version}.",
				"Update whichever side is behind so both run the same ExPOS version.",
			)
		)

	failed = [c for c in checks if c["status"] == FAIL]
	return {"ok": 0 if failed else 1, "remote_site": remote_site, "checks": checks}


def run_connection_test():
	"""Readable wrapper for `bench --site <branch> execute
	ury.ury.sync.diagnostics.run_connection_test`.

	Same checks as the desk button, printed instead of returned, so the test
	is usable on a headless bench.
	"""
	result = test_connection()
	glyph = {PASS: "PASS", FAIL: "FAIL", WARN: "WARN", SKIP: "SKIP"}

	print("\n=== ExPOS sync connection test ===")
	for check in result["checks"]:
		print(f"  [{glyph.get(check['status'], '????')}] {check['label']}")
		if check["detail"]:
			print(f"         {check['detail']}")
		if check["remedy"]:
			print(f"         → {check['remedy']}")
	verdict = "READY" if result["ok"] else "NOT READY"
	print(f"\n=== {verdict} ===")
	if result.get("remote_site"):
		print(f"  remote site: {result['remote_site']}")
	print()
	return result
