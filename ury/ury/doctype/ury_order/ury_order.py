# Copyright (c) 2023, Tridz Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from frappe.model.document import Document
from erpnext.controllers.queries import item_query
from ury.ury_pos.api import getBranch, _VALID_ORDER_TYPES
from ury.ury.api.ury_kot_generate import kot_execute
from ury.ury.api.ury_kot_generate import process_items_for_cancel_kot

from frappe import cache


class URYOrder(Document):
    pass


@frappe.whitelist()
def get_order_invoice(table=None, invoiceNo=None, order_type=None, is_payment=None):
    """returns the active invoice linked to the given table"""

    if table:
        if is_payment == "Payments":
            invoice_name = frappe.get_value(
                "POS Invoice", dict(restaurant_table=table, docstatus=0, name=invoiceNo)
            )
            
        else:
            if invoiceNo:
                invoice_name = frappe.get_value(
                    "POS Invoice",
                    dict(restaurant_table=table, docstatus=0, name=invoiceNo),
                )
               
            else:
                invoice_name = frappe.get_value(
                    "POS Invoice",
                    dict(restaurant_table=table, docstatus=0, invoice_printed=0),
                )
                
        # invoice_name = frappe.get_value("POS Invoice", dict(restaurant_table=table, docstatus=0, invoice_printed=0))
        branch, menu_name, restaurant = get_restaurant_and_menu_name(table)

        if invoice_name:
            invoice = frappe.get_doc("POS Invoice", invoice_name)

        else:
            invoice = frappe.new_doc("POS Invoice")

            invoice.naming_series = frappe.db.get_value(
                "URY Restaurant", restaurant, "invoice_series_prefix"
            )

            invoice.is_pos = 1
            invoice.update_stock = 1
            invoice.restaurant = restaurant
            invoice.branch = branch

            is_take_away = frappe.db.get_value("URY Table", table, "is_take_away")
            if is_take_away == 1:
                invoice.order_type = "Take Away"
            else:
                invoice.order_type= "Dine In"

        invoice.taxes_and_charges = frappe.db.get_value(
            "URY Restaurant", restaurant, "default_tax_template"
        )

        invoice.selling_price_list = frappe.db.get_value(
            "Price List", dict(restaurant_menu=menu_name, enabled=1)
        )

    else:

        if is_payment == "Payments":
            invoice_name = frappe.get_value(
                "POS Invoice", dict(restaurant_table=table, docstatus=0, name=invoiceNo)
            )
            
        else:
            invoice_name = frappe.get_value(
                "POS Invoice", dict(docstatus=0, name=invoiceNo)
            )
            
        if invoice_name:
            invoice = frappe.get_doc("POS Invoice", invoice_name)
            

        else:
            invoice = frappe.new_doc("POS Invoice")
            invoice.is_pos = 1
            invoice.update_stock = 1
        
        branch = getBranch()
        restaurant = frappe.db.get_value("URY Restaurant", {"branch": branch}, "name")
   
        menu=get_menu_name(order_type)
 
        if (order_type == "Aggregators" and frappe.db.get_value("Branch", branch, "custom_no_taxes") == 0) or order_type != "Aggregators":
            invoice.taxes_and_charges = frappe.db.get_value("URY Restaurant", restaurant, "default_tax_template")
        
        invoice.selling_price_list = frappe.db.get_value(
            "Price List", dict(restaurant_menu=menu, enabled=1)
        )
        
        

    return invoice


def _resolve_item_warehouse(item_code, company):
    """An item's Default Warehouse for the given company (Item Defaults),
    or None when the item has no default for that company. Used in
    item-warehouse mode (POS Profile `custom_use_pos_warehouse` OFF) so each
    sold item posts stock to its own warehouse. See CLAUDE.md 2026-06-11."""
    if not item_code or not company:
        return None
    return frappe.db.get_value(
        "Item Default",
        {"parent": item_code, "company": company},
        "default_warehouse",
    )


def _apply_pos_profile_taxes(invoice, pos_profile_name):
    """Fetch the tax template + tax category from the POS Profile onto the
    POS Invoice when they're configured there, and populate the tax rows
    from the template if they're empty.

    The POS Profile is URY's per-terminal tax source of truth. Previously
    taxes were only set from URY Restaurant.default_tax_template (often left
    blank), so orders went out untaxed even when the POS Profile had VAT
    configured. The profile takes precedence; profiles that leave these
    blank keep whatever get_order_invoice set. Called from sync_order (order
    creation) and make_invoice (payment, to cover drafts created before this
    was wired up). See CLAUDE.md "Fixes log" 2026-06-05.
    """
    if not pos_profile_name:
        return
    row = frappe.db.get_value(
        "POS Profile",
        pos_profile_name,
        ["taxes_and_charges", "tax_category"],
        as_dict=True,
    )
    if not row:
        return
    if row.taxes_and_charges:
        invoice.taxes_and_charges = row.taxes_and_charges
    if row.tax_category:
        invoice.tax_category = row.tax_category
    # Populate tax rows from the template now when empty. ERPNext's
    # set_taxes() only auto-fills for brand-new docs, so this guarantees the
    # tax applies on the first save AND fixes a re-synced older draft.
    # Guarded against double-appending.
    if row.taxes_and_charges and not invoice.get("taxes"):
        invoice.append_taxes_from_master()


