from frappe.model.document import Document


class URYOrderMergeSource(Document):
    """Child row of URY Order Merge Log. One per source invoice that
    was merged into the master. Holds JSON snapshots of items and
    payments so the merge can be cleanly reversed.
    """

    pass
