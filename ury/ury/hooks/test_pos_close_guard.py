"""Tests for the desk-close guard (2026-10-29).

Run with::

    bench --site <site> execute \\
      ury.ury.hooks.test_pos_close_guard.run_pos_close_guard_tests

`bench run-tests` is blocked on this app by a pre-existing ERPNext test
bootstrap issue, so the `run_*_tests` wrapper at the bottom drives
unittest directly. See CLAUDE.md working rule 6.

The pure arithmetic (`split_orphaned_invoices`) is tested without a bench.
The live section reads the real data on whatever site it runs against and
SKIPS rather than fails when that site has no orphaned invoices — so it is
meaningful on the client's restored backup and harmless on a clean site.
It is strictly read-only: no invoice, closing entry or opening entry is
created, modified or submitted.
"""

import unittest

import frappe

from ury.ury.hooks.ury_pos_closing_entry import (
    _may_force_desk_close,
    refuse_close_that_orphans_invoices,
)
from ury.ury_pos.api import (
    CLOSE_ELIGIBLE_INVOICE_STATUSES,
    orphaned_unconsolidated_invoices,
    split_orphaned_invoices,
)


class _ClosingEntryStub:
    """Minimal stand-in for a POS Closing Entry doc.

    Deliberately NOT `frappe._dict`: its `.items` attribute shadows
    `dict.items()`, which has bitten these tests before (CLAUDE.md,
    2026-04-16).
    """

    def __init__(self, docstatus=1, pos_profile=None, pos_invoices=None):
        self.docstatus = docstatus
        self.pos_profile = pos_profile
        self._pos_invoices = pos_invoices or []

    def get(self, key, default=None):
        if key == "pos_invoices":
            return self._pos_invoices
        if key == "pos_profile":
            return self.pos_profile
        return default


class _RefStub:
    def __init__(self, pos_invoice):
        self.pos_invoice = pos_invoice


def _row(name, total=0):
    return {"name": name, "grand_total": total}


class SplitOrphanedInvoicesTests(unittest.TestCase):
    """Pure arithmetic — no bench needed."""

    def test_no_unconsolidated_rows_means_no_orphans(self):
        orphans, total = split_orphaned_invoices([], ["A"])
        self.assertEqual(orphans, [])
        self.assertEqual(total, 0.0)

    def test_none_rows_is_tolerated(self):
        orphans, total = split_orphaned_invoices(None, None)
        self.assertEqual(orphans, [])
        self.assertEqual(total, 0.0)

    def test_everything_attached_means_no_orphans(self):
        rows = [_row("A", 10), _row("B", 20)]
        orphans, total = split_orphaned_invoices(rows, ["A", "B"])
        self.assertEqual(orphans, [])
        self.assertEqual(total, 0.0)

    def test_nothing_attached_means_all_orphans(self):
        rows = [_row("A", 10), _row("B", 20.5)]
        orphans, total = split_orphaned_invoices(rows, [])
        self.assertEqual([o["name"] for o in orphans], ["A", "B"])
        self.assertAlmostEqual(total, 30.5)

    def test_partial_attachment_reports_only_the_remainder(self):
        """The 00103 case: some swept, the rest silently left behind."""
        rows = [_row("A", 10), _row("B", 20), _row("C", 30)]
        orphans, total = split_orphaned_invoices(rows, ["B"])
        self.assertEqual([o["name"] for o in orphans], ["A", "C"])
        self.assertAlmostEqual(total, 40.0)

    def test_attached_names_not_present_are_ignored(self):
        rows = [_row("A", 10)]
        orphans, total = split_orphaned_invoices(rows, ["ZZZ", "QQQ"])
        self.assertEqual([o["name"] for o in orphans], ["A"])
        self.assertAlmostEqual(total, 10.0)

    def test_duplicate_attached_names_are_harmless(self):
        rows = [_row("A", 10), _row("B", 20)]
        orphans, total = split_orphaned_invoices(rows, ["A", "A", "A"])
        self.assertEqual([o["name"] for o in orphans], ["B"])
        self.assertAlmostEqual(total, 20.0)

    def test_blank_attached_names_do_not_swallow_rows(self):
        """A child table with an empty pos_invoice cell must not mask a row."""
        rows = [_row("A", 10)]
        orphans, _total = split_orphaned_invoices(rows, [None, "", "A"])
        self.assertEqual(orphans, [])

    def test_row_without_a_name_is_skipped(self):
        rows = [{"name": "", "grand_total": 99}, _row("A", 10)]
        orphans, total = split_orphaned_invoices(rows, [])
        self.assertEqual([o["name"] for o in orphans], ["A"])
        self.assertAlmostEqual(total, 10.0)

    def test_none_total_counts_as_zero(self):
        rows = [{"name": "A", "grand_total": None}]
        orphans, total = split_orphaned_invoices(rows, [])
        self.assertEqual(len(orphans), 1)
        self.assertEqual(total, 0.0)

    def test_non_numeric_total_still_reports_the_count(self):
        """The COUNT is the part that matters; a bad total must not crash."""
        rows = [{"name": "A", "grand_total": "not a number"}, _row("B", 5)]
        orphans, total = split_orphaned_invoices(rows, [])
        self.assertEqual(len(orphans), 2)
        self.assertAlmostEqual(total, 5.0)

    def test_input_is_not_mutated(self):
        rows = [_row("A", 10), _row("B", 20)]
        attached = ["A"]
        split_orphaned_invoices(rows, attached)
        self.assertEqual(len(rows), 2)
        self.assertEqual(attached, ["A"])

    def test_order_is_preserved(self):
        rows = [_row("C"), _row("A"), _row("B")]
        orphans, _total = split_orphaned_invoices(rows, [])
        self.assertEqual([o["name"] for o in orphans], ["C", "A", "B"])


