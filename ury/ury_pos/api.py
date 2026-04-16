import frappe
import json
from frappe import _
from datetime import date, datetime, timedelta



@frappe.whitelist()
def getTable(room):
    """Return the top-level tables in `room` for the current branch.

    Merged sources (tables whose `merged_into` is set) are excluded so
    the POS grid only shows master tables. Each row also carries a
    `merge_info` object for master tables that have an Active merge
    log, so the frontend can render the "Merged +N" badge without an
    extra round-trip. See CLAUDE.md "Fixes log" 2026-04-11.
    """
    branch_name = getBranch()
    tables = frappe.db.sql(
        """
        SELECT
            t.name, t.occupied, t.latest_invoice_time, t.is_take_away,
            t.restaurant_room, t.table_shape, t.no_of_seats,
            t.merged_into,
            (
                SELECT ml.name
                FROM `tabURY Table Merge Log` AS ml
                WHERE ml.master_table = t.name
                  AND ml.status = 'Active'
                ORDER BY ml.merged_at DESC
                LIMIT 1
            ) AS merge_log_name,
            (
                SELECT COUNT(ms.name)
                FROM `tabURY Table Merge Source` AS ms
                INNER JOIN `tabURY Table Merge Log` AS ml2
                  ON ml2.name = ms.parent
                WHERE ml2.master_table = t.name AND ml2.status = 'Active'
            ) AS merge_source_count
        FROM `tabURY Table` AS t
        WHERE t.branch = %s
          AND t.restaurant_room = %s
          AND (t.merged_into IS NULL OR t.merged_into = '')
        ORDER BY t.name
        """,
        (branch_name, room),
        as_dict=True,
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
            frappe.throw(
                _(
                    "Your user is not linked to any Branch. "
                    "Ask your administrator to open the Branch in the desk and "
                    "add you to the {0}s table."
                ).format(_("URY User")),
                title=_("Branch Not Linked"),
            )

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

def _resolve_orders_scope(terminal, cashier):
    """Translate the requested cashier-scope into an SQL `owner` clause.

    The frontend sends one of three values for ``cashier``:
      - ``None`` or ``"mine"`` → only the current user's orders.
      - ``"all"`` → all URY Cashier / URY Captain users on this terminal's
        branch (so HR users etc. who happen to have rung an order are
        excluded).
      - any other string → a specific user. Validated to make sure they
        have URY Cashier / URY Captain role on this branch; otherwise
        the request is silently downgraded to ``"mine"``.

    Server-side privilege escalation: only Administrator / System Manager /
    URY Manager / URY Captain can request anything other than ``"mine"``.
    Anything else gets downgraded to the requesting user's own orders.

    See CLAUDE.md "Fixes log" 2026-04-09.
    """
    requesting_user = frappe.session.user
    requesting_roles = set(frappe.get_roles(requesting_user))
    captain_roles = {"Administrator", "System Manager", "URY Manager", "URY Captain"}
    is_captain = (
        requesting_user == "Administrator" or bool(requesting_roles & captain_roles)
    )

    # Default and the silent-downgrade fallback.
    mine_clause = ("owner = %s", [requesting_user])

    if not cashier or cashier == "mine":
        return mine_clause

    if not is_captain:
        # Cashier requested a wider scope they aren't allowed to see.
        return mine_clause

    if cashier == "all":
        if not terminal:
            return mine_clause
        terminal_branch = frappe.db.get_value(
            "URY POS Terminal", terminal, "branch"
        )
        if not terminal_branch:
            return mine_clause
        cashier_user_ids = [
            c["user"] for c in _get_cashier_users_on_branch(terminal_branch)
        ]
        if not cashier_user_ids:
            return mine_clause
        placeholders = ", ".join(["%s"] * len(cashier_user_ids))
        return (f"owner IN ({placeholders})", cashier_user_ids)

    # Specific user — verify they're a real cashier on this branch
    # before honouring the request. Anything else downgrades to mine.
    if not terminal:
        return mine_clause
    terminal_branch = frappe.db.get_value(
        "URY POS Terminal", terminal, "branch"
    )
    if not terminal_branch:
        return mine_clause
    cashier_user_ids = {
        c["user"] for c in _get_cashier_users_on_branch(terminal_branch)
    }
    if cashier not in cashier_user_ids:
        return mine_clause
    return ("owner = %s", [cashier])


def _get_cashier_users_on_branch(branch_name):
    """Return enabled cashier users listed in the Branch's URY User
    child table who also have URY Cashier or URY Captain role.

    Returns a list of ``{user, full_name}`` dicts so callers that need
    a friendly display name (closing dialog transfer picker, Orders
    page cashier dropdown) don't have to make N+1 lookups. Callers
    that only care about the user id can read `c["user"]`.
    """
    rows = frappe.db.sql(
        """
        SELECT DISTINCT u.name AS user, u.full_name AS full_name
        FROM `tabURY User` AS uu
        INNER JOIN `tabBranch` AS b ON uu.parent = b.name
        INNER JOIN `tabUser` AS u ON u.name = uu.user
        INNER JOIN `tabHas Role` AS hr ON hr.parent = u.name
        WHERE b.branch = %s
        AND hr.role IN ('URY Cashier', 'URY Captain')
        AND u.enabled = 1
        ORDER BY u.full_name, u.name
        """,
        (branch_name,),
        as_dict=True,
    )
    return [
        {"user": r.user, "full_name": r.full_name or r.user} for r in rows
    ]


@frappe.whitelist()
def get_cashier_users_for_terminal(terminal):
    """Return the list of cashier users on this terminal's branch, for
    the captain's "Cashier" filter dropdown on the Orders page.

    Each row: ``{user, full_name}``. Sorted by full_name.
    """
    if not terminal:
        return []

    terminal_branch = frappe.db.get_value(
        "URY POS Terminal", terminal, "branch"
    )
    if not terminal_branch:
        return []

    return _get_cashier_users_on_branch(terminal_branch)


@frappe.whitelist()
def getPosInvoice(
    status,
    limit,
    limit_start,
    terminal=None,
    posting_date=None,
    cashier=None,
):
    """List POS Invoices for the Orders page.

    Filters (all optional except `status`):
      - `terminal`: scope to a single URY POS Terminal (custom_terminal).
      - `posting_date`: scope to a single posting_date (YYYY-MM-DD).
      - `cashier`: see ``_resolve_orders_scope`` for the three modes
        ("mine" / "all" / specific user).

    Status branches share most of the SQL — only the `status` value and
    a small "extra clause" differ. Refactored from four near-identical
    50-line SQL blocks into one builder. See CLAUDE.md "Fixes log"
    2026-04-09.
    """
    branch = getBranch()
    limit = int(limit) + 1
    limit_start = int(limit_start)

    # Map UI status → DB status + extra WHERE clause for the special
    # Draft/Unbilled splits that ride on the same `Draft` docstatus.
    # Charged-to-room drafts are EXCLUDED from Draft/Unbilled and get
    # their own "Room Charges" bucket (a docstatus=0 invoice that
    # won't ever submit — it's been billed to the guest's folio via
    # the iHotel integration). See CLAUDE.md "Fixes log" 2026-04-12.
    # "Pending KOTs" is a cross-status overlay — it matches any
    # docstatus=0 Draft POS Invoice that still has at least one URY
    # KOT with kot_printed=0 (i.e. at least one department is still
    # held). Uses a correlated EXISTS subquery so paid invoices (which
    # are typically cleaned up by the fire-pending-on-bill-print hook)
    # don't clutter the list.
    status_map = {
        "Draft": (
            "Draft",
            "AND (pi.invoice_printed = 1 OR (pi.invoice_printed = 0 AND COALESCE(pi.restaurant_table, '') = '')) "
            "AND (pi.custom_charge_to_room IS NULL OR pi.custom_charge_to_room = 0)",
        ),
        "Unbilled": (
            "Draft",
            "AND (pi.invoice_printed = 0 AND pi.restaurant_table IS NOT NULL) "
            "AND (pi.custom_charge_to_room IS NULL OR pi.custom_charge_to_room = 0)",
        ),
        "Recently Paid": ("Paid", ""),
        "Room Charges": (
            "Draft",
            "AND pi.custom_charge_to_room = 1",
        ),
        "Pending KOTs": (
            "Draft",
            "AND (pi.custom_charge_to_room IS NULL OR pi.custom_charge_to_room = 0) "
            "AND EXISTS ("
            "  SELECT 1 FROM `tabURY KOT` kot "
            "  WHERE kot.invoice = pi.name "
            "  AND kot.kot_printed = 0 "
            "  AND kot.docstatus != 2"
            ")",
        ),
    }
    db_status, extra_where = status_map.get(status, (status, ""))

    where_parts = ["pi.branch = %s", "pi.status = %s"]
    params = [branch, db_status]

    # Hide invoices that have been merged into another. The master
    # remains visible; only the dormant sources are filtered out.
    where_parts.append(
        "(pi.custom_merged_into IS NULL OR pi.custom_merged_into = '')"
    )

    if terminal:
        # Defensive null fallback: orders that pre-date the
        # custom_terminal field (or that somehow slipped through
        # without a terminal stamp) still show up on every terminal of
        # their branch. The branch filter above keeps the scope
        # bounded — an Accra user never sees Tamale orders. Without
        # this fallback, historical orders disappear from the Orders
        # page entirely once per-terminal scoping is enabled. See
        # CLAUDE.md "Fixes log" 2026-04-09.
        where_parts.append(
            "(pi.custom_terminal = %s OR pi.custom_terminal IS NULL OR pi.custom_terminal = '')"
        )
        params.append(terminal)
    if posting_date:
        where_parts.append("pi.posting_date = %s")
        params.append(posting_date)

    scope_clause, scope_params = _resolve_orders_scope(terminal, cashier)
    where_parts.append(f"pi.{scope_clause}")
    params.extend(scope_params)

    where_sql = " AND ".join(where_parts)
    if extra_where:
        where_sql = f"{where_sql} {extra_where}"

    sql = f"""
        SELECT
            pi.name, pi.invoice_printed, pi.grand_total, pi.restaurant_table,
            pi.cashier, pi.waiter, pi.net_total, pi.posting_time,
            pi.total_taxes_and_charges, pi.customer, pi.customer_name,
            pi.status, pi.mobile_number, pi.posting_date, pi.rounded_total,
            pi.order_type, pi.custom_order_status, pi.custom_terminal,
            pi.owner, pi.is_return, pi.return_against,
            pi.custom_charge_to_room, pi.custom_hotel_room,
            pi.custom_ihotel_profile,
            u.full_name AS owner_full_name,
            (
                SELECT ml.name
                FROM `tabURY Order Merge Log` AS ml
                WHERE ml.master_invoice = pi.name AND ml.status = 'Active'
                ORDER BY ml.merged_at DESC
                LIMIT 1
            ) AS merge_log_name,
            (
                SELECT COUNT(s.name)
                FROM `tabURY Order Merge Source` AS s
                INNER JOIN `tabURY Order Merge Log` AS ml2
                  ON ml2.name = s.parent
                WHERE ml2.master_invoice = pi.name AND ml2.status = 'Active'
            ) AS merge_source_count,
            (
                SELECT COUNT(r.name)
                FROM `tabPOS Invoice` AS r
                WHERE r.return_against = pi.name
                  AND r.is_return = 1
                  AND r.docstatus = 1
            ) AS active_return_count
        FROM `tabPOS Invoice` AS pi
        LEFT JOIN `tabUser` AS u ON u.name = pi.owner
        WHERE {where_sql}
        ORDER BY pi.modified DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, limit_start])

    rows = frappe.db.sql(sql, tuple(params), as_dict=True)

    has_next = False
    if len(rows) == limit and status != "Recently Paid":
        has_next = True
        rows.pop()

    return {"data": rows, "next": has_next}


@frappe.whitelist()
def searchPosInvoice(
    query,
    status,
    terminal=None,
    posting_date=None,
    cashier=None,
):
    """Search POS Invoices by name / customer / mobile.

    Honours the same scoping rules as `getPosInvoice` so a captain who
    types into the search box doesn't suddenly see invoices from
    yesterday on a different terminal. See CLAUDE.md "Fixes log"
    2026-04-09.
    """
    if not query:
        return {"data": [], "next": False}

    branch = getBranch()
    query_str = f"%{query.lower()}%"

    db_status = "Paid" if status == "Recently Paid" else status
    # Room Charges is a Draft-level pseudo-status; map it to Draft for
    # the DB query and let the extra WHERE clause filter by the custom
    # charge_to_room flag. See CLAUDE.md "Fixes log" 2026-04-12.
    if status == "Room Charges":
        db_status = "Draft"
    # Pending KOTs is also a Draft-level pseudo-status — docstatus=0
    # with at least one un-printed URY KOT child. See Phase B of the
    # 2026-04-16 print revamp.
    if status == "Pending KOTs":
        db_status = "Draft"
    where_parts = ["pi.branch = %s", "pi.status = %s"]
    params = [branch, db_status]

    # Hide merged-source invoices from search results too — same rule
    # as getPosInvoice.
    where_parts.append(
        "(pi.custom_merged_into IS NULL OR pi.custom_merged_into = '')"
    )

    if status == "Unbilled":
        where_parts.append("pi.restaurant_table IS NOT NULL")
        where_parts.append("pi.invoice_printed = 0")

    # Exclude charged-to-room drafts from every non-"Room Charges"
    # status so they only surface under their dedicated bucket.
    if status == "Room Charges":
        where_parts.append("pi.custom_charge_to_room = 1")
    else:
        where_parts.append(
            "(pi.custom_charge_to_room IS NULL OR pi.custom_charge_to_room = 0)"
        )

    # Pending KOTs status: correlated EXISTS clause matching any URY
    # KOT child with kot_printed=0 (same predicate used by the list
    # endpoint's status_map for consistency).
    if status == "Pending KOTs":
        where_parts.append(
            "EXISTS ("
            "  SELECT 1 FROM `tabURY KOT` kot "
            "  WHERE kot.invoice = pi.name "
            "  AND kot.kot_printed = 0 "
            "  AND kot.docstatus != 2"
            ")"
        )

    if terminal:
        # Same defensive null fallback as getPosInvoice — see
        # CLAUDE.md "Fixes log" 2026-04-09.
        where_parts.append(
            "(pi.custom_terminal = %s OR pi.custom_terminal IS NULL OR pi.custom_terminal = '')"
        )
        params.append(terminal)
    if posting_date:
        where_parts.append("pi.posting_date = %s")
        params.append(posting_date)

    scope_clause, scope_params = _resolve_orders_scope(terminal, cashier)
    where_parts.append(f"pi.{scope_clause}")
    params.extend(scope_params)

    # Search across name / customer / mobile_number.
    where_parts.append(
        "(LOWER(pi.name) LIKE %s OR LOWER(pi.customer) LIKE %s OR LOWER(pi.mobile_number) LIKE %s)"
    )
    params.extend([query_str, query_str, query_str])

    sql = f"""
        SELECT
            pi.name, pi.customer, pi.customer_name, pi.grand_total,
            pi.posting_date, pi.posting_time, pi.order_type,
            pi.restaurant_table, pi.status, pi.rounded_total, pi.net_total,
            pi.mobile_number, pi.cashier, pi.waiter, pi.invoice_printed,
            pi.custom_order_status, pi.custom_terminal, pi.owner,
            pi.is_return, pi.return_against,
            pi.custom_charge_to_room, pi.custom_hotel_room,
            pi.custom_ihotel_profile,
            u.full_name AS owner_full_name,
            (
                SELECT ml.name
                FROM `tabURY Order Merge Log` AS ml
                WHERE ml.master_invoice = pi.name AND ml.status = 'Active'
                ORDER BY ml.merged_at DESC
                LIMIT 1
            ) AS merge_log_name,
            (
                SELECT COUNT(s.name)
                FROM `tabURY Order Merge Source` AS s
                INNER JOIN `tabURY Order Merge Log` AS ml2
                  ON ml2.name = s.parent
                WHERE ml2.master_invoice = pi.name AND ml2.status = 'Active'
            ) AS merge_source_count,
            (
                SELECT COUNT(r.name)
                FROM `tabPOS Invoice` AS r
                WHERE r.return_against = pi.name
                  AND r.is_return = 1
                  AND r.docstatus = 1
            ) AS active_return_count
        FROM `tabPOS Invoice` AS pi
        LEFT JOIN `tabUser` AS u ON u.name = pi.owner
        WHERE {" AND ".join(where_parts)}
        ORDER BY pi.modified DESC
        LIMIT 10
    """

    rows = frappe.db.sql(sql, tuple(params), as_dict=True)
    return {"data": rows, "next": len(rows) == 10}
    

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
def get_session_user_info():
    """Return the current session user's identity, full name, and the
    *effective* role list — including roles inherited from any Role
    Profile assignment AND the implicit `All` / `Guest` roles.

    Why this exists:

    The React POS used to fetch the user's role list via
    `db.getDoc('User', email)` (frappe-js-sdk → REST endpoint
    `/api/resource/User/<email>`). That requires the user to have
    READ permission on the User doctype, which URY-only roles like
    URY Captain and URY Cashier don't have by default. The fetch
    silently 403s, the catch block swallows the error and returns
    `{ roles: [], full_name: '' }`, and any role-gated UI in the
    React POS (Cashier filter card, Set Price button, etc.) never
    fires because `user.roles` is empty.

    This endpoint sidesteps the doctype permission entirely. Every
    authenticated user is allowed to introspect their OWN session —
    it never reveals other users' info — so no scoping is needed.
    Uses `frappe.get_roles()` which is the canonical effective-role
    accessor (also picks up Role Profile inheritance, which raw
    `User.roles` child-table reads miss).

    See CLAUDE.md "Fixes log" 2026-04-09.
    """
    user = frappe.session.user
    full_name = frappe.db.get_value("User", user, "full_name") or ""
    roles = frappe.get_roles(user) or []
    return {
        "user": user,
        "full_name": full_name,
        "roles": roles,
    }


@frappe.whitelist()
def get_pos_profile_full(pos_profile, terminal=None):
    """Return the full POS Profile doc for the React POS, bypassing the
    REST-resource permission check.

    Background: the React POS needs the full doc (role lists, payment
    modes, applicable_for_users, etc.) to render the order panel and
    enforce some role gates. The naive approach (`db.getDoc('POS
    Profile', name)` from frappe-js-sdk) routes through
    `/api/resource/POS Profile/<name>` which calls
    `doc.check_permission("read")`. URY Cashier and URY Captain don't
    have a read perm on POS Profile by default, so the call 403s. The
    `ensure_role_permissions()` baseline tries to add a Custom DocPerm
    but that approach is fragile (cache invalidation, migrate-time
    silent failures, conflicts with admin tweaks).

    This endpoint sidesteps the REST permission check entirely:
    `frappe.get_doc()` doesn't enforce read perms — it just loads the
    doc — and as a whitelisted method we run with the session user's
    identity but don't trigger ERPNext's role-based read check on the
    POS Profile doctype.

    Authorization is enforced server-side instead: when a `terminal`
    is supplied, we verify the requested profile matches the
    terminal's `pos_profile` binding. This prevents a captain at
    branch A from reading branch B's POS Profile via this method.

    See CLAUDE.md "Fixes log" 2026-04-09.
    """
    if not pos_profile:
        frappe.throw(
            _("POS Profile name is required."),
            title=_("Missing Argument"),
        )

    if not frappe.db.exists("POS Profile", pos_profile):
        frappe.throw(
            _("POS Profile '{0}' not found.").format(pos_profile),
            frappe.DoesNotExistError,
        )

    if terminal:
        terminal_profile = frappe.db.get_value(
            "URY POS Terminal", terminal, "pos_profile"
        )
        if terminal_profile and terminal_profile != pos_profile:
            frappe.throw(
                _(
                    "Terminal '{0}' is bound to POS Profile '{1}', not '{2}'."
                ).format(terminal, terminal_profile, pos_profile),
                title=_("Profile Mismatch"),
            )

    doc = frappe.get_doc("POS Profile", pos_profile)
    return doc.as_dict()


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
        restrict_merge_to_captain = (
            pos_profiles.get("custom_restrict_merge_to_captain") or 0
        )
        # Returns default to captain-only (field default = 1).
        raw_restrict_returns = pos_profiles.get("custom_restrict_returns_to_captain")
        restrict_returns_to_captain = (
            1 if raw_restrict_returns is None else int(raw_restrict_returns or 0)
        )
        ihotel_enabled = int(pos_profiles.get("custom_ihotel_enabled") or 0)
        ihotel_charge_type = pos_profiles.get("custom_ihotel_charge_type") or None
        shift_system_mode = pos_profiles.get("custom_shift_system_mode") or "Disabled"
        # Unified print routing (2026-04-16). Expose the new fields
        # so the React POS knows which print path to drive. The
        # resolver / routing logic all lives on the backend — the
        # frontend only needs the mode to pick QZ vs CUPS vs Disabled.
        print_mode = pos_profiles.get("custom_print_mode") or None
        bill_printer = pos_profiles.get("custom_bill_printer") or None
        kitchen_kot_printer = pos_profiles.get("custom_kitchen_kot_printer") or None
        bar_kot_printer = pos_profiles.get("custom_bar_kot_printer") or None
        parcel_kot_printer = pos_profiles.get("custom_parcel_kot_printer") or None
        drinks_kot_route = pos_profiles.get("custom_drinks_kot_route") or None
        food_kot_route = pos_profiles.get("custom_food_kot_route") or None
        takeaway_kot_route = pos_profiles.get("custom_takeaway_kot_route") or None
        print_fallback_mode = pos_profiles.get("custom_print_fallback_mode") or None
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
        "custom_restrict_merge_to_captain": restrict_merge_to_captain,
        "custom_restrict_returns_to_captain": restrict_returns_to_captain,
        "custom_ihotel_enabled": ihotel_enabled,
        "custom_ihotel_charge_type": ihotel_charge_type,
        "custom_shift_system_mode": shift_system_mode,
        # Unified print routing (2026-04-16). The frontend reads
        # `custom_print_mode` to decide QZ vs CUPS vs Disabled. All
        # the routing (Food/Drinks/Takeaway -> which printer) is
        # resolved server-side in ury_print.resolve_kot_print_plan.
        "custom_print_mode": print_mode,
        "custom_bill_printer": bill_printer,
        "custom_kitchen_kot_printer": kitchen_kot_printer,
        "custom_bar_kot_printer": bar_kot_printer,
        "custom_parcel_kot_printer": parcel_kot_printer,
        "custom_drinks_kot_route": drinks_kot_route,
        "custom_food_kot_route": food_kot_route,
        "custom_takeaway_kot_route": takeaway_kot_route,
        "custom_print_fallback_mode": print_fallback_mode,
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
    needs_open = 0 if pos_opening_list else 1

    # If the cashier needs to open AND the profile uses the shift
    # system, gate the open against the assigned shift. Throws a clean
    # error when outside the window so the React POS opening dialog
    # surfaces it via the existing extractFrappeServerError path.
    # See CLAUDE.md "Fixes log" 2026-04-14.
    if needs_open:
        _enforce_shift_gate_for_open(terminal=terminal)

    return needs_open


@frappe.whitelist()
def _scope_invoices_for_opening_entry(opening_doc):
    """Return the SQL WHERE clause + params that match POS Invoices
    belonging to the given opening entry's shift.

    Scope:
      * Same pos_profile.
      * Not a consolidated invoice.
      * When `custom_terminal` is set on the opening entry, also scope
        to invoices stamped with that terminal.
      * Created on or after the opening entry's creation — defensive
        against timestamp drift caused by backdated posting_date or
        pre-opening test data polluting the shift.
      * **Shared vs strict multi-cashier mode (2026-04-13):**
        The profile's ``custom_enable_multiple_cashier`` flag decides
        whether invoice ownership is part of the scope. Under shared
        mode (flag OFF — the default), one POS Opening Entry serves
        the whole terminal and any cashier on that terminal can ring
        orders. The close must see every invoice on the terminal
        regardless of who rang it, so the ``owner`` filter is DROPPED.
        Under strict mode (flag ON), each user opens their own entry
        and closes their own — so ``pi.owner = opening_doc.user`` is
        kept to prevent A's close from consolidating B's orders.

    NOTE: we use `creation` (row insert timestamp), not
    `posting_date + posting_time`, which ERPNext's native helper does.
    Cashiers sometimes backdate posting_date to match late-entered
    orders, which would make ERPNext's timestamp-based filter exclude
    those invoices from the close. Our filter is honest about the
    invoice's actual creation time on this device.
    """
    where = [
        "pi.pos_profile = %s",
        "(pi.consolidated_invoice IS NULL OR pi.consolidated_invoice = '')",
        "pi.creation >= %s",
    ]
    params = [
        opening_doc.pos_profile,
        opening_doc.creation,
    ]

    # Strict mode: scope by opener so two users on the same terminal
    # close their own shifts independently. Shared mode: skip the
    # owner filter entirely — the single entry covers everyone on
    # this terminal.
    multi_cashier = int(
        frappe.db.get_value(
            "POS Profile",
            opening_doc.pos_profile,
            "custom_enable_multiple_cashier",
        )
        or 0
    )
    if multi_cashier:
        where.append("pi.owner = %s")
        params.append(opening_doc.user)

    terminal = getattr(opening_doc, "custom_terminal", None)
    if terminal:
        # Defensive null fallback (same pattern as getPosInvoice): an
        # invoice that predates the custom_terminal column is still
        # counted if it's otherwise in scope.
        where.append(
            "(pi.custom_terminal = %s OR pi.custom_terminal IS NULL OR pi.custom_terminal = '')"
        )
        params.append(terminal)
    return " AND ".join(where), params


def _get_shift_invoice_breakdown(opening_doc):
    """Return paid + draft invoice lists for the given opening entry.

    Each invoice dict carries enough fields for the closing dialog to
    render a draft list (name, customer_name, grand_total,
    restaurant_table). Drafts exclude invoices already merged into a
    master.

    **Orphan-original handling:** when a return invoice is in scope
    but its `return_against` original isn't (typically because the
    original was paid in a previous unclosed shift), we pull the
    original in as an extra row — provided it's unconsolidated. Without
    this, ERPNext's `consolidate_pos_invoices` hook on POS Closing
    Entry submission throws `"Row #1: The original Invoice X of return
    invoice Y is not consolidated"` and rolls back the whole close.
    """
    where_sql, params = _scope_invoices_for_opening_entry(opening_doc)

    paid = frappe.db.sql(
        f"""
        SELECT
            pi.name, pi.customer, pi.customer_name,
            pi.posting_date, pi.grand_total, pi.net_total, pi.total_qty,
            pi.total_taxes_and_charges, pi.restaurant_table,
            pi.is_return, pi.return_against
        FROM `tabPOS Invoice` AS pi
        WHERE {where_sql}
          AND pi.docstatus = 1
          AND pi.status IN ('Paid', 'Consolidated', 'Return')
        ORDER BY pi.creation ASC
        """,
        tuple(params),
        as_dict=True,
    )

    # Pull in orphan originals: any return in `paid` whose
    # `return_against` isn't already in `paid`, provided the original is
    # itself unconsolidated. Skipping this makes ERPNext's consolidation
    # hook fail on a cross-shift return.
    existing_names = {row["name"] for row in paid}
    orphan_names = {
        row["return_against"]
        for row in paid
        if row.get("is_return")
        and row.get("return_against")
        and row["return_against"] not in existing_names
    }
    if orphan_names:
        orphan_rows = frappe.db.sql(
            """
            SELECT
                pi.name, pi.customer, pi.customer_name,
                pi.posting_date, pi.grand_total, pi.net_total, pi.total_qty,
                pi.total_taxes_and_charges, pi.restaurant_table,
                pi.is_return, pi.return_against
            FROM `tabPOS Invoice` AS pi
            WHERE pi.name IN %(names)s
              AND pi.docstatus = 1
              AND (pi.consolidated_invoice IS NULL OR pi.consolidated_invoice = '')
              AND (pi.custom_merged_into IS NULL OR pi.custom_merged_into = '')
            """,
            {"names": tuple(orphan_names)},
            as_dict=True,
        )
        # Prepend so the closing entry lists the original before its
        # return — matches ERPNext's expectation in consolidate_pos_invoices.
        paid = list(orphan_rows) + paid

    draft = frappe.db.sql(
        f"""
        SELECT
            pi.name, pi.customer, pi.customer_name,
            pi.grand_total, pi.net_total, pi.restaurant_table,
            pi.invoice_printed, pi.custom_order_status
        FROM `tabPOS Invoice` AS pi
        WHERE {where_sql}
          AND pi.docstatus = 0
          AND (pi.custom_merged_into IS NULL OR pi.custom_merged_into = '')
          AND (pi.custom_charge_to_room IS NULL OR pi.custom_charge_to_room = 0)
        ORDER BY pi.creation ASC
        """,
        tuple(params),
        as_dict=True,
    )

    return paid, draft


def _sum_payments_for_paid_invoices(paid_invoices):
    """Group Sales Invoice Payment rows by mode_of_payment and sum."""
    if not paid_invoices:
        return {}
    names = [row["name"] for row in paid_invoices]
    rows = frappe.db.sql(
        """
        SELECT sip.mode_of_payment, SUM(sip.amount) AS total
        FROM `tabSales Invoice Payment` AS sip
        WHERE sip.parenttype IN ('POS Invoice', 'Sales Invoice')
          AND sip.parent IN %(names)s
        GROUP BY sip.mode_of_payment
        """,
        {"names": tuple(names)},
        as_dict=True,
    )
    return {r.mode_of_payment: float(r.total or 0) for r in rows}


@frappe.whitelist()
def preview_pos_closing_entry(opening_entry):
    """Build a preview of the POS Closing Entry for the given opening
    entry, without saving anything.

    Rewritten 2026-04-10: we run our own invoice-scope query instead of
    leaning on ERPNext's ``make_closing_entry_from_opening`` because
    that helper filters by ``posting_date + posting_time`` in a window
    between ``period_start_date`` and ``now`` — which silently drops
    any invoice whose posting_date was backdated (see the "Outdated
    POS Opening Entry" flow). The result was a preview that showed
    "2 invoices, ₵0 total" instead of the real breakdown.

    The new preview also splits paid vs draft invoices so the closing
    dialog can force the cashier to transfer drafts to another cashier
    before closing. See the companion ``submit_pos_closing_entry``
    rewrite for the transfer flow. CLAUDE.md "Fixes log" 2026-04-10.
    """
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

    paid, draft = _get_shift_invoice_breakdown(opening_doc)

    # Sum totals from the paid invoices (non-return rows count positive,
    # return rows count negative — ERPNext stores return grand_total as
    # a negative number already so plain sum is correct).
    grand_total = sum(float(row.get("grand_total") or 0) for row in paid)
    net_total = sum(float(row.get("net_total") or 0) for row in paid)
    total_qty = sum(float(row.get("total_qty") or 0) for row in paid)
    total_tax = sum(
        float(row.get("total_taxes_and_charges") or 0) for row in paid
    )

    # Payment reconciliation — group all paid invoices' payment rows by
    # mode and sum. Seed rows from the opening entry's balance_details
    # so modes with an opening float show up even when nothing was
    # collected in that mode during the shift.
    paid_by_mode = _sum_payments_for_paid_invoices(paid)
    opening_balances = {
        b.mode_of_payment: float(b.opening_amount or 0)
        for b in (opening_doc.balance_details or [])
    }
    all_modes = set(paid_by_mode.keys()) | set(opening_balances.keys())
    payments = []
    for mode in sorted(all_modes):
        opening_amount = opening_balances.get(mode, 0.0)
        expected_amount = paid_by_mode.get(mode, 0.0)
        payments.append(
            {
                "mode_of_payment": mode,
                "opening_amount": opening_amount,
                "expected_amount": expected_amount,
                # Default the counted amount to the expected so a
                # "everything matches" close is one click.
                "closing_amount": expected_amount,
            }
        )

    # Draft list for the transfer-before-close UI.
    draft_list = [
        {
            "name": row["name"],
            "customer": row.get("customer"),
            "customer_name": row.get("customer_name") or row.get("customer"),
            "grand_total": float(row.get("grand_total") or 0),
            "restaurant_table": row.get("restaurant_table"),
            "invoice_printed": int(row.get("invoice_printed") or 0),
        }
        for row in draft
    ]
    draft_grand_total = sum(r["grand_total"] for r in draft_list)

    # Transfer-target candidates: other cashiers on the same branch who
    # have URY Cashier or URY Captain role. We exclude the current user
    # (you can't transfer to yourself) and System Manager / Admin
    # because those aren't regular cashiers in the URY sense.
    transfer_candidates = _get_cashier_users_on_branch(opening_doc.branch)
    me = frappe.session.user
    transfer_candidates = [
        c for c in transfer_candidates if c["user"] != me
    ]

    return {
        "opening_entry": opening_doc.name,
        "period_start_date": str(opening_doc.period_start_date or ""),
        "period_end_date": str(frappe.utils.now_datetime()),
        "pos_profile": opening_doc.pos_profile,
        "user": opening_doc.user,
        "company": opening_doc.company,
        # Paid-side totals (this is what the closing entry will record).
        "grand_total": grand_total,
        "net_total": net_total,
        "total_quantity": total_qty,
        "total_taxes_and_charges": total_tax,
        "invoice_count": len(paid),
        "payments": payments,
        # Draft-side state drives the transfer-before-close UI.
        "draft_count": len(draft_list),
        "draft_grand_total": draft_grand_total,
        "draft_invoices": draft_list,
        "transfer_candidates": transfer_candidates,
    }


@frappe.whitelist()
def submit_pos_closing_entry(opening_entry, closing_amounts, transfer_to=None):
    """Create and submit a POS Closing Entry from the given opening
    entry, using the cashier-supplied closing amounts.

    ``closing_amounts`` is a JSON object mapping mode_of_payment names
    to the actual cash counted by the cashier.

    ``transfer_to`` is an optional user id. If the shift has any draft
    (unpaid) POS Invoices, the caller MUST pass a ``transfer_to`` user
    who will inherit those invoices. The backend re-home the drafts by
    updating their ``owner`` (and mirrors the name on the ``cashier``
    custom field) so they show up in the target cashier's "My Orders"
    filter on next page load. If drafts exist and ``transfer_to`` is
    omitted, the close is rejected with a clear error and a list of
    draft names so the cashier knows what's blocking them.

    Rewritten 2026-04-10 to compute totals ourselves (see the preview
    docstring) AND to enforce the transfer-drafts-before-close rule.

    See CLAUDE.md "Fixes log" 2026-04-10.
    """
    import json

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

    paid, draft = _get_shift_invoice_breakdown(opening_doc)

    # --- Transfer-before-close guard ----------------------------------
    if draft:
        if not transfer_to:
            draft_names = ", ".join(row["name"] for row in draft[:5])
            more = (
                f" (+{len(draft) - 5} more)" if len(draft) > 5 else ""
            )
            frappe.throw(
                _(
                    "You have {0} unpaid order(s) on this shift: {1}{2}. "
                    "Select a cashier to transfer them to before closing."
                ).format(len(draft), draft_names, more),
                title=_("Transfer Required"),
            )

        # Validate the target user: must be a URY Cashier / URY Captain
        # on the same branch, and not the current user themselves.
        me = frappe.session.user
        if transfer_to == me:
            frappe.throw(
                _("You can't transfer orders to yourself."),
                title=_("Invalid Transfer Target"),
            )
        candidates = {
            c["user"]
            for c in _get_cashier_users_on_branch(opening_doc.branch)
        }
        if transfer_to not in candidates:
            frappe.throw(
                _(
                    "Selected cashier {0} isn't listed as a URY Cashier or "
                    "URY Captain on branch {1}."
                ).format(transfer_to, opening_doc.branch),
                title=_("Invalid Transfer Target"),
            )

        # Re-home the drafts. Changing `owner` reassigns ERPNext's
        # creator back-ref, which is what our `_resolve_orders_scope`
        # filter in the Orders page reads for the "mine" / "all" /
        # specific-user filter. We also stamp the `cashier` custom
        # field (used in some URY print paths) and set a transfer
        # audit note via the `remarks` field.
        #
        # Discoverability fix (2026-04-16): clear `custom_terminal`
        # AND reset `posting_date`/`posting_time` to now. Without
        # this the receiving cashier's default Orders page filter
        # (their current terminal + today's date) hides the
        # transfers silently — we've seen it in the wild. Clearing
        # the terminal lets the defensive null fallback in
        # `getPosInvoice` ("terminal IS NULL OR terminal = '' OR
        # terminal = ?") surface them on whichever terminal the
        # receiver is on within the branch. Updating posting_date
        # is a semantic call: the draft now belongs to today's
        # business flow under the new cashier, not yesterday's
        # under the original; the `remarks` field preserves the
        # audit trail. If the receiver wants to dig, the original
        # opening entry is in the remarks line.
        target_full_name = (
            frappe.db.get_value("User", transfer_to, "full_name") or transfer_to
        )
        transfer_note = (
            f"Transferred from {me} on shift close ({opening_doc.name})"
        )
        now_datetime = frappe.utils.now_datetime()
        now_date = now_datetime.date()
        now_time = now_datetime.time()
        for row in draft:
            frappe.db.set_value(
                "POS Invoice",
                row["name"],
                {
                    "owner": transfer_to,
                    "cashier": target_full_name,
                    "remarks": transfer_note,
                    "custom_terminal": None,
                    "posting_date": now_date,
                    "posting_time": now_time,
                },
                update_modified=True,
            )
        frappe.db.commit()

    # --- Normalize paid invoice ownership -----------------------------
    # Shared-mode mismatch (2026-04-13): in shared multi-cashier mode
    # more than one user can ring orders under a single opening entry.
    # ERPNext's `validate_pos_invoices` (pos_closing_entry.py line 128)
    # hard-rejects any invoice whose `owner` doesn't equal the closing
    # entry's `user`, which in URY's flow is always `opening_doc.user`.
    # We rehome every paid invoice's `owner` to the opener so the
    # closing entry submits cleanly — and stamp a remark so the actual
    # ringer is still visible in the invoice's text history.
    #
    # This only runs when a mismatch actually exists (not every shift
    # has cross-cashier activity), keeps `cashier` untouched for
    # invoices that already match, and commits once at the end.
    opener = opening_doc.user
    rehomed_paid = 0
    for row in paid:
        inv_owner = frappe.db.get_value("POS Invoice", row["name"], "owner")
        if inv_owner and inv_owner != opener:
            frappe.db.set_value(
                "POS Invoice",
                row["name"],
                {
                    "owner": opener,
                    "remarks": f"Originally rung by {inv_owner}; "
                    f"ownership normalized on shift close ({opening_doc.name})",
                },
                update_modified=True,
            )
            rehomed_paid += 1
    if rehomed_paid:
        frappe.db.commit()

    # --- Build + insert the closing entry ------------------------------
    total_qty = sum(float(row.get("total_qty") or 0) for row in paid)
    grand_total = sum(float(row.get("grand_total") or 0) for row in paid)
    net_total = sum(float(row.get("net_total") or 0) for row in paid)
    total_tax = sum(
        float(row.get("total_taxes_and_charges") or 0) for row in paid
    )

    paid_by_mode = _sum_payments_for_paid_invoices(paid)
    opening_balances = {
        b.mode_of_payment: float(b.opening_amount or 0)
        for b in (opening_doc.balance_details or [])
    }
    all_modes = set(paid_by_mode.keys()) | set(opening_balances.keys())

    # Pre-flight validation: sanity-check the data the close depends
    # on so cashiers get actionable errors BEFORE ERPNext's deeply
    # nested consolidation chain throws something opaque. Each check
    # throws with a clear title + message naming the exact document
    # that's misconfigured. See CLAUDE.md "Fixes log" 2026-04-11.
    _validate_close_preflight(paid, opening_doc.company)

    closing_doc = frappe.new_doc("POS Closing Entry")
    closing_doc.pos_opening_entry = opening_doc.name
    closing_doc.period_start_date = opening_doc.period_start_date
    closing_doc.period_end_date = frappe.utils.now_datetime()
    closing_doc.pos_profile = opening_doc.pos_profile
    closing_doc.user = opening_doc.user
    closing_doc.company = opening_doc.company
    closing_doc.grand_total = grand_total
    closing_doc.net_total = net_total
    closing_doc.total_quantity = total_qty
    closing_doc.total_taxes_and_charges = total_tax

    for row in paid:
        closing_doc.append(
            "pos_invoices",
            {
                "pos_invoice": row["name"],
                "posting_date": row.get("posting_date"),
                "grand_total": float(row.get("grand_total") or 0),
                "customer": row.get("customer"),
                "is_return": int(row.get("is_return") or 0),
                "return_against": row.get("return_against"),
            },
        )

    for mode in sorted(all_modes):
        opening_amount = opening_balances.get(mode, 0.0)
        expected_amount = paid_by_mode.get(mode, 0.0)
        if mode in closing_amounts:
            try:
                counted = float(closing_amounts[mode])
            except (TypeError, ValueError):
                counted = expected_amount
        else:
            counted = expected_amount
        closing_doc.append(
            "payment_reconciliation",
            {
                "mode_of_payment": mode,
                "opening_amount": opening_amount,
                "expected_amount": expected_amount,
                "closing_amount": counted,
                "difference": counted - expected_amount,
            },
        )

    # URY Cashier / Captain don't have DocPerms on every doctype in
    # the long tail that ERPNext's consolidation touches (GL Entry,
    # Stock Ledger Entry, Payment Ledger Entry, Customer balance
    # updates, etc.). Running insert + submit with
    # `ignore_permissions=True` is the standard Frappe escape hatch
    # for "the caller has already been authorized at a higher level,
    # trust the internal bookkeeping downstream". The caller of this
    # method already passed the whitelist check and the upstream
    # draft-transfer guard, so this is safe.
    try:
        closing_doc.insert(ignore_permissions=True)
        closing_doc.submit()
    except Exception as err:
        # Catch the consolidation-time cascade and re-throw with a
        # pointer to the most common root causes — Mode of Payment
        # account misconfig, missing customer fields, etc. Preserves
        # the original error text for the full diagnostic trail but
        # prepends a hint so cashiers don't have to dig through the
        # traceback to know what to check.
        raise _wrap_close_error(err, opening_doc.company)

    return {
        "name": closing_doc.name,
        "transferred": len(draft),
        "transfer_to": transfer_to if draft else None,
    }


def _validate_close_preflight(paid_invoices, company):
    """Sanity-check the data the close depends on and throw clean
    errors for the common misconfigurations that otherwise surface as
    ERPNext cascade failures during consolidation.

    Checks (in order):
      1. Every paid invoice has a `customer` set.
      2. Every `Mode of Payment` used on these invoices has an
         `account` configured for the company AND that account isn't
         a Receivable account (which is what triggered the "Customer
         is required against Receivable account" bug on 2026-04-10 —
         Credit Card's account was set to Debtors).
    """
    if not paid_invoices:
        return

    # Check 1: customer on every invoice.
    missing_customer = [
        row["name"] for row in paid_invoices if not row.get("customer")
    ]
    if missing_customer:
        frappe.throw(
            _(
                "Cannot close this shift: {0} paid invoice(s) have no "
                "customer set — {1}. Open each invoice in the desk "
                "and set a customer before closing."
            ).format(len(missing_customer), ", ".join(missing_customer[:5])),
            title=_("Invoice Missing Customer"),
        )

    # Check 2: mode of payment accounts on each invoice.
    names = [row["name"] for row in paid_invoices]
    payment_rows = frappe.db.sql(
        """
        SELECT DISTINCT sip.mode_of_payment, sip.account
        FROM `tabSales Invoice Payment` AS sip
        WHERE sip.parenttype = 'POS Invoice'
          AND sip.parent IN %(names)s
          AND sip.amount != 0
        """,
        {"names": tuple(names)},
        as_dict=True,
    )
    bad_mops = []
    for row in payment_rows:
        if not row.account:
            bad_mops.append((row.mode_of_payment, "no account"))
            continue
        account_type = frappe.db.get_value("Account", row.account, "account_type")
        if account_type == "Receivable":
            bad_mops.append(
                (
                    row.mode_of_payment,
                    f"account '{row.account}' is a Receivable account",
                )
            )
    if bad_mops:
        lines = [f"- {mop}: {reason}" for mop, reason in bad_mops]
        frappe.throw(
            _(
                "Cannot close this shift: one or more Modes of Payment "
                "are misconfigured for company '{0}'.\n\n{1}\n\n"
                "Open 'Mode of Payment' in the desk for each listed "
                "mode and set its Default Account to a Bank or Cash "
                "account (not a Receivable account like Debtors). "
                "Save the Mode of Payment, then reload the close dialog."
            ).format(company, "\n".join(lines)),
            title=_("Mode of Payment Account Misconfigured"),
        )


def _wrap_close_error(err, company):
    """Re-throw a consolidation-time error with a hint pointing at
    the most common root causes. Called from the exception handler
    around `closing_doc.submit()` — by the time we get here, the
    pre-flight checks have already passed, so the error is likely
    something pre-flight didn't cover (new ERPNext edge case, data
    corruption, etc.) and the cashier still needs a breadcrumb.
    """
    msg = str(err)
    lower = msg.lower()

    if "customer is required against receivable account" in lower:
        hint = _(
            "Hint: this usually means a Mode of Payment's Default Account "
            "is pointing at a Receivable account instead of a Bank / Cash "
            "account. Check 'Mode of Payment' for company '{0}' in the desk."
        ).format(company)
    elif "debit_to" in lower or "receivable account" in lower:
        hint = _(
            "Hint: check the POS Profile's Write Off / Receivable Account "
            "configuration and the Mode of Payment account mappings for "
            "company '{0}'."
        ).format(company)
    elif "no permission" in lower or "permission" in lower:
        hint = _(
            "Hint: your user role is missing a DocType permission. This "
            "shouldn't happen on a URY role — contact an admin to re-run "
            "'bench migrate' which refreshes the URY permission baseline."
        )
    elif "customer_group" in lower or "territory" in lower:
        hint = _(
            "Hint: one of your Customers has an invalid record (missing "
            "Customer Group or Territory). Open the Customer in the desk "
            "and fill in the missing fields."
        )
    else:
        hint = _(
            "If this keeps happening, check the Error Log in the desk "
            "for the full traceback and fix any misconfigured Mode of "
            "Payment accounts or Customer records referenced there."
        )

    return frappe.ValidationError(f"{msg}\n\n{hint}")


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
    """Get the latest unprinted KOT for the current user's POS Profile.

    Response shapes (depends on which print config is active):

    **New unified config** (POS Profile.custom_print_mode == "QZ Tray"):
        {
            "kot_name": "...",
            "pos_profile": "...",
            "kot_printed": 0,
            "print_jobs": [
                {
                    "printer": "<URY Printer name>",
                    "department": "Drinks",
                    "html": "<html>...</html>",
                },
                ...
            ],
        }

    Each `print_jobs` entry carries its own PRE-RENDERED HTML that
    only contains the items for THAT department. This is how mixed
    KOTs get split — the bar only sees drinks, the kitchen only
    sees food. The frontend iterates `print_jobs` and sends each
    (printer, html) pair to QZ Tray via `printKotWithQz`.

    **Legacy config** (qz_print == 1, new custom_print_mode unset):
        {
            "kot_name": "...",
            "pos_profile": "...",
            "kot_printed": 0,
            "printers": [{"printer": "...", "custom_kot_print_format": "..."}]
        }

    The legacy path returns a list of printers and the frontend prints
    the WHOLE KOT to each — no department splitting.

    **No print mode** (both qz_print == 0 AND custom_print_mode unset / Disabled):
        {"debug": "qz_not_enabled", ...}

    See CLAUDE.md "Fixes log" 2026-04-16 (print revamp Round 1).
    """
    from ury.ury.api.ury_print import (
        resolve_kot_print_plan,
        filter_plan_for_auto_print,
        _get_printed_departments,
    )

    try:
        current_user = frappe.session.user

        # Get user's active POS Profile
        pos_opening = frappe.get_all(
            "POS Opening Entry",
            filters={
                "user": current_user,
                "docstatus": 1,
                "status": "Open",
            },
            fields=["pos_profile"],
            limit=1,
        )

        if not pos_opening:
            return {"debug": "no_pos_opening", "user": current_user}

        pos_profile = pos_opening[0].pos_profile

        # Check whether QZ is enabled via EITHER the new unified
        # config (custom_print_mode == "QZ Tray") OR the legacy
        # qz_print flag. Round 1 introduced the new config but didn't
        # yet migrate the legacy flag, so we honor both.
        profile_row = frappe.db.get_value(
            "POS Profile",
            pos_profile,
            ["qz_print", "custom_print_mode"],
            as_dict=True,
        ) or {}
        legacy_qz = int(profile_row.get("qz_print") or 0) == 1
        new_mode = profile_row.get("custom_print_mode") or ""
        new_qz = new_mode == "QZ Tray"

        if not legacy_qz and not new_qz:
            return {
                "debug": "qz_not_enabled",
                "qz_print": profile_row.get("qz_print"),
                "custom_print_mode": new_mode,
                "pos_profile": pos_profile,
            }

        # Get latest unprinted KOT. The `custom_printed_departments`
        # filter excludes KOTs whose auto-fire pass has already
        # recorded at least one department — that way the poll
        # doesn't repeatedly return the same KOT after the frontend
        # has processed it (if lastCheckedKot state is lost, e.g.
        # after a tab reload, the backend filter still prevents
        # duplicate prints). The pending-KOT flow uses a separate
        # endpoint (print_pending_kots_for_invoice) to fire held
        # departments at bill-print time.
        kot_rows = frappe.get_all(
            "URY KOT",
            filters={
                "pos_profile": pos_profile,
                "kot_printed": 0,
                "custom_printed_departments": ["in", [None, "", "[]"]],
                "docstatus": ["!=", 2],
            },
            fields=["name", "kot_printed", "creation"],
            order_by="creation desc",
            limit=1,
        )

        if not kot_rows:
            return {"debug": "no_unprinted_kots", "pos_profile": pos_profile}

        kot_doc = frappe.get_doc("URY KOT", kot_rows[0].name)

        # KDS routing mode gate. In URY Production Unit mode the
        # plan builder reads the KOT's `production` field and walks
        # that production's `printer_settings` child table instead
        # of the POS Profile's per-department fields. See CLAUDE.md
        # "Fixes log" 2026-04-16 Phase D fix.
        kds_mode = (
            frappe.db.get_value(
                "POS Profile", pos_profile, "custom_kds_routing_mode"
            )
            or "Menu Course"
        )

        # ---- URY Production Unit QZ path ----
        if new_qz and kds_mode == "URY Production Unit":
            production_name = getattr(kot_doc, "production", None)
            if not production_name:
                # No production assigned — fall through to legacy
                # printer_settings scan below so SOMETHING prints.
                return {
                    "debug": "pu_mode_no_production",
                    "pos_profile": pos_profile,
                    "kot_name": kot_doc.name,
                }

            prod_printer_rows = frappe.get_all(
                "URY Printer Settings",
                fields=[
                    "printer",
                    "custom_kot_print_format",
                    "custom_kot_print",
                    "custom_block_takeaway_kot",
                ],
                filters={
                    "parent": production_name,
                    "parenttype": "URY Production Unit",
                    "custom_kot_print": 1,
                },
                order_by="idx",
            )

            if not prod_printer_rows:
                return {
                    "debug": "pu_mode_no_kot_printers",
                    "pos_profile": pos_profile,
                    "kot_name": kot_doc.name,
                    "production": production_name,
                }

            # Takeaway-blocked rows: if the block-takeaway flag is
            # set on a printer row, skip that printer when the order
            # is a takeaway / the table is flagged takeaway.
            is_takeaway = (
                getattr(kot_doc, "table_takeaway", 0) == 1
                or not getattr(kot_doc, "restaurant_table", None)
            )

            print_jobs = []
            for row in prod_printer_rows:
                if (
                    row.custom_block_takeaway_kot
                    and is_takeaway
                ):
                    continue
                if not row.printer:
                    continue
                try:
                    html = frappe.get_print(
                        "URY KOT",
                        kot_doc.name,
                        row.custom_kot_print_format or None,
                        doc=kot_doc,
                        no_letterhead=1,
                    )
                except Exception as e:
                    frappe.log_error(
                        title="URY get_latest_kot PU render failed",
                        message=(
                            f"KOT {kot_doc.name} production={production_name} "
                            f"printer={row.printer} err={e}"
                        ),
                    )
                    continue
                print_jobs.append(
                    {
                        "printer": row.printer,
                        "department": production_name,
                        "html": html,
                    }
                )

            if not print_jobs:
                return {
                    "debug": "pu_mode_no_print_jobs",
                    "pos_profile": pos_profile,
                    "kot_name": kot_doc.name,
                    "production": production_name,
                }

            return {
                "kot_name": kot_doc.name,
                "pos_profile": pos_profile,
                "kot_printed": kot_rows[0].kot_printed,
                "production_unit_mode": 1,
                "print_jobs": print_jobs,
            }

        # ---- New unified config path (Menu Course mode) ----
        if new_qz:
            order_type = None
            if getattr(kot_doc, "invoice", None):
                order_type = frappe.db.get_value(
                    "POS Invoice", kot_doc.invoice, "order_type"
                )

            plan = resolve_kot_print_plan(
                kot_doc,
                pos_profile_name=pos_profile,
                order_type=order_type,
            )

            # Filter out departments that shouldn't auto-print on
            # order submit. Default: Drinks doesn't auto-print (it's
            # held until the cashier prints the bill). Admin can
            # flip `custom_auto_print_drinks_kot` on POS Profile.
            if plan:
                pos_profile_doc = frappe.get_cached_doc(
                    "POS Profile", pos_profile
                )
                plan = filter_plan_for_auto_print(plan, pos_profile_doc)

            # Subtract departments already successfully printed for
            # this KOT so we don't re-fire the same entry on every
            # poll tick. (Without this, the frontend would print
            # Food over and over every 3 seconds until kot_printed=1
            # flips — but kot_printed only flips when ALL depts are
            # covered, so a held Drinks would keep the KOT eligible
            # forever.)
            if plan:
                already_printed = _get_printed_departments(kot_doc)
                if already_printed:
                    plan = [
                        entry
                        for entry in plan
                        if entry["department"] not in already_printed
                    ]

            if plan:
                print_jobs = []
                # Try to pick a reasonable print format. We still read
                # it from the legacy URY Printer Settings child table
                # as a compat shim — a future round will add a
                # first-class custom_kot_print_format field on POS
                # Profile directly.
                kot_print_format = frappe.db.get_value(
                    "URY Printer Settings",
                    {
                        "parent": pos_profile,
                        "parenttype": "POS Profile",
                        "custom_kot_print": 1,
                    },
                    "custom_kot_print_format",
                )

                for entry in plan:
                    printer = entry.get("printer")
                    if not printer:
                        continue

                    # Render a filtered copy of the KOT with ONLY
                    # this department's items. Same pattern as
                    # ury_kot.multi_print_kot's new path. URY KOT's
                    # child table is `kot_items`, NOT `items`.
                    filtered_doc = frappe.copy_doc(kot_doc)
                    filtered_doc.kot_items = entry["items"]
                    filtered_doc.flags.kot_department = entry["department"]

                    try:
                        html = frappe.get_print(
                            "URY KOT",
                            kot_doc.name,
                            kot_print_format,
                            doc=filtered_doc,
                            no_letterhead=1,
                        )
                    except Exception as e:
                        frappe.log_error(
                            title="URY get_latest_kot render failed",
                            message=(
                                f"KOT {kot_doc.name} department={entry['department']} "
                                f"err={e}"
                            ),
                        )
                        continue

                    print_jobs.append(
                        {
                            "printer": printer,
                            "department": entry["department"],
                            "html": html,
                        }
                    )

                if not print_jobs:
                    return {
                        "debug": "no_print_jobs_after_plan",
                        "pos_profile": pos_profile,
                        "kot_name": kot_doc.name,
                    }

                return {
                    "kot_name": kot_doc.name,
                    "pos_profile": pos_profile,
                    "kot_printed": kot_rows[0].kot_printed,
                    "print_jobs": print_jobs,
                }
            # Plan was empty — fall through to legacy so we still
            # print SOMETHING during the migration window.

        # ---- Legacy path ----
        printer_settings = frappe.get_all(
            "URY Printer Settings",
            filters={
                "parent": pos_profile,
                "parentfield": "printer_settings",
                "custom_kot_print": 1,
            },
            fields=["printer", "custom_kot_print_format"],
        )

        if not printer_settings:
            return {
                "debug": "no_printers",
                "pos_profile": pos_profile,
                "kot_name": kot_doc.name,
            }

        return {
            "kot_name": kot_doc.name,
            "pos_profile": pos_profile,
            "kot_printed": kot_rows[0].kot_printed,
            "printers": printer_settings,
        }

    except Exception as e:
        import traceback
        return {
            "debug": "exception",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }

@frappe.whitelist()
def print_pending_kots_for_invoice(invoice):
    """Return pre-rendered print jobs for every un-printed KOT
    department on this invoice.

    Used by the Orders page's Print Invoice button: BEFORE firing the
    bill, the frontend calls this endpoint, gets a flat list of
    ``print_jobs`` (same shape as ``get_latest_kot``), and fires each
    one through QZ Tray. This is how held Drinks KOTs finally make it
    to the bar when the cashier prints the bill — the auto-fire pass
    at order-submit time skipped Drinks per
    ``filter_plan_for_auto_print``, recorded Food as printed in
    ``custom_printed_departments``, and left the KOT with
    ``kot_printed=0``. Calling this endpoint rebuilds the FULL plan
    (no auto-print filter), subtracts departments already stamped as
    printed, and returns the remainder.

    Response shape::

        {
            "invoice": "SAF00042",
            "print_jobs": [
                {
                    "printer": "<URY Printer name>",
                    "department": "Drinks",
                    "html": "<html>...</html>",
                    "kot_name": "KOT-2026-0007",
                },
                ...
            ],
        }

    An empty ``print_jobs`` list is the normal case for invoices whose
    KOTs all fully auto-fired. The caller should still treat that as
    success — just nothing to fire before the bill prints.

    Errors from the plan resolver / render are caught and logged but
    don't abort the whole call — a broken Drinks render shouldn't
    block printing the bill. The endpoint favors "best effort": any
    print job that rendered cleanly goes in the response, the rest
    are dropped with a log entry.

    See CLAUDE.md "Fixes log" 2026-04-16 (KOT print workflow tuning).
    """
    from ury.ury.api.ury_print import (
        resolve_kot_print_plan,
        _get_printed_departments,
    )

    if not invoice:
        return {"invoice": None, "print_jobs": []}

    # Validate the invoice exists and grab the order type for the
    # Takeaway route override in the resolver.
    invoice_row = frappe.db.get_value(
        "POS Invoice",
        invoice,
        ["pos_profile", "order_type"],
        as_dict=True,
    )
    if not invoice_row:
        return {"invoice": invoice, "print_jobs": []}

    pos_profile = invoice_row.pos_profile
    order_type = invoice_row.order_type

    # PU mode short-circuit: the "held Drinks until bill print" flow
    # is a Menu Course concept. In URY Production Unit mode every KOT
    # fires at order time through the production's own printers —
    # there's nothing to "fire again at bill print". Returning empty
    # here is the correct behavior and lets the Print Invoice button
    # skip straight to the bill print.
    kds_mode = (
        frappe.db.get_value(
            "POS Profile", pos_profile, "custom_kds_routing_mode"
        )
        or "Menu Course"
    )
    if kds_mode == "URY Production Unit":
        return {"invoice": invoice, "print_jobs": []}

    # Find every un-fully-printed KOT for this invoice. kot_printed=0
    # catches both "never printed anything" and "partially printed"
    # (some depts in custom_printed_departments, some still held).
    kot_rows = frappe.get_all(
        "URY KOT",
        filters={
            "invoice": invoice,
            "kot_printed": 0,
            "docstatus": ["!=", 2],
        },
        fields=["name"],
        order_by="creation asc",
    )

    if not kot_rows:
        return {"invoice": invoice, "print_jobs": []}

    # The legacy compat shim: read the print format from the old
    # URY Printer Settings child table's first KOT row. See
    # get_latest_kot for the long explanation of why this is OK as
    # a migration shim.
    kot_print_format = frappe.db.get_value(
        "URY Printer Settings",
        {
            "parent": pos_profile,
            "parenttype": "POS Profile",
            "custom_kot_print": 1,
        },
        "custom_kot_print_format",
    )

    print_jobs = []

    for row in kot_rows:
        try:
            kot_doc = frappe.get_doc("URY KOT", row.name)
        except Exception as e:
            frappe.log_error(
                title="URY print_pending_kots load KOT failed",
                message=f"invoice={invoice} kot={row.name} err={e}",
            )
            continue

        plan = resolve_kot_print_plan(
            kot_doc,
            pos_profile_name=pos_profile,
            order_type=order_type,
        )
        if not plan:
            continue

        # Subtract departments already stamped as printed by the
        # auto-fire pass so we only fire the held departments.
        already_printed = _get_printed_departments(kot_doc)
        if already_printed:
            plan = [
                entry
                for entry in plan
                if entry["department"] not in already_printed
            ]
        if not plan:
            continue

        for entry in plan:
            printer = entry.get("printer")
            if not printer:
                continue

            # Filtered in-memory copy — same pattern as
            # multi_print_kot / get_latest_kot. Kot child table is
            # `kot_items`, not `items`.
            filtered_doc = frappe.copy_doc(kot_doc)
            filtered_doc.kot_items = entry["items"]
            filtered_doc.flags.kot_department = entry["department"]

            try:
                html = frappe.get_print(
                    "URY KOT",
                    kot_doc.name,
                    kot_print_format,
                    doc=filtered_doc,
                    no_letterhead=1,
                )
            except Exception as e:
                frappe.log_error(
                    title="URY print_pending_kots render failed",
                    message=(
                        f"invoice={invoice} kot={kot_doc.name} "
                        f"department={entry['department']} err={e}"
                    ),
                )
                continue

            print_jobs.append(
                {
                    "printer": printer,
                    "department": entry["department"],
                    "html": html,
                    "kot_name": kot_doc.name,
                }
            )

    return {"invoice": invoice, "print_jobs": print_jobs}


@frappe.whitelist()
def get_pending_kot_count(terminal=None, posting_date=None):
    """Return the count of draft POS Invoices that still have at
    least one URY KOT with ``kot_printed = 0``.

    Feeds the live badge next to the "Pending KOTs" sidebar entry on
    the Orders page. Scoping follows the same rules as
    ``getPosInvoice``: branch (required), optional terminal, optional
    posting_date. Cashier scoping is deliberately omitted — pending
    KOTs are a kitchen/bar concern, not a per-cashier ledger. A
    captain arriving mid-shift sees every held ticket on the terminal
    regardless of who rang it.

    Response::

        {"count": <int>}

    See CLAUDE.md "Fixes log" 2026-04-16 (print revamp Round 1 /
    Phase B pending-KOT tracker).
    """
    branch = getBranch()
    where_parts = [
        "pi.branch = %s",
        "pi.docstatus = 0",
        "(pi.custom_merged_into IS NULL OR pi.custom_merged_into = '')",
        "(pi.custom_charge_to_room IS NULL OR pi.custom_charge_to_room = 0)",
    ]
    params = [branch]

    if terminal:
        where_parts.append(
            "(pi.custom_terminal = %s OR pi.custom_terminal IS NULL OR pi.custom_terminal = '')"
        )
        params.append(terminal)
    if posting_date:
        where_parts.append("pi.posting_date = %s")
        params.append(posting_date)

    where_parts.append(
        "EXISTS ("
        "  SELECT 1 FROM `tabURY KOT` kot "
        "  WHERE kot.invoice = pi.name "
        "  AND kot.kot_printed = 0 "
        "  AND kot.docstatus != 2"
        ")"
    )

    where_sql = " AND ".join(where_parts)
    sql = f"""
        SELECT COUNT(pi.name) AS cnt
        FROM `tabPOS Invoice` AS pi
        WHERE {where_sql}
    """
    row = frappe.db.sql(sql, tuple(params), as_dict=True)
    count = int(row[0]["cnt"]) if row else 0
    return {"count": count}


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
    """Dashboard stats for a specific date, role-scoped.

    **Cashier:** scoped to their own POS Invoices (``owner = session.user``).
    **Admin / Captain / Manager:** scoped to the whole branch
    (``branch = getBranch()``) — so the Dashboard gives them a bird's-eye
    view of the day instead of just their own rings. An extra
    ``is_admin`` flag + admin-only blocks (order-type breakdown,
    payment-mode breakdown, active cashiers) ride along in the
    response when the caller can see them.

    Response shape (all tiles default to 0 / [] when no data):
        {
            is_admin: 0|1,
            scope: 'user' | 'branch',
            total_sales, total_orders, total_customers,
            average_order_value,
            returns_count, returns_amount,
            top_selling_items: [...],
            # Admin-only:
            order_type_breakdown: [{order_type, count, amount}],
            payment_mode_breakdown: [{mode_of_payment, amount}],
            active_cashiers: [{user, full_name, invoice_count, grand_total}],
        }
    """
    try:
        if not date:
            date = frappe.utils.today()

        user = frappe.session.user
        is_admin = _user_can_see_admin_reports()

        # Scope the base query: admin sees branch-wide, cashier sees
        # their own. Both exclude merged-source invoices (a merge
        # master carries the combined total — counting the sources
        # again would double-count).
        where_parts = [
            "pi.docstatus = 1",
            "pi.posting_date = %s",
            "(pi.custom_merged_into IS NULL OR pi.custom_merged_into = '')",
        ]
        params = [date]
        if is_admin:
            branch = getBranch()
            where_parts.append("pi.branch = %s")
            params.append(branch)
            scope_label = "branch"
        else:
            where_parts.append("pi.owner = %s")
            params.append(user)
            scope_label = "user"
        where_sql = " AND ".join(where_parts)

        # Core totals (excludes returns so the headline number matches
        # "sales" not "net including refunds"; returns get their own
        # tile).
        row = frappe.db.sql(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN pi.is_return = 0 THEN pi.grand_total ELSE 0 END), 0) AS total_sales,
                SUM(CASE WHEN pi.is_return = 0 THEN 1 ELSE 0 END) AS total_orders,
                COUNT(DISTINCT pi.customer) AS total_customers,
                SUM(CASE WHEN pi.is_return = 1 THEN 1 ELSE 0 END) AS returns_count,
                COALESCE(SUM(CASE WHEN pi.is_return = 1 THEN ABS(pi.grand_total) ELSE 0 END), 0) AS returns_amount
            FROM `tabPOS Invoice` AS pi
            WHERE {where_sql}
            """,
            tuple(params),
            as_dict=True,
        )[0]
        total_sales = float(row.total_sales or 0)
        total_orders = int(row.total_orders or 0)
        total_customers = int(row.total_customers or 0)
        returns_count = int(row.returns_count or 0)
        returns_amount = float(row.returns_amount or 0)
        average_order_value = (
            total_sales / total_orders if total_orders > 0 else 0
        )

        # Top selling items — same scope.
        top_selling_items = frappe.db.sql(
            f"""
            SELECT
                ii.item_name,
                SUM(ii.qty) AS quantity,
                SUM(ii.amount) AS total_amount
            FROM `tabPOS Invoice` AS pi
            JOIN `tabPOS Invoice Item` AS ii ON ii.parent = pi.name
            WHERE {where_sql}
              AND pi.is_return = 0
            GROUP BY ii.item_code
            ORDER BY quantity DESC
            LIMIT 5
            """,
            tuple(params),
            as_dict=True,
        )

        response = {
            "is_admin": 1 if is_admin else 0,
            "scope": scope_label,
            "date": date,
            "total_sales": total_sales,
            "total_orders": total_orders,
            "total_customers": total_customers,
            "average_order_value": float(average_order_value),
            "returns_count": returns_count,
            "returns_amount": returns_amount,
            "top_selling_items": top_selling_items,
        }

        # Admin-only blocks below. Cashier's Dashboard stays lean.
        if not is_admin:
            return response

        order_type_breakdown = frappe.db.sql(
            f"""
            SELECT
                COALESCE(pi.order_type, 'Unknown') AS order_type,
                COUNT(pi.name) AS count,
                COALESCE(SUM(pi.grand_total), 0) AS amount
            FROM `tabPOS Invoice` AS pi
            WHERE {where_sql} AND pi.is_return = 0
            GROUP BY pi.order_type
            ORDER BY amount DESC
            """,
            tuple(params),
            as_dict=True,
        )

        payment_mode_breakdown = frappe.db.sql(
            f"""
            SELECT
                p.mode_of_payment,
                COALESCE(SUM(p.base_amount), 0) AS amount
            FROM `tabPOS Invoice` AS pi
            JOIN `tabSales Invoice Payment` AS p ON p.parent = pi.name
            WHERE {where_sql} AND pi.is_return = 0
            GROUP BY p.mode_of_payment
            ORDER BY amount DESC
            """,
            tuple(params),
            as_dict=True,
        )

        active_cashiers = frappe.db.sql(
            f"""
            SELECT
                pi.owner AS user,
                COALESCE(u.full_name, pi.owner) AS full_name,
                COUNT(pi.name) AS invoice_count,
                COALESCE(SUM(pi.grand_total), 0) AS grand_total
            FROM `tabPOS Invoice` AS pi
            LEFT JOIN `tabUser` AS u ON u.name = pi.owner
            WHERE {where_sql} AND pi.is_return = 0
            GROUP BY pi.owner
            ORDER BY grand_total DESC
            """,
            tuple(params),
            as_dict=True,
        )

        response["order_type_breakdown"] = order_type_breakdown
        response["payment_mode_breakdown"] = payment_mode_breakdown
        response["active_cashiers"] = active_cashiers
        return response

    except Exception as e:
        frappe.log_error(f"Error fetching dashboard stats: {str(e)}")
        return {
            "is_admin": 0,
            "scope": "user",
            "date": date or frappe.utils.today(),
            "total_sales": 0,
            "total_orders": 0,
            "total_customers": 0,
            "average_order_value": 0,
            "returns_count": 0,
            "returns_amount": 0,
            "top_selling_items": [],
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


# ============================================================
# Reports endpoints (2026-04-16 — reports batch 1)
# ------------------------------------------------------------
# All of these are scoped by branch via getBranch(). The admin-only
# endpoints re-check the caller's roles server-side via
# _user_can_see_admin_reports — the frontend hides their tabs behind
# canSeeAdminReports(user) but the server is the source of truth.
# ============================================================


def _user_can_see_admin_reports(user=None):
    """Return True when the caller can see the cross-cashier reports
    (Sales by Cashier, Sales by Category, Top/Bottom Items). Cashiers
    can only see their own shift summary.
    """
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    roles = set(frappe.get_roles(user))
    return bool(
        roles & {"System Manager", "URY Manager", "URY Captain"}
    )


def _reports_date_range(from_date, to_date):
    """Normalize a (from, to) date pair. Defaults: today-6d → today."""
    today = frappe.utils.today()
    if not from_date and not to_date:
        from_date = frappe.utils.add_days(today, -6)
        to_date = today
    elif not from_date:
        from_date = to_date
    elif not to_date:
        to_date = from_date
    return from_date, to_date


@frappe.whitelist()
def get_sales_by_cashier(from_date=None, to_date=None, terminal=None):
    """Per-cashier sales breakdown over a date range.

    Admin / captain / manager only. Returns one row per cashier who
    rang at least one invoice in the window — with invoice count,
    grand total, average order value, returns, and discount totals.
    Branch-scoped; optional terminal filter so a captain can audit a
    single till.
    """
    if not _user_can_see_admin_reports():
        frappe.throw(
            _("You don't have permission to see cross-cashier reports."),
            frappe.PermissionError,
        )

    from_date, to_date = _reports_date_range(from_date, to_date)
    branch = getBranch()

    where_parts = [
        "pi.branch = %s",
        "pi.docstatus = 1",
        "pi.posting_date BETWEEN %s AND %s",
        "(pi.custom_merged_into IS NULL OR pi.custom_merged_into = '')",
    ]
    params = [branch, from_date, to_date]
    if terminal:
        where_parts.append(
            "(pi.custom_terminal = %s OR pi.custom_terminal IS NULL OR pi.custom_terminal = '')"
        )
        params.append(terminal)

    sql = f"""
        SELECT
            pi.owner AS user,
            COALESCE(u.full_name, pi.owner) AS full_name,
            COUNT(pi.name) AS invoice_count,
            SUM(CASE WHEN pi.is_return = 0 THEN 1 ELSE 0 END) AS sale_count,
            SUM(CASE WHEN pi.is_return = 1 THEN 1 ELSE 0 END) AS return_count,
            SUM(COALESCE(pi.grand_total, 0)) AS grand_total,
            SUM(COALESCE(pi.net_total, 0)) AS net_total,
            SUM(CASE WHEN pi.is_return = 1 THEN ABS(COALESCE(pi.grand_total, 0)) ELSE 0 END) AS return_amount,
            SUM(COALESCE(pi.discount_amount, 0)) AS discount_amount,
            CASE
                WHEN SUM(CASE WHEN pi.is_return = 0 THEN 1 ELSE 0 END) > 0
                THEN SUM(CASE WHEN pi.is_return = 0 THEN COALESCE(pi.grand_total, 0) ELSE 0 END)
                     / SUM(CASE WHEN pi.is_return = 0 THEN 1 ELSE 0 END)
                ELSE 0
            END AS average_order_value
        FROM `tabPOS Invoice` AS pi
        LEFT JOIN `tabUser` AS u ON u.name = pi.owner
        WHERE {" AND ".join(where_parts)}
        GROUP BY pi.owner
        ORDER BY grand_total DESC
    """
    rows = frappe.db.sql(sql, tuple(params), as_dict=True)

    total_grand = sum(float(r.get("grand_total") or 0) for r in rows)
    total_invoices = sum(int(r.get("invoice_count") or 0) for r in rows)

    return {
        "from_date": from_date,
        "to_date": to_date,
        "branch": branch,
        "terminal": terminal or None,
        "rows": rows,
        "totals": {
            "grand_total": total_grand,
            "invoice_count": total_invoices,
        },
    }


@frappe.whitelist()
def get_sales_by_category(from_date=None, to_date=None, terminal=None):
    """Sales broken down by URY Menu Course department (Food / Drinks
    / Other) over a date range.

    Admin only. Joins POS Invoice Item → URY Menu Item → URY Menu
    Course to classify every line item. Items not on any menu course
    (or menus without a department) fall into 'Food' (the default
    department — matches `_classify_kot_item_department`). The inner
    subquery GROUP BYs by item code so an item appearing on multiple
    menu rows doesn't duplicate in the line-item join.
    """
    if not _user_can_see_admin_reports():
        frappe.throw(
            _("You don't have permission to see cross-cashier reports."),
            frappe.PermissionError,
        )

    from_date, to_date = _reports_date_range(from_date, to_date)
    branch = getBranch()

    where_parts = [
        "pi.branch = %s",
        "pi.docstatus = 1",
        "pi.is_return = 0",
        "pi.posting_date BETWEEN %s AND %s",
        "(pi.custom_merged_into IS NULL OR pi.custom_merged_into = '')",
    ]
    params = [branch, from_date, to_date]
    if terminal:
        where_parts.append(
            "(pi.custom_terminal = %s OR pi.custom_terminal IS NULL OR pi.custom_terminal = '')"
        )
        params.append(terminal)

    sql = f"""
        SELECT
            COALESCE(dept_map.department, 'Food') AS department,
            SUM(COALESCE(pii.amount, 0)) AS total_amount,
            SUM(COALESCE(pii.qty, 0)) AS total_qty,
            COUNT(DISTINCT pi.name) AS invoice_count
        FROM `tabPOS Invoice` AS pi
        INNER JOIN `tabPOS Invoice Item` AS pii ON pii.parent = pi.name
        LEFT JOIN (
            SELECT umi.item AS item_code, MIN(umc.custom_department) AS department
            FROM `tabURY Menu Item` AS umi
            INNER JOIN `tabURY Menu Course` AS umc ON umc.name = umi.course
            WHERE umi.item IS NOT NULL AND umi.item != ''
            GROUP BY umi.item
        ) AS dept_map ON dept_map.item_code = pii.item_code
        WHERE {" AND ".join(where_parts)}
        GROUP BY department
        ORDER BY total_amount DESC
    """
    rows = frappe.db.sql(sql, tuple(params), as_dict=True)

    grand = sum(float(r.get("total_amount") or 0) for r in rows)
    # Stamp the percentage server-side so the UI doesn't have to
    # re-compute on every render.
    for r in rows:
        r["percentage"] = (
            (float(r.get("total_amount") or 0) / grand * 100.0)
            if grand > 0
            else 0.0
        )

    return {
        "from_date": from_date,
        "to_date": to_date,
        "branch": branch,
        "terminal": terminal or None,
        "rows": rows,
        "totals": {"total_amount": grand},
    }


@frappe.whitelist()
def get_top_bottom_items(
    from_date=None, to_date=None, limit=10, terminal=None
):
    """Top N and bottom N menu items by quantity sold over a date
    range. Admin only.

    Returns ``{top: [...], bottom: [...]}``. Both lists ordered by
    total quantity (desc for top, asc for bottom). The bottom list
    excludes items that never sold — it's meant to surface "slow
    movers", not "never-ordered".
    """
    if not _user_can_see_admin_reports():
        frappe.throw(
            _("You don't have permission to see cross-cashier reports."),
            frappe.PermissionError,
        )

    from_date, to_date = _reports_date_range(from_date, to_date)
    branch = getBranch()
    limit = max(1, min(int(limit or 10), 50))

    where_parts = [
        "pi.branch = %s",
        "pi.docstatus = 1",
        "pi.is_return = 0",
        "pi.posting_date BETWEEN %s AND %s",
        "(pi.custom_merged_into IS NULL OR pi.custom_merged_into = '')",
    ]
    params_base = [branch, from_date, to_date]
    if terminal:
        where_parts.append(
            "(pi.custom_terminal = %s OR pi.custom_terminal IS NULL OR pi.custom_terminal = '')"
        )
        params_base.append(terminal)

    base_sql = f"""
        SELECT
            pii.item_code,
            pii.item_name,
            SUM(COALESCE(pii.qty, 0)) AS total_qty,
            SUM(COALESCE(pii.amount, 0)) AS total_amount,
            COUNT(DISTINCT pi.name) AS order_count
        FROM `tabPOS Invoice` AS pi
        INNER JOIN `tabPOS Invoice Item` AS pii ON pii.parent = pi.name
        WHERE {" AND ".join(where_parts)}
        GROUP BY pii.item_code, pii.item_name
        HAVING SUM(COALESCE(pii.qty, 0)) > 0
    """

    top_sql = base_sql + " ORDER BY total_qty DESC LIMIT %s"
    bottom_sql = base_sql + " ORDER BY total_qty ASC LIMIT %s"

    top = frappe.db.sql(top_sql, tuple(params_base + [limit]), as_dict=True)
    bottom = frappe.db.sql(
        bottom_sql, tuple(params_base + [limit]), as_dict=True
    )

    return {
        "from_date": from_date,
        "to_date": to_date,
        "branch": branch,
        "terminal": terminal or None,
        "limit": limit,
        "top": top,
        "bottom": bottom,
    }


@frappe.whitelist()
def get_my_shift_summary(terminal=None):
    """Return a snapshot of the current user's open shift — opening
    entry, paid invoice totals, draft count, per-mode-of-payment
    expected amounts.

    Visible to every role. Re-uses ``preview_pos_closing_entry`` for
    the heavy lifting so the numbers stay consistent with the Close
    Shift dialog.

    Scope: the current session's user + (optionally) the supplied
    terminal. Returns ``{has_open_shift: 0}`` when the user has no
    Open POS Opening Entry matching the filter.
    """
    user = frappe.session.user
    filters = {
        "user": user,
        "docstatus": 1,
        "status": "Open",
    }
    if terminal:
        filters["custom_terminal"] = terminal

    opening_name = frappe.db.get_value(
        "POS Opening Entry",
        filters,
        "name",
        order_by="creation desc",
    )
    if not opening_name:
        return {
            "has_open_shift": 0,
            "user": user,
            "terminal": terminal or None,
        }

    preview = preview_pos_closing_entry(opening_name)
    # Compact the preview into a reports-friendly shape. Drop the
    # transfer_candidates + draft_invoices lists (only useful inside
    # the Close Shift dialog) and stamp has_open_shift=1. The field
    # names here normalise on reports-friendly spellings (paid_count
    # vs invoice_count, total_qty vs total_quantity) so the UI
    # doesn't need to know which endpoint it's consuming.
    return {
        "has_open_shift": 1,
        "user": user,
        "full_name": frappe.db.get_value("User", user, "full_name") or user,
        "opening_entry": preview.get("opening_entry"),
        "period_start_date": preview.get("period_start_date"),
        "period_end_date": preview.get("period_end_date"),
        "pos_profile": preview.get("pos_profile"),
        "paid_count": preview.get("invoice_count"),
        "draft_count": preview.get("draft_count"),
        "grand_total": preview.get("grand_total"),
        "net_total": preview.get("net_total"),
        "total_qty": preview.get("total_quantity"),
        "total_tax": preview.get("total_taxes_and_charges"),
        "draft_grand_total": preview.get("draft_grand_total"),
        "payments": preview.get("payments"),
    }


@frappe.whitelist()
def get_merge_report(from_date=None, to_date=None, terminal=None):
    """Return every order-merge and table-merge log in the date range
    so admin can audit what got merged, by whom, and whether it's
    still active.

    Admin / captain only. Returns ``{order_merges: [...], table_merges: [...]}``
    with one row per merge log. Each row carries master name, source
    count, status, who merged + at what time, and (for Unmerged rows)
    who reversed it + when.
    """
    if not _user_can_see_admin_reports():
        frappe.throw(
            _("You don't have permission to see merge reports."),
            frappe.PermissionError,
        )

    from_date, to_date = _reports_date_range(from_date, to_date)
    branch = getBranch()

    # Order merges — source_invoices child counted via subquery.
    order_where = [
        "ml.branch = %s",
        "DATE(ml.merged_at) BETWEEN %s AND %s",
    ]
    order_params = [branch, from_date, to_date]
    if terminal:
        order_where.append(
            "(ml.custom_terminal = %s OR ml.custom_terminal IS NULL OR ml.custom_terminal = '')"
        )
        order_params.append(terminal)

    order_sql = f"""
        SELECT
            ml.name,
            ml.master_invoice,
            ml.status,
            ml.merged_at,
            ml.merged_by,
            COALESCE(ml.merged_by_full_name, ml.merged_by) AS merged_by_full_name,
            ml.unmerged_at,
            ml.unmerged_by,
            COALESCE(ml.unmerged_by_full_name, ml.unmerged_by) AS unmerged_by_full_name,
            ml.notes,
            (
                SELECT COUNT(s.name)
                FROM `tabURY Order Merge Source` AS s
                WHERE s.parent = ml.name
            ) AS source_count,
            (
                SELECT COALESCE(SUM(COALESCE(s2.original_grand_total, 0)), 0)
                FROM `tabURY Order Merge Source` AS s2
                WHERE s2.parent = ml.name
            ) AS sources_total
        FROM `tabURY Order Merge Log` AS ml
        WHERE {" AND ".join(order_where)}
        ORDER BY ml.merged_at DESC
    """
    order_merges = frappe.db.sql(order_sql, tuple(order_params), as_dict=True)

    # Table merges — source_tables child counted via subquery.
    table_where = [
        "ml.branch = %s",
        "DATE(ml.merged_at) BETWEEN %s AND %s",
    ]
    table_params = [branch, from_date, to_date]
    if terminal:
        table_where.append(
            "(ml.custom_terminal = %s OR ml.custom_terminal IS NULL OR ml.custom_terminal = '')"
        )
        table_params.append(terminal)

    table_sql = f"""
        SELECT
            ml.name,
            ml.master_table,
            ml.status,
            ml.merged_at,
            ml.merged_by,
            COALESCE(ml.merged_by_full_name, ml.merged_by) AS merged_by_full_name,
            ml.unmerged_at,
            ml.unmerged_by,
            COALESCE(ml.unmerged_by_full_name, ml.unmerged_by) AS unmerged_by_full_name,
            ml.merged_orders,
            ml.notes,
            (
                SELECT COUNT(s.name)
                FROM `tabURY Table Merge Source` AS s
                WHERE s.parent = ml.name
            ) AS source_count
        FROM `tabURY Table Merge Log` AS ml
        WHERE {" AND ".join(table_where)}
        ORDER BY ml.merged_at DESC
    """
    table_merges = frappe.db.sql(table_sql, tuple(table_params), as_dict=True)

    # Summary tiles for the page header.
    active_order_merges = sum(
        1 for r in order_merges if r.get("status") == "Active"
    )
    active_table_merges = sum(
        1 for r in table_merges if r.get("status") == "Active"
    )

    return {
        "from_date": from_date,
        "to_date": to_date,
        "branch": branch,
        "terminal": terminal or None,
        "order_merges": order_merges,
        "table_merges": table_merges,
        "summary": {
            "order_merge_count": len(order_merges),
            "order_merge_active": active_order_merges,
            "table_merge_count": len(table_merges),
            "table_merge_active": active_table_merges,
        },
    }


@frappe.whitelist()
def get_transfer_report(from_date=None, to_date=None, terminal=None):
    """Return every POS Invoice that was transferred to another
    cashier at shift-close time, in the given date range.

    Admin / captain only. Detection relies on the ``remarks`` field
    that ``submit_pos_closing_entry`` stamps in the format
    ``Transferred from <user> on shift close (<opening_entry>)``.
    Each row surfaces the original cashier (parsed from the remarks),
    the new cashier (current ``owner``), the opening entry the
    transfer happened at, the invoice state, and the grand total so
    admin can audit "who dumped what onto whom".
    """
    if not _user_can_see_admin_reports():
        frappe.throw(
            _("You don't have permission to see transfer reports."),
            frappe.PermissionError,
        )

    from_date, to_date = _reports_date_range(from_date, to_date)
    branch = getBranch()

    where_parts = [
        "pi.branch = %s",
        "pi.remarks LIKE 'Transferred from %%'",
        "pi.modified BETWEEN %s AND %s",
    ]
    params = [branch, f"{from_date} 00:00:00", f"{to_date} 23:59:59"]
    if terminal:
        where_parts.append(
            "(pi.custom_terminal = %s OR pi.custom_terminal IS NULL OR pi.custom_terminal = '')"
        )
        params.append(terminal)

    rows = frappe.db.sql(
        f"""
        SELECT
            pi.name,
            pi.owner AS new_cashier,
            COALESCE(u.full_name, pi.owner) AS new_cashier_full_name,
            pi.remarks,
            pi.modified AS transfer_time,
            pi.status,
            pi.docstatus,
            pi.grand_total,
            pi.customer,
            pi.customer_name,
            pi.restaurant_table,
            pi.posting_date,
            pi.custom_terminal
        FROM `tabPOS Invoice` AS pi
        LEFT JOIN `tabUser` AS u ON u.name = pi.owner
        WHERE {" AND ".join(where_parts)}
        ORDER BY pi.modified DESC
        """,
        tuple(params),
        as_dict=True,
    )

    # Parse "Transferred from <user> on shift close (<opening_entry>)"
    # to surface the original cashier and the opening entry for
    # display. Defensive: malformed remarks degrade to None rather
    # than blow up the report.
    import re

    pattern = re.compile(
        r"^Transferred from (\S+) on shift close \((.+)\)\s*$"
    )
    user_cache = {}

    def _full_name(u):
        if not u:
            return None
        if u in user_cache:
            return user_cache[u]
        name = frappe.db.get_value("User", u, "full_name") or u
        user_cache[u] = name
        return name

    for row in rows:
        remarks = row.get("remarks") or ""
        m = pattern.match(remarks)
        if m:
            old_user = m.group(1)
            opening_entry = m.group(2)
            row["from_cashier"] = old_user
            row["from_cashier_full_name"] = _full_name(old_user)
            row["opening_entry"] = opening_entry
        else:
            row["from_cashier"] = None
            row["from_cashier_full_name"] = None
            row["opening_entry"] = None
        # Swallow the noisy remarks field now that we've parsed it.
        del row["remarks"]

    # Summary: distinct from/to pair count and total amount moved.
    total_amount = sum(
        float(r.get("grand_total") or 0) for r in rows
    )
    pairs = {
        (r.get("from_cashier") or "?", r.get("new_cashier") or "?")
        for r in rows
    }

    return {
        "from_date": from_date,
        "to_date": to_date,
        "branch": branch,
        "terminal": terminal or None,
        "rows": rows,
        "summary": {
            "count": len(rows),
            "total_amount": total_amount,
            "distinct_pairs": len(pairs),
        },
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


# ───────────────────────────────────────────────────────────────────
# POS Invoice merge / unmerge
# ───────────────────────────────────────────────────────────────────


def _serialise_invoice_items(invoice_doc) -> str:
    """JSON snapshot of an invoice's `items` child table. Used by the
    merge log so unmerge can restore master/source state losslessly.
    Stores enough fields to recreate the row, not the full ORM object.
    """
    rows = []
    for item in invoice_doc.items or []:
        rows.append(
            {
                "item_code": item.item_code,
                "item_name": item.item_name,
                "qty": float(item.qty or 0),
                "rate": float(item.rate or 0),
                "amount": float(item.amount or 0),
                "price_list_rate": float(item.price_list_rate or 0),
                "base_price_list_rate": float(item.base_price_list_rate or 0),
                "warehouse": item.warehouse,
                "cost_center": item.cost_center,
                "income_account": item.income_account,
                "expense_account": item.expense_account,
                "uom": item.uom,
                "stock_uom": item.stock_uom,
                "conversion_factor": float(item.conversion_factor or 1),
                "comment": getattr(item, "comment", None),
                "custom_course": getattr(item, "custom_course", None),
            }
        )
    return json.dumps(rows)


def _serialise_invoice_payments(invoice_doc) -> str:
    rows = []
    for payment in invoice_doc.payments or []:
        rows.append(
            {
                "mode_of_payment": payment.mode_of_payment,
                "amount": float(payment.amount or 0),
                "account": payment.account,
                "type": payment.type,
            }
        )
    return json.dumps(rows)


def _restore_invoice_items(invoice_doc, items_json: str) -> None:
    """Replace an invoice's `items` child table with the rows from a
    snapshot. Caller is responsible for save() afterwards.
    """
    if not items_json:
        invoice_doc.items = []
        return
    try:
        rows = json.loads(items_json)
    except Exception:
        rows = []
    invoice_doc.items = []
    for row in rows:
        # Filter the snapshot dict down to fields that exist on POS
        # Invoice Item to avoid Frappe complaining about unknown keys.
        invoice_doc.append("items", row)


def _user_can_merge_orders(pos_profile_name: str | None) -> tuple[bool, bool]:
    """Return (can_merge, requesting_user_is_captain).

    `can_merge` is True if the requesting user is allowed to merge at
    all on this profile. The captain-only restriction is per-profile
    via `custom_restrict_merge_to_captain`. URY Cashier can merge own
    orders unless the restriction is on. URY Captain / URY Manager /
    Administrator can always merge.
    """
    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    captain_roles = {"Administrator", "System Manager", "URY Manager", "URY Captain"}
    is_captain = user == "Administrator" or bool(roles & captain_roles)

    restrict = 0
    if pos_profile_name:
        restrict = (
            frappe.db.get_value(
                "POS Profile", pos_profile_name, "custom_restrict_merge_to_captain"
            )
            or 0
        )

    if is_captain:
        return True, True
    if restrict:
        # Only captains can merge on this profile and the requester isn't one.
        return False, False
    if "URY Cashier" in roles:
        return True, False
    return False, False


@frappe.whitelist()
def merge_pos_invoices(invoices, notes=None):
    """Merge a list of POS Invoices into a single master.

    The first invoice in ``invoices`` becomes the master. The rest are
    flagged via ``custom_merged_into`` (hidden from the Orders page
    list) and their items are appended to the master. A
    ``URY Order Merge Log`` doctype is created with snapshots that let
    `unmerge_pos_invoices` reverse the operation cleanly.

    Validation:
    - All invoices must exist, all on the same branch + same terminal,
      all docstatus 0, status Draft, none already merged.
    - Caller must satisfy `_user_can_merge_orders` for the master's
      POS Profile (handles the captain-only restriction).
    - Cashiers can only merge their OWN orders. Captains can merge
      any cashier's orders on the same terminal.

    See CLAUDE.md "Fixes log" 2026-04-09 (merge orders feature).
    """
    if isinstance(invoices, str):
        try:
            invoices = json.loads(invoices)
        except Exception:
            invoices = [invoices]
    if not isinstance(invoices, list) or len(invoices) < 2:
        frappe.throw(
            _("Select at least two orders to merge."),
            title=_("Not Enough Orders"),
        )

    # Deduplicate while preserving order — first occurrence becomes the master.
    seen = []
    for name in invoices:
        if name not in seen:
            seen.append(name)
    invoices = seen
    if len(invoices) < 2:
        frappe.throw(
            _("Select at least two distinct orders to merge."),
            title=_("Not Enough Orders"),
        )

    master_name = invoices[0]
    source_names = invoices[1:]

    if not frappe.db.exists("POS Invoice", master_name):
        frappe.throw(
            _("Master invoice '{0}' not found.").format(master_name),
            frappe.DoesNotExistError,
        )
    master = frappe.get_doc("POS Invoice", master_name)

    can_merge, is_captain = _user_can_merge_orders(master.pos_profile)
    if not can_merge:
        frappe.throw(
            _(
                "You are not allowed to merge orders on this POS Profile. "
                "The 'Restrict Merge Orders to Captain' setting is enabled — "
                "ask a captain or manager."
            ),
            title=_("Merge Not Allowed"),
            exc=frappe.PermissionError,
        )

    requesting_user = frappe.session.user

    # Validate the master itself before touching anything.
    if master.docstatus != 0 or master.status != "Draft":
        frappe.throw(
            _("Master invoice '{0}' is not a draft order. Only unpaid drafts can be merged.").format(master_name),
            title=_("Cannot Merge"),
        )
    if master.get("custom_merged_into"):
        frappe.throw(
            _("Master invoice '{0}' is already merged into '{1}'. Pick a different master.").format(master_name, master.get("custom_merged_into")),
            title=_("Cannot Merge"),
        )
    if not is_captain and master.owner != requesting_user:
        frappe.throw(
            _("You can only merge your own orders.").format(),
            title=_("Merge Not Allowed"),
            exc=frappe.PermissionError,
        )

    master_terminal = master.get("custom_terminal")
    master_branch = master.branch
    if not master_branch:
        master_branch = frappe.db.get_value(
            "POS Profile", master.pos_profile, "branch"
        )

    # Validate every source.
    source_docs = []
    for src_name in source_names:
        if not frappe.db.exists("POS Invoice", src_name):
            frappe.throw(
                _("Source invoice '{0}' not found.").format(src_name),
                frappe.DoesNotExistError,
            )
        src = frappe.get_doc("POS Invoice", src_name)
        if src.docstatus != 0 or src.status != "Draft":
            frappe.throw(
                _("Order '{0}' is not a draft. Only unpaid drafts can be merged.").format(src_name),
                title=_("Cannot Merge"),
            )
        if src.get("custom_merged_into"):
            frappe.throw(
                _("Order '{0}' has already been merged into '{1}'.").format(src_name, src.get("custom_merged_into")),
                title=_("Cannot Merge"),
            )
        src_branch = src.branch or frappe.db.get_value(
            "POS Profile", src.pos_profile, "branch"
        )
        if src_branch != master_branch:
            frappe.throw(
                _("Order '{0}' is on a different branch ({1}) than the master ({2}). Only same-branch merges are allowed.").format(src_name, src_branch, master_branch),
                title=_("Cannot Merge"),
            )
        if (src.get("custom_terminal") or None) != (master_terminal or None):
            frappe.throw(
                _("Order '{0}' is on a different terminal ({1}) than the master ({2}). Only same-terminal merges are allowed.").format(src_name, src.get("custom_terminal") or "(none)", master_terminal or "(none)"),
                title=_("Cannot Merge"),
            )
        if not is_captain and src.owner != requesting_user:
            frappe.throw(
                _("You can only merge your own orders. Order '{0}' was rung by another cashier.").format(src_name),
                title=_("Merge Not Allowed"),
                exc=frappe.PermissionError,
            )
        source_docs.append(src)

    # Snapshot the master's pre-merge state for the unmerge path.
    master_pre_merge_items_json = _serialise_invoice_items(master)

    # Build the merge log first (in memory) so we have all the source
    # snapshots collected before we touch any docs.
    log = frappe.new_doc("URY Order Merge Log")
    log.master_invoice = master.name
    log.status = "Active"
    log.branch = master_branch
    log.custom_terminal = master_terminal
    log.merged_at = frappe.utils.now_datetime()
    log.merged_by = requesting_user
    log.merged_by_full_name = (
        frappe.db.get_value("User", requesting_user, "full_name") or ""
    )
    log.notes = notes
    log.master_pre_merge_items_json = master_pre_merge_items_json

    # For each source: snapshot, append items to master, free table,
    # and stamp custom_merged_into.
    for src in source_docs:
        log.append(
            "source_invoices",
            {
                "source_invoice": src.name,
                "original_status": src.status,
                "original_grand_total": float(src.grand_total or 0),
                "original_customer": src.customer,
                "original_customer_name": src.customer_name,
                "original_restaurant_table": src.restaurant_table,
                "original_items_json": _serialise_invoice_items(src),
                "original_payments_json": _serialise_invoice_payments(src),
            },
        )

        # Append source items to master. ERPNext will recompute totals
        # on save based on the new combined item list.
        for item in src.items or []:
            master.append(
                "items",
                {
                    "item_code": item.item_code,
                    "item_name": item.item_name,
                    "qty": item.qty,
                    "rate": item.rate,
                    "price_list_rate": item.price_list_rate,
                    "base_price_list_rate": item.base_price_list_rate,
                    "warehouse": item.warehouse,
                    "cost_center": item.cost_center,
                    "income_account": item.income_account,
                    "expense_account": item.expense_account,
                    "uom": item.uom,
                    "stock_uom": item.stock_uom,
                    "conversion_factor": item.conversion_factor,
                    "comment": getattr(item, "comment", None),
                    "custom_course": getattr(item, "custom_course", None),
                },
            )

        # Free the source's table (if any) — the master keeps its own.
        if src.restaurant_table:
            try:
                frappe.db.set_value(
                    "URY Table",
                    src.restaurant_table,
                    {"occupied": 0, "latest_invoice_time": None},
                )
            except Exception:
                pass

        # Flag the source as merged into the master.
        src.custom_merged_into = master.name
        src.flags.ignore_validate_update_after_submit = True
        src.save(ignore_permissions=True)

    # Save the master AFTER its items list is fully composed so the
    # totals get recalculated once.
    master.save(ignore_permissions=True)

    # Persist the log.
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    return {
        "merge_log": log.name,
        "master_invoice": master.name,
        "merged_count": len(source_docs),
    }


@frappe.whitelist()
def unmerge_pos_invoices(merge_log):
    """Reverse a previous merge. Restores the master's pre-merge items
    and clears `custom_merged_into` on each source. Re-occupies any
    tables the sources had freed.

    Constraints:
    - The merge log must be in 'Active' status (not already unmerged).
    - The master invoice must still be unpaid (docstatus 0, status
      Draft). Once the master has been paid, the merge is locked in.
    - Caller must be allowed to merge on this POS Profile (same role
      check as `merge_pos_invoices`).

    See CLAUDE.md "Fixes log" 2026-04-09 (merge orders feature).
    """
    if not merge_log:
        frappe.throw(
            _("Merge log name is required."),
            title=_("Missing Argument"),
        )

    if not frappe.db.exists("URY Order Merge Log", merge_log):
        frappe.throw(
            _("Merge log '{0}' not found.").format(merge_log),
            frappe.DoesNotExistError,
        )

    log = frappe.get_doc("URY Order Merge Log", merge_log)
    if log.status != "Active":
        frappe.throw(
            _("Merge log '{0}' is already unmerged.").format(merge_log),
            title=_("Already Unmerged"),
        )

    if not frappe.db.exists("POS Invoice", log.master_invoice):
        frappe.throw(
            _("Master invoice '{0}' no longer exists.").format(log.master_invoice),
            frappe.DoesNotExistError,
        )

    master = frappe.get_doc("POS Invoice", log.master_invoice)
    if master.docstatus != 0 or master.status != "Draft":
        frappe.throw(
            _("Master invoice '{0}' is no longer a draft. Once an order is paid, the merge can't be reversed.").format(log.master_invoice),
            title=_("Cannot Unmerge"),
        )

    can_merge, is_captain = _user_can_merge_orders(master.pos_profile)
    if not can_merge:
        frappe.throw(
            _("You are not allowed to unmerge orders on this POS Profile."),
            title=_("Unmerge Not Allowed"),
            exc=frappe.PermissionError,
        )

    requesting_user = frappe.session.user
    if not is_captain and master.owner != requesting_user:
        frappe.throw(
            _("You can only unmerge your own orders."),
            title=_("Unmerge Not Allowed"),
            exc=frappe.PermissionError,
        )

    # Restore the master's items from the snapshot.
    _restore_invoice_items(master, log.master_pre_merge_items_json)
    master.save(ignore_permissions=True)

    # Restore each source.
    for src_row in log.source_invoices or []:
        src_name = src_row.source_invoice
        if not frappe.db.exists("POS Invoice", src_name):
            # Source was deleted somehow — skip but keep going.
            continue
        src = frappe.get_doc("POS Invoice", src_name)
        src.custom_merged_into = None
        # Re-occupy the source's table if it had one.
        if src_row.original_restaurant_table:
            try:
                frappe.db.set_value(
                    "URY Table",
                    src_row.original_restaurant_table,
                    {"occupied": 1, "latest_invoice_time": src.creation},
                )
            except Exception:
                pass
        src.flags.ignore_validate_update_after_submit = True
        src.save(ignore_permissions=True)

    log.status = "Unmerged"
    log.unmerged_at = frappe.utils.now_datetime()
    log.unmerged_by = requesting_user
    log.unmerged_by_full_name = (
        frappe.db.get_value("User", requesting_user, "full_name") or ""
    )
    log.flags.ignore_permissions = True
    log.save()
    frappe.db.commit()

    return {
        "merge_log": log.name,
        "master_invoice": master.name,
        "unmerged_count": len(log.source_invoices or []),
    }


@frappe.whitelist()
def get_active_merge_log_for_invoice(invoice):
    """Return the most recent Active merge log where the given invoice
    is the master, or None. Used by the right panel of the React POS
    Orders page to decide whether to show the Unmerge button.
    """
    if not invoice:
        return None
    rows = frappe.get_all(
        "URY Order Merge Log",
        filters={"master_invoice": invoice, "status": "Active"},
        fields=["name", "merged_at", "merged_by", "merged_by_full_name"],
        order_by="merged_at desc",
        limit=1,
    )
    if not rows:
        return None
    log_name = rows[0].name
    log = frappe.get_doc("URY Order Merge Log", log_name)
    return {
        "name": log.name,
        "merged_at": str(log.merged_at) if log.merged_at else None,
        "merged_by": log.merged_by,
        "merged_by_full_name": log.merged_by_full_name,
        "source_count": len(log.source_invoices or []),
        "source_invoices": [
            row.source_invoice for row in (log.source_invoices or [])
        ],
    }


# ---------------------------------------------------------------------
# Return Orders (paid-invoice refund + reversal)
# ---------------------------------------------------------------------


def _get_returned_qty_per_row(source_invoice_name):
    """Return `{source_row_name: total_returned_qty}` for a POS Invoice.

    Sums the (positive) quantities of every POS Invoice Item row that
    points back at this source via `pos_invoice_item`, across every
    active (docstatus=1) return invoice that has `return_against =
    <source>`. Cancelled returns (docstatus=2) are excluded so a
    reversed return restores the capacity to return again.
    """
    if not source_invoice_name:
        return {}
    rows = frappe.db.sql(
        """
        SELECT ri.pos_invoice_item, SUM(ABS(ri.qty)) AS returned_qty
        FROM `tabPOS Invoice Item` ri
        INNER JOIN `tabPOS Invoice` r ON r.name = ri.parent
        WHERE r.return_against = %s
          AND r.is_return = 1
          AND r.docstatus = 1
          AND ri.pos_invoice_item IS NOT NULL
        GROUP BY ri.pos_invoice_item
        """,
        (source_invoice_name,),
        as_dict=True,
    )
    return {row.pos_invoice_item: float(row.returned_qty or 0) for row in rows}


def _user_can_return_orders(pos_profile_name):
    """Return (can_return, is_captain).

    Captains/Managers/Admin can always return. Cashiers can return
    only when the profile's `custom_restrict_returns_to_captain` is 0.
    Default is 1 (captain-only) — returns are sensitive (refunds +
    stock reversal), so the gate is conservative out of the box.
    """
    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    captain_roles = {"Administrator", "System Manager", "URY Manager", "URY Captain"}
    is_captain = user == "Administrator" or bool(roles & captain_roles)

    # Default ON when the field isn't set (fresh install hasn't migrated
    # yet). The conservative default matches the field's default.
    restrict = 1
    if pos_profile_name:
        raw = frappe.db.get_value(
            "POS Profile", pos_profile_name, "custom_restrict_returns_to_captain"
        )
        if raw is not None:
            restrict = int(raw or 0)

    if is_captain:
        return True, True
    if restrict:
        return False, False
    if "URY Cashier" in roles:
        return True, False
    return False, False


@frappe.whitelist()
def get_return_preview(invoice):
    """Return an item list suitable for the ReturnDialog.

    Reads the original POS Invoice and returns each item row with the
    fields the frontend needs to render a qty stepper: item_code,
    item_name, qty (original), rate, amount, uom, warehouse, and the
    POS Invoice Item row `name` so we can correlate picks back to the
    source row on submit. Also returns the original's payment modes
    so the cashier can see how the customer originally paid.
    """
    if not frappe.db.exists("POS Invoice", invoice):
        frappe.throw(_("Invoice {0} not found.").format(invoice))

    doc = frappe.get_doc("POS Invoice", invoice)

    can_return, _is_captain = _user_can_return_orders(doc.pos_profile)
    if not can_return:
        frappe.throw(
            _("You don't have permission to issue returns on this terminal."),
            title=_("Return Not Allowed"),
        )

    if doc.is_return:
        frappe.throw(
            _("This invoice is already a return document."),
            title=_("Cannot Return a Return"),
        )
    if doc.docstatus != 1:
        frappe.throw(
            _("Only submitted (paid) invoices can be returned."),
            title=_("Invoice Not Submitted"),
        )
    if doc.status not in ("Paid", "Consolidated"):
        frappe.throw(
            _("Only paid orders can be returned. Current status: {0}").format(doc.status),
            title=_("Invalid Status for Return"),
        )

    # How much of each row has already been returned across previously-
    # submitted return invoices. Used to bound the qty picker so the
    # cashier can't return more than what's physically left on the row.
    returned_map = _get_returned_qty_per_row(doc.name)

    items = []
    for row in doc.items:
        original_qty = float(row.qty or 0)
        already_returned = returned_map.get(row.name, 0.0)
        qty_remaining = max(0.0, original_qty - already_returned)
        items.append(
            {
                "row_name": row.name,
                "item_code": row.item_code,
                "item_name": row.item_name,
                "qty": original_qty,
                "qty_already_returned": already_returned,
                "qty_remaining": qty_remaining,
                "rate": float(row.rate or 0),
                "amount": float(row.amount or 0),
                "uom": row.uom,
                "warehouse": row.warehouse,
            }
        )

    payments = [
        {
            "mode_of_payment": p.mode_of_payment,
            "amount": float(p.amount or 0),
        }
        for p in (doc.payments or [])
    ]

    fully_returned = all(item["qty_remaining"] <= 0 for item in items) if items else False

    return {
        "invoice": doc.name,
        "customer": doc.customer,
        "customer_name": doc.customer_name,
        "grand_total": float(doc.grand_total or 0),
        "currency": doc.currency,
        "items": items,
        "payments": payments,
        "fully_returned": 1 if fully_returned else 0,
    }


@frappe.whitelist()
def create_pos_return(invoice, items, refund_mode, notes=None):
    """Create and submit a return POS Invoice against the original.

    Args:
        invoice: the original POS Invoice name being returned.
        items: JSON list of ``{row_name, qty}`` entries where ``qty`` is
            the POSITIVE quantity the cashier wants to refund. Items
            with qty=0 are skipped; the return doc only contains the
            rows the cashier actually picked.
        refund_mode: the Mode of Payment to use for the refund. Single
            mode per return keeps the accounting simple and matches how
            a real cash drawer works (you refund in one way).
        notes: optional free-text remarks on the return.

    Uses ERPNext's `make_return_doc` helper as the base so all the
    accounting gymnastics (negative taxes, negative stock moves,
    GL entries) work automatically. We only override:
    - the items (to match the cashier's selection)
    - the payments (to use the single chosen refund mode)
    """
    from erpnext.controllers.sales_and_purchase_return import make_return_doc

    if isinstance(items, str):
        items = json.loads(items)
    if not items:
        frappe.throw(_("No items selected to return."))

    if not refund_mode:
        frappe.throw(_("Select a refund mode of payment."))

    source_doc = frappe.get_doc("POS Invoice", invoice)

    can_return, _is_captain = _user_can_return_orders(source_doc.pos_profile)
    if not can_return:
        frappe.throw(
            _("You don't have permission to issue returns on this terminal."),
            title=_("Return Not Allowed"),
        )

    if source_doc.is_return:
        frappe.throw(
            _("Cannot return a return document."),
            title=_("Cannot Return a Return"),
        )
    if source_doc.docstatus != 1:
        frappe.throw(
            _("Only submitted (paid) invoices can be returned."),
            title=_("Invoice Not Submitted"),
        )

    # Map POS Invoice Item row name -> qty to return (positive).
    pick_by_row = {}
    for entry in items:
        row_name = entry.get("row_name")
        qty = float(entry.get("qty") or 0)
        if row_name and qty > 0:
            pick_by_row[row_name] = qty

    if not pick_by_row:
        frappe.throw(_("No items selected to return."))

    # Validate: can't return more than `original_qty - already_returned`
    # per row, and each picked row must actually exist on the source.
    # The already-returned subtraction is what blocks "return the same
    # item twice" — the failure mode that shipped in the first round.
    source_rows = {row.name: row for row in source_doc.items}
    returned_map = _get_returned_qty_per_row(invoice)
    for row_name, qty in pick_by_row.items():
        if row_name not in source_rows:
            frappe.throw(
                _("Row {0} is not part of invoice {1}.").format(row_name, invoice)
            )
        original_qty = float(source_rows[row_name].qty or 0)
        already_returned = returned_map.get(row_name, 0.0)
        remaining = original_qty - already_returned
        if qty > remaining + 1e-6:  # tiny float tolerance
            frappe.throw(
                _(
                    "Cannot return {0} of {1} — only {2} left after previous returns (original {3}, already returned {4})."
                ).format(
                    qty,
                    source_rows[row_name].item_name,
                    remaining,
                    original_qty,
                    already_returned,
                )
            )

    # Validate refund_mode is a real Mode of Payment.
    if not frappe.db.exists("Mode of Payment", refund_mode):
        frappe.throw(_("Unknown Mode of Payment: {0}").format(refund_mode))

    # Build the return doc using ERPNext's helper.
    return_doc = make_return_doc("POS Invoice", invoice)

    # Filter the return_doc's items down to just the rows the cashier
    # picked, adjusting qty to match. The helper gives us a full copy
    # of the original rows with negative qtys; we replace that.
    filtered_items = []
    for item in return_doc.items:
        # `make_return_doc` populates each item with source_row info.
        # Find the matching source row by item_code + rate as a fallback
        # because the row name itself is regenerated on the new doc.
        # ERPNext sets `pos_invoice_item` on each return item pointing
        # back at the source row name.
        source_row_name = getattr(item, "pos_invoice_item", None)
        if source_row_name and source_row_name in pick_by_row:
            pick_qty = pick_by_row[source_row_name]
            item.qty = -pick_qty
            # stock_qty mirrors qty when uom_conversion_factor is 1.
            if hasattr(item, "stock_qty"):
                item.stock_qty = -pick_qty
            filtered_items.append(item)

    if not filtered_items:
        frappe.throw(
            _("Couldn't map any selected items to the source invoice. "
              "Try refreshing the Orders page."),
        )
    return_doc.items = filtered_items

    # Replace the auto-generated payments with one row for the
    # chosen refund mode. `make_return_doc` already flipped the signs
    # of the original payments; we toss them and use the total of the
    # filtered items as the refund amount.
    return_doc.payments = []
    return_doc.append(
        "payments",
        {
            "mode_of_payment": refund_mode,
            "amount": 0,  # populated below after totals recompute
        },
    )

    if notes:
        existing = return_doc.get("remarks") or ""
        return_doc.remarks = (existing + "\n" if existing else "") + str(notes)

    # Compute totals so we know how much to refund, then update the
    # payment row with the grand_total (which is negative because qtys
    # are negative).
    return_doc.run_method("calculate_taxes_and_totals")

    refund_amount = float(return_doc.grand_total or 0)
    if return_doc.payments:
        return_doc.payments[0].amount = refund_amount
    return_doc.paid_amount = refund_amount

    return_doc.insert(ignore_permissions=False)
    return_doc.submit()

    return {
        "return_invoice": return_doc.name,
        "original_invoice": invoice,
        "refund_amount": refund_amount,
    }


# ---------------------------------------------------------------------
# Geofence (per-POS Profile location gate for login)
# ---------------------------------------------------------------------


def _haversine_meters(lat1, lon1, lat2, lon2):
    """Great-circle distance between two WGS-84 points, in meters."""
    import math

    R = 6371000.0  # Earth mean radius in meters
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))
    return R * c


