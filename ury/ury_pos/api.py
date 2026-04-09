import frappe
from frappe import _
from datetime import date, datetime, timedelta



@frappe.whitelist()
def getTable(room):
    branch_name = getBranch()   
    tables = frappe.get_all(
        "URY Table",
        fields=["name", "occupied", "latest_invoice_time", "is_take_away", "restaurant_room","table_shape","no_of_seats"],
        filters={"branch": branch_name,"restaurant_room":room,}
    )    
    return tables


@frappe.whitelist()
def getRestaurantMenu(pos_profile, room=None, order_type=None):
    """Resolve and return the active menu's items for the given context.

    Fails with specific, actionable errors when the data isn't set up yet —
    fresh installs previously hit "Please set an active menu for Restaurant
    None" which didn't explain that the URY Restaurant record itself was
    missing. See CLAUDE.md "Fixes log" 2026-04-08.

    Returns ``items: []`` successfully when the menu exists but has zero
    items — the frontend renders a dedicated empty-state rather than an
    error, so the POS still loads.
    """
    user_role = frappe.get_roles()
    pos_profile = frappe.get_doc("POS Profile", pos_profile)

    cashier = any(
        role.role in user_role for role in pos_profile.role_allowed_for_billing
    )
    branch_name = getBranch()

    restaurant = frappe.db.get_value(
        "URY Restaurant", {"branch": branch_name}, "name"
    )
    if not restaurant:
        # DocType name is wrapped in _() so the en.csv translation layer
        # rewrites "URY Restaurant" → "ExPOS Restaurant" (current brand).
        # See CLAUDE.md "Rebranding" note for the pattern.
        frappe.throw(
            _(
                "No {0} is configured for branch '{1}'. "
                "Open '{0}' in the desk, create a new record linked "
                "to this branch, and set its 'Active Menu'."
            ).format(_("URY Restaurant"), branch_name),
            title=_("Restaurant Not Configured"),
        )

    # Resolve which menu to load based on room-wise / order-type-wise / default.
    if room:
        room_wise_menu = frappe.db.get_value(
            "URY Restaurant", restaurant, "room_wise_menu"
        )
        if room_wise_menu:
            menu = frappe.db.get_value(
                "Menu for Room",
                {"parent": restaurant, "room": room},
                "menu",
            )
            if not menu:
                menu = frappe.db.get_value(
                    "URY Restaurant", restaurant, "active_menu"
                )
        else:
            menu = frappe.db.get_value(
                "URY Restaurant", restaurant, "active_menu"
            )
    elif cashier and order_type:
        order_type_wise_menu = frappe.db.get_value(
            "URY Restaurant", restaurant, "order_type_wise_menu"
        )
        if order_type_wise_menu:
            menu = frappe.db.get_value(
                "Order Type Menu",
                {"parent": restaurant, "order_type": order_type},
                "menu",
            )
            if not menu:
                menu = frappe.db.get_value(
                    "URY Restaurant", restaurant, "active_menu"
                )
        else:
            menu = frappe.db.get_value(
                "URY Restaurant", restaurant, "active_menu"
            )
    else:
        menu = frappe.db.get_value("URY Restaurant", restaurant, "active_menu")

    if not menu:
        frappe.throw(
            _(
                "{0} '{1}' has no Active Menu set. "
                "Open it in the desk and select an 'Active Menu' under the "
                "Menu Settings section."
            ).format(_("URY Restaurant"), restaurant),
            title=_("Active Menu Not Set"),
        )

    menu_items = frappe.get_all(
        "URY Menu Item",
        filters={"parent": menu, "disabled": 0},
        fields=["item", "item_name", "rate", "special_dish", "disabled", "course"],
        order_by="item_name asc",
    )

    # An empty menu is not an error — return an empty list so the POS can
    # render its "no items yet" empty state with a deep-link back to the
    # desk. Throwing here would force the user back to the "Failed to load
    # menu items" screen with nothing actionable.
    menu_items_with_image = [
        {
            "item": item.item,
            "item_name": item.item_name,
            "rate": item.rate,
            "special_dish": item.special_dish,
            "disabled": item.disabled,
            "item_image": frappe.db.get_value("Item", item.item, "image"),
            "course": item.course,
        }
        for item in menu_items
    ]
    modified = frappe.db.get_value("URY Menu", menu, "modified")

    return {
        "items": menu_items_with_image,
        "modified_time": modified,
        "name": menu,
    }

@frappe.whitelist()
def getBranch():
    user = frappe.session.user
    if user != "Administrator":
        sql_query = """
            SELECT b.branch
            FROM `tabURY User` AS a
            INNER JOIN `tabBranch` AS b ON a.parent = b.name
            WHERE a.user = %s
        """
        branch_array = frappe.db.sql(sql_query, user, as_dict=True)
        if not branch_array:
            frappe.throw("User is not Associated with any Branch.Please refresh Page")

        branch_name = branch_array[0].get("branch")

        return branch_name

    # Administrator fallback: pick the branch of the first available POS Profile
    # so Admin can load the POS without being tied to a specific URY User/Branch.
    # See CLAUDE.md "Fixes log" 2026-04-08 for context.
    pos_profile_row = frappe.db.get_value(
        "POS Profile",
        {"disabled": 0},
        ["name", "branch"],
        as_dict=True,
    )
    if not pos_profile_row or not pos_profile_row.get("branch"):
        frappe.throw(
            "Administrator has no default branch and no POS Profile with a branch is configured. "
            "Create at least one POS Profile linked to a Branch."
        )
    return pos_profile_row.get("branch")