@frappe.whitelist()
def sync_order(
    items,
    cashier,
    mode_of_payment,
    customer,
    no_of_pax,
    last_invoice,
    waiter,
    pos_profile,
    owner=None,
    last_modified_time=None,
    table=None,
    invoice=None,
    comments=None,
    order_type=None,
    aggregator_id=None,
    room=None,
    terminal=None,
    hotel_room=None,
    selected_waiter=None,
):
    # `owner` is optional. The frontend deliberately omits it when
    # updating an existing order so we don't overwrite the original
    # cashier on the audit trail (only stamps it on creation). The
    # `db_set("owner", owner)` call later in this function is gated on
    # `owner` being non-None.
    #
    # `hotel_room` is an optional iHotel intent — when the cashier
    # picked a hotel guest's room for this order, we stamp the
    # `custom_hotel_room` field on the draft so the intent survives a
    # page reload. The `custom_charge_to_room` flag is NOT set here —
    # that happens at `charge_invoice_to_room` time once the cashier
    # hits the Payment dialog's Charge to Room tab. See CLAUDE.md
    # "Fixes log" 2026-04-12.
    
    user_role = frappe.get_roles()
    posprofile = frappe.get_doc("POS Profile", pos_profile)
    
    billing_user = any(
        role.role in user_role for role in posprofile.role_allowed_for_billing
    )

    # Check if the last invoice was already billed
    if (
        last_invoice
        and frappe.db.get_value("POS Invoice", last_invoice, "invoice_printed") == 1
        and (not billing_user)
    ):
        frappe.msgprint(
            title="Invoice Already Billed",
            indicator="red",
            msg=("This order has already been billed. Please reload the page."),
        )
        return {"status": "Failure"}

    invoice = get_order_invoice(table, invoice,order_type)

    if last_invoice and last_modified_time:
        lastModifiedTime = invoice.modified
        from datetime import datetime

        if isinstance(last_modified_time, str):
            try:
                last_modified_time = datetime.strptime(
                    last_modified_time, "%Y-%m-%d %H:%M:%S.%f"
                )
            except ValueError:
                last_modified_time = datetime.strptime(
                    last_modified_time, "%Y-%m-%d %H:%M:%S"
                )
        if isinstance(lastModifiedTime, str):
            try:
                lastModifiedTime = datetime.strptime(
                    lastModifiedTime, "%Y-%m-%d %H:%M:%S.%f"
                )
            except ValueError:
                lastModifiedTime = datetime.strptime(
                    lastModifiedTime, "%Y-%m-%d %H:%M:%S"
                )
        if lastModifiedTime != last_modified_time:
            frappe.msgprint(
                title="Order has been modified",
                indicator="red",
                msg=(
                    "This order has been modified. Please reload the page to retrieve the latest edits."
                ),
            )
            return {"status": "Failure"}
    else:
        # Only block when this is a brand-new order (no last_invoice).
        # Updates to an existing draft (last_invoice set) must be
        # allowed through — the cashier explicitly opened the existing
        # invoice from the Table page and is editing it. The previous
        # version of this check fired on EVERY non-billing-user update
        # and silently returned `{"status": "Failure"}` without raising,
        # so the React POS showed "Order updated successfully" while
        # the items never persisted.
        if (
            not last_invoice
            and invoice.name
            and invoice.invoice_printed == 0
            and not billing_user
        ):
            frappe.msgprint(
                title="Table occupied ",
                indicator="red",
                msg=("{0} is already occupied . Please refresh the page.").format(
                    table
                ),
            )
            return {"status": "Failure"}

    if not customer:
        frappe.throw("Please enter valid customer details")
    else:
        invoice.customer = customer

    if order_type:
        # Guard against a corrupt order_type (e.g. a phone number leaking
        # into the field) reaching the DB. An out-of-range value silently
        # breaks the shift close later — ERPNext's consolidation rejects
        # the merged Sales Invoice (order_type is a Select). Only write a
        # recognised option; log + skip anything else so the order still
        # goes through with its computed default. See CLAUDE.md "Fixes
        # log" 2026-06-05.
        if order_type in _VALID_ORDER_TYPES:
            invoice.order_type = order_type
        else:
            try:
                frappe.log_error(
                    message=f"Ignored invalid order_type {order_type!r} for "
                    f"invoice {invoice.name or '(new)'} / customer {customer}",
                    title="URY: invalid order_type rejected at sync_order",
                )
            except Exception:
                pass

    customerdoc = frappe.get_doc("Customer", customer)
    invoice.mobile_number = customerdoc.mobile_number
    if comments:
        invoice.custom_comments = comments
    invoice.no_of_pax = no_of_pax
    invoice.pos_profile = pos_profile
    # Pull the tax template + tax category from the POS Profile (if set
    # there) onto the draft at creation time. See _apply_pos_profile_taxes.
    _apply_pos_profile_taxes(invoice, pos_profile)
    invoice.cashier = cashier
    invoice.waiter = waiter
    # Self-serve waiter (2026-07-14): if the ringing user is a URY Waiter
    # linked to a URY Waiter record, force HER waiter regardless of what the
    # client sent — she can't ring orders for anyone else. Non-waiters
    # (cashier/captain/manager/admin) get None here and keep the picked one.
    from ury.ury_pos.api import _get_self_waiter_for_user

    _self_waiter = _get_self_waiter_for_user()
    if _self_waiter:
        selected_waiter = _self_waiter.get("name")
    # Waiter feature (2026-06-10): the picked URY Waiter. Only stamp it when
    # supplied (use_waiter on + first-order pick); never clear an existing
    # waiter on a later update where the frontend doesn't send one.
    if selected_waiter:
        invoice.custom_waiter = selected_waiter
    invoice.custom_aggregator_id = aggregator_id
    invoice.custom_restaurant_room = room
    invoice.restaurant_table = table
    # iHotel intent — stamp the hotel room on the draft so it
    # survives reloads. The Payment dialog reads this and
    # auto-activates the Charge to Room tab when present. The actual
    # charge (folio write, custom_charge_to_room=1, table free) fires
    # when the cashier confirms the Charge to Room action.
    if hotel_room is not None:
        invoice.custom_hotel_room = hotel_room or None
    # Stamp the originating terminal so the invoice can be filtered/
    # reported by physical till. Only trusts terminals tied to the
    # session's branch — a spoofed terminal name from a different
    # branch is silently ignored.
    #
    # IMPORTANT: on a freshly-created POS Invoice, `invoice.branch` is
    # still None at this point because ERPNext's `fetch_from` hooks
    # haven't run yet (they fire during validate/save). Comparing
    # against `invoice.branch` directly always fails for new invoices,
    # which means `custom_terminal` was silently dropped on every
    # fresh order. Fall back to looking up the POS Profile's branch
    # directly. See CLAUDE.md "Fixes log" 2026-04-09.
    if terminal:
        terminal_branch = frappe.db.get_value(
            "URY POS Terminal", terminal, "branch"
        )
        invoice_branch = invoice.branch or frappe.db.get_value(
            "POS Profile", pos_profile, "branch"
        )
        if terminal_branch and invoice_branch and terminal_branch == invoice_branch:
            invoice.custom_terminal = terminal
    
    if order_type == "Aggregators":
        price_list = frappe.db.get_value("Aggregator Settings",{"customer": customer, "parent": invoice.branch, "parenttype": "Branch"},"price_list",)
        
        if not price_list:
            frappe.throw(f"Price list for customer {customer} in branch {invoice.branch} not found in Aggregator Settings.")
    else:
        price_list = invoice.selling_price_list

    # dummy payment
    if invoice.invoice_created == 0:
        invoice.append(
            "payments",
            dict(mode_of_payment=mode_of_payment, amount=invoice.grand_total),
        )
        invoice.invoice_created = 1

    past_item = []
    for item in invoice.items:
        previous_item = {
            "item_code": item.item_code,
            "item_name": item.item_name,
            "qty": item.qty,
            "comments": "",
        }
        past_item.append(previous_item)
        

    # Conditional checking for 'items' type:
    # - 'ury': JSON passed, hence using isinstance
    # - 'ury_pos': Already formatted list, hence using else
    if isinstance(items, str):
        items = json.loads(items)
    invoice.items = []

    # Warehouse mode (2026-06-11). When the POS Profile has
    # `custom_use_pos_warehouse` OFF, each item posts stock to its OWN
    # Default Warehouse (Item Defaults for the company) instead of the
    # single profile warehouse. We stamp each item row's warehouse here and
    # clear the header set_warehouse so ERPNext doesn't force one. Items
    # with no default warehouse get a blank warehouse — that's caught at
    # shift close by _validate_item_warehouses with a clear, item-named
    # error so a manager fixes the item.
    _raw_use_wh = (
        frappe.db.get_value("POS Profile", pos_profile, "custom_use_pos_warehouse")
        if pos_profile
        else None
    )
    # Default ON (single warehouse) when the field is unset, for back-compat.
    use_pos_warehouse = 1 if _raw_use_wh is None else int(_raw_use_wh or 0)
    invoice_company = (
        frappe.db.get_value("POS Profile", pos_profile, "company")
        if pos_profile
        else None
    )
    if not use_pos_warehouse:
        invoice.set_warehouse = None

    menu = frappe.db.get_value("URY Menu", {"branch": invoice.branch}, "name")

    for d in items:

        course = frappe.db.get_value("URY Menu Item", {"item": d.get("item"),"parent":menu}, "course")

        item_prices = frappe.db.get_list(
            "Item Price",
            filters={"item_code": d.get("item"), "price_list": price_list},
            fields=["price_list_rate"],
        )

        # "Price Not Set" branded error — covers both (a) no Item Price
        # row for the (item, price_list) pair and (b) a row exists but
        # rate is 0/null. The frontend matches on title="Price Not Set"
        # to render a rich actionable toast with a "Set Price" button
        # (admin/captain/manager only). See CLAUDE.md "Fixes log"
        # 2026-04-08.
        has_valid_price = bool(item_prices and float(item_prices[0].price_list_rate or 0) > 0)
        if not has_valid_price:
            friendly_name = d.get("item_name") or d.get("item")
            frappe.throw(
                _(
                    "No price is set for '{0}' in the active menu. "
                    "An admin needs to open '{1}' in the desk and set a "
                    "rate for this item before it can be ordered."
                ).format(friendly_name, _("ExPOS Menu")),
                title=_("Price Not Set"),
            )

        invoice.append(
            "items",
            dict(
                item_code=d.get("item"),
                item_name=d.get("item_name"),
                qty=d.get("qty"),
                **({"custom_course": course} if course else {}),
                **(
                    {"warehouse": _resolve_item_warehouse(d.get("item"), invoice_company)}
                    if not use_pos_warehouse
                    else {}
                ),
                comment=d.get("comment"),
                rate=item_prices[0].price_list_rate,
                price_list_rate=item_prices[0].price_list_rate,
                base_price_list_rate=item_prices[0].price_list_rate,
                cost_center=frappe.db.get_value(
                    "POS Profile", pos_profile, "cost_center"
                ),
            ),
        )

    # Let ERPNext's ValidationErrors propagate unwrapped — they already
    # carry a title, raise_exception flag and indicator. Wrapping them in
    # `frappe.throw(f"Error while updating order: {e}")` destroyed the
    # title, stripped the raise_exception flag on the re-raise, and
    # prepended a noisy "Error while updating order:" prefix that made
    # the frontend's error-picking logic misbehave. See CLAUDE.md
    # "Fixes log" 2026-04-08.
    invoice.save()


    try:
        kot_execute(invoice.name, customer, table, items, past_item, comments)

    except Exception as e:
        # If an exception occurs (e.g., "kot" app not found), it will be caught here without affect the code execution.
        error_msg = f"KOT Creation Failes {str(e)}"            
        frappe.log_error(error_msg, "KOT Error")

    # table status
    if invoice.invoice_printed == 0:
        frappe.db.set_value(
            "URY Table", table, {"occupied": 1, "latest_invoice_time": invoice.creation}
        )

    if owner:
        invoice.db_set("owner", owner)
    return invoice.as_dict()


