import frappe
from frappe import _
from frappe.model.document import Document


class URYPOSTerminal(Document):
    def validate(self):
        # `branch` is fetched from the room. Re-resolve on every validate so a
        # terminal that's reassigned to a different room updates its branch.
        if self.room:
            self.branch = frappe.db.get_value("URY Room", self.room, "branch")

        self._validate_pos_profile_branch()

    def _validate_pos_profile_branch(self):
        """The POS Profile linked to a terminal must belong to the same branch
        as the terminal's room. Otherwise the POS would load a profile that
        doesn't match the physical till, leading to wrong payment modes,
        wrong menus, wrong printers.

        See CLAUDE.md "Fixes log" 2026-04-08 and the "Terminal ↔ POS Profile"
        section of the POS architecture notes.
        """
        if not self.pos_profile:
            return

        profile_branch = frappe.db.get_value(
            "POS Profile", self.pos_profile, "branch"
        )
        if profile_branch and self.branch and profile_branch != self.branch:
            frappe.throw(
                _(
                    "POS Profile '{0}' is configured for branch '{1}', but this "
                    "terminal belongs to branch '{2}'. Pick a POS Profile "
                    "whose branch matches the terminal's branch."
                ).format(self.pos_profile, profile_branch, self.branch),
                title=_("Branch Mismatch"),
            )
