import frappe
from frappe.model.document import Document


class URYTableMergeLog(Document):
    """Audit log for URY Table merge / unmerge operations.

    Created by `ury.ury_pos.api.merge_tables`. Updated by
    `ury.ury_pos.api.unmerge_tables`. Direct desk edits are locked
    down via permissions on the schema — the supported flow is via
    the React POS Table page.
    """

    pass
