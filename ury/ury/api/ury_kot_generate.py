import json

import frappe
from ury.ury_pos.api import getBranch


# Load JSON data or return as is if it's already a Python dictionary
def load_json(data):
    if isinstance(data, str):
        return json.loads(data)
    return data


# Create a list of order items from a list of input items
def create_order_items(items):
    order_items = []
    for item in items:
        order_item = {
            "item_code": item.get("item", item.get("item_code")),
            "qty": item["qty"],
            "item_name": item["item_name"],
            "comments": item.get("comment", item.get("comments", "")),
        }
        order_items.append(order_item)
    return order_items


# Create a KOT (Kitchen Order Ticket) document
def create_kot_doc(
    invoice_id,
    customer,
    restaurant_table,
    items,
    kot_type,
    comments,
    pos_profile_id,
    kot_naming_series,
    production,
):
    pos_invoice = frappe.get_doc("POS Invoice", invoice_id)
    order_number = pos_invoice.custom_ury_order_number
    is_aggregator = 0
    if pos_invoice.order_type == "Aggregators":
        is_aggregator = 1
    kot_doc = frappe.get_doc(
        {
            "doctype": "URY KOT",
            "invoice": invoice_id,
            "restaurant_table": restaurant_table,
            "customer_name": customer,
            "pos_profile": pos_profile_id,
            "comments": comments,
            "type": kot_type,
            "naming_series": kot_naming_series,
            "production": production,
            "aggregator_id":pos_invoice.custom_aggregator_id,
            "is_aggregator":is_aggregator,
            "order_no":order_number
        }
    )
    branch = getBranch()
    if restaurant_table:
        room = frappe.db.get_value("URY Table", restaurant_table, "restaurant_room")
        restaurant = frappe.db.get_value("URY Table", restaurant_table, "restaurant")
        menu = frappe.db.get_value("Menu for Room", {"room": room,"parent":restaurant}, "menu")
        
    else:
        menu = frappe.db.get_value("URY Restaurant", {"branch": branch}, "active_menu")

    for item in items:
        course = frappe.db.get_value("URY Menu Item", {"item": item["item_code"],"parent":menu}, "course")
        kot_doc.append(
            "kot_items",
            {
                "item": item["item_code"],
                "item_name": item["item_name"],
                "quantity": item["qty"],
                "comments": item["comments"],
                "course":course
            },
        )
    kot_doc.insert()
    kot_doc.submit()

# Function to get all production item groups for a given branch
def get_all_production_item_groups(branch):
    productions = frappe.db.get_all(
        "URY Production Unit", filters={"branch": branch}, fields=["name"]
    )
    if productions:
        all_production_item_groups = set()
        for production in productions:
            productionItemGroupslist = frappe.get_all(
                "URY Production Item Groups",
                fields=["item_group"],
                filters={
                    "parent": production.name,
                    "parenttype": "URY Production Unit",
                },
                order_by="idx",
            )
            productionItemGroups = [
                item_group.item_group for item_group in productionItemGroupslist
            ]
            all_production_item_groups.update(productionItemGroups)
        return all_production_item_groups


