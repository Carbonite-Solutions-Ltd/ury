import frappe
from frappe.model.document import Document


class URYTableMergeSource(Document):
    """Child table row snapshotting a source URY Table at merge time.

    Owned by URY Table Merge Log.
    """

    pass