def _resolve_user_geofence(pos_profile_name):
    """Figure out which coordinates + radius to check the current user
    against for this POS Profile.

    Returns `(target_lat, target_lon, radius_meters, source_label)`
    or None when the feature is off / not configured.

    Resolution order:
      1. The POS Profile's `custom_geofence_enabled` must be 1.
      2. Find a URY User row for this session's user on the profile's
         Branch (ExPOS Users table). If the row has
         `custom_use_company_location = 0` AND explicit lat/lon, use
         those (with an optional per-user radius override).
      3. Otherwise fall back to the POS Profile's company coordinates.

    If the POS Profile has geofencing enabled but no company coords
    set (and the user doesn't have per-user coords either), the
    function returns None and the endpoint treats the check as "not
    configured" — which means no block. The admin should either
    configure the coords or disable the feature.
    """
    if not pos_profile_name:
        return None

    profile = frappe.db.get_value(
        "POS Profile",
        pos_profile_name,
        [
            "custom_geofence_enabled",
            "custom_company_latitude",
            "custom_company_longitude",
            "custom_geofence_radius_meters",
            "branch",
        ],
        as_dict=True,
    )
    if not profile or not int(profile.get("custom_geofence_enabled") or 0):
        return None

    default_radius = int(profile.get("custom_geofence_radius_meters") or 0) or 200

    branch_name = profile.get("branch")
    user = frappe.session.user

    # Per-user row lookup on the branch's ExPOS Users child table.
    if branch_name:
        rows = frappe.db.sql(
            """
            SELECT
                custom_use_company_location,
                custom_latitude,
                custom_longitude,
                custom_geofence_radius_meters
            FROM `tabURY User`
            WHERE parenttype = 'Branch' AND parent = %s AND user = %s
            LIMIT 1
            """,
            (branch_name, user),
            as_dict=True,
        )
        if rows:
            row = rows[0]
            use_company = int(row.get("custom_use_company_location") or 0)
            if not use_company:
                per_lat = row.get("custom_latitude")
                per_lon = row.get("custom_longitude")
                if per_lat and per_lon:
                    per_radius = int(row.get("custom_geofence_radius_meters") or 0)
                    return (
                        float(per_lat),
                        float(per_lon),
                        per_radius or default_radius,
                        "user",
                    )

    company_lat = profile.get("custom_company_latitude")
    company_lon = profile.get("custom_company_longitude")
    if company_lat and company_lon:
        return (
            float(company_lat),
            float(company_lon),
            default_radius,
            "company",
        )

    # Geofence is ON but nothing is configured — treat as "not
    # configured" so the admin gets an actionable state instead of an
    # unexplained block.
    return None