@frappe.whitelist()
def getBranchRoom():
    """Return the current user's branch + room as ``[{"name": room, "branch": branch}]``.

    Used by multi-cashier POS Profile mode to find the POS Opening Entry tied
    to a specific (branch, room). Historically this function hard-threw when
    the user's URY User row had no room assigned, which crashed the entire
    POS load path the moment multi-cashier was enabled.

    Behaviour (see CLAUDE.md "Fixes log" 2026-04-08):
      - Administrator: fall back to the first non-disabled POS Profile's
        branch and the first URY Room in that branch (same spirit as
        getBranch()).
      - Regular user without any URY User row: friendly error.
      - Regular user whose URY User row has no room: silently fall back to
        the first URY Room in their branch; if the branch has none, return
        ``room=None`` and let the caller cope. Do not hard-throw — the
        default URY direction is to loosen restrictions, not tighten them.
    """
    user = frappe.session.user

    if user == "Administrator":
        profile = frappe.db.get_value(
            "POS Profile",
            {"disabled": 0},
            ["name", "branch"],
            as_dict=True,
        )
        if not profile or not profile.get("branch"):
            frappe.throw(
                "Administrator has no default branch and no POS Profile with a branch is configured. "
                "Create at least one POS Profile linked to a Branch."
            )
        first_room = frappe.db.get_value("URY Room", {"branch": profile.branch}, "name")
        return [{"name": first_room, "branch": profile.branch}]

    sql_query = """
        SELECT b.branch, a.room
        FROM `tabURY User` AS a
        INNER JOIN `tabBranch` AS b ON a.parent = b.name
        WHERE a.user = %s
    """
    branch_array = frappe.db.sql(sql_query, user, as_dict=True)

    if not branch_array:
        frappe.throw(
            "Your user is not associated with any Branch. "
            "Ask your administrator to add you to a Branch's URY Users list."
        )

    branch_name = branch_array[0].get("branch")
    room_name = branch_array[0].get("room")

    if not room_name:
        # No room on the URY User row — fall back to the first URY Room in
        # this branch instead of hard-throwing. If there's no room at all,
        # leave it as None; the caller handles an empty pos_opening_list.
        room_name = frappe.db.get_value("URY Room", {"branch": branch_name}, "name")

    return [{
        "name": room_name,
        "branch": branch_name,
    }]

@frappe.whitelist()
def getRoom():
    """Return every ``(branch, room)`` pair the current user is attached to.

    Used by the legacy Vue POS (`ury.ury_pos.api.getRoom`). Administrator
    falls back to every URY Room in the first configured POS Profile's
    branch so they can load the legacy POS without a dedicated URY User
    assignment. See CLAUDE.md "Fixes log" 2026-04-08.
    """
    user = frappe.session.user

    if user == "Administrator":
        profile = frappe.db.get_value(
            "POS Profile",
            {"disabled": 0},
            ["name", "branch"],
            as_dict=True,
        )
        if not profile or not profile.get("branch"):
            frappe.throw(
                "Administrator has no default branch and no POS Profile with a branch is configured. "
                "Create at least one POS Profile linked to a Branch."
            )
        rooms = frappe.get_all(
            "URY Room",
            filters={"branch": profile.branch},
            fields=["name"],
        )
        return [{"name": r.name, "branch": profile.branch} for r in rooms]

    sql_query = """
        SELECT b.branch, a.room
        FROM `tabURY User` AS a
        INNER JOIN `tabBranch` AS b ON a.parent = b.name
        WHERE a.user = %s
    """
    branch_array = frappe.db.sql(sql_query, user, as_dict=True)

    if not branch_array:
        frappe.throw(
            "Your user is not associated with any Branch. "
            "Ask your administrator to add you to a Branch's URY Users list."
        )

    return [
        {
            "name": row.get("room"),
            "branch": row.get("branch"),
        }
        for row in branch_array
    ]

@frappe.whitelist()
def getModeOfPayment():
    posDetails = getPosProfile()
    posProfile = posDetails["pos_profile"]
    posProfiles = frappe.get_doc("POS Profile", posProfile)
    mode_of_payments = posProfiles.payments
    modeOfPayments = []
    for mop in mode_of_payments:
        modeOfPayments.append(
            {"mode_of_payment": mop.mode_of_payment, "opening_amount": float(0)}
        )
    return modeOfPayments

@frappe.whitelist()
def getInvoiceForCashier(status, cashier, limit, limit_start):
    branch = getBranch()
    updatedlist = []
    limit = int(limit)+1
    limit_start = int(limit_start)
    if status == "Draft":
        invoices = frappe.db.sql(
            """
            SELECT 
                name, invoice_printed, grand_total, restaurant_table, 
                cashier, waiter, net_total, posting_time, 
                total_taxes_and_charges, customer, status, mobile_number, 
                posting_date, rounded_total, order_type 
            FROM `tabPOS Invoice` 
            WHERE branch = %s AND status = %s AND cashier = %s
            AND (invoice_printed = 1 OR (invoice_printed = 0 AND COALESCE(restaurant_table, '') = ''))
            ORDER BY modified desc
            LIMIT %s OFFSET %s
            """,
            (branch, status, cashier, limit,limit_start),
            as_dict=True,
        )
        updatedlist.extend(invoices)
    elif status == "Unbilled":
        
        docstatus = "Draft"
        invoices = frappe.db.sql(
            """
            SELECT 
                name, invoice_printed, grand_total, restaurant_table, 
                cashier, waiter, net_total, posting_time, 
                total_taxes_and_charges, customer, status, mobile_number, 
                posting_date, rounded_total, order_type 
            FROM `tabPOS Invoice` 
            WHERE branch = %s AND status = %s AND cashier = %s
            AND (invoice_printed = 0 AND restaurant_table IS NOT NULL)
            ORDER BY modified desc
            LIMIT %s OFFSET %s
            """,
            (branch, docstatus, cashier, limit, limit_start),
            as_dict=True,
        )
        updatedlist.extend(invoices)
    elif status == "Recently Paid":
        docstatus = "Paid"
        invoices = frappe.db.sql(
            """
            SELECT 
                name, invoice_printed, grand_total, restaurant_table, 
                cashier, waiter, net_total, posting_time, 
                total_taxes_and_charges, customer, status, mobile_number,
                posting_date, rounded_total, order_type,additional_discount_percentage,discount_amount 
            FROM `tabPOS Invoice` 
            WHERE branch = %s AND status = %s AND cashier = %s
            ORDER BY modified desc
            LIMIT %s OFFSET %s
            """,
            (branch, docstatus, cashier, limit, limit_start),
            as_dict=True,
        )
        updatedlist.extend(invoices)    
    else:
        
        invoices = frappe.db.sql(
            """
            SELECT 
                name, invoice_printed, grand_total, restaurant_table, 
                cashier, waiter, net_total, posting_time, 
                total_taxes_and_charges, customer, status, mobile_number,
                posting_date, rounded_total, order_type,additional_discount_percentage,discount_amount
            FROM `tabPOS Invoice` 
            WHERE branch = %s AND status = %s AND cashier = %s
            ORDER BY modified desc
            LIMIT %s OFFSET %s
            """,
            (branch, status, cashier, limit, limit_start),
            as_dict=True,
        )

        updatedlist.extend(invoices)
    if len(updatedlist) == limit and status != "Recently Paid":
            next = True
            updatedlist.pop()
    else:
            next = False   
    return  { "data":updatedlist,"next":next}