# Process items to create KOT documents
def process_items_for_kot(
    invoice_id,
    customer,
    restaurant_table,
    items,
    comments,
    pos_profile_id,
    kot_naming_series,
    kot_type,
):
    """Create KOT docs from a list of items.

    Production Unit routing (2026-04-16 update — now OPTIONAL):
      - If the branch has URY Production Units configured AND an
        item's item_group matches one of the production's item_groups,
        a KOT is created per production with the matched items.
        (Existing behavior — unchanged for sites that use Production Units.)
      - Any items left UNMATCHED after the production loop (or ALL
        items if no production exists at all) get bundled into a
        SINGLE fallback KOT with `production=None`. The new
        department-based routing in `ury_print.resolve_kot_print_plan`
        then splits that KOT by Food/Drinks/Other downstream.

    This removes the old hard requirement that every branch needed
    a URY Production Unit before KOT creation worked. Sites that
    rely on Production Unit splitting keep their existing behavior;
    sites with simpler setups (one kitchen, one bar) no longer need
    to fake-configure a Production Unit just to get KOTs printing.

    See CLAUDE.md "Fixes log" 2026-04-16 (print revamp Round 1 / KOT
    setup simplification).
    """
    kot_items = create_order_items(items)
    pos_profile = frappe.get_doc("POS Profile", pos_profile_id)

    # 2026-04-16 KDS routing mode switch. When the POS Profile is in
    # "Menu Course" mode (default), skip production-unit splitting
    # entirely — one KOT per order, item department classification
    # drives downstream routing via ury_print.resolve_kot_print_plan
    # and kot_list item filtering. When in "URY Production Unit" mode
    # (legacy), fall through to the per-production splitting loop
    # below.
    kds_mode = pos_profile.get("custom_kds_routing_mode") or "Menu Course"
    if kds_mode == "Menu Course":
        productions = []
    else:
        productions = frappe.db.get_all(
            "URY Production Unit",
            filters={"branch": pos_profile.branch},
            fields=["name"],
        )

    # Track which items have already been assigned to a production.
    # Anything left over at the end becomes a fallback KOT.
    matched_item_codes = set()

    if productions:
        for production in productions:
            productionItemGroupslist = frappe.get_all(
                "URY Production Item Groups",
                fields=["item_group"],
                filters={
                    "parent": production.name,
                    "parenttype": "URY Production Unit",
                },
                order_by="idx",
            )
            productionItemGroups = [
                row.item_group for row in productionItemGroupslist
            ]
            production_items = [
                item
                for item in kot_items
                if frappe.db.get_value("Item", item["item_code"], "item_group")
                in productionItemGroups
            ]

            if production_items:
                invoice_exist = frappe.db.exists(
                    "URY KOT",
                    {
                        "invoice": invoice_id,
                        "docstatus": 1,
                        "production": production.name,
                    },
                )
                per_production_kot_type = (
                    "Order Modified" if invoice_exist else kot_type
                )

                create_kot_doc(
                    invoice_id,
                    customer,
                    restaurant_table,
                    production_items,
                    per_production_kot_type,
                    comments,
                    pos_profile_id,
                    kot_naming_series,
                    production.name,
                )
                for matched in production_items:
                    matched_item_codes.add(matched["item_code"])

    # Fallback path: any items not matched to a production unit
    # (or ALL items if no production exists) get bundled into one
    # KOT with production=None. The new unified print resolver
    # handles per-department routing downstream via
    # ury_print.resolve_kot_print_plan.
    #
    # IMPORTANT (2026-06-11): in URY Production Unit mode we DON'T create
    # this fallback KOT. Only items that belong to a production need a
    # kitchen ticket; anything else (e.g. a drink) shouldn't generate a
    # KOT at all. Creating the fallback here also broke order-time
    # printing: it's created LAST, so it became the "latest" KOT that
    # get_latest_kot returns — masking the real production KOT, which then
    # never auto-printed. Menu Course mode still relies on this fallback
    # (it's the single KOT that gets department-split downstream).
    unmatched_items = [
        item for item in kot_items if item["item_code"] not in matched_item_codes
    ]
    if unmatched_items and kds_mode != "URY Production Unit":
        invoice_has_fallback_kot = frappe.db.exists(
            "URY KOT",
            {
                "invoice": invoice_id,
                "docstatus": 1,
                "production": ["in", [None, ""]],
            },
        )
        fallback_kot_type = (
            "Order Modified" if invoice_has_fallback_kot else kot_type
        )
        create_kot_doc(
            invoice_id,
            customer,
            restaurant_table,
            unmatched_items,
            fallback_kot_type,
            comments,
            pos_profile_id,
            kot_naming_series,
            None,
        )


# Process items to create a cancel KOT document
def process_items_for_cancel_kot(
    invoice_id,
    customer,
    restaurant_table,
    items,
    comments,
    pos_profile_id,
    cancel_kot_naming_series,
    kot_type,
    invoiceItems,
):

    kot_items = create_order_items(items)
    pos_profile = frappe.get_doc("POS Profile", pos_profile_id)
    productions = frappe.db.get_all(
        "URY Production Unit", filters={"branch": pos_profile.branch}, fields=["name"]
    )

    for production in productions:
        productionDoc = frappe.get_doc("URY Production Unit", production.name)
        productionItemGroups = [
            item_group.item_group for item_group in productionDoc.item_groups
        ]
        production_items = [
            item
            for item in kot_items
            if frappe.get_doc("Item", item["item_code"]).item_group
            in productionItemGroups
        ]

        if production_items:
            create_cancel_kot_doc(
                invoice_id,
                restaurant_table,
                production_items,
                kot_type,
                customer,
                comments,
                pos_profile_id,
                cancel_kot_naming_series,
                invoiceItems,
                production.name,
            )


