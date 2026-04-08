"""Backfill `uom` on Item Price rows synced from URY Menus.

Before the 2026-04-08 fix, `URYMenu.make_price_list` created Item Price
rows without setting `uom`. ERPNext's standard POS Invoice validation
filters Item Price lookups by `uom = item.stock_uom`, so those null-uom
rows couldn't be matched during a POS invoice save — ERPNext then
helpfully auto-inserted a *second* (stock-uom-bearing) Item Price and
fired a `frappe.msgprint("Item Price added for <a>…</a>", alert=True)`
on every order submission. The user saw HTML-tagged noise toasts.

This patch:
- Finds Price Lists flagged as a menu price list (`restaurant_menu` set).
- For each Item Price on those price lists where `uom IS NULL OR uom = ''`,
  reads the linked Item's `stock_uom` and writes it.
- Idempotent. Safe to re-run — rows that already have a uom are skipped.

The root-cause fix in ury/ury/doctype/ury_menu/ury_menu.py prevents new
bad rows from being created. This patch cleans up the existing ones so
the same POS submission on an upgraded install stops producing the alert
toast.
"""

import frappe


def execute():
    # Defensive: `restaurant_menu` is a URY custom field on Price List.
    # If the column is missing (partial upgrade, fresh install before
    # fixtures sync), there's nothing to back-fill — just exit.
    if not frappe.db.has_column("Price List", "restaurant_menu"):
        print(
            "[URY] backfill_item_price_uom: Price List.restaurant_menu not "
            "present — skipping. Re-run after fixtures sync."
        )
        return

    menu_price_lists = frappe.get_all(
        "Price List",
        filters={"restaurant_menu": ["is", "set"]},
        pluck="name",
    )
    if not menu_price_lists:
        print("[URY] backfill_item_price_uom: no menu-linked price lists found.")
        return

    rows = frappe.get_all(
        "Item Price",
        filters={
            "price_list": ["in", menu_price_lists],
            "uom": ["in", ["", None]],
        },
        fields=["name", "item_code"],
    )

    if not rows:
        print("[URY] backfill_item_price_uom: no null-uom rows to backfill.")
        return

    backfilled = 0
    skipped_no_stock_uom = 0

    for row in rows:
        stock_uom = frappe.db.get_value("Item", row.item_code, "stock_uom")
        if not stock_uom:
            skipped_no_stock_uom += 1
            continue
        frappe.db.set_value(
            "Item Price",
            row.name,
            "uom",
            stock_uom,
            update_modified=False,
        )
        backfilled += 1

    if backfilled:
        frappe.db.commit()

    print(
        f"[URY] backfill_item_price_uom: "
        f"{backfilled} rows backfilled, "
        f"{skipped_no_stock_uom} skipped (linked Item has no stock_uom)."
    )