@frappe.whitelist()
def getPosInvoice(status, limit, limit_start):
    branch = getBranch()
    updatedlist = []
    limit = int(limit)+1
    limit_start = int(limit_start)
    if status == "Draft":
        invoices = frappe.db.sql(
            """
            SELECT 
                name, invoice_printed, grand_total, restaurant_table, 
                cashier, waiter, net_total, posting_time, 
                total_taxes_and_charges, customer, status, mobile_number, 
                posting_date, rounded_total, order_type , custom_order_status
            FROM `tabPOS Invoice` 
            WHERE branch = %s AND status = %s 
            AND (invoice_printed = 1 OR (invoice_printed = 0 AND COALESCE(restaurant_table, '') = ''))
            ORDER BY modified desc
            LIMIT %s OFFSET %s
            """,
            (branch, status, limit,limit_start),
            as_dict=True,
        )
        updatedlist.extend(invoices)
    elif status == "Unbilled":
        
        docstatus = "Draft"
        invoices = frappe.db.sql(
            """
            SELECT 
                name, invoice_printed, grand_total, restaurant_table, 
                cashier, waiter, net_total, posting_time, 
                total_taxes_and_charges, customer, status, mobile_number, 
                posting_date, rounded_total, order_type, custom_order_status
            FROM `tabPOS Invoice` 
            WHERE branch = %s AND status = %s 
            AND (invoice_printed = 0 AND restaurant_table IS NOT NULL)
            ORDER BY modified desc
            LIMIT %s OFFSET %s
            """,
            (branch, docstatus, limit, limit_start),
            as_dict=True,
        )
        updatedlist.extend(invoices)
    elif status == "Recently Paid":
        docstatus = "Paid"
        invoices = frappe.db.sql(
            """
            SELECT 
                name, invoice_printed, grand_total, restaurant_table, 
                cashier, waiter, net_total, posting_time, 
                total_taxes_and_charges, customer, status, mobile_number,
                posting_date, rounded_total, order_type,additional_discount_percentage,discount_amount, custom_order_status
            FROM `tabPOS Invoice` 
            WHERE branch = %s AND status = %s 
            ORDER BY modified desc
            LIMIT %s OFFSET %s
            """,
            (branch, docstatus, limit, limit_start),
            as_dict=True,
        )
        updatedlist.extend(invoices)    
    else:
        
        invoices = frappe.db.sql(
            """
            SELECT 
                name, invoice_printed, grand_total, restaurant_table, 
                cashier, waiter, net_total, posting_time, 
                total_taxes_and_charges, customer, status, mobile_number,
                posting_date, rounded_total, order_type,additional_discount_percentage,discount_amount
            FROM `tabPOS Invoice` 
            WHERE branch = %s AND status = %s 
            ORDER BY modified desc
            LIMIT %s OFFSET %s
            """,
            (branch, status, limit, limit_start),
            as_dict=True,
        )

        updatedlist.extend(invoices)
    if len(updatedlist) == limit and status != "Recently Paid":
            next = True
            updatedlist.pop()
    else:
            next = False   
    return  { "data":updatedlist,"next":next}


@frappe.whitelist()
def searchPosInvoice(query,status):
    if not query:
        return {"data": [], "next": False}
    query = query.lower()
    filters = {"status": "Paid" if status == "Recently Paid" else status}
    
    # Add additional conditions for Unbilled status
    if status == "Unbilled":
        filters.update({
            "status":"draft",
            "restaurant_table": ["not in", [None, ""]],  # Check if restaurant_table has value
            "invoice_printed": 0  # Check if invoice_printed is 0
        })
    pos_invoices = frappe.get_all(
        "POS Invoice",
        filters=filters,           
        or_filters=[
            ["name", "like", f"%{query}%"],
            ["customer", "like", f"%{query}%"],
            ["mobile_number", "like", f"%{query}%"],
        ],
        fields=["name", "customer", "grand_total", "posting_date", "posting_time", "order_type", "restaurant_table","status","grand_total","rounded_total","net_total","mobile_number"],
        limit_page_length=10 
    )
    
    return {"data": pos_invoices, "next": len(pos_invoices) == 10}
    

@frappe.whitelist()
def get_select_field_options():
    options = frappe.get_meta("POS Invoice").get_field("order_type").options
    if options:
        return [{"name": option} for option in options.split("\n")]
    else:
        return []


@frappe.whitelist()
def fav_items(customer):
    pos_invoices = frappe.get_all(
        "POS Invoice", filters={"customer": customer}, fields=["name"]
    )
    item_qty = {}

    for invoice in pos_invoices:
        pos_invoice = frappe.get_doc("POS Invoice", invoice.name)
        for item in pos_invoice.items:
            item_name = item.item_name
            qty = item.qty
            if item_name not in item_qty:
                item_qty[item_name] = 0
            item_qty[item_name] += qty

    favorite_items = [
        {"item_name": item_name, "qty": qty} for item_name, qty in item_qty.items()
    ]
    return favorite_items

