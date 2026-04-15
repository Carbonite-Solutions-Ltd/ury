# Copyright (c) 2026, Tridz Technologies Pvt. Ltd and contributors
# For license information, please see license.txt
"""
Unit tests for the unified print-routing helpers added in the
2026-04-16 print revamp (Round 1).

Covers:
  1. `_classify_kot_item_department` — course -> department lookup
  2. `_split_kot_items_by_department` — bucketing a KOT's items
  3. `_resolve_printer_for_department` — Drinks / Food / Takeaway
     route resolution plus fallback cascade (Kitchen -> Bill)
  4. `resolve_kot_print_plan` — the end-to-end planner on a real
     POS Profile doc, with a mixed-department KOT
  5. `apply_print_fallback` — Fallback to Bill / Fail Silently /
     Fail with Alert

Test runner: invoked via `bench execute` since `bench run-tests --app ury`
is blocked by ERPNext's test bootstrap on this site (see CLAUDE.md).

    bench --site <site> execute \\
        ury.ury.api.test_ury_print_routing.run_print_routing_tests
"""

import types
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from ury.ury.api.ury_print import (
    _classify_kot_item_department,
    _split_kot_items_by_department,
    _resolve_printer_for_department,
    resolve_kot_print_plan,
    apply_print_fallback,
)


TEST_BRANCH = "_URY Print Test Branch"
TEST_COMPANY = None  # resolved from first company in setUpClass
TEST_USER = "print-routing-test@ury-test.local"

# Unique prefixes for fixtures so cleanup is easy.
COURSE_PREFIX = "_PRTest_"
PROFILE_PREFIX = "_PRTest_Profile_"
PRINTER_PREFIX = "_PRTest_Printer_"


def run_print_routing_tests():
    """Run the print-routing test suite directly, bypassing Frappe's
    test runner."""
    frappe.flags.in_test = True
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestURYPrintRouting)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        raise RuntimeError(
            f"{len(result.failures)} failures, {len(result.errors)} errors "
            f"in URY print routing test suite."
        )
    return {
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "success": result.wasSuccessful(),
    }


