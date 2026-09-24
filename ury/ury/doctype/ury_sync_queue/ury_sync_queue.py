# Copyright (c) 2026, URY and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class URYSyncQueue(Document):
	"""One outbound document awaiting delivery to the cloud site.

	Rows are created by `ury.ury.sync.queue.enqueue` and driven by the
	scheduled workers in `ury.ury.sync.worker`. Nothing here validates or
	transforms: the state machine lives in `ury.ury.sync.rules` (pure, and
	unit-tested without a bench), and the payload is read from the
	referenced document at send time rather than snapshotted here, so a row
	can never deliver a stale copy of a sale.
	"""

	pass