# Create a cancel KOT document
def create_cancel_kot_doc(
    invoice_id,
    restaurant_table,
    cancel_items,
    kot_type,
    customer,
    comments,
    pos_profile_id,
    cancel_kot_naming_series,
    invoiceItems,
    production,
):
    pos_invoice = frappe.get_doc("POS Invoice", invoice_id)
    order_number = pos_invoice.custom_ury_order_number  
    is_aggregator = 0
    if pos_invoice.order_type == "Aggregators":
        is_aggregator = 1
    kot_list = frappe.db.get_list(
        "URY KOT",
        filters={
            "invoice": invoice_id,
            "type": ("in", ("New Order", "Order Modified")),
        },
        fields=("name"),
    )

    # Find original KOTs related to the cancel items
    original_kots = []
    for cancelItem in cancel_items:
        for kot in kot_list:
            kot_doc = frappe.get_doc("URY KOT", kot.name)
            kot_cancel_items = kot_doc.kot_items
            itemCheckFlag = False
            for kotItem in kot_cancel_items:
                if cancelItem["item_code"] == kotItem.item:
                    itemCheckFlag = True
            if itemCheckFlag:
                original_kots.append(kot_doc.name)
                break

    # Remove duplicate KOT names and join them into a single string
    set_kots = [*set(original_kots)]
    set_kots = ",".join(set_kots)
    kot_cancel_doc = frappe.get_doc(
        {
            "doctype": "URY KOT",
            "naming_series": cancel_kot_naming_series,
            "original_kot": set_kots,
            "restaurant_table": restaurant_table,
            "customer_name": customer,
            "type": kot_type,
            "invoice": invoice_id,
            "pos_profile": pos_profile_id,
            "comments": comments,
            "production": production,
            "is_aggregator":is_aggregator,
            "order_no":order_number
        }
    )

    branch = getBranch()
    if restaurant_table:
        room = frappe.db.get_value("URY Table", restaurant_table, "restaurant_room")
        restaurant = frappe.db.get_value("URY Table", restaurant_table, "restaurant")
        menu = frappe.db.get_value("Menu for Room", {"room": room,"parent":restaurant}, "menu")
        
    else:
        menu = frappe.db.get_value("URY Restaurant", {"branch": branch}, "active_menu")
    for cancelItem in cancel_items:
        course = frappe.db.get_value("URY Menu Item", {"item": cancelItem["item_code"],"parent":menu}, "course")
        for item in invoiceItems:
            if cancelItem["item_code"] == item["item_code"]:
                kot_cancel_doc.append(
                    "kot_items",
                    {
                        "item": cancelItem["item_code"],
                        "item_name": cancelItem["item_name"],
                        "cancelled_qty": abs(int(cancelItem["qty"])),
                        "quantity": item["qty"],
                        "comments": cancelItem["comments"],
                        "course":course
                    },
                )

    kot_cancel_doc.insert()
    kot_cancel_doc.submit()


# Whitelisted function to handle KOT entry
@frappe.whitelist()
def kot_execute(
    invoice_id,
    customer,
    restaurant_table=None,
    current_items=[],
    previous_items=[],
    comments=None,
):
    current_items = load_json(current_items)
    previous_items = load_json(previous_items)
    new_invoice_items_array = create_order_items(previous_items)
    new_Order_items_array = create_order_items(current_items)

    final_array = compare_two_array(new_Order_items_array, new_invoice_items_array)
    removed_item = get_removed_items(new_invoice_items_array, new_Order_items_array)

    pos_invoice = frappe.get_doc("POS Invoice", invoice_id)
    pos_profile_id = pos_invoice.pos_profile
    pos_profile = frappe.get_doc("POS Profile", pos_profile_id)
    kot_naming_series = pos_profile.custom_kot_naming_series
    if kot_naming_series:
        cancel_kot_naming_series = "CNCL-" + kot_naming_series
    else:
        frappe.throw(
            "KOT Naming Series is mandatory for the auto creation of KOT.Ensure it is configured in the POS Profile: %s"
            % pos_profile.name
        )

    positive_qty_items = [item for item in final_array if int(item["qty"]) > 0]
    negative_qty_items = [item for item in final_array if int(item["qty"]) <= 0]
    total_cancel_items = negative_qty_items + removed_item
    if positive_qty_items:
        process_items_for_kot(
            invoice_id,
            customer,
            restaurant_table,
            positive_qty_items,
            comments,
            pos_profile_id,
            kot_naming_series,
            "New Order",
        )
    if total_cancel_items:
        process_items_for_cancel_kot(
            invoice_id,
            customer,
            restaurant_table,
            total_cancel_items,
            comments,
            pos_profile_id,
            cancel_kot_naming_series,
            "Partially cancelled",
            new_invoice_items_array,
        )


# Compare two arrays and return the items that are different
def compare_two_array(array_1, array_2):
    finalarray = []
    for index, x in enumerate(array_1):
        a = list(
            filter(
                lambda y: y["item_code"] == x["item_code"] and y["qty"] == x["qty"],
                array_2,
            )
        )
        if len(a) == 0:
            b = list(filter(lambda z: z["item_code"] == x["item_code"], array_2))
            for qtb in b:
                x["qty"] = int(x["qty"]) - int(qtb["qty"])
            finalarray.append(x)
    return finalarray


# Get the items that have been removed from the second array compared to the first array
def get_removed_items(array_1, array_2):
    removed_objects = [
        obj
        for obj in array_1
        if obj["item_code"] not in [x["item_code"] for x in array_2]
    ]
    return removed_objects
