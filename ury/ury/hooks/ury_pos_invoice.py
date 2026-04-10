import frappe
from frappe import _
from frappe.utils import cstr, flt, get_datetime, now


def before_insert(doc, method):
    pos_invoice_naming(doc, method)
    order_type_update(doc, method)
    restrict_existing_order(doc, method)


def validate(doc, method):
    validate_invoice(doc, method)
    validate_customer(doc, method)
    validate_price_list(doc, method)
    validate_folio_charge_details(doc, method)


def before_submit(doc, method):
    calculate_and_set_times(doc, method)
    validate_invoice_print(doc, method)
    ro_reload_submit(doc, method)
    # Auto-settle the invoice via a "Room Charge" payment so ERPNext's
    # partial-payment guard is satisfied when charge-to-room is active.
    apply_room_charge_payment(doc)


def on_submit(doc, method):
    post_folio_charge(doc, method)


def on_cancel(doc, method):
    table_status_delete(doc, method)
    reverse_folio_charge(doc, method)


def on_trash(doc, method):
    table_status_delete(doc, method)


def validate_invoice(doc, method):
    if doc.waiter == None or doc.waiter == "":
        doc.waiter = doc.modified_by
    remove_items = frappe.db.get_value("POS Profile", doc.pos_profile, "remove_items")
    
    if doc.invoice_printed == 1 and remove_items == 0:
        # Get the original items from db
        original_doc = frappe.get_doc("POS Invoice", doc.name)
        
        # Create dictionaries to store both quantities and names
        original_items = {
            item.item_code: {"qty": item.qty, "name": item.item_name} 
            for item in original_doc.items
        }
        current_items = {
            item.item_code: {"qty": item.qty, "name": item.item_name} 
            for item in doc.items
        }
          
        # Check for removed items
        removed_items = set(original_items.keys()) - set(current_items.keys())
        
        # Check for quantity reductions
        reduced_qty_items = []
        for item_code, item_data in original_items.items():
            if (item_code in current_items and 
                current_items[item_code]["qty"] < item_data["qty"]):
                reduced_qty_items.append(
                    f"{item_data['name']} (qty reduced from {item_data['qty']} "
                    f"to {current_items[item_code]['qty']})"
                )
        
        if removed_items or reduced_qty_items:
            error_msg = []
            if removed_items:
                removed_item_names = [
                    original_items[item_code]["name"] 
                    for item_code in removed_items
                ]
                error_msg.append(f"Removed items: {', '.join(removed_item_names)}")
            if reduced_qty_items:
                error_msg.append(f"Modified quantities: {', '.join(reduced_qty_items)}")
                
            frappe.throw(
                ("Cannot modify items after invoice is printed.\n{0}")
                .format("\n".join(error_msg))
            )


def validate_customer(doc, method):
    if doc.customer_name == None or doc.customer_name == "":
        frappe.throw(
            (" Failed to load data , Please Refresh the page ").format(
                doc.customer_name
            )
        )




