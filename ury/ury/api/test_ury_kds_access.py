# Copyright (c) 2026, Tridotstech and contributors
# For license information, please see license.txt

"""Tests for kitchen-screen access (URY Production Unit "Screen Access").

Run with:
    bench --site <site> execute ury.ury.api.test_ury_kds_access.run_kds_access_tests

`bench run-tests` is blocked on these sites by ERPNext's test bootstrap, so the
direct runner below is the supported path (see CLAUDE.md working rule 6).

The rules live in pure functions and are covered without a database. The live
tests create throwaway users, tag them on the site's real production units,
exercise the endpoints as those users, and restore everything afterwards.
They need a site with at least two production units on one branch.
"""

import unittest

import frappe

from ury.ury.api.ury_kds_access import (
	PRODUCTION_ROLE,
	can_open_unit,
	get_my_production_units,
	is_kds_elevated,
	screen_groups,
	units_for_user,
)

A = "kds-a@ury-test.local"
B = "kds-b@ury-test.local"


class CanOpenUnitTests(unittest.TestCase):
	def test_empty_table_is_open_to_anyone(self):
		self.assertTrue(can_open_unit(set(), "x@y", False))

	def test_listed_user_may_open(self):
		self.assertTrue(can_open_unit({"x@y"}, "x@y", False))

	def test_unlisted_user_is_refused(self):
		self.assertFalse(can_open_unit({"a@b"}, "x@y", False))

	def test_elevated_user_opens_a_restricted_unit(self):
		self.assertTrue(can_open_unit({"a@b"}, "x@y", True))


class UnitsForUserTests(unittest.TestCase):
	MAP = {
		"Bar": {"barman@x"},
		"Grill": {"cook@x", "barman@x"},
		"Pastry": set(),
	}

	def test_one_unit(self):
		self.assertEqual(units_for_user(self.MAP, "cook@x", False), (["Grill"], "assigned"))

	def test_several_units_keep_map_order(self):
		self.assertEqual(
			units_for_user(self.MAP, "barman@x", False), (["Bar", "Grill"], "assigned")
		)

	def test_assigned_units_hide_the_open_ones(self):
		# Someone listed on a unit sees their units, not every open one too.
		names, _ = units_for_user(self.MAP, "cook@x", False)
		self.assertNotIn("Pastry", names)

	def test_unlisted_user_gets_the_open_units(self):
		self.assertEqual(units_for_user(self.MAP, "new@x", False), (["Pastry"], "open"))

	def test_unlisted_user_with_every_unit_restricted(self):
		closed = {"Bar": {"a@x"}, "Grill": {"b@x"}}
		self.assertEqual(units_for_user(closed, "new@x", False), ([], "none"))

	def test_nobody_configured_means_everything_open(self):
		# The day this ships no table has users, so nothing changes.
		fresh = {"Bar": set(), "Grill": set()}
		self.assertEqual(units_for_user(fresh, "anyone@x", False), (["Bar", "Grill"], "open"))

	def test_elevated_sees_all(self):
		self.assertEqual(
			units_for_user(self.MAP, "boss@x", True), (["Bar", "Grill", "Pastry"], "all")
		)

	def test_no_units_at_all(self):
		self.assertEqual(units_for_user({}, "x@y", False), ([], "none"))


class ElevatedTests(unittest.TestCase):
	def test_administrator(self):
		self.assertTrue(is_kds_elevated("Administrator", []))

	def test_captain_manager_system_manager(self):
		for role in ("URY Captain", "URY Manager", "System Manager"):
			self.assertTrue(is_kds_elevated("x@y", ["All", role]), role)

	def test_cashier_and_production_user_are_not(self):
		self.assertFalse(is_kds_elevated("x@y", ["URY Cashier", PRODUCTION_ROLE]))


class ScreenGroupsTests(unittest.TestCase):
	def test_production_unit_mode(self):
		self.assertEqual(screen_groups(["URY Production Unit"]), (True, []))

	def test_menu_course_mode(self):
		self.assertEqual(
			screen_groups(["Menu Course"]), (False, ["Food", "Drinks", "Other", "All"])
		)

	def test_blank_mode_is_menu_course(self):
		self.assertEqual(screen_groups([None])[0], False)

	def test_mixed_sites_get_both(self):
		show_units, departments = screen_groups(["Menu Course", "URY Production Unit"])
		self.assertTrue(show_units)
		self.assertTrue(departments)

	def test_no_profiles(self):
		self.assertEqual(screen_groups([]), (True, []))