@frappe.whitelist()
def item_query_restaurant(
    doctype="Item",
    txt="",
    searchfield="name",
    start=0,
    page_len=20,
    filters=None,
    as_dict=False,
):
    """Return items that are selected in active menu of the restaurant"""
    restaurant, menu = get_restaurant_and_menu_name(filters["table"])
    items = frappe.db.get_all("URY Menu Item", ["item"], dict(parent=menu, disabled=0))
    del filters["table"]
    filters["name"] = ("in", [d.item for d in items])

    return item_query("Item", txt, searchfield, start, page_len, filters, as_dict)


@frappe.whitelist()
def get_restaurant_and_menu_name(table):
    if not table:
        frappe.throw(_("Please select a table"))

    restaurant, branch, room, is_take_away = frappe.get_value(
        "URY Table",
        table,
        ["restaurant", "branch", "restaurant_room", "is_take_away"],
    )

    rest = frappe.db.get_value(
        "URY Restaurant",
        restaurant,
        ["room_wise_menu", "order_type_wise_menu", "active_menu"],
        as_dict=True,
    ) or {}

    # Resolve the menu with the full fallback chain so a restaurant set up
    # with ANY menu mode works: room-wise → order-type-wise → default
    # active_menu. Previously this only checked room-wise / active_menu,
    # so a dine-in table order on a restaurant that uses per-order-type
    # menus (no default active_menu) threw "Please set an active menu".
    # That's the path a waiter hits ringing on tables. 2026-07-15.
    menu = None
    if rest.get("room_wise_menu") and room:
        menu = frappe.db.get_value(
            "Menu for Room", {"parent": restaurant, "room": room}, "menu"
        )
    if not menu and rest.get("order_type_wise_menu"):
        order_type = "Take Away" if is_take_away == 1 else "Dine In"
        menu = frappe.db.get_value(
            "Order Type Menu",
            {"parent": restaurant, "order_type": order_type},
            "menu",
        )
    if not menu:
        menu = rest.get("active_menu")

    if not menu:
        frappe.throw(
            _("Please set an active menu for Restaurant {0}").format(restaurant)
        )

    return branch, menu, restaurant

