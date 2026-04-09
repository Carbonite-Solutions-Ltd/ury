import frappe
from frappe.model.document import Document


class URYOrderMergeLog(Document):
    """Audit log for POS Invoice merge / unmerge operations.

    Created by `ury.ury_pos.api.merge_pos_invoices`. Updated by
    `ury.ury_pos.api.unmerge_pos_invoices`. Direct desk edits are
    locked down via permissions on the schema (only System Manager
    can delete) — the supported flow is via the React POS.
    """

    pass