@frappe.whitelist()
def getCashier(room):
    branch = getBranch()
    cashier = None
    pos_opening_list = frappe.db.sql("""
        SELECT DISTINCT `tabPOS Opening Entry`.name 
        FROM `tabPOS Opening Entry`
        INNER JOIN `tabMultiple Rooms` 
        ON `tabMultiple Rooms`.parent = `tabPOS Opening Entry`.name
        WHERE `tabPOS Opening Entry`.branch = %s
        AND `tabPOS Opening Entry`.status = 'Open'
        AND `tabPOS Opening Entry`.docstatus = 1
        AND `tabMultiple Rooms`.room = %s
    """, (branch, room), as_dict=True)
    if pos_opening_list:
        cashier = frappe.db.get_value(
            "POS Opening Entry",
            {"name": pos_opening_list[0].name},
            "user",)
    return cashier       
    

@frappe.whitelist()
def getPosProfile(terminal=None):
    """Resolve the POS Profile for the current session.

    When ``terminal`` is supplied (the React POS always passes it — the
    device has a registered URY POS Terminal), the profile comes from
    ``URY POS Terminal.pos_profile``. This makes profile selection
    deterministic even when several POS Profiles exist for the same
    branch (Bar, Restaurant, Takeaway…).

    When ``terminal`` is not supplied (legacy Vue POS, Administrator
    experiments, direct API callers), fall back to the historical
    "first POS Profile on this branch" behaviour so nothing breaks.

    See CLAUDE.md "Fixes log" 2026-04-08 for context.
    """
    branchName = getBranch()
    waiter = frappe.session.user
    bill_present = False
    qz_host = None
    printer = None
    cashier = None
    owner = None

    posProfile = None
    if terminal:
        terminal_profile = frappe.db.get_value(
            "URY POS Terminal", terminal, "pos_profile"
        )
        if terminal_profile:
            posProfile = terminal_profile

    if not posProfile:
        posProfile = frappe.db.exists("POS Profile", {"branch": branchName})

    if not posProfile:
        frappe.throw(
            _(
                "No POS Profile is configured for branch '{0}'. "
                "Open 'POS Profile' in the desk and create one, then bind "
                "it to a URY POS Terminal."
            ).format(branchName),
            title=_("POS Profile Not Configured"),
        )

    pos_profiles = frappe.get_doc("POS Profile", posProfile)
    global_defaults = frappe.get_single('Global Defaults')
    disable_rounded_total = global_defaults.disable_rounded_total
    

    if pos_profiles.branch == branchName:
        pos_profile_name = pos_profiles.name
        warehouse = pos_profiles.warehouse
        branch = pos_profiles.branch
        company = pos_profiles.company
        tableAttention = pos_profiles.table_attention_time
        get_cashier = frappe.get_doc("POS Profile", pos_profile_name)
        print_format = pos_profiles.print_format
        paid_limit=pos_profiles.paid_limit
        enable_discount = pos_profiles.custom_enable_discount
        multiple_cashier = pos_profiles.custom_enable_multiple_cashier
        edit_order_type = pos_profiles.custom_edit_order_type
        enable_kot_reprint = pos_profiles.custom_enable_kot_reprint
        shift_hours = pos_profiles.get("custom_shift_hours") or 0
        block_orders_after_shift = (
            pos_profiles.get("custom_block_orders_after_shift_end") or 0
        )
        # Per-terminal scoping makes the cashier/owner resolution trivial:
        # whoever is logged into the React POS right now IS the cashier
        # and the owner. The old code did a SQL join through Multiple
        # Rooms to figure out "who opened the captain entry" — that
        # whole concept is gone now. Per-invoice attribution still
        # happens via POS Invoice.owner = frappe.session.user, and
        # per-terminal attribution via POS Invoice.custom_terminal.
        # See CLAUDE.md "Fixes log" 2026-04-08.
        cashier = frappe.session.user
        owner = frappe.session.user

        qz_print = pos_profiles.qz_print
        print_type = None

        for pos_profile in pos_profiles.printer_settings:
            if pos_profile.bill == 1:
                printer = pos_profile.printer
                bill_present = True
                break

        if qz_print == 1:
            print_type = "qz"
            qz_host = pos_profiles.qz_host

        elif bill_present == True:
            print_type = "network"

        else:
            print_type = "socket"

    invoice_details = {
        "pos_profile": pos_profile_name,
        "branch": branch,
        "company": company,
        "waiter": waiter,
        "warehouse": warehouse,
        "cashier": cashier,
        "print_format": print_format,
        "qz_print": qz_print,
        "qz_host": qz_host,
        "printer": printer,
        "print_type": print_type,
        "tableAttention": tableAttention,
        "paid_limit":paid_limit,
        "disable_rounded_total":disable_rounded_total,
        "enable_discount":enable_discount,
        "multiple_cashier":multiple_cashier,
        "owner":owner,
        "edit_order_type":edit_order_type,
        "enable_kot_reprint":enable_kot_reprint,
        "custom_shift_hours": shift_hours,
        "custom_block_orders_after_shift_end": block_orders_after_shift,
        # Echo the caller's terminal back so the frontend store has a
        # single source of truth for "which terminal resolved this profile".
        "terminal": terminal or None,
    }

    return invoice_details


@frappe.whitelist()
def getPosInvoiceItems(invoice):
    itemDetails = []
    taxDetails = []
    orderdItems = frappe.get_doc("POS Invoice", invoice)
    posItems = orderdItems.items
    for items in posItems:
        item_name = items.item_name
        qty = items.qty
        amount = items.rate
        itemDetails.append(
            {
                "item_name": item_name,
                "qty": qty,
                "amount": amount,
            }
        )
    taxDetail = orderdItems.taxes
    for tax in taxDetail:
        description = tax.description
        rate = tax.tax_amount
        taxDetails.append(
            {
                "description": description,
                "rate": rate,
            }
        )
    return itemDetails, taxDetails