@frappe.whitelist()
def get_menu_name(order_type):
    branch = getBranch()
    restaurant = frappe.get_value(
        "URY Restaurant",
        {"branch": branch},
        "name",
    )
    order_type_wise_menu = frappe.db.get_value(
            "URY Restaurant", restaurant, "order_type_wise_menu"
        )
    
    if order_type_wise_menu:
        menu = frappe.db.get_value(
            "Order Type Menu",
            {"parent": restaurant, "order_type": order_type},
            "menu"
        )
        if not menu:
            menu = frappe.db.get_value("URY Restaurant", restaurant, "active_menu")
    else:
        menu = frappe.db.get_value("URY Restaurant", restaurant, "active_menu")   
    return menu  
    

@frappe.whitelist()
def cancel_order(invoice_id, reason):
    # Only captains / managers / admins may cancel an order. Cashiers don't
    # see the cancel button; this enforces it server-side too (2026-06-11).
    roles = set(frappe.get_roles(frappe.session.user))
    if frappe.session.user != "Administrator" and not (
        roles & {"System Manager", "URY Manager", "URY Captain"}
    ):
        frappe.throw(
            _("Only a captain or manager can cancel an order."),
            title=_("Not Permitted"),
        )

    pos_invoice = frappe.get_doc("POS Invoice", invoice_id)

    # Update table status
    frappe.db.set_value(
        "URY Table",
        pos_invoice.restaurant_table,
        {"occupied": 0, "latest_invoice_time": None},
    )

    try:
        cancel_kot(invoice_id)

    except Exception as e:
        # If an exception occurs (e.g., "kot" app not found), it will be caught here without effecting execution
        pass

    # Update invoice status
    frappe.db.sql("""
        UPDATE `tabPOS Invoice Item`
        SET docstatus = 2
        WHERE parent = %s
    """, (invoice_id,))

    frappe.db.set_value("POS Invoice", invoice_id, "docstatus", 2)
    frappe.db.set_value("POS Invoice", invoice_id, "status", "Cancelled")
    frappe.db.set_value("POS Invoice", invoice_id, "cancel_reason", reason)