@frappe.whitelist()
def get_geofence_config(terminal=None):
    """Return `{enabled, radius_meters, source}` for the current session
    so the React POS can decide whether to request geolocation.

    Resolved against the terminal's POS Profile when possible. Returns
    `{enabled: 0}` when the feature is off — the frontend skips the
    whole geolocation dance in that case, so no browser permission
    prompt is shown.
    """
    pos_profile_name = None
    if terminal:
        pos_profile_name = frappe.db.get_value(
            "URY POS Terminal", terminal, "pos_profile"
        )
    if not pos_profile_name:
        # Fall back to first enabled profile on the user's branch so
        # Administrator / setup flows don't break.
        try:
            branch_name = getBranch()
            pos_profile_name = frappe.db.get_value(
                "POS Profile", {"branch": branch_name, "disabled": 0}, "name"
            )
        except Exception:
            pos_profile_name = None

    resolved = _resolve_user_geofence(pos_profile_name)
    if not resolved:
        return {"enabled": 0, "radius_meters": 0, "source": None}

    _lat, _lon, radius, source = resolved
    return {
        "enabled": 1,
        "radius_meters": radius,
        "source": source,
    }


@frappe.whitelist()
def validate_geofence(latitude, longitude, terminal=None):
    """Block login when the current user is outside the allowed radius.

    Call this from the React POS right after resolving the terminal
    but before any other privileged endpoints. Raises a ValidationError
    when the user is too far from the allowed location. Returns
    `{ok: 1, distance_meters, radius_meters, source}` on success, or
    `{ok: 1, enabled: 0}` when geofencing is disabled for this profile.

    Security note: the backend trusts the coordinates the browser sends.
    A determined user can spoof geolocation via devtools. This is a
    policy control, not a cryptographic one — it keeps honest cashiers
    in their branch and raises the bar for anyone trying to abuse a
    shared credential from off-site.
    """
    try:
        current_lat = float(latitude)
        current_lon = float(longitude)
    except (TypeError, ValueError):
        frappe.throw(
            _("Location data is missing or invalid."),
            title=_("Location Required"),
        )

    pos_profile_name = None
    if terminal:
        pos_profile_name = frappe.db.get_value(
            "URY POS Terminal", terminal, "pos_profile"
        )
    if not pos_profile_name:
        try:
            branch_name = getBranch()
            pos_profile_name = frappe.db.get_value(
                "POS Profile", {"branch": branch_name, "disabled": 0}, "name"
            )
        except Exception:
            pos_profile_name = None

    resolved = _resolve_user_geofence(pos_profile_name)
    if not resolved:
        return {"ok": 1, "enabled": 0}

    target_lat, target_lon, radius, source = resolved
    distance = _haversine_meters(current_lat, current_lon, target_lat, target_lon)
    if distance > radius:
        frappe.throw(
            _(
                "You are {0} m away from the allowed location (limit {1} m). "
                "Please sign in from within your assigned work area."
            ).format(int(round(distance)), int(radius)),
            title=_("Outside Allowed Location"),
        )

    return {
        "ok": 1,
        "enabled": 1,
        "distance_meters": round(distance, 1),
        "radius_meters": int(radius),
        "source": source,
    }


