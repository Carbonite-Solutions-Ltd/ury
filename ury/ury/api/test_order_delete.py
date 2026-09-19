# Copyright (c) 2026, Tridotstech and contributors
# For license information, please see license.txt

"""Tests for Delete vs Cancel (2026-09-19).

Run with:
    bench --site <site> execute ury.ury.api.test_order_delete.run_order_delete_tests

`bench run-tests` is blocked on these sites by ERPNext's test bootstrap, so the
direct runner below is the supported path (see CLAUDE.md working rule 6).

The rules are pure functions and are covered without a database. The live
tests run against the site's own orders - one locked by a cancellation the
kitchen never answered, one paid - and every one of them is rolled back, so
nothing on the site changes.
"""

import unittest

import frappe

from ury.ury.api.ury_kot_display import (
    CANCELLED_BY_CAPTAIN,
    CANCELLED_BY_WAITER,
    DELETED_ORDER,
    _finalize_invoice_cancellation,
    get_removed_orders,
    kot_list,
    merge_pending_cancellations,
    removed_kind,
)
from ury.ury.doctype.ury_order.ury_order import (
    _delete_kots_within_grace,
    can_delete_orders,
    delete_order,
)


class CanDeleteTests(unittest.TestCase):
    def test_administrator(self):
        self.assertTrue(can_delete_orders("Administrator", []))

    def test_managers(self):
        for role in ("System Manager", "URY Manager"):
            self.assertTrue(can_delete_orders("x@y", ["All", role]), role)

    def test_captain_cannot_delete(self):
        # A captain can still Cancel; Delete skips the kitchen, so it is a
        # level above.
        self.assertFalse(can_delete_orders("x@y", ["URY Captain"]))

    def test_cashier_and_waiter_cannot(self):
        self.assertFalse(can_delete_orders("x@y", ["URY Cashier", "URY Waiter"]))

    def test_no_roles(self):
        self.assertFalse(can_delete_orders("x@y", None))


class RemovedKindTests(unittest.TestCase):
    def test_deleted(self):
        self.assertEqual(removed_kind(DELETED_ORDER), "deleted")

    def test_cancelled_by_captain_and_waiter(self):
        self.assertEqual(removed_kind(CANCELLED_BY_CAPTAIN), "cancelled")
        self.assertEqual(removed_kind(CANCELLED_BY_WAITER), "cancelled")

    def test_live_tickets_are_neither(self):
        for status in ("Ready For Prepare", "Served", "", None):
            self.assertIsNone(removed_kind(status), status)


def _board(*names):
    return [frappe._dict(name=n) for n in names]


class MergePendingTests(unittest.TestCase):
    def test_pending_go_first(self):
        merged = merge_pending_cancellations(_board("A", "B"), ["P"])
        self.assertEqual([r.name for r in merged], ["P", "A", "B"])

    def test_pending_already_on_board_is_moved_not_repeated(self):
        merged = merge_pending_cancellations(_board("A", "P", "B"), ["P"])
        self.assertEqual([r.name for r in merged], ["P", "A", "B"])

    def test_repeated_pending_names_appear_once(self):
        merged = merge_pending_cancellations(_board("A"), ["P", "P", "Q"])
        self.assertEqual([r.name for r in merged], ["P", "Q", "A"])

    def test_nothing_pending_leaves_board_alone(self):
        merged = merge_pending_cancellations(_board("A", "B"), [])
        self.assertEqual([r.name for r in merged], ["A", "B"])

    def test_empty_board(self):
        self.assertEqual([r.name for r in merge_pending_cancellations(None, ["P"])], ["P"])