# Method for URY POS
@frappe.whitelist()
def make_invoice(customer, payments, cashier, pos_profile, owner, additionalDiscount=None, table=None, invoice=None, transaction_id=None):
    order_type = invoice_name = frappe.get_value("POS Invoice", invoice, "order_type")
    invoice = get_order_invoice(table, invoice, order_type, "Payments")

    if table:
        restaurant = get_restaurant_and_menu_name(table)
        invoice.restaurant = restaurant

    invoice.customer = customer
    invoice.pos_profile = pos_profile
    # Ensure the POS Profile's tax template + category are applied even if
    # the draft predates this config or was never re-synced after it was
    # set, so the tax is included in the totals below.
    _apply_pos_profile_taxes(invoice, pos_profile)
    invoice.additional_discount_percentage = additionalDiscount
    invoice.calculate_taxes_and_totals()

    for pay in invoice.payments:
        pay.delete(pay.mode_of_payment)

    for d in payments:
        invoice.append(
            "payments", dict(mode_of_payment=d["mode_of_payment"], amount=d["amount"])
        )

    # Optional transaction / reference id for non-cash payments (2026-07-16).
    if transaction_id:
        invoice.custom_transaction_id = transaction_id

    # Don't set owner - it's a read-only field set at document creation
    # invoice.owner = owner  # REMOVE THIS LINE
    
    invoice.save()
    # Do NOT wrap submit() in try/except: frappe.throw(f"...{e}").
    # That pattern strips ERPNext's error title, indicator, and
    # raise_exception flag, leaving the frontend with a generic
    # "There was an error" wrapper instead of the real diagnostic
    # ("Item Out of Stock", "Insufficient Permission", etc.). Let
    # the original ValidationError propagate cleanly so the React
    # POS's extractFrappeServerError() can pick out the title and
    # render an actionable rich toast. Same surgery already done
    # on sync_order — see CLAUDE.md "Fixes log" 2026-04-08.
    invoice.submit()


def _user_can_split_orders():
    """Return (can_split, is_captain).

    Any URY billing role can split an item bill. Captains / managers /
    admins can split ANY cashier's order; a plain cashier can only split
    their own (the caller enforces that against invoice.owner).
    """
    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    captain_roles = {"Administrator", "System Manager", "URY Manager", "URY Captain"}
    is_captain = user == "Administrator" or bool(roles & captain_roles)
    if is_captain:
        return True, True
    if "URY Cashier" in roles:
        return True, False
    return False, False


