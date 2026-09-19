# Copyright (c) 2026, Tridotstech and contributors
# For license information, please see license.txt

"""Tests for the bar stock handover report.

Run with:
    bench --site <site> execute ury.ury.api.test_ury_bar_stock.run_bar_stock_tests

`bench run-tests` is blocked on these sites by ERPNext's test bootstrap, so the
direct runner below is the supported path (see CLAUDE.md working rule 6).

The arithmetic lives in pure functions (`build_report_rows`, `summarise_rows`)
so every case is covered without a database. The live tests then exercise the
real endpoints against the site's own Bar unit and clean up after themselves.
"""

import unittest

import frappe

from ury.ury.api.ury_bar_stock import (
    build_report_rows,
    close_bar_session,
    get_bar_session_state,
    get_bar_stock_report,
    open_bar_session,
    summarise_rows,
)


def _snap(code, opening, name=None, group="Drinks", uom="Nos"):
    return {
        "item_code": code,
        "item_name": name,
        "item_group": group,
        "stock_uom": uom,
        "opening_qty": opening,
    }


class BuildReportRowTests(unittest.TestCase):
    """The sheet's arithmetic: sold = opening - what is physically left."""

    def test_normal_sale(self):
        rows = build_report_rows([_snap("A", 10)], {"A": 4})
        self.assertEqual(rows[0]["opening_qty"], 10)
        self.assertEqual(rows[0]["sold_qty"], 6)
        self.assertEqual(rows[0]["expected_qty"], 4)

    def test_nothing_moved(self):
        rows = build_report_rows([_snap("A", 10)], {"A": 10})
        self.assertEqual(rows[0]["sold_qty"], 0)

    def test_everything_sold(self):
        rows = build_report_rows([_snap("A", 10)], {"A": 0})
        self.assertEqual(rows[0]["sold_qty"], 10)
        self.assertEqual(rows[0]["expected_qty"], 0)

    def test_item_absent_from_physical_map_counts_as_zero(self):
        # No Bin row at all -> nothing on the shelf, so all of it went.
        rows = build_report_rows([_snap("A", 7)], {})
        self.assertEqual(rows[0]["expected_qty"], 0)
        self.assertEqual(rows[0]["sold_qty"], 7)

    def test_oversold_is_flagged_not_hidden(self):
        # Physically negative: more was rung than the system ever had.
        rows = build_report_rows([_snap("A", 2)], {"A": -3})
        self.assertEqual(rows[0]["expected_qty"], -3)
        self.assertEqual(rows[0]["sold_qty"], 5)
        self.assertEqual(rows[0]["is_negative"], 1)

    def test_stock_received_during_the_session_shows_as_negative_sold(self):
        # A delivery into the bar's warehouse raises the shelf count. That is
        # a real movement and must not be silently dropped.
        rows = build_report_rows([_snap("A", 5)], {"A": 12})
        self.assertEqual(rows[0]["sold_qty"], -7)
        self.assertEqual(rows[0]["is_negative"], 0)

    def test_fractional_quantities(self):
        rows = build_report_rows([_snap("A", 2.5)], {"A": 0.75})
        self.assertAlmostEqual(rows[0]["sold_qty"], 1.75)

    def test_idle_items_are_hidden_by_default(self):
        snap = [_snap("A", 0), _snap("B", 3)]
        rows = build_report_rows(snap, {"A": 0, "B": 1})
        self.assertEqual([r["item_code"] for r in rows], ["B"])

    def test_show_all_keeps_idle_items(self):
        snap = [_snap("A", 0), _snap("B", 3)]
        rows = build_report_rows(snap, {"A": 0, "B": 1}, show_all=True)
        self.assertEqual([r["item_code"] for r in rows], ["A", "B"])

    def test_zero_opening_but_sold_is_kept(self):
        # Opened empty, went negative: exactly the case a handover must show.
        rows = build_report_rows([_snap("A", 0)], {"A": -2})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sold_qty"], 2)

    def test_item_name_falls_back_to_code(self):
        rows = build_report_rows([_snap("A", 1, name=None)], {"A": 0})
        self.assertEqual(rows[0]["item_name"], "A")

    def test_empty_snapshot(self):
        self.assertEqual(build_report_rows([], {}), [])

    def test_row_order_is_preserved(self):
        snap = [_snap("C", 1), _snap("A", 1), _snap("B", 1)]
        rows = build_report_rows(snap, {})
        self.assertEqual([r["item_code"] for r in rows], ["C", "A", "B"])


class SummariseTests(unittest.TestCase):
    def test_totals(self):
        rows = build_report_rows(
            [_snap("A", 10), _snap("B", 5), _snap("C", 1)],
            {"A": 4, "B": 5, "C": -2},
        )
        totals = summarise_rows(rows)
        self.assertEqual(totals["line_count"], 3)
        # A: 10->4 moved, B: 5->5 did not, C: 1->-2 moved
        self.assertEqual(totals["moved_count"], 2)
        self.assertEqual(totals["negative_count"], 1)
        # Quantities are in mixed units, so no quantity total is published.
        self.assertNotIn("total_opening", totals)

    def test_empty(self):
        totals = summarise_rows([])
        self.assertEqual(totals["line_count"], 0)
        self.assertEqual(totals["moved_count"], 0)
        self.assertEqual(totals["negative_count"], 0)