class LiveDeleteTests(unittest.TestCase):
    """Against real orders; every test is rolled back."""

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        # An order locked by a cancellation the kitchen never answered,
        # ideally with a served ticket - the case that was stuck for good.
        row = frappe.db.sql(
            """
            SELECT pi.name, k.production
            FROM `tabPOS Invoice` pi
            INNER JOIN `tabURY KOT` k ON k.invoice = pi.name
            WHERE pi.docstatus = 0 AND pi.custom_cancel_pending = 1
              AND k.docstatus = 1 AND k.cancel_status = 'Awaiting Kitchen'
            ORDER BY (k.order_status = 'Served') DESC, pi.creation DESC
            LIMIT 1
            """,
            as_dict=True,
        )
        if not row:
            raise unittest.SkipTest("needs an order with an unanswered cancellation")
        cls.locked = row[0].name
        cls.unit = row[0].production
        cls.paid = frappe.db.get_value("POS Invoice", {"docstatus": 1}, "name")

    def tearDown(self):
        frappe.db.rollback()
        frappe.set_user("Administrator")

    def _kot_names(self, invoice):
        return frappe.get_all(
            "URY KOT", filters={"invoice": invoice, "docstatus": 1}, pluck="name"
        )

    def test_unanswered_request_now_shows_on_the_board(self):
        board = {k["name"] for k in kot_list(target=self.unit).get("KOT", [])}
        pending = set(
            frappe.get_all(
                "URY KOT",
                filters={"invoice": self.locked, "cancel_status": "Awaiting Kitchen"},
                pluck="name",
            )
        )
        self.assertTrue(pending)
        self.assertTrue(pending <= board, "pending requests missing from the board")

    def test_delete_frees_a_locked_order(self):
        result = delete_order(self.locked, reason="Kitchen cleared this a week ago")
        self.assertEqual(result["mode"], "deleted")

        inv = frappe.db.get_value(
            "POS Invoice",
            self.locked,
            ["docstatus", "status", "cancel_reason", "custom_cancel_pending",
             "custom_deleted", "custom_deleted_by", "custom_deleted_at", "custom_on_hold"],
            as_dict=True,
        )
        self.assertEqual((inv.docstatus, inv.status), (2, "Cancelled"))
        self.assertEqual(inv.custom_cancel_pending, 0)
        self.assertEqual(inv.custom_deleted, 1)
        self.assertEqual(inv.custom_deleted_by, "Administrator")
        self.assertTrue(inv.custom_deleted_at)
        self.assertFalse(inv.custom_on_hold)
        self.assertEqual(inv.cancel_reason, "Kitchen cleared this a week ago")

        for name in self._kot_names(self.locked):
            k = frappe.db.get_value(
                "URY KOT", name, ["order_status", "cancel_status", "cancel_reason"], as_dict=True
            )
            self.assertEqual(k.order_status, DELETED_ORDER, name)
            self.assertEqual(k.cancel_status, "Deleted", name)
            self.assertEqual(k.cancel_reason, "Kitchen cleared this a week ago", name)

    def test_deleted_order_leaves_the_board_and_lands_on_the_list(self):
        names = set(self._kot_names(self.locked))
        delete_order(self.locked, reason="test")
        board = {k["name"] for k in kot_list(target=self.unit).get("KOT", [])}
        self.assertFalse(names & board)

        lists = get_removed_orders(production=self.unit)
        deleted = {r["kot"]: r for r in lists["deleted"]}
        mine = [n for n in names if n in deleted]
        self.assertTrue(mine, "deleted order missing from the kitchen's Deleted list")
        self.assertEqual(deleted[mine[0]]["reason"], "test")
        self.assertEqual(deleted[mine[0]]["removed_by"], frappe.db.get_value("User", "Administrator", "full_name"))
        self.assertFalse({r["kot"] for r in lists["cancelled"]} & names)

    def test_reason_required(self):
        self.assertRaises(frappe.ValidationError, delete_order, self.locked, "   ")

    def test_paid_bill_cannot_be_deleted(self):
        if not self.paid:
            self.skipTest("no paid bill on this site")
        self.assertRaises(frappe.ValidationError, delete_order, self.paid, "x")

    def test_second_delete_is_refused(self):
        delete_order(self.locked, reason="first")
        self.assertRaises(frappe.ValidationError, delete_order, self.locked, "again")

    def test_missing_order(self):
        self.assertRaises(frappe.ValidationError, delete_order, "NO-SUCH-ORDER", "x")

    def test_captain_is_refused(self):
        captain = frappe.db.sql(
            """
            SELECT hr.parent FROM `tabHas Role` hr
            INNER JOIN `tabUser` u ON u.name = hr.parent AND u.enabled = 1
            WHERE hr.parenttype = 'User' AND hr.role = 'URY Captain'
              AND hr.parent NOT IN (
                SELECT parent FROM `tabHas Role`
                WHERE parenttype = 'User'
                  AND role IN ('System Manager', 'URY Manager', 'Administrator')
              )
            LIMIT 1
            """
        )
        if captain:
            email = captain[0][0]
        else:
            # Made inside this test's transaction, so the rollback removes it.
            email = "delete-test-captain@ury-test.local"
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Delete Test Captain",
                    "send_welcome_email": 0,
                    "roles": [{"role": "URY Captain"}],
                }
            ).insert(ignore_permissions=True)
        try:
            frappe.set_user(email)
            self.assertRaises(frappe.PermissionError, delete_order, self.locked, "x")
        finally:
            frappe.set_user("Administrator")
            frappe.cache.hdel("roles", email)

    def test_kitchen_accept_cannot_cancel_a_paid_bill(self):
        if not self.paid:
            self.skipTest("no paid bill on this site")
        self.assertFalse(_finalize_invoice_cancellation(self.paid, "x"))
        self.assertEqual(frappe.db.get_value("POS Invoice", self.paid, "docstatus"), 1)

    def test_grace_cancel_records_who_and_why(self):
        name = self._kot_names(self.locked)[0]
        _delete_kots_within_grace([{"name": name}], reason="Guest left")
        k = frappe.db.get_value(
            "URY KOT",
            name,
            ["order_status", "cancel_reason", "cancel_requested_by", "cancel_requested_at"],
            as_dict=True,
        )
        self.assertEqual(k.order_status, CANCELLED_BY_CAPTAIN)
        self.assertEqual(k.cancel_reason, "Guest left")
        self.assertEqual(k.cancel_requested_by, "Administrator")
        self.assertTrue(k.cancel_requested_at)


def run_order_delete_tests():
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for case in (CanDeleteTests, RemovedKindTests, MergePendingTests, LiveDeleteTests):
        suite.addTests(loader.loadTestsFromTestCase(case))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)}
