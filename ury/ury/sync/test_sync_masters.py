"""Tests for cloud → branch master replication.

Needs a bench (masters.py imports frappe), so run it with:

    bench --site <site> execute ury.ury.sync.test_sync_masters.run_sync_masters_tests

The watermark and ordering functions are pure, and they are the two places
where a quiet mistake is expensive: a watermark that rewinds re-pulls the same
page forever, and an order that puts Item before Item Group fails validation
on every item a branch has never seen.
"""

import unittest

from ury.ury.sync import masters


class AllowlistTests(unittest.TestCase):
	def test_known_doctypes_are_allowed(self):
		self.assertTrue(masters.is_allowed("Item"))
		self.assertTrue(masters.is_allowed("URY Menu"))

	def test_arbitrary_doctypes_are_not(self):
		# The branch holds head-office API credentials. The allowlist is what
		# stops those credentials being used to pull anything at all.
		self.assertFalse(masters.is_allowed("User"))
		self.assertFalse(masters.is_allowed("POS Invoice"))
		self.assertFalse(masters.is_allowed("GL Entry"))

	def test_item_price_is_deliberately_excluded(self):
		"""⚠ Guards the subtlest decision in the module.

		Item Price and Price List are REGENERATED on the branch by
		URY Menu.on_update -> make_price_list(). Replicating them as well
		would give those rows two writers. If someone "completes" the
		allowlist by adding them, this test is the thing that objects.
		"""
		self.assertFalse(masters.is_allowed("Item Price"))
		self.assertFalse(masters.is_allowed("Price List"))


class OrderingTests(unittest.TestCase):
	def test_dependencies_come_first(self):
		order = masters.MASTER_DOCTYPES
		self.assertLess(order.index("Item Group"), order.index("Item"))
		self.assertLess(order.index("Item Tax Template"), order.index("Item"))
		self.assertLess(order.index("Tax Category"), order.index("Item Tax Template"))
		self.assertLess(order.index("URY Menu Course"), order.index("URY Menu"))
		self.assertLess(order.index("Customer Group"), order.index("Customer"))
		self.assertLess(order.index("Territory"), order.index("Customer"))

	def test_empty_request_means_everything(self):
		self.assertEqual(masters.ordered_doctypes(), masters.MASTER_DOCTYPES)
		self.assertEqual(masters.ordered_doctypes(None), masters.MASTER_DOCTYPES)

	def test_request_is_reordered_not_trusted(self):
		# Asked for in the wrong order, returned in the right one.
		got = masters.ordered_doctypes(["Item", "Item Group"])
		self.assertEqual(got, ["Item Group", "Item"])

	def test_unknown_doctypes_are_dropped(self):
		got = masters.ordered_doctypes(["Item", "User", "GL Entry"])
		self.assertEqual(got, ["Item"])


class WatermarkTests(unittest.TestCase):
	def test_advances_to_the_highest_modified(self):
		rows = [
			{"modified": "2026-01-01 10:00:00"},
			{"modified": "2026-01-03 10:00:00"},
			{"modified": "2026-01-02 10:00:00"},
		]
		self.assertEqual(
			masters.next_watermark(rows, "2026-01-01 00:00:00"),
			"2026-01-03 10:00:00",
		)

	def test_uses_max_not_the_last_row(self):
		"""Rows arrive ordered, but max() means a caller that filters or
		reorders cannot silently rewind the watermark."""
		rows = [{"modified": "2026-05-05 09:00:00"}, {"modified": "2026-01-01 09:00:00"}]
		self.assertEqual(masters.next_watermark(rows, None), "2026-05-05 09:00:00")

	def test_never_rewinds(self):
		rows = [{"modified": "2026-01-01 10:00:00"}]
		current = "2026-06-01 00:00:00"
		self.assertEqual(masters.next_watermark(rows, current), current)

	def test_empty_page_leaves_it_alone(self):
		self.assertEqual(masters.next_watermark([], "2026-01-01 00:00:00"), "2026-01-01 00:00:00")
		self.assertIsNone(masters.next_watermark([], None))

	def test_rows_without_modified_are_ignored(self):
		self.assertEqual(masters.next_watermark([{"name": "X"}], "2026-01-01 00:00:00"),
		                 "2026-01-01 00:00:00")


class SanitiseTests(unittest.TestCase):
	def test_volatile_bookkeeping_is_stripped(self):
		out = masters.sanitise(
			{
				"name": "ITEM-1",
				"item_name": "Jollof",
				"owner": "someone@cloud",
				"modified_by": "someone@cloud",
				"creation": "2026-01-01 00:00:00",
				"modified": "2026-01-02 00:00:00",
				"_user_tags": "x",
				"_comments": "[]",
			}
		)
		self.assertEqual(out["name"], "ITEM-1")
		self.assertEqual(out["item_name"], "Jollof")
		for gone in ("owner", "modified_by", "creation", "modified", "_user_tags", "_comments"):
			self.assertNotIn(gone, out)

	def test_children_are_kept_but_their_names_dropped(self):
		"""Child rows are rebuilt on apply rather than matched by name, so a
		stale child cannot survive an update."""
		out = masters.sanitise(
			{
				"name": "MENU-1",
				"items": [
					{"name": "abc123", "item": "ITEM-1", "rate": 10, "idx": 1,
					 "owner": "x", "creation": "2026-01-01 00:00:00"},
				],
			}
		)
		self.assertEqual(len(out["items"]), 1)
		child = out["items"][0]
		self.assertEqual(child["item"], "ITEM-1")
		self.assertEqual(child["idx"], 1, "idx must survive — it is the row order")
		self.assertNotIn("name", child)
		self.assertNotIn("owner", child)

	def test_empty_and_missing_input_do_not_explode(self):
		self.assertEqual(masters.sanitise({}), {})
		self.assertEqual(masters.sanitise(None), {})

	def test_non_dict_child_rows_are_skipped(self):
		out = masters.sanitise({"name": "X", "items": ["junk", {"item": "ITEM-1"}]})
		self.assertEqual(out["items"], [{"item": "ITEM-1"}])


def run_sync_masters_tests():
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (AllowlistTests, OrderingTests, WatermarkTests, SanitiseTests):
		suite.addTests(loader.loadTestsFromTestCase(case))
	unittest.TextTestRunner(verbosity=2).run(suite)
