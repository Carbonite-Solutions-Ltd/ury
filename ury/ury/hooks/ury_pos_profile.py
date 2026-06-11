import frappe
from frappe import _, msgprint


def validate(doc, method):
    validate_bill_check(doc, method)
    validate_cost_center(doc, method)
    clear_warehouse_in_item_mode(doc, method)


def clear_warehouse_in_item_mode(doc, method):
    """In item-warehouse mode (`custom_use_pos_warehouse` OFF) the single
    profile Warehouse must be blank — otherwise ERPNext's `set_warehouse`
    would force it onto every POS Invoice item row and defeat the per-item
    routing. Clear it on save. (The field is also hidden + non-mandatory in
    this mode via Property Setters.) See CLAUDE.md 2026-06-11."""
    if not doc.get("custom_use_pos_warehouse"):
        doc.warehouse = None


def on_update(doc, method):
    """Hooks that fire after the POS Profile is saved."""
    sync_negative_stock_on_menu_items(doc, method)


def validate_bill_check(doc, method):
    for row in doc.printer_settings:
        if not row.bill or not row.printer:
            msgprint(
                _(
                    "Either Bill is not enabled / Printer is not selected in Printer Settings."
                )
            )


def validate_cost_center(doc, method):
    if not doc.cost_center:
        frappe.throw(_("Cost center is mandatory."))


def sync_negative_stock_on_menu_items(doc, method):
    """
    When ``custom_allow_negative_stock_on_menu_items`` flips on the POS
    Profile, walk every URY Menu Item under the profile's restaurant
    and stamp ``Item.allow_negative_stock`` on each Item master with
    ``is_stock_item = 1``. Toggling the field off reverses the stamp on
    the same set.

    Caveats:
      * ``allow_negative_stock`` lives on the Item master, so two POS
        Profiles sharing the same item will fight (last save wins).
      * The "off" path stamps a literal ``0`` rather than NULL, so an
        admin who manually flipped the flag for some other reason will
        get it cleared. Acceptable trade-off — the toggle is meant to
        be the source of truth.
      * Runs only when the field actually changes (``has_value_changed``)
        so resaving the profile for unrelated reasons is a no-op.
    """
    # Skip when nothing changed. ``has_value_changed`` returns True for
    # brand-new docs, which is what we want — a freshly-checked profile
    # should propagate immediately on first save.
    if not doc.has_value_changed("custom_allow_negative_stock_on_menu_items"):
        return

    restaurant = getattr(doc, "restaurant", None)
    if not restaurant:
        # Profile isn't tied to a restaurant yet — nothing to walk.
        return

    target_value = 1 if doc.custom_allow_negative_stock_on_menu_items else 0

    menu_names = _collect_menus_for_restaurant(restaurant)
    if not menu_names:
        return

    # Pull every distinct stock-tracked Item linked from any of those
    # menus in one shot. Filtering by is_stock_item=1 here means we never
    # touch service items / non-stock items even if they're on a menu.
    item_codes = frappe.get_all(
        "URY Menu Item",
        filters={
            "parenttype": "URY Menu",
            "parent": ("in", list(menu_names)),
        },
        pluck="item",
    )
    if not item_codes:
        return

    stock_items = frappe.get_all(
        "Item",
        filters={
            "name": ("in", list({code for code in item_codes if code})),
            "is_stock_item": 1,
        },
        pluck="name",
    )
    if not stock_items:
        return

    # Bulk update via db.set_value loop — keeps each Item's modified
    # timestamp consistent without paying for a full doc save per item.
    # set_value bypasses validate(), which is what we want here: we
    # don't need item validation to fire just to toggle one Check field.
    for item_code in stock_items:
        frappe.db.set_value(
            "Item",
            item_code,
            "allow_negative_stock",
            target_value,
            update_modified=False,
        )

    frappe.msgprint(
        _("Updated allow_negative_stock = {0} on {1} stock-tracked items across {2} menus.").format(
            target_value, len(stock_items), len(menu_names)
        ),
        alert=True,
        indicator="blue",
    )


def _collect_menus_for_restaurant(restaurant_name):
    """
    Return the set of URY Menu names tied to a restaurant via any of:
      * URY Restaurant.active_menu (default menu)
      * Menu for Room rows (when room_wise_menu is on)
      * Order Type Menu rows (when order_type_wise_menu is on)
    Missing fields are tolerated so the caller doesn't crash on
    misconfigured restaurants.
    """
    menus = set()

    restaurant = frappe.get_doc("URY Restaurant", restaurant_name)

    if restaurant.active_menu:
        menus.add(restaurant.active_menu)

    for row in (restaurant.menu_for_room or []):
        if row.menu:
            menus.add(row.menu)

    for row in (restaurant.order_type_menu or []):
        if row.menu:
            menus.add(row.menu)

    return menus
