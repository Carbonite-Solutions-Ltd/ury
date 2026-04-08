import frappe
from frappe.model.document import Document


class URYPOSTerminal(Document):
    def validate(self):
        if self.room:
            self.branch = frappe.db.get_value("URY Room", self.room, "branch")