@frappe.whitelist()
def posOpening(terminal=None):
    """Return 1 if the current cashier needs to open POS, 0 otherwise.

    Scope is decided by the POS Profile's ``custom_enable_multiple_cashier``
    flag (set per profile in the desk):

    - **multi_cashier OFF (shared mode):** one POS Opening Entry per
      terminal per shift. The first user to arrive on a terminal opens
      it, everyone else just logs in. Returns 0 (POS is open) as soon
      as ANY user has an open submitted entry on this terminal.
    - **multi_cashier ON (strict mode):** each user opens their own
      entry on the terminal. Returns 0 only if THIS user has an open
      submitted entry on this terminal. Used when you want strict
      per-cashier shift accounting.

    See CLAUDE.md "Fixes log" 2026-04-08.

    When ``terminal`` is omitted (legacy Vue POS, Administrator
    experiments), falls back to the historical branch-only check so
    older callers don't break.
    """
    branchName = getBranch()

    if not terminal:
        # Legacy / Administrator path: scope by branch only.
        pos_opening_list = frappe.get_all(
            "POS Opening Entry",
            fields=["name", "docstatus", "status"],
            filters={"branch": branchName, "status": "Open", "docstatus": 1},
            limit=1,
        )
        return 0 if pos_opening_list else 1

    # Per-terminal path. Determine scope from the POS Profile.
    pos_profile = frappe.db.get_value(
        "URY POS Terminal", terminal, "pos_profile"
    )
    multiple_cashier = (
        frappe.db.get_value(
            "POS Profile", pos_profile, "custom_enable_multiple_cashier"
        )
        if pos_profile
        else 0
    )

    filters = {
        "custom_terminal": terminal,
        "status": "Open",
        "docstatus": 1,
    }
    if multiple_cashier:
        filters["user"] = frappe.session.user

    pos_opening_list = frappe.get_all(
        "POS Opening Entry",
        fields=["name"],
        filters=filters,
        limit=1,
    )
    return 0 if pos_opening_list else 1


@frappe.whitelist()
def preview_pos_closing_entry(opening_entry):
    """Build a preview of the POS Closing Entry for the given opening
    entry, without saving anything.

    Wraps ERPNext's
    ``erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry.make_closing_entry_from_opening``
    so the React POS can render an in-POS closing dialog instead of
    deep-linking to the desk. The wrapper returns a slim dict shape that
    matches what the dialog actually needs (totals + payment rows), so
    we don't ship the full doc with all the relations.

    See CLAUDE.md "Fixes log" 2026-04-09.
    """
    from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import (
        make_closing_entry_from_opening,
    )

    if not frappe.db.exists("POS Opening Entry", opening_entry):
        frappe.throw(
            _("POS Opening Entry '{0}' not found.").format(opening_entry),
            frappe.DoesNotExistError,
        )

    opening_doc = frappe.get_doc("POS Opening Entry", opening_entry)
    if opening_doc.status != "Open":
        frappe.throw(
            _(
                "POS Opening Entry '{0}' is not open (status: {1}). "
                "Only open entries can be closed."
            ).format(opening_entry, opening_doc.status),
            title=_("Already Closed"),
        )

    closing_doc = make_closing_entry_from_opening(opening_doc)

    # Carry the opening_amount over from the opening entry's
    # balance_details (the make_ helper hard-codes opening_amount=0).
    opening_balances = {
        b.mode_of_payment: float(b.opening_amount or 0)
        for b in (opening_doc.balance_details or [])
    }
    payments = []
    for row in closing_doc.payment_reconciliation:
        opening_amount = opening_balances.get(row.mode_of_payment, 0.0)
        expected_amount = float(row.expected_amount or 0)
        payments.append(
            {
                "mode_of_payment": row.mode_of_payment,
                "opening_amount": opening_amount,
                "expected_amount": expected_amount,
                # The closing dialog will let the user edit this. We
                # default it to expected so a one-click "everything
                # matches" close just works.
                "closing_amount": expected_amount,
            }
        )

    return {
        "opening_entry": opening_doc.name,
        "period_start_date": str(opening_doc.period_start_date or ""),
        "period_end_date": str(closing_doc.period_end_date or ""),
        "pos_profile": closing_doc.pos_profile,
        "user": closing_doc.user,
        "company": closing_doc.company,
        "grand_total": float(closing_doc.grand_total or 0),
        "net_total": float(closing_doc.net_total or 0),
        "total_quantity": float(closing_doc.total_quantity or 0),
        "total_taxes_and_charges": float(closing_doc.total_taxes_and_charges or 0),
        "payments": payments,
        "invoice_count": len(closing_doc.pos_invoices or [])
        + len(closing_doc.sales_invoices or []),
    }


@frappe.whitelist()
def submit_pos_closing_entry(opening_entry, closing_amounts):
    """Create and submit a POS Closing Entry from the given opening
    entry, using the cashier-supplied closing amounts.

    ``closing_amounts`` is a JSON object mapping mode_of_payment names
    to the actual cash counted by the cashier (as numbers, not strings).
    Any payment mode missing from the dict defaults to its expected
    amount.

    Returns ``{"name": <closing entry name>}`` on success. Errors are
    propagated as ValidationError so the frontend's standard
    error-handling pipeline picks them up.

    See CLAUDE.md "Fixes log" 2026-04-09.
    """
    import json

    from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import (
        make_closing_entry_from_opening,
    )

    if isinstance(closing_amounts, str):
        try:
            closing_amounts = json.loads(closing_amounts)
        except Exception:
            closing_amounts = {}
    if not isinstance(closing_amounts, dict):
        closing_amounts = {}

    if not frappe.db.exists("POS Opening Entry", opening_entry):
        frappe.throw(
            _("POS Opening Entry '{0}' not found.").format(opening_entry),
            frappe.DoesNotExistError,
        )

    opening_doc = frappe.get_doc("POS Opening Entry", opening_entry)
    if opening_doc.status != "Open":
        frappe.throw(
            _(
                "POS Opening Entry '{0}' is not open (status: {1}). "
                "Only open entries can be closed."
            ).format(opening_entry, opening_doc.status),
            title=_("Already Closed"),
        )

    closing_doc = make_closing_entry_from_opening(opening_doc)

    # Carry opening_amount over so the closing entry's balance vs
    # difference math matches what the cashier saw in the dialog.
    opening_balances = {
        b.mode_of_payment: float(b.opening_amount or 0)
        for b in (opening_doc.balance_details or [])
    }
    for row in closing_doc.payment_reconciliation:
        row.opening_amount = opening_balances.get(row.mode_of_payment, 0.0)
        if row.mode_of_payment in closing_amounts:
            try:
                row.closing_amount = float(closing_amounts[row.mode_of_payment])
            except (TypeError, ValueError):
                row.closing_amount = float(row.expected_amount or 0)
        else:
            row.closing_amount = float(row.expected_amount or 0)
        row.difference = float(row.closing_amount or 0) - float(
            row.expected_amount or 0
        )

    closing_doc.insert()
    closing_doc.submit()

    return {"name": closing_doc.name}


