"""Tests for report scoping and the Sales by Staff payment filter.

Two things are locked down here:

1. NO REPORT IS TERMINAL-SCOPED (2026-09-23). Passing a `terminal` to
   any report endpoint must not change a single figure. This is the
   regression that mattered: on the client's data 2,610 submitted
   invoices carry `custom_terminal = 'Airport Main Terminal'` and
   exactly ONE carries 'Main Restaurant Cashier', so the same report
   read GHS 1,096,759 from one till and GHS 565 from the other. Two
   sets of books for the same window.

2. On Account is filterable on Sales by Staff. It is the ABSENCE of a
   tender, so it has no `Sales Invoice Payment` row and needs its own
   sentinel + predicate.

Run:
  bench --site <site> execute \
    ury.ury.api.test_report_scope.run_report_scope_tests
"""

import json
import unittest

import frappe

from ury.ury_pos import api
from ury.ury_pos.api import (
    ACTIVE_BRANCH_CACHE,
    ON_ACCOUNT_PAYMENT_FILTER,
    _payment_mode_clause,
)

TEST_SID = "ury-report-scope-test"


def _pin_session_to_the_branch_with_the_data():
    """Point this session's active branch at the branch that actually
    holds invoices, exactly as opening the POS on one of its terminals
    would. Without it getBranch() falls back to the first POS Profile's
    branch for Administrator, which on this data is an EMPTY branch —
    every live assertion would then pass vacuously against zero rows.
    """
    frappe.set_user("Administrator")
    frappe.session.sid = TEST_SID
    row = frappe.db.sql(
        """SELECT branch FROM `tabPOS Invoice`
           WHERE docstatus = 1 AND IFNULL(branch, '') != ''
           GROUP BY branch ORDER BY COUNT(*) DESC LIMIT 1"""
    )
    branch = row[0][0] if row else None
    if branch:
        api._set_active_branch(branch)
    return branch


def _unpin_session():
    frappe.cache.hdel(ACTIVE_BRANCH_CACHE, TEST_SID)


# ── pure: the payment-method filter predicate ───────────────────────


class PaymentModeClauseTests(unittest.TestCase):
    def test_no_filter_returns_nothing(self):
        for empty in (None, "", 0):
            clause, params = _payment_mode_clause(empty)
            self.assertIsNone(clause)
            self.assertEqual(params, [])

    def test_real_mode_matches_a_payment_row(self):
        clause, params = _payment_mode_clause("Cash")
        self.assertIn("tabSales Invoice Payment", clause)
        self.assertIn("sip.mode_of_payment = %s", clause)
        self.assertEqual(params, ["Cash"])

    def test_on_account_reads_the_invoice_not_a_payment_row(self):
        """The whole point: an on-account bill has NO payment row to
        match, so matching one would always return nothing."""
        clause, params = _payment_mode_clause(ON_ACCOUNT_PAYMENT_FILTER)
        self.assertIn("custom_on_account_amount", clause)
        self.assertNotIn("tabSales Invoice Payment", clause)
        self.assertEqual(params, [], "predicate is literal, takes no params")

    def test_sentinel_cannot_collide_with_a_mode_of_payment(self):
        """`__` prefix + no real Mode of Payment may be named that."""
        self.assertTrue(ON_ACCOUNT_PAYMENT_FILTER.startswith("__"))
        self.assertFalse(
            frappe.db.exists("Mode of Payment", ON_ACCOUNT_PAYMENT_FILTER)
        )

    def test_a_mode_named_like_the_sentinel_is_read_as_the_sentinel(self):
        """Documented precedence, so nobody is surprised later."""
        clause, _ = _payment_mode_clause(ON_ACCOUNT_PAYMENT_FILTER)
        self.assertIn("custom_on_account_amount", clause)


# ── live: no report may be terminal-scoped ──────────────────────────


# Wall-clock fields: these are now() at call time, so two calls a
# millisecond apart differ for reasons that have nothing to do with
# terminal scoping.
VOLATILE = {"period_end_date"}


def _norm(value):
    """Comparable snapshot of a report response, volatile keys aside."""
    if isinstance(value, dict):
        value = {k: v for k, v in value.items() if k not in VOLATILE}
    return json.dumps(value, sort_keys=True, default=str)


