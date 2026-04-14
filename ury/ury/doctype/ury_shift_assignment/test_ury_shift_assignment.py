# Copyright (c) 2026, Tridz Technologies Pvt. Ltd and contributors
# For license information, please see license.txt
"""
Unit tests for the URY Shift system, with a focus on cross-midnight
shifts (shifts whose end_time is earlier than start_time — e.g.
a night shift 18:00 -> 06:00).

Covers:
  1. URY Shift.validate — cross-midnight allowed, zero-length rejected
  2. _compute_occupancy_ranges — expanding a shift + weekday pattern
     into (weekday_index, start_sec, end_sec) tuples, including the
     two-range expansion for cross-midnight shifts.
  3. URY Shift Assignment._validate_no_overlap — overlap detection
     across day boundaries.
  4. _resolve_active_shift_for_user_ury — finding the right shift at
     a given moment, including shifts that started yesterday and
     extend into today.

Tests that exercise `get_shift_status` / `_enforce_shift_gate_for_open`
would require POS Profile + Terminal fixtures and session-user
swapping; those are covered by manual end-to-end testing. The unit
tests here hit the core resolver and overlap logic which is where
the cross-midnight subtlety actually lives.

Run with:
    bench --site <site> run-tests --app ury \\
        --module ury.ury.doctype.ury_shift_assignment.test_ury_shift_assignment
"""

import datetime
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from ury.ury_pos.api import _resolve_active_shift_for_user_ury
from ury.ury.doctype.ury_shift_assignment.ury_shift_assignment import (
    _compute_occupancy_ranges,
)


def run_cross_day_tests():
    """Run the cross-day shift test suite directly, bypassing Frappe's
    test runner (which triggers ERPNext's BootStrapTestData and fails
    on this non-test site). Invoke via::

        bench --site <site> execute \\
            ury.ury.doctype.ury_shift_assignment.test_ury_shift_assignment.run_cross_day_tests
    """
    frappe.flags.in_test = True
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestURYShiftCrossDay)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        raise RuntimeError(
            f"{len(result.failures)} failures, {len(result.errors)} errors "
            f"in URY Shift cross-day test suite."
        )
    return {
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "success": result.wasSuccessful(),
    }


TEST_USER = "cross-day-cashier@ury-test.local"
TEST_BRANCH = "_URY Cross Day Test Branch"

# 2026-04-20 is a Monday (weekday 0). All time-based tests anchor to
# this date so they're deterministic regardless of what day the suite
# actually runs.
MONDAY = datetime.date(2026, 4, 20)
TUESDAY = MONDAY + datetime.timedelta(days=1)
WEDNESDAY = MONDAY + datetime.timedelta(days=2)


