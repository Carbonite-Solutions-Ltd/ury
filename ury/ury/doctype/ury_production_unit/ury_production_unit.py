# Copyright (c) 2023, Tridz Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class URYProductionUnit(Document):
	def validate(self):
		self._dedupe_users()

	def _dedupe_users(self):
		"""Drop blank and repeated rows from the Screen Access table.

		A user listed twice is harmless to the access check, but it clutters
		the table and makes "who can open this screen" harder to read.
		"""
		seen = set()
		kept = []
		for row in self.get("users") or []:
			if not row.user or row.user in seen:
				continue
			seen.add(row.user)
			kept.append(row)
		if len(kept) != len(self.get("users") or []):
			self.set("users", kept)