class NoTerminalScopeTests(unittest.TestCase):
    """Every report endpoint, called with and without a terminal."""

    @classmethod
    def setUpClass(cls):
        cls.branch = _pin_session_to_the_branch_with_the_data()
        cls.terminals = frappe.get_all(
            "URY POS Terminal", pluck="name", limit=10
        )
        rng = frappe.db.sql(
            """SELECT MIN(posting_date) a, MAX(posting_date) b
               FROM `tabPOS Invoice` WHERE docstatus = 1"""
        )
        cls.frm, cls.to = (rng and rng[0]) or (None, None)

    @classmethod
    def tearDownClass(cls):
        _unpin_session()

    def test_the_fixture_is_not_vacuous(self):
        """Guard: if the window has no invoices every other assertion
        here passes against zeros and proves nothing."""
        report = api.get_sales_by_cashier(self.frm, self.to)
        self.assertTrue(self.branch, "no branch carries submitted invoices")
        self.assertGreater(len(report["rows"]), 0, "no staff rows to compare")
        self.assertGreater(float(report["totals"]["grand_total"]), 0)

    def _endpoints(self):
        """(label, callable taking a terminal) for every report."""
        f, t = self.frm, self.to
        return [
            ("sales_by_cashier",
             lambda term: api.get_sales_by_cashier(f, t, term)),
            ("sales_by_cashier/waiter",
             lambda term: api.get_sales_by_cashier(f, t, term, "waiter")),
            ("sales_by_category",
             lambda term: api.get_sales_by_category(f, t, term)),
            ("top_bottom_items",
             lambda term: api.get_top_bottom_items(f, t, 10, term)),
            ("course_sales",
             lambda term: api.get_course_sales(f, t, term)),
            ("meal_period_sales",
             lambda term: api.get_meal_period_sales(f, t, term)),
            ("sales_by_payment_method",
             lambda term: api.get_sales_by_payment_method(f, t, term)),
            ("merge_report",
             lambda term: api.get_merge_report(f, t, term)),
            ("transfer_report",
             lambda term: api.get_transfer_report(f, t, term)),
            ("payment_splits_report",
             lambda term: api.get_payment_splits_report(f, t, term)),
            ("shift_history",
             lambda term: api.get_shift_history(f, t, term)),
            ("my_shift_summary",
             lambda term: api.get_my_shift_summary(term)),
        ]

    def test_every_report_ignores_the_terminal(self):
        self.assertTrue(self.terminals, "site has no terminals to test with")
        for label, call in self._endpoints():
            baseline = _norm(call(None))
            for term in self.terminals:
                self.assertEqual(
                    baseline,
                    _norm(call(term)),
                    "%s changed when scoped to terminal %r" % (label, term),
                )

    def test_reports_never_echo_a_terminal_back(self):
        """A heading or printout must not label branch-wide figures
        with one till."""
        for label, call in self._endpoints():
            for term in (None, self.terminals[0]):
                res = call(term)
                if isinstance(res, dict) and "terminal" in res:
                    self.assertIsNone(
                        res["terminal"],
                        "%s echoed a terminal (%r)" % (label, term),
                    )

    def test_the_reported_discrepancy_is_gone(self):
        """The user's actual symptom: two tills, two grand totals."""
        totals = {
            term: api.get_sales_by_cashier(self.frm, self.to, term)["totals"][
                "grand_total"
            ]
            for term in self.terminals
        }
        self.assertEqual(
            len(set(totals.values())),
            1,
            "Sales by Staff still differs per terminal: %r" % totals,
        )

    def test_staff_drilldown_also_ignores_the_terminal(self):
        report = api.get_sales_by_cashier(self.frm, self.to)
        if not report["rows"]:
            self.skipTest("no staff rows in window")
        staff = report["rows"][0]["user"]
        baseline = _norm(
            api.get_staff_invoices(staff, self.frm, self.to, None)
        )
        for term in self.terminals:
            self.assertEqual(
                baseline,
                _norm(api.get_staff_invoices(staff, self.frm, self.to, term)),
                "drill-down changed on terminal %r" % term,
            )


# ── live: the On Account filter ─────────────────────────────────────


class OnAccountFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.branch = _pin_session_to_the_branch_with_the_data()
        rng = frappe.db.sql(
            """SELECT MIN(posting_date) a, MAX(posting_date) b
               FROM `tabPOS Invoice` WHERE docstatus = 1"""
        )
        cls.frm, cls.to = (rng and rng[0]) or (None, None)
        cls.all = api.get_sales_by_cashier(cls.frm, cls.to)
        cls.oa = api.get_sales_by_cashier(
            cls.frm, cls.to, None, "cashier", ON_ACCOUNT_PAYMENT_FILTER
        )

    @classmethod
    def tearDownClass(cls):
        _unpin_session()

    def test_the_fixture_is_not_vacuous(self):
        self.assertGreater(len(self.all["rows"]), 0)
        self.assertGreater(
            float(self.all["totals"].get("on_account") or 0),
            0,
            "no on-account money in window — the filter is untested",
        )

    def test_option_offered_only_when_there_is_on_account_money(self):
        expected = 1 if (self.all["totals"].get("on_account") or 0) > 0 else 0
        self.assertEqual(self.all.get("has_on_account"), expected)

    def test_backend_publishes_the_sentinel_for_the_frontend(self):
        self.assertEqual(
            self.all.get("on_account_filter_value"), ON_ACCOUNT_PAYMENT_FILTER
        )

    def test_filtering_keeps_every_penny_of_on_account_money(self):
        """Filtering TO on-account bills cannot lose on-account money."""
        self.assertAlmostEqual(
            float(self.all["totals"].get("on_account") or 0),
            float(self.oa["totals"].get("on_account") or 0),
            places=2,
        )

    def test_filtering_is_a_strict_subset_of_the_unfiltered_total(self):
        self.assertLessEqual(
            float(self.oa["totals"]["grand_total"]),
            float(self.all["totals"]["grand_total"]) + 0.01,
        )

    def test_every_returned_row_actually_has_on_account_money(self):
        if not self.oa["rows"]:
            self.skipTest("no on-account bills in window")
        for row in self.oa["rows"]:
            self.assertGreater(float(row.get("on_account") or 0), 0, row["user"])

    def test_drilldown_returns_only_on_account_bills(self):
        if not self.oa["rows"]:
            self.skipTest("no on-account bills in window")
        row = self.oa["rows"][0]
        invoices = api.get_staff_invoices(
            row["user"], self.frm, self.to, None, "cashier",
            ON_ACCOUNT_PAYMENT_FILTER,
        )
        self.assertEqual(
            len(invoices), int(row["invoice_count"]),
            "drill-down disagrees with the row it expanded from",
        )
        for inv in invoices:
            self.assertGreater(
                frappe.db.get_value(
                    "POS Invoice", inv["name"], "custom_on_account_amount"
                ) or 0,
                0,
                inv["name"],
            )

    def test_dropdown_options_survive_being_used(self):
        """The list you pick from must not shrink because you picked."""
        self.assertEqual(
            self.all.get("payment_mode_options"),
            self.oa.get("payment_mode_options"),
        )
        self.assertEqual(
            self.all.get("has_on_account"), self.oa.get("has_on_account")
        )

    def test_a_real_mode_filter_still_works(self):
        modes = self.all.get("payment_mode_options") or []
        if not modes:
            self.skipTest("no payment modes in window")
        mode = modes[0]
        res = api.get_sales_by_cashier(
            self.frm, self.to, None, "cashier", mode
        )
        self.assertEqual(res["payment_mode"], mode)
        self.assertLessEqual(
            float(res["totals"]["grand_total"]),
            float(self.all["totals"]["grand_total"]) + 0.01,
        )
        self.assertGreater(len(res["rows"]), 0)


def run_report_scope_tests():
    """bench run-tests is blocked by the pre-existing ERPNext bootstrap
    issue on this site, so drive unittest directly (CLAUDE.md rule 6)."""
    suite = unittest.TestSuite()
    load = unittest.TestLoader().loadTestsFromTestCase
    for case in (
        PaymentModeClauseTests,
        NoTerminalScopeTests,
        OnAccountFilterTests,
    ):
        suite.addTests(load(case))
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    print(
        "\n%d run, %d failures, %d errors, %d skipped"
        % (res.testsRun, len(res.failures), len(res.errors), len(res.skipped))
    )
    return not (res.failures or res.errors)