def _plan_item_split(item_qtys, bills):
    """Pure allocation planner for an item split — no frappe calls, so
    it's fully unit-testable.

    ``item_qtys``: {row_name: total_qty}. ``bills``: list of dicts each
    with an 'allocations' list of {source_row, qty}.

    Returns ``(errors, remaining, leftover_rows)``:
      - ``errors``: list of ``(bill_index, code, row_name)`` tuples, one
        per bad allocation. ``code`` in {"empty", "unknown",
        "nonpositive", "over"}.
      - ``remaining``: {row_name: qty still unallocated after all bills}.
      - ``leftover_rows``: row_names with remaining qty > 0 (i.e. not
        fully allocated). 1e-6 tolerance for decimal-qty float noise.
    """
    remaining = {k: float(v or 0) for k, v in item_qtys.items()}
    errors = []
    for idx, bill in enumerate(bills):
        allocations = bill.get("allocations") or []
        if not allocations:
            errors.append((idx, "empty", None))
            continue
        for alloc in allocations:
            row_name = alloc.get("source_row")
            qty = float(alloc.get("qty") or 0)
            if row_name not in remaining:
                errors.append((idx, "unknown", row_name))
                continue
            if qty <= 0:
                errors.append((idx, "nonpositive", row_name))
                continue
            if qty > remaining[row_name] + 1e-6:
                errors.append((idx, "over", row_name))
                continue
            remaining[row_name] -= qty
    leftover_rows = [k for k, v in remaining.items() if abs(v) > 1e-6]
    return errors, remaining, leftover_rows