class LiveBarSessionTests(unittest.TestCase):
    """End-to-end against the site's own Bar unit. Restores what it changes."""

    @classmethod
    def setUpClass(cls):
        cls.bar = frappe.db.get_value("URY Production Unit", {"production": "Bar"}, "name")
        cls.other = frappe.db.get_value(
            "URY Production Unit", {"production": ("!=", cls.bar or "")}, "name"
        )
        cls.created = []
        cls.original_type = None
        if cls.bar:
            cls.original_type = frappe.db.get_value("URY Production Unit", cls.bar, "unit_type")
            frappe.db.set_value("URY Production Unit", cls.bar, "unit_type", "Bar",
                                update_modified=False)
            frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        for name in frappe.get_all(
            "URY Bar Session", filters={"production_unit": cls.bar or ""}, pluck="name"
        ):
            frappe.delete_doc("URY Bar Session", name, force=True, ignore_permissions=True)
        if cls.bar:
            frappe.db.set_value("URY Production Unit", cls.bar, "unit_type",
                                cls.original_type, update_modified=False)
        frappe.db.commit()

    def setUp(self):
        if not self.bar:
            self.skipTest("no production unit named 'Bar' on this site")

    def test_state_reports_a_bar(self):
        state = get_bar_session_state(self.bar)
        self.assertEqual(state["is_bar"], 1)
        self.assertGreater(state["item_count"], 0)

    def test_non_bar_unit_is_refused(self):
        if not self.other:
            self.skipTest("only one production unit on this site")
        frappe.db.set_value("URY Production Unit", self.other, "unit_type", "Kitchen",
                            update_modified=False)
        self.assertEqual(get_bar_session_state(self.other)["is_bar"], 0)
        with self.assertRaises(frappe.ValidationError):
            open_bar_session(self.other)

    def test_unknown_unit_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            get_bar_session_state("No Such Unit ZZZ")

    def test_all_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            get_bar_session_state("All")

    def test_open_snapshots_every_item(self):
        result = open_bar_session(self.bar)
        self.created.append(result["session"])
        doc = frappe.get_doc("URY Bar Session", result["session"])
        self.assertEqual(doc.status, "Open")
        self.assertEqual(len(doc.items), result["item_count"])
        self.assertTrue(all(r.item_code for r in doc.items))
        # opening = system - already-sold-but-not-yet-deducted
        for row in doc.items:
            self.assertAlmostEqual(
                row.opening_qty, row.system_qty - row.unposted_sold_qty, places=6
            )

    def test_snapshot_resolves_one_warehouse_per_item(self):
        result = open_bar_session(self.bar)
        self.created.append(result["session"])
        doc = frappe.get_doc("URY Bar Session", result["session"])
        resolved = {r.warehouse for r in doc.items if r.warehouse}
        self.assertTrue(resolved, "no warehouse resolved for any bar item")

    def test_opening_again_closes_the_previous_session(self):
        first = open_bar_session(self.bar)["session"]
        second = open_bar_session(self.bar)
        self.created += [first, second["session"]]
        self.assertIn(first, second["closed_previous"])
        self.assertEqual(frappe.db.get_value("URY Bar Session", first, "status"), "Closed")
        open_now = frappe.get_all(
            "URY Bar Session",
            filters={"production_unit": self.bar, "status": "Open"},
            pluck="name",
        )
        self.assertEqual(open_now, [second["session"]])

    def test_report_is_internally_consistent(self):
        self.created.append(open_bar_session(self.bar)["session"])
        report = get_bar_stock_report(self.bar)
        self.assertEqual(report["has_session"], 1)
        for row in report["rows"]:
            self.assertAlmostEqual(
                row["opening_qty"] - row["sold_qty"], row["expected_qty"], places=6
            )
        totals = report["totals"]
        self.assertEqual(totals["line_count"], len(report["rows"]))

    def test_show_all_returns_at_least_as_many_rows(self):
        self.created.append(open_bar_session(self.bar)["session"])
        filtered = get_bar_stock_report(self.bar)
        everything = get_bar_stock_report(self.bar, show_all=1)
        self.assertGreaterEqual(len(everything["rows"]), len(filtered["rows"]))
        self.assertEqual(filtered["hidden_count"],
                         len(everything["rows"]) - len(filtered["rows"]))

    def test_close_then_report_still_works(self):
        self.created.append(open_bar_session(self.bar)["session"])
        self.assertEqual(close_bar_session(self.bar)["closed"], 1)
        # Idempotent: closing again is not an error.
        self.assertEqual(close_bar_session(self.bar)["closed"], 0)
        report = get_bar_stock_report(self.bar)
        self.assertEqual(report["status"], "Closed")

    def test_report_without_any_session(self):
        for name in frappe.get_all(
            "URY Bar Session", filters={"production_unit": self.bar}, pluck="name"
        ):
            frappe.delete_doc("URY Bar Session", name, force=True, ignore_permissions=True)
        frappe.db.commit()
        self.assertEqual(get_bar_stock_report(self.bar)["has_session"], 0)


def run_bar_stock_tests():
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for case in (BuildReportRowTests, SummariseTests, LiveBarSessionTests):
        suite.addTests(loader.loadTestsFromTestCase(case))
    unittest.TextTestRunner(verbosity=2).run(suite)
