# Copyright (c) 2026, URY and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class URYRemoteSale(Document):
	"""Read-only mirror of a sale made on a branch site.

	No hooks, no validation, no links to masters, no accounting. That is the
	entire point: this site may not have the POS Opening Entry, the terminal
	or even the branch the sale refers to, and an insert must never fail
	because of it.

	Replicating real POS Invoices here is not viable. Doing so would fire
	`pos_invoice_naming` (re-assigning the name), ERPNext's
	`validate_pos_opening_entry` (which throws outright, because the cloud
	has no open shift for that profile) and `set_order_number` (recomputing
	the order number from the wrong baseline) — and suppressing all three
	would be fragile in a way that corrupts replicas silently.
	"""

	pass
