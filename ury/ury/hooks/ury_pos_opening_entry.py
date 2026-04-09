import frappe
from frappe import _
from frappe.utils import now


def validate(doc, method):
    set_cashier_room(doc, method)
    validate_terminal_branch(doc, method)


def before_save(doc, method):
    # main_pos_open_check (the captain-must-be-open gate) was DELETED on
    # 2026-04-08 as part of the per-terminal opening-entry revamp.
    # Under the new model, opening entries are scoped per-terminal (and
    # per-user when multi_cashier is enabled), which makes the captain
    # gate meaningless. Do not re-add it. See CLAUDE.md "Fixes log".
    set_current_time(doc, method)


def set_cashier_room(doc, method):
    """Stamp ``custom_room`` (and the multi-room child table) on the
    opening entry from the URY User row that matches this user/branch.
    Harmless metadata; kept because some reports filter on it.
    """
    room = frappe.db.sql(
        """
            SELECT room, parent
            FROM `tabURY User`
            WHERE parent=%s AND user=%s
        """,
        (doc.branch, doc.user),
        as_dict=True,
    )

    if room:
        doc.custom_room = room[0]["room"]
        multiple_cashier = frappe.db.get_value(
            "POS Profile", doc.pos_profile, "custom_enable_multiple_cashier"
        )
        if multiple_cashier:
            doc.custom_rooms = []
            for r in room:
                doc.append("custom_rooms", {"room": r["room"]})


def set_current_time(doc, method):
    """For multi-cashier strict mode, stamp ``period_start_date`` to now()
    on save so each user's shift has an accurate start timestamp.
    """
    multiple_cashier = frappe.db.get_value(
        "POS Profile", doc.pos_profile, "custom_enable_multiple_cashier"
    )
    if multiple_cashier:
        doc.period_start_date = now()


def validate_terminal_branch(doc, method):
    """If the opening entry has a ``custom_terminal``, verify the
    terminal's branch matches the entry's branch. A mismatched terminal
    is a config error and is rejected outright. See CLAUDE.md "Fixes
    log" 2026-04-08.
    """
    if not doc.get("custom_terminal"):
        return

    terminal_branch = frappe.db.get_value(
        "URY POS Terminal", doc.custom_terminal, "branch"
    )
    if terminal_branch and doc.branch and terminal_branch != doc.branch:
        frappe.throw(
            _(
                "POS Terminal '{0}' belongs to branch '{1}', but this "
                "opening entry is for branch '{2}'. Pick a terminal whose "
                "branch matches the opening entry's branch."
            ).format(doc.custom_terminal, terminal_branch, doc.branch),
            title=_("Branch Mismatch"),
        )