@frappe.whitelist()
def reverse_pos_return(return_invoice):
    """Cancel a submitted return POS Invoice to undo a return.

    Uses ERPNext's native `cancel()` which creates a docstatus=2 state
    and reverses all the GL / stock entries. The original (non-return)
    invoice is untouched — its status stays as it was.

    Validation:
    - The doc must exist, be a return (`is_return=1`), and be currently
      submitted (`docstatus=1`). Already-cancelled returns throw.
    - The caller must satisfy `_user_can_return_orders` for the
      return's POS Profile.
    """
    if not frappe.db.exists("POS Invoice", return_invoice):
        frappe.throw(_("Invoice {0} not found.").format(return_invoice))

    doc = frappe.get_doc("POS Invoice", return_invoice)

    if not doc.is_return:
        frappe.throw(
            _("Invoice {0} is not a return document.").format(return_invoice),
            title=_("Not a Return"),
        )
    if doc.docstatus != 1:
        frappe.throw(
            _("Invoice {0} is not submitted (docstatus {1}). Nothing to reverse.").format(
                return_invoice, doc.docstatus
            ),
            title=_("Cannot Reverse"),
        )

    can_return, _is_captain = _user_can_return_orders(doc.pos_profile)
    if not can_return:
        frappe.throw(
            _("You don't have permission to reverse returns on this terminal."),
            title=_("Reverse Not Allowed"),
        )

    # Let ERPNext's cancel() do the heavy lifting. ValidationErrors
    # (e.g. consolidated into a period close) propagate cleanly so the
    # frontend toast surfaces the real reason.
    doc.cancel()

    return {
        "return_invoice": return_invoice,
        "original_invoice": doc.return_against,
    }