class LiveAccessTests(unittest.TestCase):
	"""A is tagged on one unit, B on two; the third unit is left open."""

	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		units = frappe.get_all("URY Production Unit", fields=["name", "branch"], order_by="name")
		by_branch = {}
		for u in units:
			by_branch.setdefault(u.branch, []).append(u.name)
		branch, names = max(by_branch.items(), key=lambda kv: len(kv[1]))
		if len(names) < 2:
			raise unittest.SkipTest("needs two production units on one branch")
		cls.branch = branch
		cls.u1, cls.u2 = names[0], names[1]
		cls.others = [n for n in (u.name for u in units) if n not in (cls.u1, cls.u2)]

		# Remember every unit's table so it can be put back exactly.
		cls.saved = {
			u.name: [r.user for r in frappe.get_doc("URY Production Unit", u.name).users]
			for u in units
		}
		for name in cls.saved:
			cls._set_users(name, [])

		for email in (A, B):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": email.split("@")[0],
					"send_welcome_email": 0,
					"roles": [{"role": PRODUCTION_ROLE}],
				}
			).insert(ignore_permissions=True)

		cls._set_users(cls.u1, [A, B, B])  # duplicate on purpose: validate drops it
		cls._set_users(cls.u2, [B])
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for name, users in cls.saved.items():
			cls._set_users(name, users)
		for email in (A, B):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		frappe.db.commit()

	@staticmethod
	def _set_users(unit, users):
		doc = frappe.get_doc("URY Production Unit", unit)
		doc.set("users", [{"user": u} for u in users])
		doc.save(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_duplicate_rows_are_dropped_on_save(self):
		users = [r.user for r in frappe.get_doc("URY Production Unit", self.u1).users]
		self.assertEqual(sorted(users), sorted([A, B]))

	def test_single_unit_user(self):
		frappe.set_user(A)
		res = get_my_production_units()
		self.assertEqual(res["scope"], "assigned")
		self.assertEqual([u["name"] for u in res["units"]], [self.u1])

	def test_multi_unit_user(self):
		frappe.set_user(B)
		res = get_my_production_units()
		self.assertEqual(sorted(u["name"] for u in res["units"]), sorted([self.u1, self.u2]))

	def test_current_unit_checks(self):
		frappe.set_user(A)
		self.assertEqual(get_my_production_units(current=self.u1)["current_allowed"], 1)
		self.assertEqual(get_my_production_units(current=self.u2)["current_allowed"], 0)
		not_a_unit = get_my_production_units(current="Food")
		self.assertEqual((not_a_unit["current_is_unit"], not_a_unit["current_allowed"]), (0, 1))
		for other in self.others:  # tables left empty -> open to anyone
			self.assertEqual(get_my_production_units(current=other)["current_allowed"], 1)

	def test_administrator_sees_every_unit(self):
		res = get_my_production_units()
		self.assertEqual(res["scope"], "all")
		self.assertEqual(len(res["units"]), len(self.saved))

	def test_kot_list_refuses_a_unit_not_on_the_user(self):
		from ury.ury.api.ury_kot_display import kot_list

		frappe.set_user(A)
		res = kot_list(target=self.u2)
		self.assertEqual(res.get("access_denied"), 1)
		self.assertEqual(res.get("KOT"), [])

	def test_kot_list_opens_own_unit_without_a_branch_row(self):
		from ury.ury.api.ury_kot_display import kot_list

		frappe.set_user(A)
		res = kot_list(target=self.u1)
		self.assertFalse(res.get("access_denied"))
		self.assertFalse(res.get("error"))
		self.assertEqual(res.get("Branch"), self.branch)

	def test_served_endpoints_refuse_another_unit(self):
		from ury.ury.api.ury_kot_display import get_served_summary, served_kot_list

		frappe.set_user(A)
		self.assertRaises(frappe.PermissionError, served_kot_list, self.u2)
		self.assertRaises(frappe.PermissionError, get_served_summary, self.u2)
		served_kot_list(self.u1)  # own unit: no error

	def test_bar_endpoints_refuse_another_unit(self):
		from ury.ury.api.ury_bar_stock import get_bar_session_state

		frappe.set_user(A)
		self.assertRaises(frappe.PermissionError, get_bar_session_state, self.u2)
		frappe.set_user(B)
		self.assertEqual(get_bar_session_state(self.u2)["production"], self.u2)

	def test_get_branch_falls_back_to_the_assigned_unit(self):
		from ury.ury_pos.api import getBranch

		frappe.set_user(A)
		self.assertEqual(getBranch(), self.branch)


def run_kds_access_tests():
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (
		CanOpenUnitTests,
		UnitsForUserTests,
		ElevatedTests,
		ScreenGroupsTests,
		LiveAccessTests,
	):
		suite.addTests(loader.loadTestsFromTestCase(case))
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	return {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)}
