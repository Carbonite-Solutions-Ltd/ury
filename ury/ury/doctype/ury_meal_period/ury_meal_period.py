# Copyright (c) 2026, Tridots Tech and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class URYMealPeriod(Document):
	def validate(self):
		self._dedupe_rows()
		self._warn_on_overlap()

	def _dedupe_rows(self):
		"""Two rows for the same item would double-count it in the report."""
		seen = set()
		kept = []
		for row in self.get("items") or []:
			if not row.item or row.item in seen:
				continue
			seen.add(row.item)
			kept.append(row)
		self.items = kept
		for idx, row in enumerate(self.items, start=1):
			row.idx = idx

		seen_groups = set()
		kept_groups = []
		for row in self.get("item_groups") or []:
			if not row.item_group or row.item_group in seen_groups:
				continue
			seen_groups.add(row.item_group)
			kept_groups.append(row)
		self.item_groups = kept_groups
		for idx, row in enumerate(self.item_groups, start=1):
			row.idx = idx

	def _warn_on_overlap(self):
		"""An item on two meal periods is counted in BOTH.

		Not an error — a site may legitimately serve the same dish at lunch
		and dinner — but it silently makes the period totals overlap, so it
		is worth saying out loud once rather than leaving someone to wonder
		why the numbers don't add up.
		"""
		mine = {row.item for row in (self.get("items") or []) if row.item}
		if not mine:
			return

		clashes = frappe.db.sql(
			"""
			SELECT DISTINCT mpi.item, mp.name AS period
			FROM `tabURY Meal Period Item` mpi
			JOIN `tabURY Meal Period` mp ON mp.name = mpi.parent
			WHERE mpi.parenttype = 'URY Meal Period'
			  AND mp.name != %(me)s
			  AND mp.disabled = 0
			  AND mpi.item IN %(items)s
			""",
			{"me": self.name or "__new__", "items": tuple(mine)},
			as_dict=True,
		)
		if not clashes:
			return

		listed = ", ".join(f"{c['item']} ({c['period']})" for c in clashes[:8])
		if len(clashes) > 8:
			listed += _(" and {0} more").format(len(clashes) - 8)
		frappe.msgprint(
			_(
				"These items are also on another meal period, so they will be counted in both: {0}"
			).format(listed),
			title=_("Item On More Than One Meal Period"),
			indicator="orange",
		)