# ---------------------------------------------------------------------
# Table merge / unmerge (cross-room, same-branch, optional order merge)
# ---------------------------------------------------------------------


def _get_top_level_master_table(table_name):
    """Walk the `merged_into` chain until we find a URY Table that
    isn't merged anywhere. Returns the final top-level master name.

    Nested merges are supported: if A → B and B → C, calling this with
    A returns C. Defends against cycles by capping the walk at 20 hops.
    """
    if not table_name:
        return None
    current = table_name
    seen = set()
    for _ in range(20):
        if current in seen:
            # Cycle — shouldn't happen, bail.
            return current
        seen.add(current)
        merged_into = frappe.db.get_value("URY Table", current, "merged_into")
        if not merged_into:
            return current
        current = merged_into
    return current


def _get_active_drafts_on_table(table_name):
    """Return draft POS Invoices currently sitting on this table (or
    any table in its merged-into chain). Used by the merge validator
    to decide whether to force merge_orders=1.
    """
    if not table_name:
        return []
    return frappe.db.sql(
        """
        SELECT name, owner, custom_terminal, grand_total, customer,
               customer_name, creation
        FROM `tabPOS Invoice`
        WHERE restaurant_table = %s
          AND docstatus = 0
          AND (custom_merged_into IS NULL OR custom_merged_into = '')
        ORDER BY creation
        """,
        (table_name,),
        as_dict=True,
    )