def calculate_and_set_times(doc, method):
    # Set arrived_time to creation time
    doc.arrived_time = doc.creation

    # Get current time as datetime object
    current_time = get_datetime(now())
    
    # Convert doc.creation from string to datetime object
    creation_datetime = get_datetime(doc.creation)
    
    # Calculate time difference (both are now datetime objects)
    time_difference = current_time - creation_datetime
    
    # Format the time difference
    total_seconds = int(time_difference.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    formatted_spend_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    doc.total_spend_time = formatted_spend_time


def validate_invoice_print(doc, method):
    # Check if the invoice has been printed
    invoice_printed = frappe.db.get_value("POS Invoice", doc.name, "invoice_printed")

    # If the invoice is associated with a restaurant table and hasn't been printed
    if doc.restaurant_table and invoice_printed == 0:
        frappe.throw(
            "Printing the invoice is mandatory before submitting. Please print the invoice."
        )


def table_status_delete(doc, method):
    if doc.restaurant_table:
        frappe.db.set_value(
            "URY Table",
            doc.restaurant_table,
            {"occupied": 0, "latest_invoice_time": None},
        )


def pos_invoice_naming(doc, method):
    pos_profile = frappe.get_doc("POS Profile", doc.pos_profile)
    restaurant = pos_profile.restaurant

    if not doc.restaurant_table:
        doc.naming_series = frappe.db.get_value(
            "URY Restaurant", restaurant, "invoice_series_prefix"
        )
        
        if doc.order_type == "Aggregators":
            doc.naming_series = frappe.db.get_value(
                "URY Restaurant", restaurant, "aggregator_series_prefix"
            )
    


def order_type_update(doc, method):
    if doc.restaurant_table:
        if not doc.order_type:
            is_take_away = frappe.db.get_value(
                "URY Table", doc.restaurant_table, "is_take_away"
            )
            if is_take_away == 1:
                doc.order_type = "Take Away"
            else:
                doc.order_type = "Dine In"
    


# reload restaurant order page if submitted invoice is open there
def ro_reload_submit(doc, method):
    frappe.publish_realtime("reload_ro", {"name": doc.name})


def validate_price_list(doc, method):
        
    if doc.restaurant:
        
        if doc.restaurant_table:
            room = frappe.db.get_value("URY Table", doc.restaurant_table, "restaurant_room")
            menu_name = (
                frappe.db.get_value("URY Restaurant", doc.restaurant, "active_menu")
                if not frappe.db.get_value(
                    "URY Restaurant", doc.restaurant, "room_wise_menu"
                )
                else frappe.db.get_value(
                    "Menu for Room", {"parent": doc.restaurant, "room": room}, "menu"
                )
            )

            doc.selling_price_list = frappe.db.get_value(
                "Price List", dict(restaurant_menu=menu_name, enabled=1)
            )
        
        if doc.order_type == "Aggregators":
            price_list = frappe.db.get_value("Aggregator Settings",
                {"customer": doc.customer, "parent": doc.branch, "parenttype": "Branch"},
                "price_list",
                )
            
            if not price_list:
                frappe.throw(f"Price list for customer {doc.customer} in branch {doc.branch} not found in Aggregator Settings.")
                
            doc.selling_price_list = price_list
            
        else:
            menu_name = frappe.db.get_value("URY Restaurant", doc.restaurant, "active_menu") 

            doc.selling_price_list = frappe.db.get_value(
                "Price List", dict(restaurant_menu=menu_name, enabled=1)
            )
            

def restrict_existing_order(doc, event):
    if doc.restaurant_table:
        invoice_exist = frappe.db.exists(
            "POS Invoice",
            {
                "restaurant_table": doc.restaurant_table,
                "docstatus": 0,
                "invoice_printed": 0,
            },
        )
        if invoice_exist:
            frappe.throw(
                ("Table {0} has an existing invoice").format(doc.restaurant_table)
            )


def validate_folio_charge_details(doc, method):
    meta = frappe.get_meta("POS Invoice")
    if not meta.has_field("custom_charge_to_room"):
        return

    if not cint_safe(doc.custom_charge_to_room):
        if meta.has_field("custom_ihotel_room"):
            doc.custom_ihotel_room = None
        doc.custom_ihotel_profile = None
        doc.custom_guest = None
        return

    if not doc.customer:
        frappe.throw(
            _(
                "Select a Customer first. Charge to Room only lists hotel rooms "
                "for iHotel Guests linked to that Customer."
            )
        )

    guest_ids_for_customer = get_guest_names_for_pos_customer(doc.customer)
    if not guest_ids_for_customer and not doc.get("custom_ihotel_profile"):
        frappe.throw(
            _(
                "No iHotel Guest matches this Customer. "
                "In iHotel, open the Guest profile and set ERPXpand Customer to this Customer, "
                "or use the same Guest Name as the Customer Name."
            )
        )

    has_room_field = meta.has_field("custom_ihotel_room")

    if has_room_field and doc.get("custom_ihotel_room"):
        profile_name = resolve_ihotel_profile_for_customer_room(
            doc.customer, doc.custom_ihotel_room
        )
        if not profile_name:
            frappe.throw(
                _(
                    "No open iHotel folio for room {0} for a Guest linked to this Customer."
                ).format(doc.custom_ihotel_room)
            )
        _validate_profile_open(profile_name)
        doc.custom_ihotel_profile = profile_name
        guest = frappe.db.get_value("iHotel Profile", profile_name, "guest")
        doc.custom_guest = guest
        return

    # Legacy: allow direct profile if present (older data / imports).
    if doc.get("custom_ihotel_profile"):
        _validate_profile_open(doc.custom_ihotel_profile)
        profile_guest = frappe.db.get_value(
            "iHotel Profile", doc.custom_ihotel_profile, "guest"
        )
        doc.custom_guest = profile_guest
        allowed = guest_ids_for_customer
        if profile_guest and allowed and profile_guest not in allowed:
            frappe.throw(
                _("This folio belongs to a Guest that is not linked to the selected Customer.")
            )
        return

    frappe.throw(_("Please select a hotel room when Charge to Room is enabled."))


def post_folio_charge(doc, method):
    if not should_post_folio_charge(doc):
        return

    if folio_charge_exists(doc.custom_ihotel_profile, doc.name, positive_only=True):
        return

    profile = frappe.get_doc("iHotel Profile", doc.custom_ihotel_profile)
    amount = flt(doc.net_total)
    if not amount:
        return

    profile.append("charges", {
        "charge_date": doc.posting_date,
        "charge_type": "Food & Beverage",
        # Use the actual doctype name so it reads "Sales Invoice ABC-001" when in SI mode
        "description": f"{doc.doctype} {doc.name}",
        "quantity": 1,
        "rate": amount,
        "amount": amount,
        "reference_doctype": doc.doctype,
        "reference_name": doc.name,
    })
    profile.save(ignore_permissions=True)


def reverse_folio_charge(doc, method):
    if not should_post_folio_charge(doc):
        return

    if not folio_charge_exists(doc.custom_ihotel_profile, doc.name, positive_only=True):
        return

    if folio_charge_exists(doc.custom_ihotel_profile, doc.name, negative_only=True):
        return

    profile = frappe.get_doc("iHotel Profile", doc.custom_ihotel_profile)
    amount = flt(doc.net_total)
    if not amount:
        return

    profile.append("charges", {
        "charge_date": frappe.utils.nowdate(),
        "charge_type": "Food & Beverage",
        "description": f"Reversal of {doc.doctype} {doc.name}",
        "quantity": 1,
        "rate": -amount,
        "amount": -amount,
        "reference_doctype": doc.doctype,
        "reference_name": doc.name,
    })
    profile.save(ignore_permissions=True)


def _ensure_room_charge_mop(company, ar_account):
    """Create the 'Room Charge' Mode of Payment if it doesn't exist yet,
    and make sure the company→account mapping is present.

    Uses the company's AR (Debtors) account so the GL reads:
        Dr Debtors (Room Charge)  Cr Revenue
    — the same as a credit sale; iHotel tracks the actual collection.
    """
    mop_name = "Room Charge"
    if not frappe.db.exists("Mode of Payment", mop_name):
        mop = frappe.get_doc({
            "doctype": "Mode of Payment",
            "mode_of_payment": mop_name,
            "type": "General",
            "accounts": [{"company": company, "default_account": ar_account}],
        })
        mop.insert(ignore_permissions=True)
        frappe.db.commit()
        return

    # Ensure the account row for this company exists
    has_account = frappe.db.exists(
        "Mode of Payment Account",
        {"parent": mop_name, "company": company},
    )
    if not has_account:
        mop = frappe.get_doc("Mode of Payment", mop_name)
        mop.append("accounts", {"company": company, "default_account": ar_account})
        mop.save(ignore_permissions=True)
        frappe.db.commit()


def apply_room_charge_payment(doc):
    """When 'Charge to Room' is ticked and the invoice is not yet fully paid,
    add a 'Room Charge' payment entry for the outstanding balance so ERPNext's
    POS partial-payment validation passes.

    Safe to call for both POS Invoice and Sales Invoice (is_pos).
    Does nothing when charge-to-room is not enabled.
    """
    if not cint_safe(getattr(doc, "custom_charge_to_room", 0)):
        return

    invoice_total = flt(doc.rounded_total) or flt(doc.grand_total)
    already_paid = flt(doc.paid_amount)
    outstanding = round(invoice_total - already_paid, 2)

    if outstanding <= 0:
        return  # Already fully covered by another payment mode

    ar_account = (
        doc.debit_to
        or frappe.db.get_value("Company", doc.company, "default_receivable_account")
    )
    _ensure_room_charge_mop(doc.company, ar_account)

    # Add the payment row that covers the remaining outstanding amount
    doc.append("payments", {
        "mode_of_payment": "Room Charge",
        "account": ar_account,
        "amount": outstanding,
        "default": 0,
    })
    # Recalculate so ERPNext's validators see the updated totals
    doc.paid_amount = invoice_total
    doc.outstanding_amount = 0


def should_post_folio_charge(doc):
    """Works for both POS Invoice and Sales Invoice (when Sales Invoice mode is active in POS)."""
    meta = frappe.get_meta(doc.doctype)
    return (
        meta.has_field("custom_charge_to_room")
        and cint_safe(doc.custom_charge_to_room)
        and doc.custom_ihotel_profile
    )


def _validate_profile_open(profile_name):
    """Block posting to Transferred or Closed folios; allow Open and Settled
    (Settled reopens automatically when a new charge is appended)."""
    status = frappe.db.get_value("iHotel Profile", profile_name, "status")
    if status not in ("Open", "Settled"):
        frappe.throw(_("iHotel Profile {0} cannot accept charges (status: {1}).").format(profile_name, status))


def get_guest_names_for_pos_customer(customer):
    """iHotel Guest doc names that correspond to this POS Customer.

    Match order:
    1) Guest.customer equals this Customer (set when iHotel syncs Guest → Customer)
    2) Guest Name equals Customer.customer_name (fallback when link not set)
    """
    if not customer:
        return []

    guests = frappe.get_all("Guest", filters={"customer": customer}, pluck="name")
    if guests:
        return guests

    cust_name = frappe.db.get_value("Customer", customer, "customer_name")
    if cust_name:
        guest_id = frappe.db.get_value("Guest", {"guest_name": cust_name}, "name")
        if guest_id:
            return [guest_id]
    return []


def resolve_ihotel_profile_for_customer_room(customer, room_name):
    """Find the active folio for this room where the stay Guest matches this Customer.

    Accepts Open and Settled folios — Settled folios auto-reopen when a charge is added.
    Uses ci.status = 'Checked In' to confirm the guest is still in-house.
    """
    if not customer or not room_name:
        return None

    guest_names = get_guest_names_for_pos_customer(customer)
    if not guest_names:
        return None

    placeholders = ", ".join(["%s"] * len(guest_names))
    # Room on folio may be empty on older data; fall back to Checked In.room.
    profiles = frappe.db.sql(
        f"""
        SELECT p.name
        FROM `tabiHotel Profile` p
        INNER JOIN `tabChecked In` ci ON ci.name = p.hotel_stay AND ci.docstatus = 1
        WHERE ci.status = 'Checked In'
          AND p.status IN ('Open', 'Settled')
          AND COALESCE(NULLIF(TRIM(p.room), ''), ci.room) = %s
          AND ci.guest IN ({placeholders})
        """,
        tuple([room_name] + guest_names),
    )
    profiles = [row[0] for row in profiles]

    if len(profiles) > 1:
        frappe.throw(
            _(
                "More than one active folio matches this room for Guests linked to this Customer. "
                "Please fix the duplicate in iHotel."
            )
        )
    return profiles[0] if profiles else None


@frappe.whitelist()
def get_pos_guest_names_for_charge_to_room(customer):
    """Guest document names for this POS Customer (for room link filter label: Guest, not Customer)."""
    if not customer:
        return []
    return get_guest_names_for_pos_customer(customer)


def _guest_names_from_room_link_filters(filters):
    """Resolve guest ids from link search filters (guest in [...]) or legacy customer key."""
    if not filters:
        return []
    raw = filters.get("guest")
    if raw is not None:
        if isinstance(raw, (list, tuple)) and len(raw) >= 2 and cstr(raw[0]).lower() == "in":
            inner = raw[1]
            if isinstance(inner, (list, tuple)):
                return [x for x in inner if x]
            return [inner] if inner else []
        if isinstance(raw, (list, tuple)):
            return [x for x in raw if x]
    customer = filters.get("customer")
    if customer:
        return get_guest_names_for_pos_customer(customer)
    return []


@frappe.whitelist()
def get_ihotel_folio_from_room(customer, room):
    """Resolve folio profile and guest for POS after room selection."""
    if not customer or not room:
        return {}
    profile = resolve_ihotel_profile_for_customer_room(customer, room)
    if not profile:
        return {}
    guest = frappe.db.get_value("iHotel Profile", profile, "guest")
    return {"profile": profile, "guest": guest}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_ihotel_rooms_for_customer_query(
    doctype, txt, searchfield, start, page_len, filters
):
    """Link search: rooms where the guest is currently checked in (Open or Settled folio).

    Client passes filters ``guest`` = ``[\"in\", [guest_name, ...]]`` so the link UI
    shows *Guest* (guest names), not *Customer*.
    Settled folios are included because they auto-reopen when a new charge is added.
    """
    guest_names = _guest_names_from_room_link_filters(filters or {})
    if not guest_names:
        return []

    placeholders = ", ".join(["%s"] * len(guest_names))
    txt = txt or ""
    return frappe.db.sql(
        f"""
        SELECT DISTINCT room.name, room.room_number
        FROM `tabiHotel Profile` p
        INNER JOIN `tabChecked In` ci ON ci.name = p.hotel_stay AND ci.docstatus = 1
        INNER JOIN `tabRoom` room ON room.name = COALESCE(NULLIF(TRIM(p.room), ''), ci.room)
        WHERE ci.status = 'Checked In'
          AND p.status IN ('Open', 'Settled')
          AND ci.guest IN ({placeholders})
          AND COALESCE(NULLIF(TRIM(ci.room), ''), NULLIF(TRIM(p.room), '')) IS NOT NULL
          AND (room.name LIKE %s OR IFNULL(room.room_number, '') LIKE %s)
        ORDER BY room.room_number, room.name
        LIMIT %s, %s
        """,
        tuple(guest_names + [f"%{txt}%", f"%{txt}%", int(start), int(page_len)]),
    )


def folio_charge_exists(profile_name, invoice_name, positive_only=False, negative_only=False):
    rows = frappe.db.sql(
        """
        SELECT amount
        FROM `tabFolio Charge`
        WHERE parent = %s
          AND parenttype = 'iHotel Profile'
          AND parentfield = 'charges'
          AND reference_doctype = 'POS Invoice'
          AND reference_name = %s
        """,
        (profile_name, invoice_name),
        as_dict=True,
    )

    if not rows:
        return False

    if positive_only:
        return any(flt(row.amount) > 0 for row in rows)

    if negative_only:
        return any(flt(row.amount) < 0 for row in rows)

    return True


def cint_safe(value):
    try:
        return int(value or 0)
    except Exception:
        return 0
