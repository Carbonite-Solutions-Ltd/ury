# Copyright (c) 2026, Tridz Technologies Pvt. Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


CASHIER_ROLES = ("URY Cashier", "URY Captain", "URY Manager")


class URYShiftAssignment(Document):
    def validate(self):
        self._validate_user_role()
        self._validate_effective_dates()
        self._validate_no_overlap()

    def _validate_user_role(self):
        """The assigned user must hold a URY cashier-side role.
        Otherwise the assignment is meaningless (the user can't open
        a POS Opening Entry anyway).
        """
        if not self.user:
            return
        roles = set(
            frappe.get_roles(self.user)
        )
        if not (roles & set(CASHIER_ROLES)):
            frappe.throw(
                _(
                    "User {0} doesn't have any URY cashier role "
                    "({1}). Assign one of those roles before "
                    "creating a shift assignment."
                ).format(self.user, ", ".join(CASHIER_ROLES)),
                title=_("Invalid User Role"),
            )

    def _validate_effective_dates(self):
        if (
            self.effective_to
            and self.effective_from
            and self.effective_to < self.effective_from
        ):
            frappe.throw(
                _("Effective To ({0}) must be on or after Effective From ({1}).")
                .format(self.effective_to, self.effective_from),
                title=_("Invalid Date Range"),
            )

    def _validate_no_overlap(self):
        """Reject overlapping Active assignments for the same user.

        Overlap detection handles BOTH same-day shifts and
        cross-midnight shifts (where the shift end_time is earlier
        than start_time, meaning the shift spans into the next day).

        Algorithm:
          1. For each assignment, expand its weekly schedule into a
             set of absolute (weekday_index, start_sec, end_sec)
             occupancy ranges. A non-cross-midnight shift produces
             ONE range per assigned weekday; a cross-midnight shift
             produces TWO ranges per assigned weekday (one on the
             start day from start_sec to 86400, and one on the
             following day from 0 to end_sec).
          2. Two assignments overlap if their effective dates
             intersect AND any of their occupancy ranges share a
             weekday index and have intersecting seconds-since-midnight
             windows.

        Two non-overlapping shifts on the same user are always
        allowed (Morning 06-14 + Evening 16-22 → no overlap).
        """
        if self.status != "Active" or not self.user or not self.shift:
            return

        my_shift = frappe.get_doc("URY Shift", self.shift)
        if not my_shift.start_time or not my_shift.end_time:
            return

        my_ranges = _compute_occupancy_ranges(my_shift, self.days_of_week)
        if not my_ranges:
            return

        my_from = self.effective_from
        my_to = self.effective_to

        candidates = frappe.get_all(
            "URY Shift Assignment",
            filters={
                "user": self.user,
                "status": "Active",
                "name": ("!=", self.name or ""),
            },
            pluck="name",
        )

        for other_name in candidates:
            other = frappe.get_doc("URY Shift Assignment", other_name)

            # Effective date overlap.
            if my_to and other.effective_from and my_to < other.effective_from:
                continue
            if other.effective_to and my_from and other.effective_to < my_from:
                continue

            other_shift = frappe.get_doc("URY Shift", other.shift)
            if not other_shift.start_time or not other_shift.end_time:
                continue

            other_ranges = _compute_occupancy_ranges(
                other_shift, other.days_of_week
            )
            if not other_ranges:
                continue

            # Pairwise intersect on (weekday_index, start_sec, end_sec).
            for (wd_a, start_a, end_a) in my_ranges:
                for (wd_b, start_b, end_b) in other_ranges:
                    if wd_a != wd_b:
                        continue
                    if end_a <= start_b or end_b <= start_a:
                        continue
                    frappe.throw(
                        _(
                            "Overlapping shift assignment {0} ({1}: "
                            "{2}\u2013{3}) already exists for user {4}. "
                            "Two shifts on the same user can't run at "
                            "the same time of day \u2014 cross-midnight "
                            "shifts count on BOTH the start day and the "
                            "day they extend into."
                        ).format(
                            other.name,
                            other.shift,
                            other_shift.start_time,
                            other_shift.end_time,
                            self.user,
                        ),
                        title=_("Shift Overlap"),
                    )


_WEEKDAY_INDEX = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


def _time_to_seconds(t):
    """Convert a Frappe Time / timedelta / str value to seconds-since-midnight."""
    if t is None:
        return None
    if hasattr(t, "total_seconds"):
        return int(t.total_seconds())
    if hasattr(t, "hour"):
        return t.hour * 3600 + t.minute * 60 + (t.second or 0)
    if isinstance(t, str):
        parts = t.split(":")
        if len(parts) >= 2:
            h = int(parts[0])
            m = int(parts[1])
            s = int(parts[2]) if len(parts) > 2 else 0
            return h * 3600 + m * 60 + s
    return None


def _compute_occupancy_ranges(shift_doc, days_of_week_rows):
    """Expand a shift + days_of_week table into a list of absolute
    (weekday_index, start_sec, end_sec) ranges representing every
    (day, time-window) the shift actually occupies.

    - Non-crossing shift (end > start): one range per assigned day.
    - Cross-midnight shift (end < start): two ranges per assigned day
      — (assigned_day, start, 86400) + (assigned_day+1 mod 7, 0, end).
    - Empty days_of_week is treated as "every day of the week".
    """
    start_sec = _time_to_seconds(shift_doc.start_time)
    end_sec = _time_to_seconds(shift_doc.end_time)
    if start_sec is None or end_sec is None:
        return []

    days = {
        _WEEKDAY_INDEX[d.day]
        for d in (days_of_week_rows or [])
        if d.day in _WEEKDAY_INDEX
    }
    if not days:
        days = set(range(7))  # "every day"

    ranges = []
    crosses_midnight = end_sec <= start_sec

    for wd in days:
        if crosses_midnight:
            ranges.append((wd, start_sec, 86400))
            ranges.append(((wd + 1) % 7, 0, end_sec))
        else:
            ranges.append((wd, start_sec, end_sec))
    return ranges