@frappe.whitelist()
def merge_tables(
    tables,
    merge_orders=0,
    master=None,
    notes=None,
    freed_sources=None,
):
    """Merge several URY Tables into one master.

    Args:
        tables: list of URY Table names (or JSON-encoded). Must contain
            at least two distinct entries.
        merge_orders: 1 to also merge any draft POS Invoices sitting
            on the selected tables into the master's draft. When any
            source table has a draft, the frontend should force this
            to 1 — the backend will throw if not.
        master: optional explicit master table name. Defaults to the
            first entry in ``tables``. Must itself be in the list.
        notes: optional free-text note stored on the merge log.
        freed_sources: optional list of source table names that the
            customer has vacated — those tables will be marked as
            NOT merged-into (kept available for new customers) while
            their orders are still combined onto the master. The
            default behavior (source NOT in this list) keeps the
            source hidden from the grid so ONE physical table hosts
            the combined order.

    Validation:
      - All tables must exist, all on the same branch.
      - Every selected table must currently have an active draft
        order on it. Empty/available tables can't participate — there
        would be nothing to merge. This catches the "why are you
        merging empty tables?" bug where cashiers accidentally merge
        Available tables and silently lose track of them.
      - None of the selected tables can already be merged into another
        (the sources must be top-level). The master CAN be a table
        that itself was previously a master — nested merges are fine.
      - Caller must satisfy `_user_can_merge_orders` for the master's
        POS Profile (reuses the order-merge captain gate).
      - Cross-room is allowed; cross-branch is banned.

    Orders side: when ``merge_orders=1``, delegates the order merge
    to ``merge_pos_invoices`` so both flows share the same code path
    (and produce a URY Order Merge Log alongside the URY Table Merge
    Log, linked via ``order_merge_log``).

    See CLAUDE.md "Fixes log" 2026-04-11.
    """
    if isinstance(tables, str):
        try:
            tables = json.loads(tables)
        except Exception:
            tables = [tables]
    if not isinstance(tables, list) or len(tables) < 2:
        frappe.throw(
            _("Select at least two tables to merge."),
            title=_("Not Enough Tables"),
        )
    merge_orders = int(merge_orders or 0)

    if isinstance(freed_sources, str):
        try:
            freed_sources = json.loads(freed_sources)
        except Exception:
            freed_sources = []
    freed_sources_set = set(freed_sources or [])

    # Dedup while preserving order.
    seen = []
    for name in tables:
        if name and name not in seen:
            seen.append(name)
    tables = seen
    if len(tables) < 2:
        frappe.throw(
            _("Select at least two distinct tables to merge."),
            title=_("Not Enough Tables"),
        )

    # Resolve master.
    master_name = master if master and master in tables else tables[0]
    source_names = [t for t in tables if t != master_name]

    if not frappe.db.exists("URY Table", master_name):
        frappe.throw(
            _("Master table '{0}' not found.").format(master_name),
            frappe.DoesNotExistError,
        )
    master_doc = frappe.get_doc("URY Table", master_name)

    # The master CAN already be merged into another table — in which
    # case we walk the chain to find the real top-level master and
    # redirect the merge to that. This supports "merge B (a master) into
    # C (also a master)" — functionally equivalent to merging B's
    # whole tree onto C.
    if master_doc.merged_into:
        top = _get_top_level_master_table(master_doc.name)
        if top and top != master_doc.name:
            master_doc = frappe.get_doc("URY Table", top)
            master_name = master_doc.name

    master_branch = master_doc.branch
    master_pos_profile = frappe.db.get_value(
        "POS Profile", {"branch": master_branch, "disabled": 0}, "name"
    )
    can_merge, is_captain = _user_can_merge_orders(master_pos_profile)
    if not can_merge:
        frappe.throw(
            _(
                "You are not allowed to merge tables on this POS Profile. "
                "The 'Restrict Merge Orders to Captain' setting is enabled "
                "\u2014 ask a captain or manager."
            ),
            title=_("Merge Not Allowed"),
            exc=frappe.PermissionError,
        )

    requesting_user = frappe.session.user

    # The master must have an active draft too — we're combining
    # orders into it, so an empty master isn't meaningful.
    master_drafts = _get_active_drafts_on_table(master_doc.name)
    if not master_drafts:
        frappe.throw(
            _(
                "Table '{0}' has no active order. Only tables that "
                "currently have an open order can be merged \u2014 pick "
                "a table with a customer on it."
            ).format(master_doc.name),
            title=_("Table Is Available"),
        )

    # Validate every source table.
    source_docs = []
    source_drafts = {}  # source_name -> list of draft invoices
    empty_sources = []
    for src_name in source_names:
        if not frappe.db.exists("URY Table", src_name):
            frappe.throw(
                _("Table '{0}' not found.").format(src_name),
                frappe.DoesNotExistError,
            )
        src = frappe.get_doc("URY Table", src_name)
        if src.branch != master_branch:
            frappe.throw(
                _(
                    "Table '{0}' is on branch '{1}' but the master is on '{2}'. "
                    "Only same-branch merges are allowed."
                ).format(src_name, src.branch, master_branch),
                title=_("Cross-Branch Merge Blocked"),
            )
        if src.merged_into:
            frappe.throw(
                _(
                    "Table '{0}' is already merged into '{1}'. Pick a "
                    "top-level table instead."
                ).format(src_name, src.merged_into),
                title=_("Already Merged"),
            )
        drafts = _get_active_drafts_on_table(src_name)
        if not drafts:
            empty_sources.append(src_name)
        source_drafts[src_name] = drafts
        source_docs.append(src)

    # Every selected source must have at least one draft. Empty tables
    # have nothing to merge — the cashier almost certainly clicked
    # them by mistake.
    if empty_sources:
        frappe.throw(
            _(
                "These tables are available (no active order), so "
                "there's nothing to merge: {0}. Pick only tables that "
                "currently have a customer on them."
            ).format(", ".join(empty_sources[:10])),
            title=_("Empty Tables Selected"),
        )

    # The "orders must be merged" path is implicit now — every
    # selected table has a draft by the checks above, so we always
    # proceed with the order merge. Keep the flag for backward compat
    # but force it on.
    merge_orders = 1

    # When captain-restricted, cashiers can only merge tables where
    # every draft on every source is their own.
    if not is_captain:
        stranger_drafts = []
        for src_name, drafts in source_drafts.items():
            for d in drafts:
                if d["owner"] != requesting_user:
                    stranger_drafts.append(d["name"])
        if stranger_drafts:
            frappe.throw(
                _(
                    "Some of the orders on the selected tables belong to "
                    "other cashiers: {0}. Only a captain can merge across "
                    "cashiers."
                ).format(", ".join(stranger_drafts[:5])),
                title=_("Merge Not Allowed"),
                exc=frappe.PermissionError,
            )

    # Validate freed_sources against the selection.
    unknown_freed = [
        n for n in freed_sources_set if n not in source_names
    ]
    if unknown_freed:
        frappe.throw(
            _(
                "freed_sources must reference the selected source tables. "
                "Unknown entries: {0}"
            ).format(", ".join(unknown_freed[:5])),
            title=_("Invalid Input"),
        )

    # Build the table merge log.
    log = frappe.new_doc("URY Table Merge Log")
    log.master_table = master_doc.name
    log.status = "Active"
    log.branch = master_branch
    log.pos_profile = master_pos_profile
    log.merged_at = frappe.utils.now_datetime()
    log.merged_by = requesting_user
    log.merged_by_full_name = (
        frappe.db.get_value("User", requesting_user, "full_name") or ""
    )
    log.notes = notes
    log.master_pre_merge_occupied = int(master_doc.occupied or 0)
    log.merged_orders = 0  # updated below once we run the order merge

    # Collect every draft across master + sources for the order merge.
    # The first one becomes the order merge master — prefer the
    # master's own draft.
    all_drafts = list(master_drafts)
    for src in source_docs:
        all_drafts.extend(source_drafts.get(src.name, []))
    draft_names = [d["name"] for d in all_drafts]
    seen_inv = []
    for n in draft_names:
        if n not in seen_inv:
            seen_inv.append(n)
    order_merge_result = None
    if len(seen_inv) >= 2:
        ordered = [master_drafts[0]["name"]] + [
            n for n in seen_inv if n != master_drafts[0]["name"]
        ]
        order_merge_result = merge_pos_invoices(
            ordered,
            notes=_("Auto-merged alongside table merge {0}").format(
                log.name if log.name else ""
            ),
        )
        # Re-home the order merge master's `restaurant_table` onto
        # the table merge master (so the resulting combined order
        # sits on the final chosen table).
        try:
            frappe.db.set_value(
                "POS Invoice",
                order_merge_result["master_invoice"],
                "restaurant_table",
                master_doc.name,
            )
        except Exception:
            pass
        log.merged_orders = 1
        log.order_merge_log = order_merge_result["merge_log"]

    # Snapshot each source and flip its merged_into (or free it when
    # the cashier told us the customers vacated that table).
    for src in source_docs:
        had_draft = bool(source_drafts.get(src.name))
        original_invoice = None
        if had_draft:
            original_invoice = source_drafts[src.name][0]["name"]
        freed = src.name in freed_sources_set
        log.append(
            "source_tables",
            {
                "source_table": src.name,
                "original_room": src.restaurant_room,
                "original_occupied": int(src.occupied or 0),
                "had_active_order": int(had_draft),
                "original_invoice": original_invoice,
            },
        )
        if freed:
            # Customers vacated this table — keep it AVAILABLE in the
            # grid for the next customer. We do NOT set `merged_into`
            # because the table isn't logically under the master; its
            # old order is on the master now but the physical table
            # is free. Unmerge will restore the order onto the source
            # and re-occupy it at that point.
            frappe.db.set_value(
                "URY Table",
                src.name,
                {
                    "merged_into": None,
                    "occupied": 0,
                    "latest_invoice_time": None,
                },
            )
        else:
            # Customers still sitting at this table. Hide it behind
            # the master: `merged_into` is set, so `getTable` filters
            # it out of the grid. The cashier interacts with the
            # master from now on.
            frappe.db.set_value(
                "URY Table",
                src.name,
                {
                    "merged_into": master_doc.name,
                    "occupied": 0,
                    "latest_invoice_time": None,
                },
            )

    # The master now holds the combined order — mark it occupied.
    frappe.db.set_value(
        "URY Table",
        master_doc.name,
        {"occupied": 1},
    )

    log.insert(ignore_permissions=True)
    frappe.db.commit()

    return {
        "merge_log": log.name,
        "master_table": master_doc.name,
        "merged_count": len(source_docs),
        "freed_count": len(freed_sources_set),
        "order_merge_log": (
            order_merge_result["merge_log"] if order_merge_result else None
        ),
        "order_master": (
            order_merge_result["master_invoice"] if order_merge_result else None
        ),
    }