@frappe.whitelist()
def get_pos_open_entry(terminal=None):
    """Return metadata about the *currently open* POS Opening Entry that
    `posOpening()` would consider "this user's session".

    Used by:
    - The "Existing Open Entry" branch of the React POS opening dialog,
      so it can deep-link to the specific entry that's blocking a new
      open. See CLAUDE.md "Fixes log" 2026-04-09.
    - The Shift Hours watcher, so the frontend can compute "how long has
      this shift been open" against the profile's `custom_shift_hours`
      threshold and show a banner.

    Returns ``None`` when there's no matching open entry. Returns
    ``{name, period_start_date, posting_date, pos_profile, user}`` when
    there is one.

    Scoping rules mirror ``posOpening()``:
    - With ``terminal``: per-terminal (and per-user when the profile's
      ``custom_enable_multiple_cashier`` is on).
    - Without ``terminal``: legacy branch-only fallback so the old Vue
      POS / Administrator paths keep working.

    There's also a third lookup mode used by the Existing-Entry dialog:
    when the per-terminal/per-user check returns nothing BUT ERPNext's
    standard ``check_open_pos_exists`` would still fire (because some
    *other* user on this profile has an open entry), the dialog needs
    to find that other entry to deep-link to it. The frontend passes
    ``include_profile_match=1`` to opt into this broader lookup.
    """
    branch_name = getBranch()

    def _entry(filters):
        rows = frappe.get_all(
            "POS Opening Entry",
            filters=filters,
            fields=[
                "name",
                "period_start_date",
                "posting_date",
                "pos_profile",
                "user",
            ],
            order_by="period_start_date desc",
            limit=1,
        )
        return rows[0] if rows else None

    if not terminal:
        return _entry(
            {"branch": branch_name, "status": "Open", "docstatus": 1}
        )

    pos_profile = frappe.db.get_value(
        "URY POS Terminal", terminal, "pos_profile"
    )
    multiple_cashier = (
        frappe.db.get_value(
            "POS Profile", pos_profile, "custom_enable_multiple_cashier"
        )
        if pos_profile
        else 0
    )

    filters = {
        "custom_terminal": terminal,
        "status": "Open",
        "docstatus": 1,
    }
    if multiple_cashier:
        filters["user"] = frappe.session.user

    found = _entry(filters)
    if found:
        return found

    # Fallback: ERPNext's POS Opening Entry validate hook blocks new
    # entries on `(pos_profile, status=Open)` regardless of terminal —
    # so a same-profile entry from another user/terminal can still
    # collide. The dialog needs to find that entry to deep-link.
    if pos_profile:
        return _entry(
            {
                "pos_profile": pos_profile,
                "status": "Open",
                "docstatus": 1,
            }
        )

    return None


@frappe.whitelist()
def getAggregator():
    branchName = getBranch()
    aggregatorList = frappe.get_all(
        "Aggregator Settings",
        fields=["customer"],
        filters={"parent": branchName, "parenttype": "Branch"},
    )
    return aggregatorList


@frappe.whitelist()
def getAggregatorItem(aggregator):
    branchName = getBranch()
    aggregatorItem = []
    aggregatorItemList = []
    priceList = frappe.db.get_value(
        "Aggregator Settings",
        {"customer": aggregator, "parent": branchName, "parenttype": "Branch"},
        "price_list",
    )
    aggregatorItem = frappe.get_all(
        "Item Price",
        fields=["item_code", "item_name", "price_list_rate"],
        filters={"selling": 1, "price_list": priceList},
    )
    aggregatorItemList = [
        {
            "item": item.item_code,
            "item_name": item.item_name,
            "rate": item.price_list_rate,
            "item_image": frappe.db.get_value("Item", item.item, "image"),
        }
        for item in aggregatorItem
        if not frappe.db.get_value("Item", item.item_code, "disabled")
    ]
    return aggregatorItemList

@frappe.whitelist()
def getAggregatorMOP(aggregator):
    branchName = getBranch()
    
    modeOfPayment = frappe.db.get_value(
        "Aggregator Settings",
        {"customer": aggregator, "parent": branchName, "parenttype": "Branch"},
        "mode_of_payments",
    )
    modeOfPaymentsList = []
    modeOfPaymentsList.append(
            {"mode_of_payment": modeOfPayment, "opening_amount": float(0)}
    )
    return modeOfPaymentsList


