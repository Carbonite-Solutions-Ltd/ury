# Copyright (c) 2026, ury and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class URYPINChangeLog(Document):
	"""Append-only audit trail of PIN / enrollment changes.

	Written only by `ury.ury.biometric.api._log_pin_event` with
	`ignore_permissions=True`. Every field is read-only in the UI and the
	doctype grants no create or write permission to any role — the log is
	evidence, so it must not be editable after the fact by the people it
	records.

	It NEVER stores a PIN or a PIN hash. Only the fact that a change
	happened, who did it, to whom, and when.
	"""

	pass