def _get_post_merge_invoices(master_table, merged_at):
    """Return the list of POS Invoice docs on `master_table` that were
    created AFTER `merged_at`. Used by the unmerge flow to decide
    whether the unmerge is allowed (when the profile's
    ``custom_allow_unmerge_after_new_orders`` is off) and, if so, to
    ask the cashier which destination table each new order should go
    to.
    """
    if not master_table or not merged_at:
        return []
    return frappe.db.sql(
        """
        SELECT name, owner, customer, customer_name, grand_total,
               docstatus, status, creation
        FROM `tabPOS Invoice`
        WHERE restaurant_table = %s
          AND creation > %s
          AND (custom_merged_into IS NULL OR custom_merged_into = '')
        ORDER BY creation
        """,
        (master_table, merged_at),
        as_dict=True,
    )


@frappe.whitelist()
def get_active_table_merge_log(table):
    """Return metadata about the active table merge log that has
    ``table`` as its master, or None. Powers the unmerge button on
    the Table page + drives the unmerge dialog's initial state.

    Response shape: ``{name, merged_at, merged_by, merged_by_full_name,
    merged_orders, order_merge_log, source_count, source_tables,
    post_merge_orders, unmerge_allowed_without_additional_handling}``.
    """
    if not table:
        return None
    rows = frappe.db.sql(
        """
        SELECT name, merged_at, merged_by, merged_by_full_name,
               merged_orders, order_merge_log, pos_profile
        FROM `tabURY Table Merge Log`
        WHERE master_table = %s AND status = 'Active'
        ORDER BY merged_at DESC
        LIMIT 1
        """,
        (table,),
        as_dict=True,
    )
    if not rows:
        return None
    row = rows[0]
    log = frappe.get_doc("URY Table Merge Log", row.name)
    source_tables = [
        {
            "source_table": s.source_table,
            "original_room": s.original_room,
            "original_occupied": int(s.original_occupied or 0),
            "had_active_order": int(s.had_active_order or 0),
            "original_invoice": s.original_invoice,
        }
        for s in (log.source_tables or [])
    ]
    post_merge = _get_post_merge_invoices(table, log.merged_at)
    allow_after_new = int(
        frappe.db.get_value(
            "POS Profile",
            row.pos_profile,
            "custom_allow_unmerge_after_new_orders",
        )
        or 0
    )
    return {
        "name": row.name,
        "merged_at": str(log.merged_at) if log.merged_at else None,
        "merged_by": log.merged_by,
        "merged_by_full_name": log.merged_by_full_name,
        "merged_orders": int(log.merged_orders or 0),
        "order_merge_log": log.order_merge_log,
        "source_count": len(source_tables),
        "source_tables": source_tables,
        "post_merge_orders": post_merge,
        "custom_allow_unmerge_after_new_orders": allow_after_new,
    }


@frappe.whitelist()
def unmerge_tables(merge_log, order_assignments=None):
    """Reverse a previous table merge.

    Args:
        merge_log: URY Table Merge Log name.
        order_assignments: optional JSON map ``{invoice: destination_table}``
            required when the master has post-merge orders AND the POS
            Profile's ``custom_allow_unmerge_after_new_orders`` is on.
            Each invoice on the master created after ``merge_log.merged_at``
            must appear in this map. Destinations must be tables that
            are either the master itself or one of the merge's source
            tables.

    Behavior:
      1. If the master has no post-merge invoices, unmerge is a
         simple single action (restores tables + optionally reverses
         the order merge).
      2. If the master has post-merge invoices AND the profile
         disallows it, throws with a clear error listing the offending
         invoices.
      3. If the profile allows it, requires ``order_assignments`` for
         every post-merge invoice, applies them (by updating each
         invoice's ``restaurant_table`` in place), then proceeds with
         the unmerge.

    See CLAUDE.md "Fixes log" 2026-04-11.
    """
    if not merge_log:
        frappe.throw(
            _("Merge log name is required."), title=_("Missing Argument")
        )
    if not frappe.db.exists("URY Table Merge Log", merge_log):
        frappe.throw(
            _("Table merge log '{0}' not found.").format(merge_log),
            frappe.DoesNotExistError,
        )

    if isinstance(order_assignments, str):
        try:
            order_assignments = json.loads(order_assignments)
        except Exception:
            order_assignments = {}
    order_assignments = order_assignments or {}

    log = frappe.get_doc("URY Table Merge Log", merge_log)
    if log.status != "Active":
        frappe.throw(
            _("Table merge log '{0}' is already unmerged.").format(merge_log),
            title=_("Already Unmerged"),
        )

    if not frappe.db.exists("URY Table", log.master_table):
        frappe.throw(
            _("Master table '{0}' no longer exists.").format(log.master_table),
            frappe.DoesNotExistError,
        )

    can_merge, is_captain = _user_can_merge_orders(log.pos_profile)
    if not can_merge:
        frappe.throw(
            _("You are not allowed to unmerge tables on this POS Profile."),
            title=_("Unmerge Not Allowed"),
            exc=frappe.PermissionError,
        )
    requesting_user = frappe.session.user

    # Identify post-merge orders on the master.
    post_merge = _get_post_merge_invoices(log.master_table, log.merged_at)
    allow_after_new = int(
        frappe.db.get_value(
            "POS Profile",
            log.pos_profile,
            "custom_allow_unmerge_after_new_orders",
        )
        or 0
    )

    valid_destinations = {log.master_table} | {
        s.source_table for s in (log.source_tables or [])
    }

    if post_merge:
        if not allow_after_new:
            names = ", ".join(r["name"] for r in post_merge[:5])
            extra = "" if len(post_merge) <= 5 else f" (+{len(post_merge) - 5} more)"
            frappe.throw(
                _(
                    "Cannot unmerge: there are {0} order(s) on the master "
                    "table that were created after the merge \u2014 {1}{2}. "
                    "Pay or cancel those orders first, OR ask an admin to "
                    "turn on 'Allow Table Unmerge After New Orders' on "
                    "the POS Profile."
                ).format(len(post_merge), names, extra),
                title=_("Unmerge Blocked: New Orders"),
            )
        # Validate assignments.
        missing = []
        bad_dest = []
        for inv in post_merge:
            dest = order_assignments.get(inv["name"])
            if not dest:
                missing.append(inv["name"])
            elif dest not in valid_destinations:
                bad_dest.append((inv["name"], dest))
        if missing:
            frappe.throw(
                _(
                    "You must pick a destination table for each new order: "
                    "missing {0}."
                ).format(", ".join(missing[:5])),
                title=_("Missing Destination"),
            )
        if bad_dest:
            details = ", ".join(f"{n} \u2192 {d}" for n, d in bad_dest[:5])
            frappe.throw(
                _(
                    "Destination must be the master or one of the merge's "
                    "source tables. Invalid assignments: {0}"
                ).format(details),
                title=_("Invalid Destination"),
            )
        # Apply assignments.
        for inv in post_merge:
            dest = order_assignments[inv["name"]]
            if dest != log.master_table:
                frappe.db.set_value(
                    "POS Invoice",
                    inv["name"],
                    "restaurant_table",
                    dest,
                )

    # Pre-flight check for sources that were FREED at merge time
    # (customers vacated, table returned to Available). If a new
    # customer has since sat at one of those tables and rung a new
    # order, restoring the old order onto it would create a
    # two-order conflict. Block the unmerge with a clear error
    # pointing at the offending tables.
    freed_sources_with_new_orders = []
    for src_row in log.source_tables or []:
        src_name = src_row.source_table
        if not frappe.db.exists("URY Table", src_name):
            continue
        # A source is "freed" if it isn't currently merged into this
        # master. Un-freed sources will be hidden behind the master
        # via `merged_into` and therefore can't have new orders.
        still_merged = (
            frappe.db.get_value("URY Table", src_name, "merged_into")
            == log.master_table
        )
        if still_merged:
            continue
        # Check for post-merge drafts on this freed source.
        new_drafts = frappe.db.sql(
            """
            SELECT name
            FROM `tabPOS Invoice`
            WHERE restaurant_table = %s
              AND creation > %s
              AND docstatus = 0
              AND (custom_merged_into IS NULL OR custom_merged_into = '')
            ORDER BY creation
            LIMIT 5
            """,
            (src_name, log.merged_at),
            as_dict=True,
        )
        if new_drafts:
            freed_sources_with_new_orders.append(
                (src_name, [d["name"] for d in new_drafts])
            )

    if freed_sources_with_new_orders:
        details = "; ".join(
            f"{t} has {', '.join(ns)}"
            for t, ns in freed_sources_with_new_orders[:5]
        )
        frappe.throw(
            _(
                "Cannot unmerge: one or more of the freed source tables "
                "now have a new customer on them \u2014 {0}. Pay or "
                "cancel those new orders before unmerging, otherwise the "
                "old orders would collide with the new ones."
            ).format(details),
            title=_("Unmerge Blocked: Tables Reused"),
        )

    # Reverse the order merge first (if there was one) — this restores
    # the pre-merge draft orders so they're pointing at their original
    # source tables BEFORE we put those tables back.
    if log.merged_orders and log.order_merge_log:
        order_log_exists = frappe.db.exists(
            "URY Order Merge Log", log.order_merge_log
        )
        if order_log_exists:
            order_log_status = frappe.db.get_value(
                "URY Order Merge Log", log.order_merge_log, "status"
            )
            if order_log_status == "Active":
                # unmerge_pos_invoices will throw if the master was paid;
                # let that propagate.
                unmerge_pos_invoices(log.order_merge_log)

    # Restore each source table: clear merged_into + restore original
    # occupied / latest_invoice_time state if the source had an active
    # order (which was restored by the order unmerge above).
    for src_row in log.source_tables or []:
        src_name = src_row.source_table
        if not frappe.db.exists("URY Table", src_name):
            continue
        updates = {"merged_into": None}
        if src_row.had_active_order:
            updates["occupied"] = 1
            updates["latest_invoice_time"] = frappe.utils.now_datetime().time()
        else:
            updates["occupied"] = int(src_row.original_occupied or 0)
        frappe.db.set_value("URY Table", src_name, updates)

    # If the master was not occupied before the merge and has no
    # post-merge orders, reset its occupied flag to match the snapshot.
    if not post_merge and not int(log.master_pre_merge_occupied or 0):
        frappe.db.set_value(
            "URY Table", log.master_table, {"occupied": 0, "latest_invoice_time": None}
        )

    log.status = "Unmerged"
    log.unmerged_at = frappe.utils.now_datetime()
    log.unmerged_by = requesting_user
    log.unmerged_by_full_name = (
        frappe.db.get_value("User", requesting_user, "full_name") or ""
    )
    log.flags.ignore_permissions = True
    log.save()
    frappe.db.commit()

    return {
        "merge_log": log.name,
        "master_table": log.master_table,
        "unmerged_count": len(log.source_tables or []),
        "reassigned_orders": len(post_merge),
    }


def auto_unmerge_table_if_active(master_table):
    """Internal helper: when a table's merge has served its purpose
    (e.g. the master invoice was printed and is on its way to payment),
    sweep any active URY Table Merge Log on this table and clear the
    sources back out.

    Differs from `unmerge_tables` in two ways:
      1. Skips the user permission check — this is a system action
         triggered by the print/payment flow, not a cashier choice.
      2. Skips the post-merge-order block — by the time we get here
         the master's invoice is already on its way out, so there's
         no draft to strand. Any new draft created on the master
         AFTER this auto-unmerge is unrelated and stays put.

    Returns the merge log name when an unmerge happened, None when
    there was no active merge to clear. Logs (but doesn't raise) on
    failure so the print path doesn't blow up if something's weird.
    """
    if not master_table:
        return None
    log_name = frappe.db.get_value(
        "URY Table Merge Log",
        {"master_table": master_table, "status": "Active"},
        "name",
    )
    if not log_name:
        return None

    try:
        log = frappe.get_doc("URY Table Merge Log", log_name)

        # Reverse the order merge first if there was one. The order
        # merge unmerge will throw if the master invoice is already
        # paid — that's fine, we want it to skip in that case (the
        # consolidated invoice is now part of the closing flow and
        # can't be split anyway).
        if log.merged_orders and log.order_merge_log:
            order_log_status = frappe.db.get_value(
                "URY Order Merge Log", log.order_merge_log, "status"
            )
            if order_log_status == "Active":
                try:
                    unmerge_pos_invoices(log.order_merge_log)
                except Exception:
                    # Master invoice may already be submitted/paid; the
                    # order unmerge can't proceed. The TABLE unmerge
                    # still should — we just leave the orders as-is.
                    pass

        # Clear `merged_into` on each source so they reappear in the
        # grid as Available.
        for src_row in log.source_tables or []:
            src_name = src_row.source_table
            if not frappe.db.exists("URY Table", src_name):
                continue
            still_merged = (
                frappe.db.get_value("URY Table", src_name, "merged_into")
                == log.master_table
            )
            updates = {"merged_into": None, "occupied": 0, "latest_invoice_time": None}
            # Sources that were freed at merge time stayed Available all
            # along — `still_merged` is False — and we don't want to
            # touch them. Only re-clear sources that ARE currently
            # hidden behind the master.
            if still_merged:
                frappe.db.set_value("URY Table", src_name, updates)

        log.status = "Unmerged"
        log.unmerged_at = frappe.utils.now_datetime()
        log.unmerged_by = frappe.session.user
        log.unmerged_by_full_name = (
            frappe.db.get_value("User", frappe.session.user, "full_name") or ""
        )
        log.flags.ignore_permissions = True
        log.save()
        return log.name
    except Exception as exc:
        frappe.log_error(
            title="Auto-unmerge table failed",
            message=f"master_table={master_table} log={log_name}\n{exc}",
        )
        return None


# ---------------------------------------------------------------------
# iHotel integration
# ---------------------------------------------------------------------


def _ihotel_enabled(pos_profile_name):
    """Whether the given POS Profile has the iHotel toggle on."""
    if not pos_profile_name:
        return False
    val = frappe.db.get_value(
        "POS Profile", pos_profile_name, "custom_ihotel_enabled"
    )
    return bool(int(val or 0))


@frappe.whitelist()
def get_guest_rooms_for_customer(customer):
    """Return all open iHotel Profiles for guests linked to this
    Customer. Powers the "Hotel Guest" room picker — when the cashier
    selects a customer, we filter down to rooms that (a) belong to a
    guest whose ``Guest.customer`` points at this customer, and
    (b) have an open profile (``status = 'Open'``). Returns an empty
    list when no open rooms match.

    Response shape: ``[{profile, room, guest, guest_name,
    check_in_date, check_out_date}, ...]``.
    """
    if not customer:
        return []

    # Find guests linked to this customer.
    guests = frappe.db.sql(
        """
        SELECT name, guest_name
        FROM `tabGuest`
        WHERE customer = %s
        ORDER BY guest_name
        """,
        (customer,),
        as_dict=True,
    )
    if not guests:
        return []

    guest_names = [g.name for g in guests]
    profiles = frappe.db.sql(
        """
        SELECT
            name, room, guest, guest_name, check_in_date, check_out_date,
            status
        FROM `tabiHotel Profile`
        WHERE status = 'Open'
          AND guest IN %(guests)s
        ORDER BY check_in_date DESC
        """,
        {"guests": tuple(guest_names)},
        as_dict=True,
    )
    return [
        {
            "profile": p.name,
            "room": p.room,
            "guest": p.guest,
            "guest_name": p.guest_name,
            "check_in_date": str(p.check_in_date) if p.check_in_date else None,
            "check_out_date": str(p.check_out_date) if p.check_out_date else None,
        }
        for p in profiles
    ]


@frappe.whitelist()
def validate_hotel_room_for_customer(customer, hotel_room):
    """Return the open iHotel Profile for (customer, room) or throw.

    Called from the React POS right before the cashier picks a room on
    a new order — validates that:
      1. The iHotel Profile for the given room is in status Open.
      2. The profile's guest is linked to the selected customer.
    Returns ``{profile, guest, guest_name, room_rate}`` on success.
    Throws a clear error on any failure so the cashier can't start an
    order against a room that isn't checked in / doesn't match the
    customer.
    """
    if not customer or not hotel_room:
        frappe.throw(
            _("Customer and room are required."),
            title=_("Missing Data"),
        )

    profile = frappe.db.sql(
        """
        SELECT p.name, p.guest, p.guest_name, p.room_rate, p.status,
               g.customer AS guest_customer
        FROM `tabiHotel Profile` AS p
        INNER JOIN `tabGuest` AS g ON g.name = p.guest
        WHERE p.room = %s
          AND p.status = 'Open'
        LIMIT 1
        """,
        (hotel_room,),
        as_dict=True,
    )
    if not profile:
        frappe.throw(
            _(
                "Room '{0}' has no open hotel stay. Ask the guest to "
                "check in before charging to this room."
            ).format(hotel_room),
            title=_("No Open Stay"),
        )
    row = profile[0]
    if row.guest_customer != customer:
        frappe.throw(
            _(
                "Room '{0}' is checked in under guest '{1}' who is "
                "linked to a different customer. Pick the correct "
                "customer or room."
            ).format(hotel_room, row.guest_name or row.guest),
            title=_("Customer Mismatch"),
        )
    return {
        "profile": row.name,
        "guest": row.guest,
        "guest_name": row.guest_name,
        "room_rate": float(row.room_rate or 0),
    }


@frappe.whitelist()
def charge_invoice_to_room(invoice, hotel_room):
    """Charge a POS Invoice to a hotel guest's room.

    Writes a single Folio Charge row onto the matching open iHotel
    Profile, stamps the POS Invoice with the charge_to_room trio of
    custom fields, marks it as printed, frees its table, and leaves
    the POS Invoice as `docstatus=0` (a charged draft). Charged
    drafts are excluded from:
      - The cashier's shift close breakdown (they don't block close)
      - The Orders page Draft / Unbilled filters (they appear under
        the new "Room Charges" status instead)
      - `restrict_existing_order` (a new customer on the same table
        gets a fresh draft, not the charged one)

    This avoids double-posting to the GL: iHotel's own checkout flow
    posts the actual accounting when the guest settles their folio.

    Args:
        invoice: POS Invoice name to charge.
        hotel_room: iHotel Room name. Must match an open profile
            whose guest links to the invoice's customer.

    Returns:
        {invoice, ihotel_profile, folio_charge_row, amount}
    """
    if not invoice or not hotel_room:
        frappe.throw(
            _("Invoice and hotel_room are required."),
            title=_("Missing Data"),
        )

    inv = frappe.get_doc("POS Invoice", invoice)
    if inv.docstatus != 0:
        frappe.throw(
            _(
                "Invoice '{0}' is not a draft (docstatus {1}). Only "
                "draft orders can be charged to a room."
            ).format(invoice, inv.docstatus),
            title=_("Invoice Not Editable"),
        )
    if inv.get("custom_charge_to_room"):
        frappe.throw(
            _(
                "Invoice '{0}' has already been charged to a room "
                "({1}). Un-charge it from the desk before retrying."
            ).format(invoice, inv.get("custom_hotel_room")),
            title=_("Already Charged"),
        )
    if not _ihotel_enabled(inv.pos_profile):
        frappe.throw(
            _(
                "iHotel integration is not enabled on POS Profile "
                "'{0}'. Turn on 'Enable iHotel Integration' in the "
                "desk first."
            ).format(inv.pos_profile),
            title=_("iHotel Not Enabled"),
        )

    charge_type = frappe.db.get_value(
        "POS Profile", inv.pos_profile, "custom_ihotel_charge_type"
    )
    if not charge_type:
        frappe.throw(
            _(
                "POS Profile '{0}' has iHotel enabled but no 'iHotel "
                "Charge Type' set. Pick one in the desk before "
                "charging to room."
            ).format(inv.pos_profile),
            title=_("Charge Type Not Set"),
        )

    # Re-validate room + customer linkage (the frontend already
    # pre-validated but don't trust the client).
    validation = validate_hotel_room_for_customer(inv.customer, hotel_room)
    profile_name = validation["profile"]

    # Build the folio description: "Cafe: 2x Fanta, 1x Burger" style.
    # One row per POS Invoice (user's option B from the design round).
    item_parts = []
    for row in inv.items or []:
        item_parts.append(
            f"{int(row.qty) if row.qty == int(row.qty) else row.qty}x {row.item_name}"
        )
    description = (
        f"POS {inv.name}: " + ", ".join(item_parts)
        if item_parts
        else f"POS {inv.name}"
    )
    if len(description) > 140:
        description = description[:137] + "…"

    amount = float(inv.grand_total or 0)

    # Write the Folio Charge row on the iHotel Profile.
    profile_doc = frappe.get_doc("iHotel Profile", profile_name)
    profile_doc.append(
        "charges",
        {
            "charge_date": inv.posting_date or frappe.utils.today(),
            "charge_type": charge_type,
            "description": description,
            "quantity": 1,
            "rate": amount,
            "amount": amount,
            "reference_doctype": "POS Invoice",
            "reference_name": inv.name,
        },
    )
    # Nudge the profile's total_amount so the summary widget stays
    # accurate. outstanding_balance is recomputed by iHotel's own
    # validate hook on save.
    profile_doc.total_amount = float(profile_doc.total_amount or 0) + amount
    profile_doc.flags.ignore_permissions = True
    profile_doc.save()
    # Grab the name of the charge row we just appended (last in list).
    last_row = profile_doc.charges[-1] if profile_doc.charges else None
    folio_charge_row = last_row.name if last_row else None

    # Stamp the POS Invoice. db.set_value bypasses validate/save so
    # the charged-draft flag sticks without triggering the
    # modification-time check or URY's other POS Invoice hooks. Also
    # mark the invoice as printed so subsequent shift-close flows see
    # it as "done".
    frappe.db.set_value(
        "POS Invoice",
        inv.name,
        {
            "custom_charge_to_room": 1,
            "custom_hotel_room": hotel_room,
            "custom_ihotel_profile": profile_name,
            "invoice_printed": 1,
            "custom_order_status": "Room Charged",
        },
        update_modified=True,
    )

    # Free the table so the next customer can be seated there. We
    # also auto-unmerge if this table was a merge master — same
    # pattern as the print flow.
    if inv.restaurant_table:
        frappe.db.set_value(
            "URY Table",
            inv.restaurant_table,
            {"occupied": 0, "latest_invoice_time": None},
        )
        auto_unmerge_table_if_active(inv.restaurant_table)

    frappe.db.commit()
    return {
        "invoice": inv.name,
        "ihotel_profile": profile_name,
        "folio_charge_row": folio_charge_row,
        "amount": amount,
    }