@frappe.whitelist()
def split_invoice_by_item(source_invoice, bills, table=None):
    """Split a draft POS Invoice's items into N separate submitted
    invoices, settling each with its own customer + payments.

    ``bills`` is a JSON list (or already-parsed list). Each entry:
        {
          "customer": <name>,
          "allocations": [{"source_row": <POS Invoice Item.name>,
                           "qty": <number>}, ...],
          "payments": [{"mode_of_payment": <mode>, "amount": <number>}, ...],
          "additional_discount_percentage": <number, optional>
        }

    Approach (see CLAUDE.md "Fixes log" 2026-06-05): cancel the source
    draft and create N brand-new submitted POS Invoices. This is
    symmetric (one loop builds every bill), naturally idempotent (the
    cancelled source is the lock against a double-split — a second call
    sees docstatus != 0 and throws), and gives KOT re-pointing one
    deterministic target.

    Everything runs in ONE request → a single implicit commit. Any
    failure (stock, payment mismatch, validation) rolls the whole split
    back and leaves the source draft intact. ERPNext ValidationErrors
    propagate unwrapped so the React POS can render the real message.

    Returns ``{source_invoice, bills: [<new names>], table_freed}``.
    """
    if isinstance(bills, str):
        bills = json.loads(bills)
    if not isinstance(bills, list) or len(bills) < 2:
        frappe.throw(
            _("An item split needs at least two bills."),
            title=_("Invalid Split"),
        )

    if not frappe.db.exists("POS Invoice", source_invoice):
        frappe.throw(
            _("POS Invoice '{0}' not found.").format(source_invoice),
            frappe.DoesNotExistError,
        )

    source = frappe.get_doc("POS Invoice", source_invoice)

    # --- Guard rails -------------------------------------------------
    if source.docstatus != 0:
        frappe.throw(
            _(
                "Only a draft order can be split. '{0}' is already "
                "submitted or cancelled."
            ).format(source_invoice),
            title=_("Cannot Split"),
        )
    if source.get("custom_merged_into"):
        frappe.throw(
            _(
                "'{0}' has been merged into another order and can't be split."
            ).format(source_invoice),
            title=_("Cannot Split"),
        )
    if int(source.get("custom_charge_to_room") or 0):
        frappe.throw(
            _(
                "'{0}' is charged to a hotel room and can't be split."
            ).format(source_invoice),
            title=_("Cannot Split"),
        )

    # Permission: cashier may split their own order; captain any order.
    can_split, is_captain = _user_can_split_orders()
    if not can_split:
        frappe.throw(
            _("You don't have permission to split orders."),
            frappe.PermissionError,
            title=_("Not Allowed"),
        )
    if not is_captain and source.owner != frappe.session.user:
        frappe.throw(
            _(
                "You can only split your own orders. Ask a captain to split "
                "this one."
            ),
            frappe.PermissionError,
            title=_("Not Allowed"),
        )

    # --- Allocation validation (no writes yet) -----------------------
    # The math lives in the pure `_plan_item_split` helper so it can be
    # unit-tested without a real invoice. Here we just map its result to
    # friendly, item-named error messages.
    src_rows = {row.name: row for row in source.items}
    item_qtys = {row.name: float(row.qty or 0) for row in source.items}
    errors, _remaining, leftover_rows = _plan_item_split(item_qtys, bills)

    if errors:
        idx, code, row_name = errors[0]
        label = (
            src_rows[row_name].item_name
            if row_name in src_rows
            else (row_name or _("item"))
        )
        if code == "empty":
            frappe.throw(
                _("Bill {0} has no items.").format(idx + 1),
                title=_("Invalid Split"),
            )
        if code == "unknown":
            frappe.throw(
                _(
                    "Bill {0} references an item that isn't on this order."
                ).format(idx + 1),
                title=_("Invalid Split"),
            )
        if code == "nonpositive":
            frappe.throw(
                _(
                    "Bill {0}: quantity for {1} must be greater than zero."
                ).format(idx + 1, label),
                title=_("Invalid Split"),
            )
        # code == "over"
        frappe.throw(
            _(
                "Bill {0}: you allocated more {1} than the order has left "
                "to split."
            ).format(idx + 1, label),
            title=_("Invalid Split"),
        )

    if leftover_rows:
        leftovers = ", ".join(
            src_rows[r].item_name for r in leftover_rows if r in src_rows
        )
        frappe.throw(
            _(
                "Every item must be fully allocated across the bills. "
                "Unallocated: {0}."
            ).format(leftovers),
            title=_("Incomplete Split"),
        )

    # --- Build + submit each bill ------------------------------------
    restaurant_table = source.get("restaurant_table")
    new_names = []
    for idx, bill in enumerate(bills):
        new_inv = frappe.new_doc("POS Invoice")
        new_inv.is_pos = 1
        new_inv.update_stock = 1
        new_inv.naming_series = source.naming_series
        new_inv.company = source.company
        new_inv.restaurant = source.get("restaurant")
        new_inv.branch = source.branch
        new_inv.restaurant_table = restaurant_table
        new_inv.order_type = source.order_type
        new_inv.pos_profile = source.pos_profile
        new_inv.taxes_and_charges = source.taxes_and_charges
        new_inv.selling_price_list = source.selling_price_list
        new_inv.custom_terminal = source.get("custom_terminal")
        new_inv.waiter = source.get("waiter")
        new_inv.cashier = source.get("cashier")
        new_inv.no_of_pax = source.get("no_of_pax")
        new_inv.customer = bill.get("customer") or source.customer
        cust_mobile = frappe.db.get_value(
            "Customer", new_inv.customer, "mobile_number"
        )
        if cust_mobile:
            new_inv.mobile_number = cust_mobile

        for alloc in bill.get("allocations"):
            src = src_rows[alloc["source_row"]]
            new_inv.append(
                "items",
                dict(
                    item_code=src.item_code,
                    item_name=src.item_name,
                    qty=float(alloc["qty"]),
                    uom=src.get("uom"),
                    conversion_factor=src.get("conversion_factor") or 1,
                    rate=src.rate,
                    price_list_rate=src.get("price_list_rate"),
                    base_price_list_rate=src.get("base_price_list_rate"),
                    cost_center=src.get("cost_center"),
                    warehouse=src.get("warehouse"),
                    **(
                        {"custom_course": src.get("custom_course")}
                        if src.get("custom_course")
                        else {}
                    ),
                    **(
                        {"comment": src.get("comment")}
                        if src.get("comment")
                        else {}
                    ),
                ),
            )

        disc = bill.get("additional_discount_percentage")
        if disc:
            new_inv.additional_discount_percentage = disc

        new_inv.calculate_taxes_and_totals()

        # Two ways to settle each bill:
        #   (a) explicit `payments` [{mode_of_payment, amount}] — the sum
        #       must match the backend grand total within 1c (the backend
        #       total is authoritative); or
        #   (b) a single `payment_mode` string — the backend auto-creates
        #       one payment row for the full grand total. This is what the
        #       item-split UI uses, since the frontend can't compute the
        #       per-bill tax to fill an exact amount.
        grand = float(new_inv.grand_total or 0)
        new_inv.set("payments", [])
        payments = bill.get("payments") or []
        if payments:
            pay_total = sum(float(p.get("amount") or 0) for p in payments)
            if abs(pay_total - grand) > 0.01:
                frappe.throw(
                    _(
                        "Bill {0}: payments ({1}) don't match the bill total "
                        "({2})."
                    ).format(idx + 1, pay_total, grand),
                    title=_("Payment Mismatch"),
                )
            for p in payments:
                new_inv.append(
                    "payments",
                    dict(
                        mode_of_payment=p["mode_of_payment"],
                        amount=float(p["amount"]),
                    ),
                )
        else:
            mode = bill.get("payment_mode")
            if not mode:
                frappe.throw(
                    _("Bill {0}: pick a payment method.").format(idx + 1),
                    title=_("Payment Required"),
                )
            new_inv.append(
                "payments", dict(mode_of_payment=mode, amount=grand)
            )

        new_inv.insert()
        new_inv.submit()
        new_names.append(new_inv.name)

    # --- Re-point KOTs to the last bill (no re-fire) -----------------
    # The food already went to the kitchen at order time. Do NOT fire a
    # CNCL KOT and do NOT re-fire — just re-home the existing KOT rows so
    # they don't dangle on the about-to-be-cancelled source. The last
    # bill is a deterministic single target (a physical KOT represents
    # what the kitchen fired, not what each payer owes).
    last_bill = new_names[-1]
    frappe.db.sql(
        """UPDATE `tabURY KOT` SET invoice=%s
           WHERE invoice=%s AND docstatus != 2""",
        (last_bill, source_invoice),
    )

    # --- Free the table once (after the last bill) -------------------
    table_freed = False
    if restaurant_table:
        frappe.db.set_value(
            "URY Table",
            restaurant_table,
            {"occupied": 0, "latest_invoice_time": None},
        )
        table_freed = True

    # --- Cancel the source draft last --------------------------------
    # Mirror cancel_order's direct-SQL cancel: the source never reached
    # docstatus=1 so there's no GL/stock to reverse; flipping it to
    # Cancelled removes it from the Orders page and locks against a
    # double-split.
    frappe.db.sql(
        "UPDATE `tabPOS Invoice Item` SET docstatus = 2 WHERE parent = %s",
        (source_invoice,),
    )
    frappe.db.set_value("POS Invoice", source_invoice, "docstatus", 2)
    frappe.db.set_value("POS Invoice", source_invoice, "status", "Cancelled")

    return {
        "source_invoice": source_invoice,
        "bills": new_names,
        "table_freed": table_freed,
    }


