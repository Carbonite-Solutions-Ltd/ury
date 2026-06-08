import frappe
from frappe.model.document import Document


class URYInvoiceTransfer(Document):
    """Request/approval record for handing an unpaid POS Invoice (draft)
    from one cashier to another at shift close.

    Created Pending by `ury.ury_pos.api.submit_pos_closing_entry` when a
    captain closes a shift with unpaid drafts. Resolved to Approved /
    Rejected by `approve_transfer` / `reject_transfer` when the receiving
    cashier acts on it from the Orders page "Incoming Transfers" filter.

    The doctype is the source of truth + audit chain; the POS Invoice
    carries a denormalized `custom_transfer_status` flag for cheap Orders
    filtering. Direct desk edits are not the supported flow — the React
    POS drives every transition. See CLAUDE.md "Fixes log" 2026-06-05.
    """

    pass