# ---------------------------------------------------------------------
# URY Shift system (added 2026-04-14)
# ---------------------------------------------------------------------
#
# The shift system gates POS Opening Entry creation against a per-user
# weekly schedule. Two backends are supported, picked by the POS
# Profile's `custom_shift_system_mode` field:
#
#   - "URY Shift": uses URY-owned `URY Shift` (template) + `URY Shift
#     Assignment` (User -> Shift with effective dates and weekday
#     pattern). No HRMS dependency. The recommended default for
#     restaurant deployments without HR.
#   - "HRMS Shift Type": uses ERPNext HRMS `Shift Type` + `Shift
#     Assignment` via the Employee linked to the user. Used when the
#     site has the hrms app installed and already runs HR scheduling.
#   - "Disabled": no shift system; POS Opening Entry has no time gate
#     beyond the existing custom_shift_hours soft reminder.
#
# See CLAUDE.md "Fixes log" 2026-04-14.


def _shift_system_mode(pos_profile_name):
    """Read the POS Profile's shift_system_mode field, defaulting to
    Disabled when the column or value is missing."""
    if not pos_profile_name:
        return "Disabled"
    val = frappe.db.get_value(
        "POS Profile", pos_profile_name, "custom_shift_system_mode"
    )
    return val or "Disabled"


def _is_shift_admin(user=None):
    """Administrator + System Manager always bypass the shift gate so
    the operator who set the system up can never lock themselves out."""
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    return "System Manager" in frappe.get_roles(user)


_WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def _now_local():
    """Site-local now. ERPNext stores time fields in the site's tz."""
    return frappe.utils.now_datetime()


def _seconds_in_window(now_dt, start_seconds, end_seconds):
    """Return today's elapsed seconds since midnight, as an int."""
    return now_dt.hour * 3600 + now_dt.minute * 60 + now_dt.second


def _time_to_seconds(t):
    """Convert a Time / timedelta / 'HH:MM:SS' string to seconds."""
    if t is None:
        return None
    if hasattr(t, "total_seconds"):
        return int(t.total_seconds())
    if hasattr(t, "hour"):
        return t.hour * 3600 + t.minute * 60 + (t.second or 0)
    if isinstance(t, str):
        parts = t.split(":")
        if len(parts) >= 2:
            h = int(parts[0])
            m = int(parts[1])
            s = int(parts[2]) if len(parts) > 2 else 0
            return h * 3600 + m * 60 + s
    return None


def _resolve_active_shift_for_user_ury(user, branch=None, _now_dt=None):
    """URY backend: find the active URY Shift Assignment for this user
    right now, with proper cross-midnight handling.

    For each lookup we consider assignments whose weekday matches
    TODAY AND assignments whose weekday matches YESTERDAY (because a
    cross-midnight shift assigned to yesterday may still be running
    into today, e.g. Monday 18:00 \u2192 Tuesday 06:00).

    Internal math uses real ``datetime`` objects anchored to specific
    days so cross-midnight comparisons just work. The returned
    ``info`` dict still exposes ``start_seconds`` / ``end_seconds`` /
    ``open_window_*_seconds`` / ``late_close_seconds`` but those are
    relative to the ``anchor`` (see below) — the frontend uses them
    for display via ``_seconds_to_hhmm`` only, so it doesn't notice
    that "end 06:00" on a cross-midnight shift is actually 06:00
    the next calendar day.

    Priority: in_window (returned immediately) > live > ended > upcoming.

    See CLAUDE.md "Fixes log" 2026-04-14 + 2026-04-15 (cross-midnight).

    ``_now_dt`` is an internal test hook — when passed, both the
    "today" anchor and the "now" moment are derived from it so unit
    tests can freeze time without monkey-patching ``frappe.utils.getdate``.
    """
    import datetime

    if _now_dt is not None:
        today = _now_dt.date()
    else:
        today = frappe.utils.getdate()
    yesterday = today - datetime.timedelta(days=1)
    weekday_today = _WEEKDAY_NAMES[today.weekday()]
    weekday_yesterday = _WEEKDAY_NAMES[yesterday.weekday()]

    # Pull all Active assignments matching this user whose effective
    # range includes either today or yesterday. A yesterday-only
    # assignment would be filtered out by `effective_from <= today`
    # if effective_from was yesterday, so we use effective_from <=
    # today and check effective_to >= yesterday.
    filters = {
        "user": user,
        "status": "Active",
        "effective_from": ("<=", today),
    }
    rows = frappe.get_all(
        "URY Shift Assignment",
        filters=filters,
        fields=["name", "shift", "effective_from", "effective_to", "branch"],
    )

    # candidates is a list of (assignment_row, candidate_day) tuples.
    # A single assignment may produce two candidates — one anchored
    # to today (the shift starts today) and one anchored to yesterday
    # (the shift started yesterday and may still be running today
    # via cross-midnight).
    candidates = []
    for r in rows:
        if r.effective_to and r.effective_to < yesterday:
            continue
        if branch and r.branch and r.branch != branch:
            continue

        days = frappe.get_all(
            "URY Shift Day",
            filters={"parent": r.name, "parenttype": "URY Shift Assignment"},
            pluck="day",
        )
        empty_days = not days  # empty table = every day

        # Today as the start day.
        if (empty_days or weekday_today in days) and (
            not r.effective_to or r.effective_to >= today
        ) and r.effective_from <= today:
            candidates.append((r, today))

        # Yesterday as the start day — only useful for cross-midnight
        # shifts. We still add it here; the inner loop will skip it
        # when the shift doesn't cross midnight.
        if (empty_days or weekday_yesterday in days) and (
            not r.effective_to or r.effective_to >= yesterday
        ) and r.effective_from <= yesterday:
            candidates.append((r, yesterday))

    if not candidates:
        return None

    now = _now_dt if _now_dt is not None else _now_local()
    if not isinstance(now, datetime.datetime):
        now = datetime.datetime.now()

    live = None
    ended = None
    ended_ends_at = None  # datetime — most recently ended
    upcoming = None
    upcoming_starts_at = None  # datetime — soonest upcoming

    for cand, anchor_day in candidates:
        shift_doc = frappe.get_doc("URY Shift", cand.shift)
        if shift_doc.disabled:
            continue
        start_secs = _time_to_seconds(shift_doc.start_time)
        end_secs = _time_to_seconds(shift_doc.end_time)
        if start_secs is None or end_secs is None:
            continue

        crosses_midnight = end_secs <= start_secs

        # Skip yesterday-anchored candidates that don't cross midnight
        # — they already ended yesterday and aren't relevant.
        if anchor_day == yesterday and not crosses_midnight:
            continue

        before = int(shift_doc.tolerance_minutes_before or 0) * 60
        after_start = int(shift_doc.tolerance_minutes_after_start or 0) * 60
        after_end = int(shift_doc.tolerance_minutes_after_end or 0) * 60

        start_dt = datetime.datetime.combine(
            anchor_day, datetime.time(0, 0)
        ) + datetime.timedelta(seconds=start_secs)

        if crosses_midnight:
            end_dt = datetime.datetime.combine(
                anchor_day + datetime.timedelta(days=1), datetime.time(0, 0)
            ) + datetime.timedelta(seconds=end_secs)
        else:
            end_dt = datetime.datetime.combine(
                anchor_day, datetime.time(0, 0)
            ) + datetime.timedelta(seconds=end_secs)

        open_window_start_dt = start_dt - datetime.timedelta(seconds=before)
        open_window_end_dt = start_dt + datetime.timedelta(seconds=after_start)
        late_close_dt = end_dt + datetime.timedelta(seconds=after_end)

        info = {
            "assignment": cand.name,
            "shift": cand.shift,
            "shift_name": shift_doc.shift_name,
            "branch": shift_doc.branch,
            # Display-only seconds (HH:MM portion). Cross-midnight
            # end_seconds is the raw time-of-day, NOT offset by 24h,
            # so the banner shows e.g. "Ended at 06:00" correctly.
            "start_seconds": start_secs,
            "end_seconds": end_secs,
            "open_window_start_seconds": (start_secs - before) % 86400,
            "open_window_end_seconds": (start_secs + after_start) % 86400,
            "late_close_seconds": (end_secs + after_end) % 86400,
            "tolerance_minutes_before": before // 60,
            "tolerance_minutes_after_start": after_start // 60,
            "tolerance_minutes_after_end": after_end // 60,
            "crosses_midnight": 1 if crosses_midnight else 0,
            "anchor_day": str(anchor_day),
            # Internal datetime fields — the dispatcher uses them.
            "_start_dt": start_dt,
            "_end_dt": end_dt,
            "_open_window_start_dt": open_window_start_dt,
            "_open_window_end_dt": open_window_end_dt,
            "_late_close_dt": late_close_dt,
        }

        if open_window_start_dt <= now <= open_window_end_dt:
            return info

        if start_dt <= now <= end_dt:
            live = info
            continue

        if now > end_dt:
            if ended_ends_at is None or end_dt > ended_ends_at:
                ended = info
                ended_ends_at = end_dt
            continue

        if start_dt > now:
            if upcoming_starts_at is None or start_dt < upcoming_starts_at:
                upcoming = info
                upcoming_starts_at = start_dt

    return live or ended or upcoming or None


def _resolve_active_shift_for_user_hrms(user, branch=None):
    """HRMS backend: find an active ERPNext Shift Assignment for the
    Employee linked to this user. Returns the same dict shape as the
    URY path (including ``_start_dt`` etc. internal datetime fields)
    or None when nothing matches / hrms isn't installed.

    Cross-midnight is auto-detected via ``end_time <= start_time``.
    We consider both today's and yesterday's HRMS Shift Assignments
    so an overnight shift that began yesterday and runs into today
    is still recognized.
    """
    import datetime

    if not frappe.db.exists("DocType", "Shift Assignment"):
        return None
    if not frappe.db.exists("DocType", "Shift Type"):
        return None

    # Find the employee linked to this user.
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if not employee:
        return None

    today = frappe.utils.getdate()
    yesterday = today - datetime.timedelta(days=1)
    rows = frappe.get_all(
        "Shift Assignment",
        filters={
            "employee": employee,
            "status": "Active",
            "docstatus": 1,
            "start_date": ("<=", today),
        },
        fields=["name", "shift_type", "start_date", "end_date"],
    )

    # Candidates: each (row, anchor_day) pair. HRMS doesn't carry
    # weekday patterns — the assignment is active every day in its
    # date range — so we just check both today and yesterday.
    candidates = []
    for r in rows:
        if r.end_date and r.end_date < yesterday:
            continue
        if r.start_date <= today:
            candidates.append((r, today))
        if r.start_date <= yesterday and (
            not r.end_date or r.end_date >= yesterday
        ):
            candidates.append((r, yesterday))

    if not candidates:
        return None

    now = _now_local()
    if not isinstance(now, datetime.datetime):
        now = datetime.datetime.now()

    live = None
    ended = None
    ended_ends_at = None
    upcoming = None
    upcoming_starts_at = None

    for cand, anchor_day in candidates:
        shift_type = frappe.get_doc("Shift Type", cand.shift_type)
        start_secs = _time_to_seconds(getattr(shift_type, "start_time", None))
        end_secs = _time_to_seconds(getattr(shift_type, "end_time", None))
        if start_secs is None or end_secs is None:
            continue

        crosses_midnight = end_secs <= start_secs
        if anchor_day == yesterday and not crosses_midnight:
            continue

        # HRMS Shift Type uses different field names / not all are
        # present. Map best we can; default to 15 min before / 30
        # after start / 60 after end.
        before = (
            int(getattr(shift_type, "begin_check_in_before_shift_start_time", 15) or 0)
            * 60
        )
        after_end = (
            int(getattr(shift_type, "allow_check_out_after_shift_end_time", 60) or 0)
            * 60
        )
        after_start = 30 * 60  # not modeled by HRMS; URY default

        start_dt = datetime.datetime.combine(
            anchor_day, datetime.time(0, 0)
        ) + datetime.timedelta(seconds=start_secs)
        if crosses_midnight:
            end_dt = datetime.datetime.combine(
                anchor_day + datetime.timedelta(days=1), datetime.time(0, 0)
            ) + datetime.timedelta(seconds=end_secs)
        else:
            end_dt = datetime.datetime.combine(
                anchor_day, datetime.time(0, 0)
            ) + datetime.timedelta(seconds=end_secs)
        open_window_start_dt = start_dt - datetime.timedelta(seconds=before)
        open_window_end_dt = start_dt + datetime.timedelta(seconds=after_start)
        late_close_dt = end_dt + datetime.timedelta(seconds=after_end)

        info = {
            "assignment": cand.name,
            "shift": cand.shift_type,
            "shift_name": cand.shift_type,
            "branch": branch,
            "start_seconds": start_secs,
            "end_seconds": end_secs,
            "open_window_start_seconds": (start_secs - before) % 86400,
            "open_window_end_seconds": (start_secs + after_start) % 86400,
            "late_close_seconds": (end_secs + after_end) % 86400,
            "tolerance_minutes_before": before // 60,
            "tolerance_minutes_after_start": after_start // 60,
            "tolerance_minutes_after_end": after_end // 60,
            "crosses_midnight": 1 if crosses_midnight else 0,
            "anchor_day": str(anchor_day),
            "_start_dt": start_dt,
            "_end_dt": end_dt,
            "_open_window_start_dt": open_window_start_dt,
            "_open_window_end_dt": open_window_end_dt,
            "_late_close_dt": late_close_dt,
        }

        if open_window_start_dt <= now <= open_window_end_dt:
            return info
        if start_dt <= now <= end_dt:
            live = info
            continue
        if now > end_dt:
            if ended_ends_at is None or end_dt > ended_ends_at:
                ended = info
                ended_ends_at = end_dt
            continue
        if start_dt > now:
            if upcoming_starts_at is None or start_dt < upcoming_starts_at:
                upcoming = info
                upcoming_starts_at = start_dt

    return live or ended or upcoming or None


def _resolve_active_shift_for_user(user, pos_profile_name=None, branch=None):
    """Top-level resolver. Picks the URY or HRMS backend based on the
    POS Profile's `custom_shift_system_mode`. Returns a dict (see the
    backend helpers for the shape) or None when no shift is assigned
    for this user today.
    """
    mode = _shift_system_mode(pos_profile_name)
    if mode == "URY Shift":
        return _resolve_active_shift_for_user_ury(user, branch=branch)
    if mode == "HRMS Shift Type":
        return _resolve_active_shift_for_user_hrms(user, branch=branch)
    return None


def _seconds_to_hhmm(secs):
    """Render a seconds-since-midnight value as 'HH:MM' (24h)."""
    if secs is None:
        return None
    secs = int(secs) % (24 * 3600)
    h = secs // 3600
    m = (secs % 3600) // 60
    return f"{h:02d}:{m:02d}"


@frappe.whitelist()
def get_shift_status(terminal=None):
    """Return the current shift status for the logged-in user on the
    given terminal. Drives the React POS shift banner + the open-time
    gate.

    Response shape::

        {
            "mode": "Disabled" | "URY Shift" | "HRMS Shift Type",
            "bypass": True/False,         # admin bypass
            "has_shift": True/False,
            "shift_name": "Morning Shift" or null,
            "branch": "Accra" or null,
            "start_time": "06:00" or null,     # 24h HH:MM
            "end_time":   "14:00" or null,
            "now": "10:32",
            "can_open": True/False,            # POS Opening Entry allowed right now
            "status": "before_window" | "in_window" | "running" | "after_end" | "outside" | "no_shift" | "disabled" | "bypass",
            "reason": short string or null,
        }
    """
    user = frappe.session.user
    pos_profile = None
    branch = None
    if terminal:
        pos_profile = frappe.db.get_value(
            "URY POS Terminal", terminal, "pos_profile"
        )
        branch = frappe.db.get_value(
            "URY POS Terminal", terminal, "branch"
        )
    else:
        try:
            branch = getBranch()
        except Exception:
            branch = None

    mode = _shift_system_mode(pos_profile)
    now = _now_local()
    now_hhmm = f"{now.hour:02d}:{now.minute:02d}"

    if mode == "Disabled":
        return {
            "mode": mode,
            "bypass": False,
            "has_shift": False,
            "shift_name": None,
            "branch": branch,
            "start_time": None,
            "end_time": None,
            "now": now_hhmm,
            "can_open": True,
            "status": "disabled",
            "reason": None,
        }

    if _is_shift_admin(user):
        return {
            "mode": mode,
            "bypass": True,
            "has_shift": False,
            "shift_name": None,
            "branch": branch,
            "start_time": None,
            "end_time": None,
            "now": now_hhmm,
            "can_open": True,
            "status": "bypass",
            "reason": "Administrator / System Manager bypass",
        }

    info = _resolve_active_shift_for_user(
        user, pos_profile_name=pos_profile, branch=branch
    )
    if not info:
        return {
            "mode": mode,
            "bypass": False,
            "has_shift": False,
            "shift_name": None,
            "branch": branch,
            "start_time": None,
            "end_time": None,
            "now": now_hhmm,
            "can_open": False,
            "status": "no_shift",
            "reason": _("No shift is assigned to you today."),
        }

    # Status decisions run off the datetime fields so cross-midnight
    # shifts work. Display fields (start_time, end_time, reason
    # strings) still show the raw HH:MM so the banner says
    # "Ended at 06:00" rather than "Ended at 30:00".
    start_dt = info.get("_start_dt")
    end_dt = info.get("_end_dt")
    open_start_dt = info.get("_open_window_start_dt")
    open_end_dt = info.get("_open_window_end_dt")

    start_secs = info["start_seconds"]
    end_secs = info["end_seconds"]

    if open_start_dt and open_end_dt and open_start_dt <= now <= open_end_dt:
        status = "in_window"
        can_open = True
        reason = None
    elif open_start_dt and now < open_start_dt:
        status = "before_window"
        can_open = False
        reason = _(
            "Your shift opens at {0}. Come back in a few minutes."
        ).format(_seconds_to_hhmm(info["open_window_start_seconds"]))
    elif start_dt and end_dt and start_dt <= now <= end_dt:
        status = "running"
        can_open = False  # past the open window — must have opened earlier
        reason = _(
            "Your shift open window has passed. Speak to a captain "
            "to open the POS for you."
        )
    elif end_dt and now > end_dt:
        status = "after_end"
        can_open = False
        reason = _(
            "Your shift ended at {0}. Time to close the POS."
        ).format(_seconds_to_hhmm(end_secs))
    else:
        status = "outside"
        can_open = False
        reason = _("Outside your assigned shift window.")

    return {
        "mode": mode,
        "bypass": False,
        "has_shift": True,
        "shift_name": info["shift_name"],
        "branch": info["branch"],
        "start_time": _seconds_to_hhmm(start_secs),
        "end_time": _seconds_to_hhmm(end_secs),
        "now": now_hhmm,
        "can_open": can_open,
        "status": status,
        "reason": reason,
        "tolerance_minutes_before": info["tolerance_minutes_before"],
        "tolerance_minutes_after_start": info["tolerance_minutes_after_start"],
        "tolerance_minutes_after_end": info["tolerance_minutes_after_end"],
        "crosses_midnight": info.get("crosses_midnight", 0),
    }


def _enforce_shift_gate_for_open(terminal=None):
    """Throw a clean error if the current user can't open the POS
    Opening Entry right now according to their assigned shift. Called
    from `posOpening` when shift system mode is enabled. Bypasses for
    Administrator + System Manager.
    """
    user = frappe.session.user
    if _is_shift_admin(user):
        return

    pos_profile = None
    branch = None
    if terminal:
        pos_profile = frappe.db.get_value(
            "URY POS Terminal", terminal, "pos_profile"
        )
        branch = frappe.db.get_value(
            "URY POS Terminal", terminal, "branch"
        )

    mode = _shift_system_mode(pos_profile)
    if mode == "Disabled":
        return

    info = _resolve_active_shift_for_user(
        user, pos_profile_name=pos_profile, branch=branch
    )
    if not info:
        frappe.throw(
            _(
                "No shift is assigned to you today. A captain or manager "
                "must create a URY Shift Assignment for your user before "
                "you can open the POS."
            ),
            title=_("No Shift Assigned"),
        )

    now = _now_local()
    open_start_dt = info.get("_open_window_start_dt")
    open_end_dt = info.get("_open_window_end_dt")
    if not (open_start_dt and open_end_dt and open_start_dt <= now <= open_end_dt):
        frappe.throw(
            _(
                "Your shift {0} opens at {1} (window {2}\u2013{3}). "
                "It's currently {4}. POS Opening Entry can only be "
                "created inside that window."
            ).format(
                info["shift_name"],
                _seconds_to_hhmm(info["start_seconds"]),
                _seconds_to_hhmm(info["open_window_start_seconds"]),
                _seconds_to_hhmm(info["open_window_end_seconds"]),
                f"{now.hour:02d}:{now.minute:02d}",
            ),
            title=_("Outside Shift Window"),
        )