@frappe.whitelist()
def get_order_items_for_split(invoice):
    """Return a draft POS Invoice's items (with row names) for the
    item-split allocator. Row names are needed so the frontend can map
    each allocation back to a specific POS Invoice Item row.
    """
    if not frappe.db.exists("POS Invoice", invoice):
        frappe.throw(
            _("POS Invoice '{0}' not found.").format(invoice),
            frappe.DoesNotExistError,
        )
    doc = frappe.get_doc("POS Invoice", invoice)
    if doc.docstatus != 0:
        frappe.throw(
            _("Only a draft order can be split."),
            title=_("Cannot Split"),
        )
    items = [
        {
            "row_name": row.name,
            "item_code": row.item_code,
            "item_name": row.item_name,
            "qty": float(row.qty or 0),
            "rate": float(row.rate or 0),
            "uom": row.get("uom"),
        }
        for row in doc.items
    ]
    return {
        "invoice": doc.name,
        "table": doc.get("restaurant_table"),
        "customer": doc.customer,
        "customer_name": doc.customer_name,
        "grand_total": float(doc.grand_total or 0),
        "items": items,
    }


# Cancel KOT Doc Creation
def cancel_kot(invoice_id):

    pos_invoice = frappe.get_doc("POS Invoice", invoice_id)
    pos_profile_id = pos_invoice.pos_profile
    pos_profile = frappe.get_doc("POS Profile", pos_profile_id)
    kot_naming_series = pos_profile.custom_kot_naming_series
    cancel_kot_naming_series = "CNCL-" + kot_naming_series

    items = []
    # Create a list of items for the canceled KOT
    for item in pos_invoice.items:
        order_item = {
            "item_code": item.get("item", item.get("item_code")),
            "qty": item.qty,
            "item_name": item.item_name,
        }
        items.append(order_item)

    if pos_invoice.restaurant_table:
        restaurant_table = pos_invoice.restaurant_table
    else:
        restaurant_table = None

    # Process items for a canceled KOT
    process_items_for_cancel_kot(
        invoice_id,
        pos_invoice.customer,
        restaurant_table,
        items,
        "",
        pos_profile_id,
        cancel_kot_naming_series,
        "Cancelled",
        items,
    )

    # Set the KOTs associated with the invoice as canceled
    kot_list = frappe.db.get_list(
        "URY KOT",
        filters={
            "invoice": invoice_id,
            "type": ("in", ("New Order", "Order Modified")),
            "docstatus": 1,
        },
        fields=("*"),
    )

    for item in kot_list:
        kot_doc = frappe.get_doc("URY KOT", item.name)
        kot_doc.docstatus = 2
        kot_doc.save()


def change_table_in_kot(invoice, new_table, branch):
    # Get a list of KOTs associated with the POS Invoice
    kot_list = frappe.get_all(
        "URY KOT",
        filters={
            "invoice": invoice,
            "docstatus": 1,
            "order_status": "Ready For Prepare",
            "verified": 0,
        },
    )

    # Update each KOT's restaurant_table and send a real-time update
    for kot in kot_list:
        frappe.db.set_value("URY KOT", kot.name, "restaurant_table", new_table)
        production = frappe.db.get_value("URY KOT", kot.name, "production")
        kot_channel = "{}_{}_{}".format("kot_update", branch, production)
        frappe.publish_realtime(kot_channel)
