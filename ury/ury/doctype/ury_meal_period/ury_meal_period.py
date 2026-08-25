# Copyright (c) 2026, Tridots Tech and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from ury.ury_pos.api import meal_period_seconds, time_to_seconds


class URYMealPeriod(Document):
	def validate(self):
		self._validate_window()
		self._warn_on_overlap()

	def _validate_window(self):
		start, end = time_to_seconds(self.start_time), time_to_seconds(self.end_time)
		if start is None or end is None:
			frappe.throw(
				_("Set both a start and an end time."), title=_("Times Required")
			)
		if start == end:
			frappe.throw(
				_("Start and end time cannot be the same — that is a zero-length service."),
				title=_("Invalid Window"),
			)

	def _warn_on_overlap(self):
		"""Two services covering the same minute would both claim a bill.

		The report assigns each bill to exactly ONE period (first match by
		display order), so an overlap does not double-count — it silently
		hands the bill to whichever period sorts first, which is not
		obvious. Say it once, here, rather than leaving someone to wonder
		why dinner looks light.
		"""
		mine = meal_period_seconds(self.start_time, self.end_time)
		if not mine:
			return

		others = frappe.get_all(
			"URY Meal Period",
			filters={"disabled": 0, "name": ["!=", self.name or "__new__"]},
			fields=["name", "start_time", "end_time"],
		)
		clashes = []
		for o in others:
			theirs = meal_period_seconds(o.start_time, o.end_time)
			if not theirs:
				continue
			# Both are lists of (from, to) spans already unwrapped across
			# midnight, so a plain pairwise intersection is enough.
			if any(a[0] <= b[1] and b[0] <= a[1] for a in mine for b in theirs):
				clashes.append(o.name)

		if clashes:
			frappe.msgprint(
				_(
					"This window overlaps {0}. A bill in the overlapping minutes is counted "
					"once, under whichever period has the lower Display Order."
				).format(", ".join(clashes)),
				title=_("Overlapping Meal Periods"),
				indicator="orange",
			)
