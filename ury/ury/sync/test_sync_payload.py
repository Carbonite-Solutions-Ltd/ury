"""Unit tests for the sync payload builder and the failure classifier.

Neither needs a site or a database — `to_payload` and `classify_failure`
are pure over plain values. Run with the bench python:

    env/bin/python -m unittest ury.ury.sync.test_sync_payload -v

or via the repo's usual entry point:

    bench --site <site> execute ury.ury.sync.test_sync_payload.run_sync_payload_tests
"""

import json
import unittest

from ury.ury.sync import payload as P
from ury.ury.sync import transport as T

SITE = "branch1.example.com"


def _invoice(**overrides):
	base = {
		"name": "AIR-00042",
		"owner": "cashier@example.com",
		"branch": "Airport",
		"pos_profile": "Airport",
		"posting_date": "2026-09-24",
		"posting_time": "19:41:02",
		"customer": "Cash Customer - Airport",
		"customer_name": "Cash Customer",
		"order_type": "Dine In",
		"restaurant_table": "MR-Tab 18",
		"status": "Paid",
		"is_return": 0,
		"net_total": 100.0,
		"total_taxes_and_charges": 20.0,
		"discount_amount": 0.0,
		"grand_total": 120.0,
		"paid_amount": 120.0,
		"custom_terminal": "Airport Main Terminal",
		"custom_waiter": "Georgina",
		"cashier": "cashier@example.com",
		"custom_on_account_amount": 0,
		"no_of_pax": "3",
	}
	base.update(overrides)
	return base


class PayloadShapeTests(unittest.TestCase):
	def test_header_fields_are_copied(self):
		out = P.to_payload(_invoice(), [], [], SITE)
		self.assertEqual(out["branch"], "Airport")
		self.assertEqual(out["grand_total"], 120.0)
		self.assertEqual(out["order_type"], "Dine In")

	def test_owner_is_renamed_to_raised_by(self):
		# `owner` is a Frappe builtin and would be overwritten on insert at
		# the far end, silently losing who rang the sale.
		out = P.to_payload(_invoice(), [], [], SITE)
		self.assertEqual(out["raised_by"], "cashier@example.com")
		self.assertNotIn("owner", out)

	def test_custom_prefixed_fields_are_flattened(self):
		out = P.to_payload(_invoice(), [], [], SITE)
		self.assertEqual(out["terminal"], "Airport Main Terminal")
		self.assertEqual(out["waiter"], "Georgina")
		self.assertEqual(out["on_account_amount"], 0)

	def test_no_of_pax_is_coerced_to_an_int(self):
		# It is a Data field on POS Invoice (an Int on Sales Invoice — a
		# long-standing legacy mismatch), so it arrives as a string.
		self.assertEqual(P.to_payload(_invoice(), [], [], SITE)["no_of_pax"], 3)
		self.assertEqual(
			P.to_payload(_invoice(no_of_pax="2.0"), [], [], SITE)["no_of_pax"], 2
		)

	def test_a_junk_or_missing_pax_never_raises(self):
		# A sale that arrives with covers of 0 beats one that does not
		# arrive at all.
		for bad in (None, "", "abc", [], {}):
			self.assertEqual(
				P.to_payload(_invoice(no_of_pax=bad), [], [], SITE)["no_of_pax"], 0
			)

	def test_missing_header_fields_are_tolerated(self):
		# A branch running an older build may not carry every field.
		out = P.to_payload({"name": "X-1"}, [], [], SITE)
		self.assertEqual(out["invoice_name"], "X-1")
		self.assertIsNone(out["branch"])

	def test_the_payload_is_versioned(self):
		out = P.to_payload(_invoice(), [], [], SITE)
		self.assertEqual(out["payload_version"], P.PAYLOAD_VERSION)


