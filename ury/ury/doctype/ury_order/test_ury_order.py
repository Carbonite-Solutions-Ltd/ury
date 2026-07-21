# Copyright (c) 2023, Tridz Technologies Pvt. Ltd. and contributors
# See license.txt

import unittest

from frappe.tests.utils import FrappeTestCase

from ury.ury.doctype.ury_order.ury_order import (
    _find_invoice_by_idempotency_key,
    _should_stamp_idempotency,
)


class TestURYOrder(FrappeTestCase):
    pass


class IdempotencyDecisionTests(unittest.TestCase):
    """Pure decision logic for the offline order-queue de-duplication
    (Phase B, 2026-07-21). `_should_stamp_idempotency` decides whether to
    write the client-generated key onto a POS Invoice at sync time."""

    def test_stamp_when_key_supplied_and_invoice_has_no_key(self):
        self.assertTrue(_should_stamp_idempotency("key-1", None))

    def test_stamp_when_invoice_key_is_empty_string(self):
        self.assertTrue(_should_stamp_idempotency("key-1", ""))

    def test_no_stamp_when_invoice_already_has_a_key(self):
        # Never overwrite an existing key — a reused draft keeps its
        # identity so a replay of a DIFFERENT queued order can't hijack it.
        self.assertFalse(_should_stamp_idempotency("key-2", "key-1"))

    def test_no_stamp_when_no_key_supplied(self):
        self.assertFalse(_should_stamp_idempotency(None, None))
        self.assertFalse(_should_stamp_idempotency("", None))

    def test_no_stamp_when_no_key_even_if_invoice_key_empty(self):
        self.assertFalse(_should_stamp_idempotency(None, ""))

    def test_returns_plain_bool(self):
        self.assertIsInstance(_should_stamp_idempotency("k", None), bool)
        self.assertIsInstance(_should_stamp_idempotency(None, None), bool)


class IdempotencyLookupGuardTests(unittest.TestCase):
    """The lookup short-circuits (no DB hit) for an empty/None key, so a
    normal (non-queued) order never triggers a spurious de-dup query."""

    def test_none_key_returns_none(self):
        self.assertIsNone(_find_invoice_by_idempotency_key(None))

    def test_empty_key_returns_none(self):
        self.assertIsNone(_find_invoice_by_idempotency_key(""))


def run_idempotency_tests():
    """Direct unittest runner for the Phase B idempotency logic.

    `bench run-tests` is blocked by ERPNext's test bootstrap on this site
    (see CLAUDE.md working rule 6), so run these via:

        bench --site <site> execute \\
          ury.ury.doctype.ury_order.test_ury_order.run_idempotency_tests
    """
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(IdempotencyDecisionTests))
    suite.addTests(loader.loadTestsFromTestCase(IdempotencyLookupGuardTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return {
        "run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
    }