class TestURYPrintRouting(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.flags.in_test = True

        # Branch fixture (URY adds a required user Table on Branch).
        if not frappe.db.exists("User", TEST_USER):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": TEST_USER,
                    "first_name": "PrintRouting",
                    "last_name": "Test",
                    "enabled": 1,
                    "send_welcome_email": 0,
                    "roles": [{"role": "URY Cashier"}],
                }
            ).insert(ignore_permissions=True)
        if not frappe.db.exists("Branch", TEST_BRANCH):
            branch = frappe.get_doc(
                {"doctype": "Branch", "branch": TEST_BRANCH}
            )
            branch.append("user", {"user": TEST_USER})
            branch.insert(ignore_permissions=True)
        frappe.db.commit()

    def setUp(self):
        self._clean()

    def tearDown(self):
        self._clean()
        # Also drop the per-request course cache so each test runs
        # against a fresh department map.
        if hasattr(frappe.local, "_ury_course_dept_cache"):
            del frappe.local._ury_course_dept_cache

    def _clean(self):
        frappe.db.sql(
            "DELETE FROM `tabURY Menu Course` WHERE name LIKE %s",
            (COURSE_PREFIX + "%",),
        )
        # Reset the request-level cache between tests.
        if hasattr(frappe.local, "_ury_course_dept_cache"):
            del frappe.local._ury_course_dept_cache
        frappe.db.commit()

    def _make_course(self, name, department):
        # URY Menu Course autoname is `field:course`, so we set the
        # `course` field explicitly rather than forcing `name`.
        doc = frappe.get_doc(
            {
                "doctype": "URY Menu Course",
                "course": COURSE_PREFIX + name,
                "custom_department": department,
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    def _make_profile_doc(self, **overrides):
        """Build a dict-like that stands in for a POS Profile doc.
        Resolver helpers only call `.get(fieldname)` so a plain dict
        works. This avoids having to create a real POS Profile (which
        needs Company, warehouse, naming series, etc).
        """
        base = {
            "custom_print_mode": "QZ Tray",
            "custom_bill_printer": PRINTER_PREFIX + "Bill",
            "custom_kitchen_kot_printer": PRINTER_PREFIX + "Kitchen",
            "custom_bar_kot_printer": PRINTER_PREFIX + "Bar",
            "custom_parcel_kot_printer": PRINTER_PREFIX + "Parcel",
            "custom_drinks_kot_route": "Bar",
            "custom_food_kot_route": "Kitchen",
            "custom_takeaway_kot_route": "Parcel",
            "custom_print_fallback_mode": "Fallback to Bill Printer",
        }
        base.update(overrides)
        return frappe._dict(base)

    def _make_kot_item(self, item_code, course, qty=1):
        """Build a KOT item row as a dict-like (tests don't create
        real URY KOT / URY KOT Items docs — the helpers only read
        the `course` attribute)."""
        return frappe._dict(
            item_code=item_code,
            course=COURSE_PREFIX + course,
            qty=qty,
        )

    def _make_kot_doc(self, items):
        """Build a namespace-like KOT doc with the given items list.

        We use `types.SimpleNamespace` here instead of `frappe._dict`
        because `_dict` inherits from `dict` — and `dict.items()` is
        a built-in method that shadows the `items` attribute we're
        trying to set. A SimpleNamespace has no such collision.
        """
        return types.SimpleNamespace(items=items)

    # ---------------------------------------------------------------
    # 1. Item classification
    # ---------------------------------------------------------------

    def test_classify_food_course(self):
        self._make_course("Mains", "Food")
        item = self._make_kot_item("Burger", "Mains")
        self.assertEqual(_classify_kot_item_department(item), "Food")

    def test_classify_drinks_course(self):
        self._make_course("Beers", "Drinks")
        item = self._make_kot_item("Beer", "Beers")
        self.assertEqual(_classify_kot_item_department(item), "Drinks")

    def test_classify_other_course(self):
        self._make_course("Desserts", "Other")
        item = self._make_kot_item("Ice Cream", "Desserts")
        self.assertEqual(_classify_kot_item_department(item), "Other")

    def test_classify_unknown_course_defaults_to_food(self):
        """An item whose course doesn't exist in the map is Food."""
        item = self._make_kot_item("Mystery", "Nonexistent")
        self.assertEqual(_classify_kot_item_department(item), "Food")

    def test_classify_item_with_no_course_defaults_to_food(self):
        item = frappe._dict(item_code="Uncategorized", course=None)
        self.assertEqual(_classify_kot_item_department(item), "Food")

    # ---------------------------------------------------------------
    # 2. Bucket splitting
    # ---------------------------------------------------------------

    def test_split_single_department(self):
        self._make_course("Mains", "Food")
        kot = self._make_kot_doc(
            [
                self._make_kot_item("Burger", "Mains"),
                self._make_kot_item("Steak", "Mains"),
            ]
        )
        buckets = _split_kot_items_by_department(kot)
        self.assertEqual(set(buckets.keys()), {"Food"})
        self.assertEqual(len(buckets["Food"]), 2)

    def test_split_mixed_departments(self):
        self._make_course("Mains", "Food")
        self._make_course("Beers", "Drinks")
        kot = self._make_kot_doc(
            [
                self._make_kot_item("Burger", "Mains"),
                self._make_kot_item("Beer", "Beers", qty=2),
                self._make_kot_item("Fries", "Mains"),
            ]
        )
        buckets = _split_kot_items_by_department(kot)
        self.assertEqual(set(buckets.keys()), {"Food", "Drinks"})
        self.assertEqual(len(buckets["Food"]), 2)
        self.assertEqual(len(buckets["Drinks"]), 1)

    def test_split_empty_kot(self):
        kot = self._make_kot_doc([])
        buckets = _split_kot_items_by_department(kot)
        self.assertEqual(buckets, {})

    def test_split_reads_kot_items_attribute(self):
        """_get_kot_items_list must prefer `kot_items` (the real URY
        KOT child table name) over `items`. Previously the helper
        used only `items` which threw AttributeError on real KOT
        docs — reported by the user on 2026-04-16."""
        self._make_course("Mains", "Food")
        self._make_course("Beers", "Drinks")
        # Simulate a real URY KOT doc — kot_items, not items.
        kot = types.SimpleNamespace(
            kot_items=[
                self._make_kot_item("Burger", "Mains"),
                self._make_kot_item("Beer", "Beers"),
            ]
        )
        buckets = _split_kot_items_by_department(kot)
        self.assertEqual(set(buckets.keys()), {"Food", "Drinks"})

    # ---------------------------------------------------------------
    # 3. _resolve_printer_for_department
    # ---------------------------------------------------------------

    def test_resolve_drinks_to_bar(self):
        profile = self._make_profile_doc()
        printer = _resolve_printer_for_department(profile, "Drinks")
        self.assertEqual(printer, PRINTER_PREFIX + "Bar")

    def test_resolve_food_to_kitchen(self):
        profile = self._make_profile_doc()
        printer = _resolve_printer_for_department(profile, "Food")
        self.assertEqual(printer, PRINTER_PREFIX + "Kitchen")

    def test_resolve_food_takeaway_to_parcel(self):
        """Takeaway orders override the Food route to go to Parcel."""
        profile = self._make_profile_doc()
        printer = _resolve_printer_for_department(
            profile, "Food", order_type="Take Away"
        )
        self.assertEqual(printer, PRINTER_PREFIX + "Parcel")

    def test_resolve_food_takeaway_fallback_to_kitchen(self):
        """Takeaway with Parcel printer empty -> Kitchen."""
        profile = self._make_profile_doc(custom_parcel_kot_printer=None)
        printer = _resolve_printer_for_department(
            profile, "Food", order_type="Take Away"
        )
        self.assertEqual(printer, PRINTER_PREFIX + "Kitchen")

    def test_resolve_food_takeaway_route_override_kitchen(self):
        """If custom_takeaway_kot_route is set to Kitchen, use Kitchen
        regardless of Parcel printer."""
        profile = self._make_profile_doc(custom_takeaway_kot_route="Kitchen")
        printer = _resolve_printer_for_department(
            profile, "Food", order_type="Take Away"
        )
        self.assertEqual(printer, PRINTER_PREFIX + "Kitchen")

    def test_resolve_drinks_bar_empty_cascades_to_kitchen(self):
        """When the bar printer is empty, cascade to Kitchen -> Bill."""
        profile = self._make_profile_doc(custom_bar_kot_printer=None)
        printer = _resolve_printer_for_department(profile, "Drinks")
        self.assertEqual(printer, PRINTER_PREFIX + "Kitchen")

    def test_resolve_drinks_bar_and_kitchen_empty_cascades_to_bill(self):
        """When Bar AND Kitchen are empty, cascade to Bill."""
        profile = self._make_profile_doc(
            custom_bar_kot_printer=None,
            custom_kitchen_kot_printer=None,
        )
        printer = _resolve_printer_for_department(profile, "Drinks")
        self.assertEqual(printer, PRINTER_PREFIX + "Bill")

    def test_resolve_drinks_route_set_to_bill(self):
        """Admin explicitly routed Drinks to Bill."""
        profile = self._make_profile_doc(custom_drinks_kot_route="Bill")
        printer = _resolve_printer_for_department(profile, "Drinks")
        self.assertEqual(printer, PRINTER_PREFIX + "Bill")

    def test_resolve_other_department_uses_food_route(self):
        """'Other' (e.g. desserts) routes with Food."""
        profile = self._make_profile_doc()
        printer = _resolve_printer_for_department(profile, "Other")
        self.assertEqual(printer, PRINTER_PREFIX + "Kitchen")

    # ---------------------------------------------------------------
    # 4. resolve_kot_print_plan  (end-to-end, needs real POS Profile)
    # ---------------------------------------------------------------
    # These tests need a POS Profile that can be loaded via
    # `frappe.get_cached_doc`. Creating a real one requires Company +
    # warehouse + naming series which is too much plumbing. Instead
    # we monkey-patch `frappe.get_cached_doc` for the duration of the
    # test so the helper reads our dict-like stand-in.

    def test_plan_unset_mode_returns_empty(self):
        """When custom_print_mode is empty, plan is [] — caller
        falls back to the legacy path."""
        self._make_course("Mains", "Food")
        kot = self._make_kot_doc([self._make_kot_item("Burger", "Mains")])
        profile = self._make_profile_doc(custom_print_mode=None)

        real_get_cached_doc = frappe.get_cached_doc
        frappe.get_cached_doc = lambda dt, name=None: profile
        try:
            plan = resolve_kot_print_plan(
                kot, pos_profile_name=PROFILE_PREFIX + "Test"
            )
        finally:
            frappe.get_cached_doc = real_get_cached_doc

        self.assertEqual(plan, [])

    def test_plan_disabled_mode_returns_empty(self):
        self._make_course("Mains", "Food")
        kot = self._make_kot_doc([self._make_kot_item("Burger", "Mains")])
        profile = self._make_profile_doc(custom_print_mode="Disabled")

        real_get_cached_doc = frappe.get_cached_doc
        frappe.get_cached_doc = lambda dt, name=None: profile
        try:
            plan = resolve_kot_print_plan(
                kot, pos_profile_name=PROFILE_PREFIX + "Test"
            )
        finally:
            frappe.get_cached_doc = real_get_cached_doc

        self.assertEqual(plan, [])

    def test_plan_food_only_produces_one_entry(self):
        self._make_course("Mains", "Food")
        kot = self._make_kot_doc(
            [
                self._make_kot_item("Burger", "Mains"),
                self._make_kot_item("Steak", "Mains"),
            ]
        )
        profile = self._make_profile_doc()

        real_get_cached_doc = frappe.get_cached_doc
        frappe.get_cached_doc = lambda dt, name=None: profile
        try:
            plan = resolve_kot_print_plan(
                kot, pos_profile_name=PROFILE_PREFIX + "Test"
            )
        finally:
            frappe.get_cached_doc = real_get_cached_doc

        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["department"], "Food")
        self.assertEqual(plan[0]["printer"], PRINTER_PREFIX + "Kitchen")
        self.assertEqual(len(plan[0]["items"]), 2)

    def test_plan_mixed_kot_splits_into_two_entries(self):
        """KOT with Food + Drinks produces two plan entries — one
        each, with ONLY the items for that department."""
        self._make_course("Mains", "Food")
        self._make_course("Beers", "Drinks")
        kot = self._make_kot_doc(
            [
                self._make_kot_item("Burger", "Mains"),
                self._make_kot_item("Beer", "Beers", qty=2),
            ]
        )
        profile = self._make_profile_doc()

        real_get_cached_doc = frappe.get_cached_doc
        frappe.get_cached_doc = lambda dt, name=None: profile
        try:
            plan = resolve_kot_print_plan(
                kot, pos_profile_name=PROFILE_PREFIX + "Test"
            )
        finally:
            frappe.get_cached_doc = real_get_cached_doc

        self.assertEqual(len(plan), 2)
        by_dept = {e["department"]: e for e in plan}
        self.assertIn("Food", by_dept)
        self.assertIn("Drinks", by_dept)
        self.assertEqual(by_dept["Food"]["printer"], PRINTER_PREFIX + "Kitchen")
        self.assertEqual(by_dept["Drinks"]["printer"], PRINTER_PREFIX + "Bar")
        # Each bucket only has its own items.
        self.assertEqual(len(by_dept["Food"]["items"]), 1)
        self.assertEqual(len(by_dept["Drinks"]["items"]), 1)
        self.assertEqual(by_dept["Food"]["items"][0].item_code, "Burger")
        self.assertEqual(by_dept["Drinks"]["items"][0].item_code, "Beer")

    def test_plan_takeaway_overrides_food_to_parcel(self):
        """Food on a takeaway order routes to Parcel, not Kitchen."""
        self._make_course("Mains", "Food")
        kot = self._make_kot_doc([self._make_kot_item("Burger", "Mains")])
        profile = self._make_profile_doc()

        real_get_cached_doc = frappe.get_cached_doc
        frappe.get_cached_doc = lambda dt, name=None: profile
        try:
            plan = resolve_kot_print_plan(
                kot,
                pos_profile_name=PROFILE_PREFIX + "Test",
                order_type="Take Away",
            )
        finally:
            frappe.get_cached_doc = real_get_cached_doc

        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["printer"], PRINTER_PREFIX + "Parcel")

    # ---------------------------------------------------------------
    # 5. apply_print_fallback
    # ---------------------------------------------------------------

    def test_fallback_bill_returns_bill_printer_with_header(self):
        profile = self._make_profile_doc(
            custom_print_fallback_mode="Fallback to Bill Printer"
        )
        entry = {"department": "Drinks", "items": [], "printer": None}
        should_print, printer, header = apply_print_fallback(entry, profile)
        self.assertTrue(should_print)
        self.assertEqual(printer, PRINTER_PREFIX + "Bill")
        self.assertIn("DRINKS", header)
        self.assertIn("OFFLINE", header)

    def test_fallback_bill_header_for_food(self):
        profile = self._make_profile_doc()
        entry = {"department": "Food", "items": [], "printer": None}
        _, _, header = apply_print_fallback(entry, profile)
        self.assertIn("FOOD", header)

    def test_fallback_silent_returns_no_print(self):
        profile = self._make_profile_doc(
            custom_print_fallback_mode="Fail Silently"
        )
        entry = {"department": "Drinks", "items": [], "printer": None}
        should_print, printer, header = apply_print_fallback(entry, profile)
        self.assertFalse(should_print)
        self.assertIsNone(printer)

    def test_fallback_alert_returns_no_print(self):
        profile = self._make_profile_doc(
            custom_print_fallback_mode="Fail with Alert"
        )
        entry = {"department": "Drinks", "items": [], "printer": None}
        should_print, printer, header = apply_print_fallback(entry, profile)
        self.assertFalse(should_print)

    def test_fallback_bill_empty_means_no_print(self):
        """When the fallback target (bill printer) is ALSO empty,
        there's no safe target — don't print."""
        profile = self._make_profile_doc(custom_bill_printer=None)
        entry = {"department": "Drinks", "items": [], "printer": None}
        should_print, printer, header = apply_print_fallback(entry, profile)
        self.assertFalse(should_print)