class ItemAndPaymentTests(unittest.TestCase):
	def test_items_are_mapped_with_their_comment(self):
		items = [
			{
				"item_code": "FANTA",
				"item_name": "Fanta",
				"course": "Drinks",
				"item_group": "NON ALCOHOLIC",
				"qty": 2,
				"stock_qty": 2,
				"rate": 15,
				"amount": 30,
				"comment": "no ice",
			}
		]
		out = P.to_payload(_invoice(), items, [], SITE)
		self.assertEqual(len(out["items"]), 1)
		self.assertEqual(out["items"][0]["item_code"], "FANTA")
		self.assertEqual(out["items"][0]["comment"], "no ice")

	def test_no_items_is_fine(self):
		self.assertEqual(P.to_payload(_invoice(), None, None, SITE)["items"], [])

	def test_payments_serialise_to_json(self):
		payments = [
			{"mode_of_payment": "Cash", "amount": 70},
			{"mode_of_payment": "Momo", "amount": 50},
		]
		out = P.to_payload(_invoice(), [], payments, SITE)
		decoded = json.loads(out["payments_json"])
		self.assertEqual(len(decoded), 2)
		self.assertEqual(decoded[0]["mode_of_payment"], "Cash")
		self.assertEqual(decoded[1]["amount"], 50)

	def test_payments_json_is_always_valid_json(self):
		out = P.to_payload(_invoice(), [], [], SITE)
		self.assertEqual(json.loads(out["payments_json"]), [])


class RemoteKeyTests(unittest.TestCase):
	def test_the_key_is_scoped_by_site(self):
		self.assertEqual(P.remote_key(SITE, "AIR-00042"), f"{SITE}|AIR-00042")

	def test_two_branches_reusing_a_number_do_not_collide(self):
		# The whole reason the key is not just the invoice name: if the
		# per-branch invoice prefixes were never configured, two branches
		# WILL mint the same name, and one would overwrite the other.
		self.assertNotEqual(
			P.remote_key("branch1.example.com", "M-0001"),
			P.remote_key("branch2.example.com", "M-0001"),
		)

	def test_the_payload_carries_its_own_key(self):
		out = P.to_payload(_invoice(), [], [], SITE)
		self.assertEqual(out["remote_key"], f"{SITE}|AIR-00042")


class FailureClassificationTests(unittest.TestCase):
	def test_an_explicit_rejection_is_permanent(self):
		permanent, message = T.classify_failure(
			status_code=200,
			body={"message": {"status": "rejected", "reason": "missing invoice_name"}},
		)
		self.assertTrue(permanent)
		self.assertIn("missing invoice_name", message)

	def test_a_network_exception_is_transient(self):
		permanent, message = T.classify_failure(exception=OSError("timed out"))
		self.assertFalse(permanent)
		self.assertIn("timed out", message)

	def test_server_errors_are_transient(self):
		for code in (500, 502, 503, 504):
			permanent, _m = T.classify_failure(status_code=code, body="boom")
			self.assertFalse(permanent, code)

	def test_auth_failures_are_transient_on_purpose(self):
		# Bad credentials are a configuration mistake someone will fix, and
		# the retries then succeed on their own. Marking these Failed would
		# mean re-queueing every stranded sale by hand afterwards.
		for code in (401, 403):
			permanent, _m = T.classify_failure(status_code=code, body="denied")
			self.assertFalse(permanent, code)

	def test_a_frappe_validation_error_is_transient(self):
		# 417 is Frappe's ValidationError status. The receiver raises rather
		# than rejects for anything it might recover from, so a 417 here
		# means "this site could not store it *now*".
		permanent, _m = T.classify_failure(status_code=417, body="ValidationError")
		self.assertFalse(permanent)

	def test_THE_INVARIANT_only_an_explicit_rejection_is_ever_permanent(self):
		# Everything that is not the receiver saying "no, and never" must be
		# retried, because abandoning a row loses a real sale from the books.
		cases = [
			dict(exception=OSError("reset")),
			dict(status_code=200, body={"message": {"status": "accepted"}}),
			dict(status_code=200, body="not json"),
			dict(status_code=301, body=""),
			dict(status_code=400, body="bad"),
			dict(status_code=404, body="no route"),
			dict(status_code=429, body="slow down"),
			dict(status_code=500, body="boom"),
			dict(status_code=None, body=None),
		]
		for case in cases:
			permanent, _m = T.classify_failure(**case)
			self.assertFalse(permanent, case)

	def test_a_rejection_without_a_reason_still_classifies(self):
		permanent, message = T.classify_failure(
			status_code=200, body={"message": {"status": "rejected"}}
		)
		self.assertTrue(permanent)
		self.assertIn("no reason given", message)


def run_sync_payload_tests():
	"""bench --site <site> execute ury.ury.sync.test_sync_payload.run_sync_payload_tests"""
	loader = unittest.TestLoader()
	suite = loader.loadTestsFromModule(__import__(__name__, fromlist=["*"]))
	unittest.TextTestRunner(verbosity=2).run(suite)
