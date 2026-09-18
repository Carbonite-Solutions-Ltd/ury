# Copyright (c) 2026, Tridotstech and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class URYBarSession(Document):
	def validate(self):
		# One open session per unit is the whole point: the session IS the
		# handover boundary, so two open at once would make "sold since
		# opening" ambiguous. open_bar_session() closes the previous one
		# before inserting; this is the backstop for a desk-side edit.
		if self.status != "Open":
			return

		clash = frappe.db.get_value(
			"URY Bar Session",
			{
				"production_unit": self.production_unit,
				"status": "Open",
				"name": ("!=", self.name or ""),
			},
			"name",
		)
		if clash:
			frappe.throw(
				_("{0} is already open for this unit. Close it before opening another.").format(clash),
				title=_("Bar Already Open"),
			)
