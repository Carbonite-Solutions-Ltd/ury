"""Unit tests for URY biometric + PIN authentication.

Per CLAUDE.md rule 6, `bench run-tests` is blocked on this site by a
pre-existing ERPNext bootstrap trap. Run these via:

    bench --site <site> execute ury.ury.biometric.test_biometric.run_biometric_tests

The tests cover pure-function logic (PIN hashing, template decoding,
rate-limit keys) that doesn't need a live Frappe test DB, plus a second
class that exercises the doctype + endpoint round trip against the
current site's DB (idempotent — cleans up after itself).
"""

from __future__ import annotations

import base64
import os
import secrets
import unittest

import frappe

from ury.ury.biometric import api as biometric_api


# ---------------------------------------------------------------------------
# Pure-function tests (no DB needed)
# ---------------------------------------------------------------------------

class PINFormatTests(unittest.TestCase):
	def test_valid_six_digit_pin_accepted(self):
		self.assertEqual(biometric_api._validate_pin_format("123456"), "123456")
		self.assertEqual(biometric_api._validate_pin_format("  987654  "), "987654")

	def test_short_pin_rejected(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			biometric_api._validate_pin_format("12345")

	def test_long_pin_rejected(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			biometric_api._validate_pin_format("1234567")

	def test_non_digit_pin_rejected(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			biometric_api._validate_pin_format("12345a")

	def test_empty_pin_rejected(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			biometric_api._validate_pin_format("")

	def test_none_pin_rejected(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			biometric_api._validate_pin_format(None)  # type: ignore[arg-type]


class PINHashTests(unittest.TestCase):
	def test_hash_roundtrip_verifies(self):
		h = biometric_api._hash_pin("112233")
		self.assertTrue(biometric_api._verify_pin("112233", h))

	def test_hash_rejects_wrong_pin(self):
		h = biometric_api._hash_pin("112233")
		self.assertFalse(biometric_api._verify_pin("112234", h))

	def test_same_pin_different_hashes(self):
		# pbkdf2_sha256 must use a unique salt per call
		h1 = biometric_api._hash_pin("112233")
		h2 = biometric_api._hash_pin("112233")
		self.assertNotEqual(h1, h2, "hash should differ due to random salt")

	def test_empty_hash_not_verified(self):
		self.assertFalse(biometric_api._verify_pin("112233", ""))
		self.assertFalse(biometric_api._verify_pin("", "whatever"))


class TemplateValidationTests(unittest.TestCase):
	def _settings(self, lo: int = 300, hi: int = 3500) -> dict:
		return {"min_template_bytes": lo, "max_template_bytes": hi}

	def _valid_blob(self, size: int = 1200) -> str:
		return base64.b64encode(os.urandom(size)).decode("ascii")

	def test_valid_template_accepted(self):
		blob = self._valid_blob(1200)
		clean, length = biometric_api._decode_and_validate_template(blob, self._settings())
		self.assertEqual(length, 1200)
		self.assertEqual(clean, blob)

	def test_template_too_small_rejected(self):
		blob = self._valid_blob(50)
		with self.assertRaises(frappe.exceptions.ValidationError):
			biometric_api._decode_and_validate_template(blob, self._settings())

	def test_template_too_large_rejected(self):
		blob = self._valid_blob(4000)
		with self.assertRaises(frappe.exceptions.ValidationError):
			biometric_api._decode_and_validate_template(blob, self._settings())

	def test_empty_template_rejected(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			biometric_api._decode_and_validate_template("", self._settings())

	def test_non_base64_rejected(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			biometric_api._decode_and_validate_template("this is not base64!!", self._settings())

	def test_whitespace_stripped(self):
		blob = self._valid_blob(1200)
		padded = "  \n" + blob + "\r\n"
		clean, length = biometric_api._decode_and_validate_template(padded, self._settings())
		self.assertEqual(length, 1200)
		self.assertEqual(clean, blob)

	def test_url_encoded_template_accepted(self):
		raw = os.urandom(1200)
		# Simulate ISSOnline's sometimes-URL-encoded output: = → %3D, / → %2F
		b64 = base64.b64encode(raw).decode("ascii")
		url_encoded = b64.replace("=", "%3D").replace("/", "%2F").replace("+", "%2B")
		clean, length = biometric_api._decode_and_validate_template(url_encoded, self._settings())
		self.assertEqual(length, 1200)


class SettingsDefaultsTests(unittest.TestCase):
	def test_get_settings_returns_dict(self):
		s = biometric_api._get_settings()
		self.assertIsInstance(s, dict)
		self.assertIn("enabled", s)

	def test_disabled_when_not_configured(self):
		# Even before the admin enables biometrics, the getter shouldn't crash
		s = biometric_api._get_settings()
		self.assertIn(s["enabled"], (0, 1))


# ---------------------------------------------------------------------------
# DB round-trip tests (idempotent, clean up after themselves)
# ---------------------------------------------------------------------------

TEST_USER_PREFIX = "_ury_bio_test_"


def _create_test_user(suffix: str, role: str = "URY Cashier") -> str:
	email = f"{TEST_USER_PREFIX}{suffix}@ury-test.local"
	if frappe.db.exists("User", email):
		return email
	user = frappe.get_doc({
		"doctype": "User",
		"email": email,
		"first_name": f"Biotest {suffix}",
		"send_welcome_email": 0,
		"enabled": 1,
		"user_type": "System User",
		"roles": [{"role": role}],
	})
	user.insert(ignore_permissions=True)
	return email


def _cleanup_test_users() -> None:
	rows = frappe.get_all(
		"User",
		filters={"email": ["like", f"{TEST_USER_PREFIX}%"]},
		pluck="name",
	)
	for u in rows:
		if frappe.db.exists("URY Biometric Enrollment", u):
			frappe.delete_doc("URY Biometric Enrollment", u, ignore_permissions=True, force=1)
		frappe.delete_doc("User", u, ignore_permissions=True, force=1)
	frappe.db.commit()


class EnrollmentRoundTripTests(unittest.TestCase):
	"""Exercises `enroll_biometric` against the real doctype.

	Requires the session user to be Administrator (so the captain-check passes)
	and the biometric feature to be enabled on the site. If either isn't true,
	tests are skipped with a clear message.
	"""

	@classmethod
	def setUpClass(cls):
		if frappe.session.user != "Administrator":
			raise unittest.SkipTest("must be run as Administrator")
		# Flip the settings on for the duration of the test
		settings = frappe.get_doc("URY Biometric Settings")
		cls._was_enabled = settings.enabled
		if not settings.enabled:
			settings.enabled = 1
			settings.save(ignore_permissions=True)
			frappe.db.commit()
		cls.user = _create_test_user("rt")

	@classmethod
	def tearDownClass(cls):
		_cleanup_test_users()
		if not cls._was_enabled:
			settings = frappe.get_doc("URY Biometric Settings")
			settings.enabled = 0
			settings.save(ignore_permissions=True)
			frappe.db.commit()

	def setUp(self):
		# Start each test with a clean enrollment slate for self.user
		if frappe.db.exists("URY Biometric Enrollment", self.user):
			frappe.delete_doc(
				"URY Biometric Enrollment", self.user,
				ignore_permissions=True, force=1,
			)
			frappe.db.commit()

	def _valid_template_b64(self, size: int = 1200) -> str:
		return base64.b64encode(secrets.token_bytes(size)).decode("ascii")

	def test_enroll_new_user_creates_row(self):
		result = biometric_api.enroll_biometric(
			user=self.user,
			fingerprint_template_b64=self._valid_template_b64(),
			primary_finger="Right Index",
			pin="112233",
		)
		self.assertEqual(result["action"], "created")
		self.assertEqual(result["user"], self.user)
		self.assertTrue(frappe.db.exists("URY Biometric Enrollment", self.user))
		row = frappe.get_doc("URY Biometric Enrollment", self.user)
		self.assertEqual(row.fingerprint_template_length, 1200)
		self.assertEqual(row.primary_finger, "Right Index")
		self.assertEqual(row.fingerprint_enrolled_by, "Administrator")
		self.assertTrue(row.pin_hash)
		# Admin-friendly: doesn't leak secret material
		self.assertNotIn("112233", row.pin_hash)

	def test_re_enroll_existing_user_updates_row(self):
		# Ensure a row exists
		biometric_api.enroll_biometric(
			user=self.user,
			fingerprint_template_b64=self._valid_template_b64(),
			pin="112233",
		)
		# Re-enroll with a different template + new finger; same PIN works via change_pin not here
		result = biometric_api.enroll_biometric(
			user=self.user,
			fingerprint_template_b64=self._valid_template_b64(1500),
			primary_finger="Left Thumb",
		)
		self.assertEqual(result["action"], "updated")
		row = frappe.get_doc("URY Biometric Enrollment", self.user)
		self.assertEqual(row.fingerprint_template_length, 1500)
		self.assertEqual(row.primary_finger, "Left Thumb")

	def test_enroll_new_without_pin_rejected(self):
		# A new user (different email so we're actually creating a new row)
		fresh = _create_test_user("nopin")
		with self.assertRaises(frappe.exceptions.ValidationError):
			biometric_api.enroll_biometric(
				user=fresh,
				fingerprint_template_b64=self._valid_template_b64(),
				primary_finger="Right Index",
			)

	def test_enroll_non_ury_user_rejected(self):
		email = f"{TEST_USER_PREFIX}stranger@ury-test.local"
		if not frappe.db.exists("User", email):
			# Create with no URY role
			user = frappe.get_doc({
				"doctype": "User",
				"email": email,
				"first_name": "Stranger",
				"send_welcome_email": 0,
				"enabled": 1,
				"user_type": "System User",
			})
			user.insert(ignore_permissions=True)
		with self.assertRaises(frappe.exceptions.ValidationError):
			biometric_api.enroll_biometric(
				user=email,
				fingerprint_template_b64=self._valid_template_b64(),
				pin="112233",
			)

	def test_admin_reset_unlocks_pin(self):
		biometric_api.enroll_biometric(
			user=self.user,
			fingerprint_template_b64=self._valid_template_b64(),
			pin="112233",
		)
		# Simulate lockout
		frappe.db.set_value(
			"URY Biometric Enrollment", self.user,
			{"failed_pin_attempts": 99, "pin_locked_until": "2099-01-01 00:00:00"},
		)
		frappe.db.commit()
		result = biometric_api.admin_reset_enrollment(user=self.user, delete=0)
		self.assertEqual(result["action"], "unlocked")
		row = frappe.get_doc("URY Biometric Enrollment", self.user)
		self.assertEqual(row.failed_pin_attempts, 0)
		self.assertFalse(row.pin_locked_until)

	def test_admin_reset_delete_removes_row(self):
		biometric_api.enroll_biometric(
			user=self.user,
			fingerprint_template_b64=self._valid_template_b64(),
			pin="112233",
		)
		result = biometric_api.admin_reset_enrollment(user=self.user, delete=1)
		self.assertEqual(result["action"], "deleted")
		self.assertFalse(frappe.db.exists("URY Biometric Enrollment", self.user))


class PinLoginFailurePathTests(unittest.TestCase):
	"""Verifies that pin_login rejects a bad PIN and increments the failure counter.

	Doesn't test the success path (would create a session mid-test and break the
	test runner). The success path is exercised manually via the browser.
	"""

	@classmethod
	def setUpClass(cls):
		if frappe.session.user != "Administrator":
			raise unittest.SkipTest("must be run as Administrator")
		settings = frappe.get_doc("URY Biometric Settings")
		cls._was_enabled = settings.enabled
		if not settings.enabled:
			settings.enabled = 1
			settings.save(ignore_permissions=True)
			frappe.db.commit()
		cls.user = _create_test_user("pinlogin")
		biometric_api.enroll_biometric(
			user=cls.user,
			fingerprint_template_b64=base64.b64encode(secrets.token_bytes(1200)).decode("ascii"),
			pin="112233",
		)

	@classmethod
	def tearDownClass(cls):
		_cleanup_test_users()
		if not cls._was_enabled:
			settings = frappe.get_doc("URY Biometric Settings")
			settings.enabled = 0
			settings.save(ignore_permissions=True)
			frappe.db.commit()

	def test_wrong_pin_bumps_counter(self):
		# Reset counter
		frappe.db.set_value(
			"URY Biometric Enrollment", self.user,
			{"failed_pin_attempts": 0, "pin_locked_until": None},
		)
		frappe.db.commit()
		with self.assertRaises(frappe.exceptions.AuthenticationError):
			biometric_api.pin_login(username=self.user, pin="999999")
		new = frappe.db.get_value("URY Biometric Enrollment", self.user, "failed_pin_attempts")
		self.assertEqual(new, 1)

	def test_missing_user_returns_generic_error(self):
		with self.assertRaises(frappe.exceptions.AuthenticationError):
			biometric_api.pin_login(username="nobody@nowhere.test", pin="112233")


# ---------------------------------------------------------------------------
# Direct-runner entry point (bypasses bench run-tests)
# ---------------------------------------------------------------------------

def run_biometric_tests(*, verbosity: int = 2) -> str:
	"""Invoke via `bench --site <site> execute ury.ury.biometric.test_biometric.run_biometric_tests`.

	Frappe's test bootstrap is broken on this dev site (see CLAUDE.md Fixes log
	2026-04-15). Calling `unittest.TextTestRunner` directly bypasses it and still
	uses the live site's DB connection which is what we want for the DB-backed
	suites.
	"""
	loader = unittest.TestLoader()
	suite = unittest.TestSuite()
	for cls in (
		PINFormatTests,
		PINHashTests,
		TemplateValidationTests,
		SettingsDefaultsTests,
		EnrollmentRoundTripTests,
		PinLoginFailurePathTests,
	):
		suite.addTests(loader.loadTestsFromTestCase(cls))
	runner = unittest.TextTestRunner(verbosity=verbosity, stream=None)
	result = runner.run(suite)
	line = (
		f"[URY biometric tests] ran={result.testsRun} "
		f"failures={len(result.failures)} errors={len(result.errors)} "
		f"skipped={len(result.skipped)}"
	)
	print(line)
	return line