@frappe.whitelist()
def validate_pos_close(pos_profile, terminal=None):
    """Return the closing status for the previous business day.

    Scoped per-terminal when ``terminal`` is supplied so an unclosed
    entry on Bar 1 doesn't block the cashier on Restaurant A. When the
    POS Profile has ``custom_enable_multiple_cashier`` enabled, the
    check is also scoped per-user (strict per-cashier shift accounting).

    Response shape (new — used by the React POS opening dialog so it can
    deep-link directly to the unclosed entry instead of dumping the user
    on /app):
        {"status": "Success"}
        {"status": "Failed", "unclosed_entry": "POS-OPEN-..."}

    See CLAUDE.md "Fixes log" 2026-04-08 for context.
    """
    enable_unclosed_pos_check = frappe.db.get_value(
        "POS Profile", pos_profile, "custom_daily_pos_close"
    )

    if not enable_unclosed_pos_check:
        return {"status": "Success"}

    current_datetime = frappe.utils.now_datetime()
    start_of_day = current_datetime.replace(hour=5, minute=0, second=0, microsecond=0)

    if current_datetime > start_of_day:
        previous_day = start_of_day - timedelta(days=1)
    else:
        previous_day = start_of_day

    # Match posOpening's scoping rules so the "previous day not closed"
    # check follows the same per-terminal / per-user model. Without
    # terminal scoping a single unclosed entry on Bar 1 would also
    # block Restaurant A on the same branch.
    filters = {
        "posting_date": previous_day.date(),
        "status": "Open",
        "pos_profile": pos_profile,
        "docstatus": 1,
    }
    if terminal:
        filters["custom_terminal"] = terminal
        multiple_cashier = frappe.db.get_value(
            "POS Profile", pos_profile, "custom_enable_multiple_cashier"
        )
        if multiple_cashier:
            filters["user"] = frappe.session.user

    unclosed_pos_opening = frappe.db.exists("POS Opening Entry", filters)

    if unclosed_pos_opening:
        return {"status": "Failed", "unclosed_entry": unclosed_pos_opening}

    return {"status": "Success"}

