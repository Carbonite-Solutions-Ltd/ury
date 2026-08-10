import frappe
from frappe import _


def validate(doc,method):
    update_menu_item(doc,method)
    update_variants_add_on(doc, method)
    
    
def update_menu_item(doc, event):
    menu_items = frappe.get_all('URY Menu Item', filters={'item': doc.item_code})
    for menu_item in menu_items:
        frappe.db.set_value('URY Menu Item', menu_item.name, 'item_name', doc.item_name)

def update_variants_add_on(doc, event):
    """Validate the optional POS add-on / variant tables on an Item.

    Read with `doc.get(...)`, NOT attribute access. Both fields are
    shipped as customizations (`ury/ury/custom/item.json`,
    `sync_on_migrate`), so they only exist once a site has migrated
    since they were added. Attribute access raised

        AttributeError: 'Item' object has no attribute
                        'custom_pos_add_on_items'

    on a site that had not — and because this runs in `validate`, that
    took out **every Item save on the whole site**, including plain
    stock items with nothing to do with the POS. An optional add-on
    feature must never be able to block core item creation.

    `doc.get()` returns None for an absent field, so a site missing the
    customization degrades to "no add-ons configured" and saves
    normally. Once it migrates, the tables appear and validation
    resumes. See CLAUDE.md "Fixes log" 2026-08-05.
    """
    for fieldname, label in (
        ("custom_pos_add_on_items", "POS Add On Items"),
        ("custom_pos_item_variants", "POS Item Variants"),
    ):
        for row in doc.get(fieldname) or []:
            if not row.item:
                continue
            if not frappe.db.exists("URY Menu Item", {"item": row.item}):
                frappe.throw(
                    _("Item '{0}' in {1} is not on any {2}.").format(
                        row.item, label, _("URY Menu")
                    ),
                    title=_("Not On The Menu"),
                )
