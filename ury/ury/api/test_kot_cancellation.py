"""Tests for the cancellation grace window + POS→kitchen handshake.

Run with:
    bench --site <site> execute \
        ury.ury.api.test_kot_cancellation.run_cancellation_tests

`bench run-tests` is blocked on this site by a pre-existing ERPNext
bootstrap failure (see CLAUDE.md rule 6), so this file ships its own
runner that drives unittest directly.

The two functions under test here are the ones that actually decide
whether a cook gets interrupted, so they are covered exhaustively:
precedence between the two config levels, and the boundary of the
window itself.
"""

import unittest
from datetime import datetime, timedelta

from ury.ury.api.ury_kot_display import (
    DEFAULT_CANCEL_GRACE_MINUTES,
    _grace_expired,
    _pick_grace_minutes,
    _plan_item_removal,
)


class PickGraceMinutesTests(unittest.TestCase):
    """Production Unit wins, POS Profile is the fallback, 2 is the floor."""

    def test_unit_wins_over_profile(self):
        self.assertEqual(_pick_grace_minutes(5, 2), 5)

    def test_profile_used_when_unit_unset(self):
        # The Menu Course case: a KOT has no production unit at all, so
        # without this fallback the feature would silently never fire.
        self.assertEqual(_pick_grace_minutes(None, 7), 7)

    def test_default_when_neither_set(self):
        self.assertEqual(_pick_grace_minutes(None, None), DEFAULT_CANCEL_GRACE_MINUTES)

    def test_zero_unit_means_unset_not_no_grace(self):
        # An Int field left at its 0 default must inherit, not collapse
        # the window to nothing and force every cancel through the
        # kitchen.
        self.assertEqual(_pick_grace_minutes(0, 6), 6)

    def test_zero_at_both_levels_falls_to_default(self):
        self.assertEqual(_pick_grace_minutes(0, 0), DEFAULT_CANCEL_GRACE_MINUTES)

    def test_unit_wins_even_when_profile_is_larger(self):
        # A bar can un-pour for longer than a kitchen can un-cook, so a
        # SMALLER unit value must still beat a larger profile default.
        self.assertEqual(_pick_grace_minutes(1, 30), 1)


class GraceExpiredTests(unittest.TestCase):
    """The window boundary."""

    def setUp(self):
        self.created = datetime(2026, 7, 31, 12, 0, 0)

    def _at(self, **kw):
        return self.created + timedelta(**kw)

    def test_immediately_after_creation_is_inside(self):
        self.assertFalse(_grace_expired(self.created, self._at(seconds=1), 2))

    def test_well_inside_window(self):
        self.assertFalse(_grace_expired(self.created, self._at(seconds=90), 2))

    def test_exactly_on_boundary_is_still_inside(self):
        # Strictly greater-than: on the line you keep the grace.
        self.assertFalse(_grace_expired(self.created, self._at(minutes=2), 2))

    def test_one_second_past_boundary_expires(self):
        self.assertTrue(_grace_expired(self.created, self._at(minutes=2, seconds=1), 2))

    def test_long_past_expires(self):
        self.assertTrue(_grace_expired(self.created, self._at(hours=3), 2))

    def test_larger_window_still_inside(self):
        self.assertFalse(_grace_expired(self.created, self._at(minutes=4), 5))

    def test_clock_skew_backwards_does_not_expire(self):
        # A KOT whose creation is somehow ahead of "now" (clock skew
        # between app servers) must not read as expired -- that would
        # force a kitchen round-trip for an order placed seconds ago.
        self.assertFalse(_grace_expired(self.created, self._at(seconds=-30), 2))

    def test_zero_window_expires_immediately(self):
        # _pick_grace_minutes never yields 0, but the primitive should
        # still behave sanely if it is ever called with one directly.
        self.assertTrue(_grace_expired(self.created, self._at(seconds=1), 0))


def run_cancellation_tests():
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for case in (PickGraceMinutesTests, GraceExpiredTests, PlanItemRemovalTests):
        suite.addTests(loader.loadTestsFromTestCase(case))
    unittest.TextTestRunner(verbosity=2).run(suite)


class _Row:
    """Stand-in for a POS Invoice Item row (only needs item_code/qty)."""

    def __init__(self, item_code, qty):
        self.item_code = item_code
        self.qty = qty

    def __repr__(self):
        return f"{self.item_code}x{self.qty}"


class PlanItemRemovalTests(unittest.TestCase):
    """Which invoice lines survive a partial cancellation, and at what qty.

    This is the arithmetic that decides what the customer is billed for
    after the kitchen accepts, so the awkward shapes are covered: partial
    pulls, the same item listed on two rows, and asking for more than is
    there.
    """

    def test_untouched_when_nothing_wanted(self):
        rows = [_Row("A", 2), _Row("B", 1)]
        keep, left = _plan_item_removal(rows, {})
        self.assertEqual(len(keep), 2)
        self.assertEqual([r.qty for r in keep], [2, 1])
        self.assertFalse(any(left.values()))

    def test_whole_line_removed(self):
        rows = [_Row("A", 2), _Row("B", 1)]
        keep, left = _plan_item_removal(rows, {"A": 2})
        self.assertEqual([r.item_code for r in keep], ["B"])
        self.assertEqual(left["A"], 0)

    def test_partial_pull_reduces_qty_in_place(self):
        rows = [_Row("A", 5), _Row("B", 1)]
        keep, _ = _plan_item_removal(rows, {"A": 2})
        self.assertEqual(len(keep), 2)
        self.assertEqual(keep[0].qty, 3)

    def test_other_items_untouched(self):
        rows = [_Row("A", 5), _Row("B", 4)]
        keep, _ = _plan_item_removal(rows, {"A": 5})
        self.assertEqual([(r.item_code, r.qty) for r in keep], [("B", 4)])

    def test_quantity_spread_across_duplicate_rows(self):
        # The same item can legitimately appear twice (different notes).
        # Pulling 3 must eat the first row whole and take 1 off the next.
        rows = [_Row("A", 2), _Row("A", 3)]
        keep, left = _plan_item_removal(rows, {"A": 3})
        self.assertEqual([(r.item_code, r.qty) for r in keep], [("A", 2)])
        self.assertEqual(left["A"], 0)

    def test_over_asking_is_reported_not_silently_swallowed(self):
        rows = [_Row("A", 1)]
        keep, left = _plan_item_removal(rows, {"A": 4})
        self.assertEqual(keep, [])
        self.assertEqual(left["A"], 3)

    def test_removing_everything_leaves_nothing_to_keep(self):
        rows = [_Row("A", 1), _Row("B", 2)]
        keep, _ = _plan_item_removal(rows, {"A": 1, "B": 2})
        self.assertEqual(keep, [])

    def test_unknown_item_code_is_a_no_op(self):
        rows = [_Row("A", 1)]
        keep, left = _plan_item_removal(rows, {"ZZZ": 1})
        self.assertEqual(len(keep), 1)
        self.assertEqual(left["ZZZ"], 1)
