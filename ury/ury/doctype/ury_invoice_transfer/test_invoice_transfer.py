"""Unit tests for the invoice-transfer blocking decision.

Per CLAUDE.md rule 6, `bench run-tests` is blocked on this site by a
pre-existing ERPNext bootstrap trap. Run these via:

    bench --site <site> execute ury.ury.doctype.ury_invoice_transfer.test_invoice_transfer.run_invoice_transfer_tests

These cover the pure `_excluded_from_blocking` decision — the subtle bit
of the captain-only transfer workflow. The rule:
  - a Pending transfer excludes the draft from blocking (offered, in
    flight — and the idempotency guard against double-transfer);
  - an Approved transfer to SOMEONE ELSE excludes it (handed off);
  - an Approved transfer to the current user does NOT exclude it (they
    accepted it, it's their draft now and still blocks their close).
The surrounding endpoints (submit/approve/reject) are thin DB glue over
this decision. See CLAUDE.md "Fixes log" 2026-06-05.
"""

from __future__ import annotations

import unittest

from ury.ury_pos import api


class TransferBlockingTests(unittest.TestCase):
    def test_empty_rows(self):
        self.assertEqual(api._excluded_from_blocking([], "a@x"), set())

    def test_pending_is_excluded(self):
        rows = [{"invoice": "INV1", "status": "Pending", "to_user": "b@x"}]
        self.assertEqual(api._excluded_from_blocking(rows, "a@x"), {"INV1"})

    def test_pending_to_me_still_excluded(self):
        # I haven't accepted it yet — it's not blocking my close.
        rows = [{"invoice": "INV1", "status": "Pending", "to_user": "a@x"}]
        self.assertEqual(api._excluded_from_blocking(rows, "a@x"), {"INV1"})

    def test_approved_to_other_is_excluded(self):
        rows = [{"invoice": "INV1", "status": "Approved", "to_user": "b@x"}]
        self.assertEqual(api._excluded_from_blocking(rows, "a@x"), {"INV1"})

    def test_approved_to_me_is_not_excluded(self):
        # I accepted it; it's my unpaid draft now and must block my close.
        rows = [{"invoice": "INV1", "status": "Approved", "to_user": "a@x"}]
        self.assertEqual(api._excluded_from_blocking(rows, "a@x"), set())

    def test_mixed_set(self):
        rows = [
            {"invoice": "INV1", "status": "Pending", "to_user": "b@x"},
            {"invoice": "INV2", "status": "Approved", "to_user": "a@x"},  # mine -> blocks
            {"invoice": "INV3", "status": "Approved", "to_user": "c@x"},  # other -> excluded
        ]
        self.assertEqual(
            api._excluded_from_blocking(rows, "a@x"), {"INV1", "INV3"}
        )

    def test_idempotency_pending_prevents_retransfer(self):
        # Two passes over the same Pending transfer (ending the shift
        # twice) — both exclude INV1, so it never re-blocks/re-transfers.
        rows = [{"invoice": "INV1", "status": "Pending", "to_user": "b@x"}]
        first = api._excluded_from_blocking(rows, "a@x")
        second = api._excluded_from_blocking(rows, "a@x")
        self.assertEqual(first, second)
        self.assertEqual(first, {"INV1"})

    def test_multiple_transfers_same_invoice(self):
        # INV1 was transferred A->B (Approved) then offered B->C (Pending).
        # From A's view it's handed off (excluded). From C's view it's
        # pending (excluded, not yet accepted).
        rows = [
            {"invoice": "INV1", "status": "Approved", "to_user": "b@x"},
            {"invoice": "INV1", "status": "Pending", "to_user": "c@x"},
        ]
        self.assertEqual(api._excluded_from_blocking(rows, "a@x"), {"INV1"})
        self.assertEqual(api._excluded_from_blocking(rows, "c@x"), {"INV1"})
        # From B's view: the A->B approval is to_user=b == me (blocks),
        # but the B->C pending also excludes it. Pending wins → excluded.
        self.assertEqual(api._excluded_from_blocking(rows, "b@x"), {"INV1"})


# ---------------------------------------------------------------------------
# Close-shift robustness helpers (same api module) — 2026-06-05
# ---------------------------------------------------------------------------

class RootCauseMessageTests(unittest.TestCase):
    """`_root_cause_message` unmasks the real consolidation error from
    ERPNext's secondary 'Failed-status comment' cascade."""

    def test_single_exception(self):
        self.assertEqual(api._root_cause_message(ValueError("boom")), "boom")

    def test_chained_context_returns_root(self):
        try:
            try:
                raise ValueError("real cause")
            except ValueError:
                raise RuntimeError("masking error")
        except RuntimeError as e:
            self.assertEqual(api._root_cause_message(e), "real cause")

    def test_explicit_cause_returns_root(self):
        e = RuntimeError("top")
        e.__cause__ = ValueError("root")
        self.assertEqual(api._root_cause_message(e), "root")


class OrderTypeValidityTests(unittest.TestCase):
    """The set the order_type repair + sync_order guard validate against."""

    def test_all_real_types_valid(self):
        for t in ("", "Dine In", "Take Away", "Delivery", "Phone In", "Aggregators"):
            self.assertIn(t, api._VALID_ORDER_TYPES)

    def test_phone_number_is_invalid(self):
        self.assertNotIn("0248288729", api._VALID_ORDER_TYPES)


def run_invoice_transfer_tests(*, verbosity: int = 2) -> str:
    """Invoke via
    `bench --site <site> execute ury.ury.doctype.ury_invoice_transfer.test_invoice_transfer.run_invoice_transfer_tests`.
    """
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TransferBlockingTests))
    suite.addTests(loader.loadTestsFromTestCase(RootCauseMessageTests))
    suite.addTests(loader.loadTestsFromTestCase(OrderTypeValidityTests))
    result = unittest.TextTestRunner(verbosity=verbosity, stream=None).run(suite)
    line = (
        f"[URY transfer tests] ran={result.testsRun} "
        f"failures={len(result.failures)} errors={len(result.errors)}"
    )
    print(line)
    return line
