# Copyright (c) 2023, Tridz Technologies  and Contributors
# See license.txt

import types
import unittest

from ury.ury.doctype.ury_menu.ury_menu import (
	_diff_menu_item,
	_find_menu_item_row,
	_pick_menu_item_rate,
)


def _row(item, rate=0, course=None):
	return types.SimpleNamespace(item=item, rate=rate, course=course)


class TestMenuItemRatePrecedence(unittest.TestCase):
	def test_explicit_rate_wins(self):
		self.assertEqual(_pick_menu_item_rate(15, 5), 15.0)

	def test_explicit_zero_is_respected(self):
		# 0 is a real, explicit price — not "unset" — so it must win.
		self.assertEqual(_pick_menu_item_rate(0, 5), 0.0)

	def test_standard_rate_fallback(self):
		self.assertEqual(_pick_menu_item_rate(None, 5), 5.0)

	def test_empty_string_treated_as_unset(self):
		# Currency dialog field comes back as "" when blank.
		self.assertEqual(_pick_menu_item_rate("", 5), 5.0)

	def test_all_unset_defaults_to_zero(self):
		self.assertEqual(_pick_menu_item_rate(None, None), 0.0)

	def test_string_numbers_are_coerced(self):
		self.assertEqual(_pick_menu_item_rate("12.5", None), 12.5)


class TestFindMenuItemRow(unittest.TestCase):
	def test_present_returns_row(self):
		rows = [_row("Fanta"), _row("Sprite", rate=20)]
		found = _find_menu_item_row(rows, "Sprite")
		self.assertIsNotNone(found)
		self.assertEqual(found.rate, 20)

	def test_absent_returns_none(self):
		self.assertIsNone(_find_menu_item_row([_row("Fanta")], "Coke"))

	def test_empty_menu_returns_none(self):
		self.assertIsNone(_find_menu_item_row([], "Coke"))


class TestDiffMenuItem(unittest.TestCase):
	def test_no_change(self):
		self.assertEqual(_diff_menu_item(80, "Mains", 80, "Mains"), [])

	def test_rate_float_equality_is_no_change(self):
		# 80 (int row) vs 80.0 (resolved) must not register as a change.
		self.assertEqual(_diff_menu_item(80, "Mains", 80.0, "Mains"), [])

	def test_rate_change(self):
		changes = _diff_menu_item(80, "Mains", 120, "Mains")
		self.assertEqual(changes, [{"field": "Rate", "old": 80.0, "new": 120.0}])

	def test_course_change(self):
		changes = _diff_menu_item(80, "Starters", 80, "Mains")
		self.assertEqual(changes, [{"field": "Course", "old": "Starters", "new": "Mains"}])

	def test_both_change(self):
		changes = _diff_menu_item(80, "Starters", 120, "Mains")
		fields = {c["field"] for c in changes}
		self.assertEqual(fields, {"Rate", "Course"})

	def test_course_none_vs_empty_is_no_change(self):
		# An existing NULL course and a blank dialog value are equivalent.
		self.assertEqual(_diff_menu_item(80, None, 80, None), [])

	def test_course_set_to_blank_is_a_change(self):
		changes = _diff_menu_item(80, "Mains", 80, None)
		self.assertEqual(changes, [{"field": "Course", "old": "Mains", "new": ""}])


def run_menu_tests():
	"""Direct unittest runner — bypasses bench run-tests (ERPNext test bootstrap
	is a known blocker on this site, see CLAUDE.md rule 6). Invoke via:
	bench --site <site> execute ury.ury.doctype.ury_menu.test_ury_menu.run_menu_tests
	"""
	loader = unittest.TestLoader()
	suite = unittest.TestSuite()
	for case in (TestMenuItemRatePrecedence, TestFindMenuItemRow, TestDiffMenuItem):
		suite.addTests(loader.loadTestsFromTestCase(case))
	unittest.TextTestRunner(verbosity=2).run(suite)