@frappe.whitelist(allow_guest=True)
def get_latest_kot():
    """Get the latest unprinted KOT for the current user's POS Profile"""
    try:
        current_user = frappe.session.user
        
        # Get user's active POS Profile
        pos_opening = frappe.get_all(
            "POS Opening Entry",
            filters={
                "user": current_user,
                "docstatus": 1,
                "status": "Open"
            },
            fields=["pos_profile"],
            limit=1
        )
        
        if not pos_opening:
            return {"debug": "no_pos_opening", "user": current_user}
        
        pos_profile = pos_opening[0].pos_profile
        
        # Check if QZ is enabled
        qz_print = frappe.db.get_value("POS Profile", pos_profile, "qz_print")
        
        if qz_print != 1:
            return {"debug": "qz_not_enabled", "qz_print": qz_print, "pos_profile": pos_profile}
        
        # Get latest unprinted KOT
        kot = frappe.get_all(
            "URY KOT",
            filters={
                "pos_profile": pos_profile,
                "kot_printed": 0,
                "docstatus": ["!=", 2]
            },
            fields=["name", "kot_printed", "creation"],
            order_by="creation desc",
            limit=1
        )
        
        if not kot:
            return {"debug": "no_unprinted_kots", "pos_profile": pos_profile}
        
        kot_doc = kot[0]
        
        # Get printer settings - FIXED: Removed item_group which doesn't exist
        printer_settings = frappe.get_all(
            "URY Printer Settings",
            filters={
                "parent": pos_profile,
                "parentfield": "printer_settings",
                "custom_kot_print": 1
            },
            fields=["printer", "custom_kot_print_format"]
        )
        
        if not printer_settings:
            return {
                "debug": "no_printers", 
                "pos_profile": pos_profile, 
                "kot_name": kot_doc.name  # FIXED: Include kot_name in debug response
            }
        
        # FIXED: Return proper structure
        return {
            "kot_name": kot_doc.name,
            "pos_profile": pos_profile,
            "kot_printed": kot_doc.kot_printed,
            "printers": printer_settings
        }
        
    except Exception as e:
        import traceback
        return {
            "debug": "exception",
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@frappe.whitelist(methods=['GET'])
def mark_kot_printed(kot_name):
    """Mark a KOT as printed"""
    try:
        if not frappe.db.exists("URY KOT", kot_name):
            return {"status": "error", "message": "KOT not found"}
        
        frappe.db.set_value("URY KOT", kot_name, "kot_printed", 1, update_modified=False)
        frappe.db.commit()
        
        return {"status": "success"}
    except Exception as e:
        frappe.log_error(f"mark_kot_printed error: {str(e)}")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def test_get_kots():
    """Test function to see all unprinted KOTs"""
    try:
        kots = frappe.get_all(
            "URY KOT",
            filters={
                "kot_printed": 0,
                "docstatus": ["!=", 2]
            },
            fields=["name", "kot_printed", "pos_profile", "creation"],
            order_by="creation desc",
            limit=3
        )
        
        return {
            "user": frappe.session.user,
            "kots_count": len(kots),
            "kots": kots
        }
    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def get_kitchen_notifications():
    """Get kitchen order status notifications for the current user"""
    try:
        user = frappe.session.user
        
        # Get POS Invoices with custom_order_status = 'Served' AND custom_clear_from_notification = 0
        notifications = frappe.db.sql("""
            SELECT 
                pi.name as invoice,
                pi.customer_name,
                pi.restaurant_table,
                pi.posting_date,
                pi.posting_time,
                pi.grand_total,
                pi.custom_order_status,
                k.name as kot_name,
                k.order_status as kot_status,
                k.creation as kot_creation,
                GROUP_CONCAT(
                    CONCAT(ki.item_name, ' x', CAST(ki.quantity AS CHAR)) 
                    ORDER BY ki.idx 
                    SEPARATOR ', '
                ) as items_list,
                COUNT(DISTINCT ki.name) as items_count
            FROM `tabPOS Invoice` pi
            LEFT JOIN `tabURY KOT` k ON k.invoice = pi.name
            LEFT JOIN `tabURY KOT Items` ki ON ki.parent = k.name
            WHERE pi.custom_order_status = 'Served'
            AND (pi.custom_clear_from_notification IS NULL OR pi.custom_clear_from_notification = 0)
            AND pi.owner = %s
            AND pi.posting_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
            GROUP BY pi.name
            ORDER BY k.creation DESC
            LIMIT 50
        """, (user,), as_dict=True)
        
        return notifications
        
    except Exception as e:
        frappe.log_error(f"Error fetching kitchen notifications: {str(e)}")
        return []

@frappe.whitelist()
def clear_notification(invoice_name):
    """Clear a notification by setting custom_clear_from_notification = 1"""
    try:
        if frappe.db.exists("POS Invoice", invoice_name):
            frappe.db.set_value(
                "POS Invoice",
                invoice_name,
                "custom_clear_from_notification",
                1,
                update_modified=False
            )
            frappe.db.commit()
            return {"status": "success", "message": "Notification cleared"}
        return {"status": "error", "message": "Invoice not found"}
    except Exception as e:
        frappe.log_error(f"Error clearing notification: {str(e)}")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def get_dashboard_stats(date=None):
    """Get dashboard statistics for a specific date"""
    try:
        if not date:
            date = frappe.utils.today()
        
        user = frappe.session.user
        
        # Get total sales
        total_sales = frappe.db.sql("""
            SELECT COALESCE(SUM(grand_total), 0) as total
            FROM `tabPOS Invoice`
            WHERE posting_date = %s
            AND owner = %s
            AND docstatus = 1
        """, (date, user), as_dict=True)[0].total
        
        # Get total orders
        total_orders = frappe.db.count("POS Invoice", {
            "posting_date": date,
            "owner": user,
            "docstatus": 1
        })
        
        # Get unique customers
        total_customers = frappe.db.sql("""
            SELECT COUNT(DISTINCT customer) as count
            FROM `tabPOS Invoice`
            WHERE posting_date = %s
            AND owner = %s
            AND docstatus = 1
        """, (date, user), as_dict=True)[0].count
        
        # Calculate average order value
        average_order_value = total_sales / total_orders if total_orders > 0 else 0
        
        # Get top selling items
        top_selling_items = frappe.db.sql("""
            SELECT 
                ii.item_name,
                SUM(ii.qty) as quantity,
                SUM(ii.amount) as total_amount
            FROM `tabPOS Invoice` pi
            JOIN `tabPOS Invoice Item` ii ON ii.parent = pi.name
            WHERE pi.posting_date = %s
            AND pi.owner = %s
            AND pi.docstatus = 1
            GROUP BY ii.item_code
            ORDER BY quantity DESC
            LIMIT 5
        """, (date, user), as_dict=True)
        
        return {
            "total_sales": float(total_sales),
            "total_orders": total_orders,
            "total_customers": total_customers,
            "average_order_value": float(average_order_value),
            "top_selling_items": top_selling_items
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching dashboard stats: {str(e)}")
        return {
            "total_sales": 0,
            "total_orders": 0,
            "total_customers": 0,
            "average_order_value": 0,
            "top_selling_items": []
        }


@frappe.whitelist()
def get_daily_sales(date=None):
    """Get daily sales invoices for a specific date"""
    try:
        if not date:
            date = frappe.utils.today()
        
        user = frappe.session.user
        
        # Get invoices
        invoices = frappe.db.sql("""
            SELECT 
                pi.name,
                pi.posting_date,
                pi.posting_time,
                pi.customer_name,
                pi.grand_total,
                pi.status,
                pi.restaurant_table,
                COUNT(ii.name) as items_count
            FROM `tabPOS Invoice` pi
            LEFT JOIN `tabPOS Invoice Item` ii ON ii.parent = pi.name
            WHERE pi.posting_date = %s
            AND pi.owner = %s
            AND pi.docstatus = 1
            GROUP BY pi.name
            ORDER BY pi.posting_time DESC
        """, (date, user), as_dict=True)
        
        # Get payment method totals - correct table name
        payment_totals = frappe.db.sql("""
            SELECT 
                p.mode_of_payment,
                SUM(p.base_amount) as total_amount
            FROM `tabPOS Invoice` pi
            JOIN `tabSales Invoice Payment` p ON p.parent = pi.name
            WHERE pi.posting_date = %s
            AND pi.owner = %s
            AND pi.docstatus = 1
            GROUP BY p.mode_of_payment
            ORDER BY total_amount DESC
        """, (date, user), as_dict=True)
        
        return {
            "invoices": invoices,
            "payment_totals": payment_totals
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching daily sales: {str(e)}")
        return {
            "invoices": [],
            "payment_totals": []
        }


@frappe.whitelist()
def get_terminals():
    """List all active POS Terminals for the current user's branch.

    Used by the React POS setup screen to let the admin pick which terminal
    this device is. Includes ``pos_profile`` so the caller can show which
    profile a terminal is bound to before selection.
    """
    branch = getBranch()
    terminals = frappe.get_all(
        "URY POS Terminal",
        filters={"branch": branch, "disabled": 0},
        fields=["name", "room", "branch", "description", "pos_profile"],
        order_by="name asc",
    )
    return terminals


@frappe.whitelist()
def get_terminal_config(terminal):
    """Fetch POS Terminal configuration by name.

    Returns the terminal's room, branch, description and — crucially —
    the ``pos_profile`` it's bound to. The React POS uses this to resolve
    the profile without guessing by branch. See CLAUDE.md "Fixes log"
    2026-04-08 ("URY POS Terminal ↔ POS Profile binding").
    """
    if not frappe.db.exists("URY POS Terminal", terminal):
        frappe.throw(
            _("POS Terminal '{0}' not found.").format(terminal),
            frappe.DoesNotExistError,
        )

    doc = frappe.get_doc("URY POS Terminal", terminal)

    if doc.disabled:
        frappe.throw(
            _("POS Terminal '{0}' is disabled.").format(terminal),
            frappe.ValidationError,
        )

    if not doc.pos_profile:
        frappe.throw(
            _(
                "POS Terminal '{0}' has no POS Profile set. "
                "Open it in the desk and link a POS Profile before using it."
            ).format(terminal),
            title=_("Terminal Not Configured"),
        )

    return {
        "terminal": doc.name,
        "room": doc.room,
        "branch": doc.branch,
        "description": doc.description,
        "pos_profile": doc.pos_profile,
    }
