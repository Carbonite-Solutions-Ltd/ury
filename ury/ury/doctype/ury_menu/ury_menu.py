# Copyright (c) 2023, Tridz Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class URYMenu(Document):
    def validate(self):
        for d in self.items:
            if not d.rate:
                d.rate = frappe.db.get_value("Item", d.item, "standard_rate")

    def on_update(self):
        """Sync Price List"""
        self.make_price_list()

    def on_trash(self):
        """clear prices"""
        self.clear_item_price()

    def clear_item_price(self, price_list=None):
        """clear all item prices for this menu"""
        if not price_list:
            price_list = self.get_price_list().name
        frappe.db.sql("delete from `tabItem Price` where price_list = %s", price_list)

    def make_price_list(self):
        # create price list for menu
        price_list = self.get_price_list()
        self.db_set("price_list", price_list.name)

        # delete old items
        self.clear_item_price(price_list.name)

        for d in self.items:
            # Always stamp uom = item.stock_uom. Without a uom on the Item
            # Price, ERPNext's standard POS Invoice validation can't match
            # this price row during save and falls through to
            # insert_item_price() which creates a duplicate and fires a
            # noisy "Item Price added for <a>…</a>" alert on every order.
            # See CLAUDE.md "Fixes log" 2026-04-08.
            stock_uom = frappe.db.get_value("Item", d.item, "stock_uom")
            frappe.get_doc(
                dict(
                    doctype="Item Price",
                    price_list=price_list.name,
                    item_code=d.item,
                    price_list_rate=d.rate,
                    uom=stock_uom,
                )
            ).insert()

    def get_price_list(self):
        """Create price list for menu if missing"""
        price_list_name = frappe.db.get_value(
            "Price List", dict(restaurant_menu=self.name)
        )
        if price_list_name:
            price_list = frappe.get_doc("Price List", price_list_name)
        else:
            price_list = frappe.new_doc("Price List")
            price_list.restaurant_menu = self.name
            price_list.price_list_name = self.name

        price_list.enabled = 1
        price_list.selling = 1
        price_list.save()

        return price_list
