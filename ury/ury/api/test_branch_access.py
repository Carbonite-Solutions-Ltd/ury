# Copyright (c) 2026, Tridotstech and contributors
# For license information, please see license.txt

"""Tests for branch access on POS terminals (2026-09-19).

Run with:
    bench --site <site> execute ury.ury.api.test_branch_access.run_branch_access_tests

Rule: a user may only use the terminals of branches whose ExPOS Users table
lists them; Administrator and System Manager have every branch. Once the POS
opens on a terminal, getBranch() follows that terminal's branch for the
session.

The live tests need a site with two branches that each have a terminal. They
add throwaway users inside a transaction that is rolled back after every test.
"""

import unittest

import frappe

from ury.ury_pos.api import (
    ACTIVE_BRANCH_CACHE,
    can_use_branch,
    getBranch,
    getPosProfile,
    get_terminal_config,
    get_terminals,
)

TEST_SID = "ury-branch-access-test-sid"


class CanUseBranchTests(unittest.TestCase):
    def test_own_branch(self):
        self.assertTrue(can_use_branch("Airport", ["Airport"], False))

    def test_other_branch_refused(self):
        self.assertFalse(can_use_branch("Sitout", ["Airport"], False))

    def test_user_on_two_branches(self):
        self.assertTrue(can_use_branch("Sitout", ["Airport", "Sitout"], False))

    def test_all_access(self):
        self.assertTrue(can_use_branch("Sitout", [], True))

    def test_no_branches(self):
        self.assertFalse(can_use_branch("Airport", [], False))
        self.assertFalse(can_use_branch("Airport", None, False))

    def test_blank_branch_refused(self):
        self.assertFalse(can_use_branch("", ["Airport"], False))
        self.assertFalse(can_use_branch(None, ["Airport"], False))


class LiveBranchAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        rows = frappe.db.sql(
            """
            SELECT t.branch, MIN(t.name)
            FROM `tabURY POS Terminal` t
            INNER JOIN `tabPOS Profile` p ON p.name = t.pos_profile AND p.branch = t.branch
            WHERE t.disabled = 0
            GROUP BY t.branch
            ORDER BY t.branch
            """
        )
        if len(rows) < 2:
            raise unittest.SkipTest("needs two branches with a terminal each")
        (cls.branch_a, cls.term_a), (cls.branch_b, cls.term_b) = rows[0], rows[1]

    def setUp(self):
        self._old_sid = getattr(frappe.session, "sid", None)
        frappe.session.sid = TEST_SID
        self.made = []

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.session.sid = self._old_sid
        frappe.cache.hdel(ACTIVE_BRANCH_CACHE, TEST_SID)
        frappe.db.rollback()
        for email in self.made:
            frappe.cache.hdel("roles", email)

    def _user(self, email, roles, branches):
        frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": email.split("@")[0],
                "send_welcome_email": 0,
                "roles": [{"role": r} for r in roles],
            }
        ).insert(ignore_permissions=True)
        for branch in branches:
            row = frappe.get_doc(
                {
                    "doctype": "URY User",
                    "parent": branch,
                    "parenttype": "Branch",
                    "parentfield": "user",
                    "user": email,
                }
            )
            row.db_insert()
        self.made.append(email)
        frappe.set_user(email)
        # `frappe.set_user` resets the session; keep the test key for caching.
        frappe.session.sid = TEST_SID
        return email

    def test_single_branch_user_sees_only_their_terminals(self):
        self._user("ba-one@ury-test.local", ["URY Cashier"], [self.branch_a])
        branches = {t["branch"] for t in get_terminals()}
        self.assertEqual(branches, {self.branch_a})

    def test_single_branch_user_refused_other_terminal(self):
        self._user("ba-one@ury-test.local", ["URY Cashier"], [self.branch_a])
        self.assertRaises(frappe.PermissionError, get_terminal_config, self.term_b)
        self.assertRaises(frappe.PermissionError, getPosProfile, self.term_b)
        self.assertEqual(get_terminal_config(self.term_a)["branch"], self.branch_a)

    def test_two_branch_user_follows_the_terminal(self):
        self._user("ba-two@ury-test.local", ["URY Cashier"], [self.branch_a, self.branch_b])
        self.assertEqual(
            {t["branch"] for t in get_terminals()}, {self.branch_a, self.branch_b}
        )
        get_terminal_config(self.term_b)
        self.assertEqual(getBranch(), self.branch_b)
        get_terminal_config(self.term_a)
        self.assertEqual(getBranch(), self.branch_a)

    def test_remembered_branch_ignored_once_access_is_gone(self):
        self._user("ba-one@ury-test.local", ["URY Cashier"], [self.branch_a])
        frappe.cache.hset(ACTIVE_BRANCH_CACHE, TEST_SID, self.branch_b)
        self.assertEqual(getBranch(), self.branch_a)

    def test_administrator_on_either_branch(self):
        # The crash: an Administrator on the terminal of a branch other than
        # the first POS Profile's used to hit UnboundLocalError.
        for term, branch in ((self.term_a, self.branch_a), (self.term_b, self.branch_b)):
            profile = getPosProfile(terminal=term)
            self.assertEqual(profile["branch"], branch)
            self.assertEqual(getBranch(), branch)

    def test_system_manager_sees_every_branch(self):
        self._user("ba-sm@ury-test.local", ["System Manager"], [])
        self.assertEqual(
            {t["branch"] for t in get_terminals()} >= {self.branch_a, self.branch_b},
            True,
        )
        self.assertEqual(get_terminal_config(self.term_b)["branch"], self.branch_b)

    def test_unlinked_user_gets_the_branch_message(self):
        self._user("ba-none@ury-test.local", ["URY Cashier"], [])
        self.assertRaises(frappe.ValidationError, get_terminals)


def run_branch_access_tests():
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for case in (CanUseBranchTests, LiveBranchAccessTests):
        suite.addTests(loader.loadTestsFromTestCase(case))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)}
