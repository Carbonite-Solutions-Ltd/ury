# Copyright (c) 2026, Tridz Technologies Pvt. Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class URYShift(Document):
    def validate(self):
        self._validate_time_window()

    def _validate_time_window(self):
        """Reject zero-length shifts. Cross-midnight shifts (end_time
        earlier than start_time, e.g. 18:00 -> 06:00) are supported
        and auto-detected by the resolver: the shift is treated as
        spanning from start_day at start_time to the following day at
        end_time. The weekday in the Shift Assignment refers to the
        day the shift STARTS.

        See CLAUDE.md "Fixes log" 2026-04-14 (URY Shift system) and
        2026-04-15 (cross-midnight support)."""
        if not self.start_time or not self.end_time:
            return
        if self.end_time == self.start_time:
            frappe.throw(
                _(
                    "End Time must differ from Start Time \u2014 a "
                    "zero-length shift is meaningless."
                ),
                title=_("Invalid Time Window"),
            )