class TestURYShiftCrossDay(FrappeTestCase):
    # ---------------------------------------------------------------
    # Fixture helpers
    # ---------------------------------------------------------------

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.flags.in_test = True

        # Create the test user first so the Branch's URY User child
        # table has a valid row to reference.
        if not frappe.db.exists("User", TEST_USER):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": TEST_USER,
                    "first_name": "CrossDay",
                    "last_name": "Cashier",
                    "enabled": 1,
                    "send_welcome_email": 0,
                    "roles": [{"role": "URY Cashier"}],
                }
            )
            user.flags.ignore_permissions = True
            user.insert(ignore_permissions=True)
        else:
            user = frappe.get_doc("User", TEST_USER)
            if not any(r.role == "URY Cashier" for r in user.roles):
                user.append("roles", {"role": "URY Cashier"})
                user.save(ignore_permissions=True)

        if not frappe.db.exists("Branch", TEST_BRANCH):
            # URY adds a required `user` Table (URY User) on Branch.
            # Populate it with the test cashier so the mandatory
            # check passes.
            branch = frappe.get_doc(
                {
                    "doctype": "Branch",
                    "branch": TEST_BRANCH,
                }
            )
            branch.append("user", {"user": TEST_USER})
            branch.flags.ignore_permissions = True
            branch.insert(ignore_permissions=True)

        frappe.db.commit()

    def setUp(self):
        self._clean_fixtures()

    def tearDown(self):
        self._clean_fixtures()

    def _clean_fixtures(self):
        """Remove any shift/assignment rows this test suite creates."""
        frappe.db.sql(
            """
            DELETE FROM `tabURY Shift Day`
            WHERE parenttype = 'URY Shift Assignment'
              AND parent IN (
                  SELECT name FROM `tabURY Shift Assignment`
                  WHERE user = %s
              )
            """,
            (TEST_USER,),
        )
        frappe.db.sql(
            "DELETE FROM `tabURY Shift Assignment` WHERE user = %s",
            (TEST_USER,),
        )
        frappe.db.sql(
            "DELETE FROM `tabURY Shift` WHERE shift_name LIKE %s",
            ("_XDTest_%",),
        )
        frappe.db.commit()

    def _create_shift(self, name, start, end, **kwargs):
        """Create a URY Shift with the `_XDTest_` name prefix."""
        full_name = f"_XDTest_{name}"
        if frappe.db.exists("URY Shift", full_name):
            frappe.delete_doc(
                "URY Shift", full_name, force=True, ignore_permissions=True
            )
        doc = frappe.get_doc(
            {
                "doctype": "URY Shift",
                "shift_name": full_name,
                "branch": TEST_BRANCH,
                "start_time": start,
                "end_time": end,
                "tolerance_minutes_before": kwargs.get("before", 15),
                "tolerance_minutes_after_start": kwargs.get("after_start", 30),
                "tolerance_minutes_after_end": kwargs.get("after_end", 60),
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    def _create_assignment(self, shift_name, days, effective_from=None):
        full_name = f"_XDTest_{shift_name}"
        doc = frappe.get_doc(
            {
                "doctype": "URY Shift Assignment",
                "user": TEST_USER,
                "shift": full_name,
                "effective_from": effective_from or MONDAY,
                "status": "Active",
                "days_of_week": [{"day": d} for d in days],
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    # ---------------------------------------------------------------
    # 1. URY Shift.validate
    # ---------------------------------------------------------------

    def test_shift_validate_cross_midnight_allowed(self):
        """A shift with end_time < start_time should save cleanly."""
        shift = self._create_shift("Night_18_06", "18:00:00", "06:00:00")
        self.assertIsNotNone(shift.name)
        self.assertEqual(str(shift.start_time), "18:00:00")

    def test_shift_validate_zero_length_rejected(self):
        """A shift with end_time == start_time should throw."""
        with self.assertRaises(frappe.ValidationError):
            self._create_shift("Zero", "12:00:00", "12:00:00")

    # ---------------------------------------------------------------
    # 2. Occupancy ranges (pure function)
    # ---------------------------------------------------------------

    def test_occupancy_non_crossing_single_day(self):
        """Non-crossing shift -> one range per assigned weekday."""
        shift = frappe._dict(start_time="09:00:00", end_time="17:00:00")
        days = [frappe._dict(day="Monday")]
        ranges = _compute_occupancy_ranges(shift, days)
        # 09:00 = 32400, 17:00 = 61200, Monday = 0
        self.assertEqual(ranges, [(0, 32400, 61200)])

    def test_occupancy_non_crossing_multiple_days(self):
        shift = frappe._dict(start_time="09:00:00", end_time="17:00:00")
        days = [frappe._dict(day="Monday"), frappe._dict(day="Friday")]
        ranges = _compute_occupancy_ranges(shift, days)
        self.assertEqual(
            set(ranges),
            {(0, 32400, 61200), (4, 32400, 61200)},
        )

    def test_occupancy_cross_midnight_expands(self):
        """Cross-midnight shift -> two ranges: start day tail + next day head."""
        shift = frappe._dict(start_time="18:00:00", end_time="06:00:00")
        days = [frappe._dict(day="Monday")]
        ranges = _compute_occupancy_ranges(shift, days)
        # Monday 18:00-24:00 (64800, 86400) + Tuesday 00:00-06:00 (0, 21600)
        self.assertEqual(
            set(ranges),
            {(0, 64800, 86400), (1, 0, 21600)},
        )

    def test_occupancy_cross_midnight_sunday_wraps_to_monday(self):
        """Sunday cross-midnight -> weekday wrap from Sunday (6) to Monday (0)."""
        shift = frappe._dict(start_time="22:00:00", end_time="05:00:00")
        days = [frappe._dict(day="Sunday")]
        ranges = _compute_occupancy_ranges(shift, days)
        # Sunday 22:00-24:00 (79200, 86400) + Monday 00:00-05:00 (0, 18000)
        self.assertEqual(
            set(ranges),
            {(6, 79200, 86400), (0, 0, 18000)},
        )

    def test_occupancy_empty_days_every_day_cross_midnight(self):
        """Empty days_of_week = every day. Cross-midnight = 2*7 = 14 ranges."""
        shift = frappe._dict(start_time="23:00:00", end_time="07:00:00")
        ranges = _compute_occupancy_ranges(shift, [])
        self.assertEqual(len(ranges), 14)
        # Spot check: Monday tail + Tuesday head
        self.assertIn((0, 82800, 86400), ranges)  # Mon 23:00-24:00
        self.assertIn((1, 0, 25200), ranges)  # Tue 00:00-07:00

    # ---------------------------------------------------------------
    # 3. Overlap validation
    # ---------------------------------------------------------------

    def test_overlap_cross_midnight_vs_next_day_morning_conflicts(self):
        """
        Night shift Mon 18-06 occupies Tue 00:00-06:00.
        A Tuesday Morning shift 03-11 overlaps with that tail.
        """
        self._create_shift("Night_18_06", "18:00:00", "06:00:00")
        self._create_shift("LateBreakfast_3_11", "03:00:00", "11:00:00")
        self._create_assignment("Night_18_06", ["Monday"])
        with self.assertRaises(frappe.ValidationError):
            self._create_assignment("LateBreakfast_3_11", ["Tuesday"])

    def test_overlap_cross_midnight_vs_later_tuesday_ok(self):
        """
        Night shift Mon 18-06 ends at Tue 06:00.
        A Tuesday afternoon shift 12-20 has a clean gap — no overlap.
        """
        self._create_shift("Night_18_06", "18:00:00", "06:00:00")
        self._create_shift("Afternoon_12_20", "12:00:00", "20:00:00")
        self._create_assignment("Night_18_06", ["Monday"])
        # Should save cleanly — no ValidationError.
        self._create_assignment("Afternoon_12_20", ["Tuesday"])

    def test_overlap_same_day_conflicts(self):
        """Two overlapping same-day shifts on the same day should conflict."""
        self._create_shift("A_9_14", "09:00:00", "14:00:00")
        self._create_shift("B_13_18", "13:00:00", "18:00:00")
        self._create_assignment("A_9_14", ["Wednesday"])
        with self.assertRaises(frappe.ValidationError):
            self._create_assignment("B_13_18", ["Wednesday"])

    def test_overlap_same_day_non_overlapping_ok(self):
        """Non-overlapping same-day shifts should save cleanly."""
        self._create_shift("Morning_6_14", "06:00:00", "14:00:00")
        self._create_shift("Evening_16_22", "16:00:00", "22:00:00")
        self._create_assignment("Morning_6_14", ["Thursday"])
        self._create_assignment("Evening_16_22", ["Thursday"])

    def test_overlap_cross_midnight_vs_cross_midnight_same_day(self):
        """Two cross-midnight shifts on the same start day with
        overlapping windows should conflict."""
        self._create_shift("NightA_20_04", "20:00:00", "04:00:00")
        self._create_shift("NightB_22_06", "22:00:00", "06:00:00")
        self._create_assignment("NightA_20_04", ["Friday"])
        with self.assertRaises(frappe.ValidationError):
            self._create_assignment("NightB_22_06", ["Friday"])

    # ---------------------------------------------------------------
    # 4. Resolver — cross-midnight time points
    # ---------------------------------------------------------------

    def _resolve_at(self, when):
        return _resolve_active_shift_for_user_ury(TEST_USER, _now_dt=when)

    def test_resolver_no_assignment_returns_none(self):
        info = self._resolve_at(
            datetime.datetime.combine(MONDAY, datetime.time(12, 0))
        )
        self.assertIsNone(info)

    def test_resolver_cross_before_open_window_is_upcoming(self):
        """17:30 Mon with Mon 18:00-06:00. Open window starts 17:45."""
        self._create_shift("Night_18_06", "18:00:00", "06:00:00")
        self._create_assignment(
            "Night_18_06", ["Monday"], effective_from=MONDAY
        )
        info = self._resolve_at(
            datetime.datetime.combine(MONDAY, datetime.time(17, 30))
        )
        self.assertIsNotNone(info)
        self.assertEqual(info["shift_name"], "_XDTest_Night_18_06")
        self.assertEqual(info["crosses_midnight"], 1)
        # Upcoming: _start_dt is in the future relative to `when`.
        self.assertGreater(
            info["_start_dt"],
            datetime.datetime.combine(MONDAY, datetime.time(17, 30)),
        )

    def test_resolver_cross_in_open_window_returns_immediately(self):
        """17:50 Mon is inside the 17:45-18:30 open window."""
        self._create_shift("Night_18_06", "18:00:00", "06:00:00")
        self._create_assignment(
            "Night_18_06", ["Monday"], effective_from=MONDAY
        )
        info = self._resolve_at(
            datetime.datetime.combine(MONDAY, datetime.time(17, 50))
        )
        self.assertIsNotNone(info)
        self.assertEqual(
            info["_open_window_start_dt"],
            datetime.datetime.combine(MONDAY, datetime.time(17, 45)),
        )
        self.assertEqual(
            info["_open_window_end_dt"],
            datetime.datetime.combine(MONDAY, datetime.time(18, 30)),
        )

    def test_resolver_cross_running_before_midnight(self):
        """22:00 Mon — shift running (past open window, before end)."""
        self._create_shift("Night_18_06", "18:00:00", "06:00:00")
        self._create_assignment(
            "Night_18_06", ["Monday"], effective_from=MONDAY
        )
        info = self._resolve_at(
            datetime.datetime.combine(MONDAY, datetime.time(22, 0))
        )
        self.assertIsNotNone(info)
        self.assertEqual(info["_start_dt"].date(), MONDAY)
        self.assertEqual(info["_end_dt"].date(), TUESDAY)
        # `now` is between start and end → live
        now = datetime.datetime.combine(MONDAY, datetime.time(22, 0))
        self.assertLessEqual(info["_start_dt"], now)
        self.assertGreater(info["_end_dt"], now)

    def test_resolver_cross_running_after_midnight(self):
        """03:00 Tue — yesterday's Mon 18-06 shift still running."""
        self._create_shift("Night_18_06", "18:00:00", "06:00:00")
        self._create_assignment(
            "Night_18_06", ["Monday"], effective_from=MONDAY
        )
        info = self._resolve_at(
            datetime.datetime.combine(TUESDAY, datetime.time(3, 0))
        )
        self.assertIsNotNone(info)
        # Anchor day is yesterday (Mon) because the shift STARTED Mon.
        self.assertEqual(info["anchor_day"], str(MONDAY))
        self.assertEqual(info["_start_dt"].date(), MONDAY)
        self.assertEqual(info["_end_dt"].date(), TUESDAY)

    def test_resolver_cross_after_end_tuesday_morning(self):
        """07:00 Tue — past the 06:00 end of Mon 18-06 shift."""
        self._create_shift("Night_18_06", "18:00:00", "06:00:00")
        self._create_assignment(
            "Night_18_06", ["Monday"], effective_from=MONDAY
        )
        info = self._resolve_at(
            datetime.datetime.combine(TUESDAY, datetime.time(7, 0))
        )
        self.assertIsNotNone(info)
        # Returned as "ended" — end_dt is before now.
        now = datetime.datetime.combine(TUESDAY, datetime.time(7, 0))
        self.assertLess(info["_end_dt"], now)
        self.assertEqual(info["anchor_day"], str(MONDAY))

    def test_resolver_cross_far_after_end_wednesday_none(self):
        """Wednesday — no assignment anywhere near. Resolver returns None."""
        self._create_shift("Night_18_06", "18:00:00", "06:00:00")
        self._create_assignment(
            "Night_18_06", ["Monday"], effective_from=MONDAY
        )
        info = self._resolve_at(
            datetime.datetime.combine(WEDNESDAY, datetime.time(12, 0))
        )
        # Neither today (Wed) nor yesterday (Tue) matches the Mon
        # assignment weekday, so nothing is returned.
        self.assertIsNone(info)

    def test_resolver_non_crossing_same_day_running(self):
        """Sanity: 12:00 Mon with Mon 09-17 shift — running."""
        self._create_shift("Day_9_17", "09:00:00", "17:00:00")
        self._create_assignment(
            "Day_9_17", ["Monday"], effective_from=MONDAY
        )
        info = self._resolve_at(
            datetime.datetime.combine(MONDAY, datetime.time(12, 0))
        )
        self.assertIsNotNone(info)
        self.assertEqual(info["crosses_midnight"], 0)
        self.assertEqual(info["_start_dt"].date(), MONDAY)
        self.assertEqual(info["_end_dt"].date(), MONDAY)

    def test_resolver_non_crossing_yesterday_not_considered(self):
        """
        Non-crossing shifts never span midnight, so yesterday's
        assignment must NOT surface today even if the user had one.
        """
        self._create_shift("Day_9_17", "09:00:00", "17:00:00")
        # Assignment for Monday only.
        self._create_assignment(
            "Day_9_17", ["Monday"], effective_from=MONDAY
        )
        # Query at Tuesday 10:00 — Mon assignment shouldn't match.
        info = self._resolve_at(
            datetime.datetime.combine(TUESDAY, datetime.time(10, 0))
        )
        self.assertIsNone(info)

    def test_resolver_picks_live_over_ended_on_same_user(self):
        """
        Cashier has two cross-midnight assignments: Mon Night (18-06)
        and Wed Night (18-06). At 03:00 Tue, Monday's is still running,
        Wednesday's hasn't started — should return the live Monday one.
        """
        self._create_shift("Night_18_06", "18:00:00", "06:00:00")
        self._create_assignment(
            "Night_18_06", ["Monday", "Wednesday"], effective_from=MONDAY
        )
        info = self._resolve_at(
            datetime.datetime.combine(TUESDAY, datetime.time(3, 0))
        )
        self.assertIsNotNone(info)
        # Anchor = Monday (yesterday), meaning the running Mon shift wins.
        self.assertEqual(info["anchor_day"], str(MONDAY))

    def test_resolver_empty_days_every_day_cross_midnight(self):
        """Every-day cross-midnight shift: at 02:00 Tue, the resolver
        picks up Monday's running instance of the shift."""
        self._create_shift("AllNight_22_06", "22:00:00", "06:00:00")
        self._create_assignment(
            "AllNight_22_06", [], effective_from=MONDAY  # every day
        )
        info = self._resolve_at(
            datetime.datetime.combine(TUESDAY, datetime.time(2, 0))
        )
        self.assertIsNotNone(info)
        self.assertEqual(info["crosses_midnight"], 1)
        # At 02:00 Tue, Monday's shift (22:00 Mon -> 06:00 Tue) is live.
        self.assertEqual(info["anchor_day"], str(MONDAY))

    def test_resolver_tolerance_extends_before_window(self):
        """
        A 30-minute before-start tolerance moves the open window earlier.
        At 17:40 Mon with tolerance_before=30, the 18:00 shift's open
        window (17:30-18:30) is already active.
        """
        self._create_shift(
            "Night_18_06_early",
            "18:00:00",
            "06:00:00",
            before=30,
        )
        self._create_assignment(
            "Night_18_06_early", ["Monday"], effective_from=MONDAY
        )
        info = self._resolve_at(
            datetime.datetime.combine(MONDAY, datetime.time(17, 40))
        )
        self.assertIsNotNone(info)
        self.assertEqual(
            info["_open_window_start_dt"],
            datetime.datetime.combine(MONDAY, datetime.time(17, 30)),
        )