class CloseEligibleStatusTests(unittest.TestCase):
    def test_on_account_statuses_are_included(self):
        """Do NOT narrow this back — see the constant's comment."""
        for status in ("Unpaid", "Partly Paid", "Overdue"):
            self.assertIn(status, CLOSE_ELIGIBLE_INVOICE_STATUSES)

    def test_paid_and_return_are_included(self):
        for status in ("Paid", "Consolidated", "Return"):
            self.assertIn(status, CLOSE_ELIGIBLE_INVOICE_STATUSES)

    def test_draft_is_not_a_close_eligible_status(self):
        """Drafts block a close; they are never swept into one."""
        self.assertNotIn("Draft", CLOSE_ELIGIBLE_INVOICE_STATUSES)


class GuardGateTests(unittest.TestCase):
    """The guard's early-exit gates, using a doc stub."""

    def test_draft_save_is_never_blocked(self):
        doc = _ClosingEntryStub(docstatus=0, pos_profile="__nope__")
        refuse_close_that_orphans_invoices(doc)  # must not raise

    def test_cancelled_is_never_blocked(self):
        doc = _ClosingEntryStub(docstatus=2, pos_profile="__nope__")
        refuse_close_that_orphans_invoices(doc)  # must not raise

    def test_missing_profile_is_not_blocked(self):
        doc = _ClosingEntryStub(docstatus=1, pos_profile=None)
        refuse_close_that_orphans_invoices(doc)  # must not raise

    def test_administrator_may_force(self):
        self.assertTrue(_may_force_desk_close("Administrator"))


