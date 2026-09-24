# Copyright (c) 2026, Ury and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class URYMasterSyncState(Document):
	"""One row per replicated master doctype, holding the cloud watermark.

	Read-only in practice: written by ury.ury.sync.masters.pull(). Clearing
	`last_modified` on a row forces the next pull to re-fetch that doctype in
	full, which is the intended way to repair a branch that has drifted.
	"""

	pass