class LiveOrphanScopeTests(unittest.TestCase):
    """Read-only checks against whatever data this site actually holds."""

    @classmethod
    def setUpClass(cls):
        cls.profile = frappe.db.sql(
            """
            SELECT pos_profile, COUNT(*) n
              FROM `tabPOS Invoice`
             WHERE docstatus = 1
               AND (consolidated_invoice IS NULL OR consolidated_invoice = '')
             GROUP BY pos_profile
             ORDER BY n DESC
             LIMIT 1
            """,
            as_dict=True,
        )
        cls.profile = cls.profile[0]["pos_profile"] if cls.profile else None

    def test_unknown_profile_returns_nothing(self):
        orphans, total = orphaned_unconsolidated_invoices("__no_such_profile__")
        self.assertEqual(orphans, [])
        self.assertEqual(total, 0.0)

    def test_blank_profile_returns_nothing(self):
        for bad in (None, "", 0):
            orphans, total = orphaned_unconsolidated_invoices(bad)
            self.assertEqual(orphans, [])
            self.assertEqual(total, 0.0)

    def test_the_fixture_is_not_vacuous(self):
        """Guard against the whole live section silently proving nothing."""
        if not self.profile:
            self.skipTest("no unconsolidated invoices on this site")
        orphans, _total = orphaned_unconsolidated_invoices(self.profile)
        self.assertGreater(len(orphans), 0)

    def test_attaching_everything_clears_the_orphans(self):
        """A POS close attaches the whole wide scope, so it must pass."""
        if not self.profile:
            self.skipTest("no unconsolidated invoices on this site")
        orphans, _total = orphaned_unconsolidated_invoices(self.profile)
        names = [o["name"] for o in orphans]
        still, total = orphaned_unconsolidated_invoices(self.profile, names)
        self.assertEqual(still, [])
        self.assertEqual(total, 0.0)

    def test_attaching_all_but_one_leaves_exactly_that_one(self):
        if not self.profile:
            self.skipTest("no unconsolidated invoices on this site")
        orphans, _total = orphaned_unconsolidated_invoices(self.profile)
        if len(orphans) < 2:
            self.skipTest("need at least 2 orphans")
        names = [o["name"] for o in orphans]
        still, _t = orphaned_unconsolidated_invoices(self.profile, names[1:])
        self.assertEqual([s["name"] for s in still], [names[0]])

    def test_guard_refuses_a_desk_close_that_attaches_nothing(self):
        """The POS-CLO-2026-00104 case, reproduced."""
        if not self.profile:
            self.skipTest("no unconsolidated invoices on this site")
        victim = frappe.db.sql(
            """
            SELECT u.name FROM `tabUser` u
             WHERE u.enabled = 1 AND u.name NOT IN ('Administrator', 'Guest')
               AND EXISTS (SELECT 1 FROM `tabHas Role` r
                            WHERE r.parent = u.name AND r.role = 'URY Cashier')
               AND NOT EXISTS (SELECT 1 FROM `tabHas Role` r2
                                WHERE r2.parent = u.name
                                  AND r2.role = 'System Manager')
             LIMIT 1
            """,
            as_dict=True,
        )
        if not victim:
            self.skipTest("no non-override cashier on this site")

        original = frappe.session.user
        try:
            frappe.set_user(victim[0]["name"])
            self.assertFalse(_may_force_desk_close())
            doc = _ClosingEntryStub(
                docstatus=1, pos_profile=self.profile, pos_invoices=[]
            )
            with self.assertRaises(frappe.ValidationError):
                refuse_close_that_orphans_invoices(doc)
        finally:
            frappe.set_user(original)

    def test_guard_passes_when_the_close_attached_everything(self):
        """And the POS path, which must NOT be blocked."""
        if not self.profile:
            self.skipTest("no unconsolidated invoices on this site")
        victim = frappe.db.sql(
            """
            SELECT u.name FROM `tabUser` u
             WHERE u.enabled = 1 AND u.name NOT IN ('Administrator', 'Guest')
               AND EXISTS (SELECT 1 FROM `tabHas Role` r
                            WHERE r.parent = u.name AND r.role = 'URY Cashier')
               AND NOT EXISTS (SELECT 1 FROM `tabHas Role` r2
                                WHERE r2.parent = u.name
                                  AND r2.role = 'System Manager')
             LIMIT 1
            """,
            as_dict=True,
        )
        if not victim:
            self.skipTest("no non-override cashier on this site")

        orphans, _total = orphaned_unconsolidated_invoices(self.profile)
        refs = [_RefStub(o["name"]) for o in orphans]

        original = frappe.session.user
        try:
            frappe.set_user(victim[0]["name"])
            doc = _ClosingEntryStub(
                docstatus=1, pos_profile=self.profile, pos_invoices=refs
            )
            refuse_close_that_orphans_invoices(doc)  # must not raise
        finally:
            frappe.set_user(original)


def run_pos_close_guard_tests():
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for cls in (
        SplitOrphanedInvoicesTests,
        CloseEligibleStatusTests,
        GuardGateTests,
        LiveOrphanScopeTests,
    ):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(
        f"\n{result.testsRun} run, "
        f"{len(result.failures)} failed, "
        f"{len(result.errors)} errored, "
        f"{len(result.skipped)} skipped"
    )
    # Return a plain dict, not the TextTestResult: `bench execute` JSON-encodes
    # whatever it gets back and chokes on the result object.
    return {
        "run": result.testsRun,
        "failed": len(result.failures),
        "errored": len(result.errors),
        "skipped": len(result.skipped),
    }
