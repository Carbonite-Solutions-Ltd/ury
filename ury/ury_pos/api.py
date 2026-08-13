import frappe
import json
from frappe import _
from frappe.utils import flt
from datetime import date, datetime, timedelta



@frappe.whitelist()
def getTable(room):
    """Return the top-level tables in `room` for the current branch.

    Merged sources (tables whose `merged_into` is set) are excluded so
    the POS grid only shows master tables. Each row also carries a
    `merge_info` object for master tables that have an Active merge
    log, so the frontend can render the "Merged +N" badge without an
    extra round-trip. See CLAUDE.md "Fixes log" 2026-04-11.

    **Ordering is NATURAL (numeric), not lexicographic.** Table names end
    in a number ("MR-Tab 1" … "MR-Tab 30"), and a plain `ORDER BY t.name`
    compares them as TEXT — so "MR-Tab 10" sorts before "MR-Tab 2" and
    the grid read 1, 10, 11 … 19, 2, 20 … 29, 3, 30, 4. Table 3 ended up
    near the bottom, which is confusing on a busy floor.

    Sorting on the trailing digits fixes it for any prefix and any
    starting number, so a room numbered 37-50 or 51-70 stays in order
    too. `REGEXP_SUBSTR` anchors on the END of the name specifically so a
    digit in the PREFIX can't hijack the sort (a room coded "R2-Tab 5"
    must sort on 5, not 25). Names with no trailing number fall back to
    999999 and sort alphabetically at the end.

    The `NULLIF` is load-bearing and easy to drop by mistake:
    `REGEXP_SUBSTR` returns an EMPTY STRING (not NULL) when nothing
    matches, and `CAST('' AS UNSIGNED)` is 0 — so without it the COALESCE
    never fires and a non-numeric name like "Bar Counter" sorts FIRST
    instead of last.
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
        ORDER BY
            COALESCE(
                CAST(NULLIF(REGEXP_SUBSTR(t.name, '[0-9]+$'), '') AS UNSIGNED),
                999999
            ),
            t.name
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

    # A self-serve waiter isn't in role_allowed_for_billing, but she DOES
    # place orders and so needs the same order-type-wise / room-wise menu
    # resolution as a cashier — otherwise she falls through to the
    # restaurant's default active_menu, which is unset on restaurants that
    # use per-order-type menus, and the menu fails to load. 2026-07-15.
    cashier = any(
        role.role in user_role for role in pos_profile.role_allowed_for_billing
    ) or bool(_get_self_waiter_for_user())
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

def _resolve_orders_scope(terminal, cashier, self_waiter=None):
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

    # NOTE: every clause returned here is FULLY qualified with the `pi.`
    # table alias (the callers splice `scope_clause` directly, no prefix)
    # so the waiter branch below can use a parenthesised OR without the
    # `pi.(...)` splice breaking. 2026-07-15.

    # Waiter-only users (self-serve waiters) see orders they placed
    # themselves (owner) AND orders a cashier rang on their behalf
    # (custom_waiter = their waiter record). So a cashier-for-waiter
    # order shows in BOTH the cashier's list (owner) and the waiter's
    # (custom_waiter). Non-waiters get None here. 2026-07-15.
    # The caller may pass a precomputed self_waiter to avoid a second
    # lookup (getPosInvoice needs it for the terminal-skip decision too).
    if self_waiter is None:
        self_waiter = _get_self_waiter_for_user(requesting_user)
    if self_waiter:
        mine_clause = (
            "(pi.owner = %s OR pi.custom_waiter = %s)",
            [requesting_user, self_waiter["name"]],
        )
    else:
        mine_clause = ("pi.owner = %s", [requesting_user])

    if not cashier or cashier == "mine":
        return mine_clause

    if not is_captain:
        # Cashier requested a wider scope they aren't allowed to see.
        return mine_clause

    # Filter by a specific WAITER. The dropdown sends "waiter:<record>" so
    # we can tell it apart from a cashier user id. A waiter's orders are
    # keyed by custom_waiter (set on BOTH her self-placed orders and orders
    # a cashier rang for her), so this shows everything she served. Captain-
    # only (we're past the is_captain gate). 2026-07-15.
    if isinstance(cashier, str) and cashier.startswith("waiter:"):
        waiter_name = cashier.split(":", 1)[1]
        if not waiter_name:
            return mine_clause
        return ("pi.custom_waiter = %s", [waiter_name])

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
        # "All" now means all staff, not just cashiers: include every order
        # that has a waiter assigned (self-placed by a waiter OR rung for
        # her by a cashier) alongside the cashiers' own orders. Waiters ring
        # orders now, so excluding them made "All" hide real activity.
        # 2026-07-15.
        if not cashier_user_ids:
            return ("pi.custom_waiter IS NOT NULL", [])
        placeholders = ", ".join(["%s"] * len(cashier_user_ids))
        return (
            f"(pi.owner IN ({placeholders}) OR pi.custom_waiter IS NOT NULL)",
            cashier_user_ids,
        )

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
    return ("pi.owner = %s", [cashier])


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
    """Return the staff options for the captain's "Cashier" filter dropdown
    on the Orders page: cashier users on this terminal's branch PLUS every
    active waiter (waiters ring orders now too).

    Each row: ``{user, full_name, kind}`` where ``kind`` is ``"cashier"`` or
    ``"waiter"``. For a waiter the ``user`` value is ``"waiter:<record>"`` —
    the token the scope resolver decodes to filter by ``custom_waiter``. For
    a cashier it's the plain user id (filtered by ``owner``). Sorted with
    cashiers first, then waiters, each by full_name. 2026-07-15.
    """
    if not terminal:
        return []

    terminal_branch = frappe.db.get_value(
        "URY POS Terminal", terminal, "branch"
    )
    if not terminal_branch:
        return []

    rows = [
        {"user": c["user"], "full_name": c["full_name"], "kind": "cashier"}
        for c in _get_cashier_users_on_branch(terminal_branch)
    ]

    # URY Waiter has no branch link, so list every active waiter — the
    # orders query is already branch-scoped, so a waiter with no orders on
    # this branch simply returns nothing when selected.
    waiters = frappe.get_all(
        "URY Waiter",
        filters={"disabled": 0},
        fields=["name", "full_name"],
        order_by="full_name asc",
    )
    rows += [
        {
            "user": f"waiter:{w['name']}",
            "full_name": w["full_name"] or w["name"],
            "kind": "waiter",
        }
        for w in waiters
    ]

    return rows


# ───────────────────────────────────────────────────────────────────
# Invoice transfer workflow (2026-06-05)
#
# Captains offer unpaid drafts to another cashier at shift close; the
# receiving cashier approves/rejects from the Orders page "Incoming
# Transfers" filter. The URY Invoice Transfer doctype is the source of
# truth + audit chain; the POS Invoice carries a denormalized
# custom_transfer_status flag for the Orders page. See CLAUDE.md
# "Fixes log" 2026-06-05.
# ───────────────────────────────────────────────────────────────────


def _user_is_captain(user=None):
    user = user or frappe.session.user
    roles = set(frappe.get_roles(user))
    captain_roles = {"Administrator", "System Manager", "URY Manager", "URY Captain"}
    return user == "Administrator" or bool(roles & captain_roles)


def _user_can_close_shift(user=None):
    """Who may close the day: **URY Manager only**, plus Administrator /
    System Manager as a break-glass (2026-08-05).

    Deliberately NARROWER than `_user_is_captain` - a URY Captain can no
    longer close. This REVERSES the soft gate agreed on 2026-07-29,
    which warned and recorded but never blocked. That reasoning was
    built around a lone captain being unavailable; URY Manager is in
    practice the widest of the three URY roles, so a hard gate here does
    not strand a shift the way a captain-only rule would have.

    ⚠ The risk that remains is POS Profile's `custom_daily_pos_close`.
    With that ON, an unclosed previous day blocks the POS outright, so
    "no manager last night" becomes "nobody can trade this morning".
    Administrator and System Manager are retained precisely so that
    state is recoverable from the desk. Do not remove them without
    providing another way out.
    """
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    return bool(set(frappe.get_roles(user)) & {"System Manager", "URY Manager"})


def _require_shift_closer():
    """Hard gate on closing. The POS hides End Shift and the closing
    dialog refuses, but this is the half that actually enforces it -
    the endpoint is whitelisted and reachable directly."""
    if not _user_can_close_shift():
        frappe.throw(
            _(
                "Only an {0} can close the day. Closing counts the drawer "
                "and consolidates this shift's sales into the accounts. "
                "Ask a manager to close this shift."
            ).format(_("URY Manager")),
            title=_("Not Permitted"),
        )


def _excluded_from_blocking(transfer_rows, current_user):
    """Pure decision: given transfer rows [{invoice, status, to_user}],
    return the set of invoices that should NOT block `current_user`'s
    shift close.

    A draft is 'in the transfer pipeline' (excluded) when it has:
      - a Pending transfer (offered, awaiting the receiver — also the
        idempotency guard against double-transfer on a repeated close), or
      - an Approved transfer to a user OTHER than `current_user` (already
        handed off).
    An Approved transfer whose to_user IS `current_user` is NOT excluded:
    they accepted it, it's their draft now and still blocks them.
    """
    excluded = set()
    for row in transfer_rows:
        status = row.get("status")
        invoice = row.get("invoice")
        if status == "Pending":
            excluded.add(invoice)
        elif status == "Approved" and row.get("to_user") != current_user:
            excluded.add(invoice)
    return excluded


def _drafts_with_active_transfer(invoice_names, current_user):
    """Return the subset of `invoice_names` that already have an active
    transfer for `current_user`'s close. Thin DB wrapper around the pure
    `_excluded_from_blocking` decision."""
    if not invoice_names:
        return set()
    rows = frappe.db.sql(
        """
        SELECT invoice, status, to_user
        FROM `tabURY Invoice Transfer`
        WHERE invoice IN %(names)s
          AND status IN ('Pending', 'Approved')
        """,
        {"names": tuple(invoice_names)},
        as_dict=True,
    )
    return _excluded_from_blocking([dict(r) for r in rows], current_user)


def _get_captain_users_on_branch(branch_name):
    """Like _get_cashier_users_on_branch but only URY Captain / URY
    Manager — used to pick a 'captain queue' owner when a transfer is
    rejected."""
    rows = frappe.db.sql(
        """
        SELECT DISTINCT u.name AS user, u.full_name AS full_name
        FROM `tabURY User` AS uu
        INNER JOIN `tabBranch` AS b ON uu.parent = b.name
        INNER JOIN `tabUser` AS u ON u.name = uu.user
        INNER JOIN `tabHas Role` AS hr ON hr.parent = u.name
        WHERE b.branch = %s
        AND hr.role IN ('URY Captain', 'URY Manager')
        AND u.enabled = 1
        ORDER BY u.full_name, u.name
        """,
        (branch_name,),
        as_dict=True,
    )
    return [{"user": r.user, "full_name": r.full_name or r.user} for r in rows]


def _transfer_hop_count(invoice):
    """How many APPROVED (landed) transfers this invoice has had so far.
    A rejected transfer doesn't consume a hop."""
    return frappe.db.count(
        "URY Invoice Transfer", {"invoice": invoice, "status": "Approved"}
    )


@frappe.whitelist()
def get_incoming_transfers(terminal=None, posting_date=None):
    """Pending invoice transfers addressed to the current user, for the
    Orders page 'Incoming Transfers' filter.

    Branch-scoped (a cashier only sees transfers on their branch). NOT
    terminal/date scoped — the receiver may be on any terminal and the
    transfer is theirs to resolve regardless. The `terminal`/
    `posting_date` params are accepted (the Orders page passes them
    uniformly) but ignored. Transfers whose invoice is no longer a Draft
    (paid / cancelled elsewhere) are hidden so the receiver never acts
    on a dead one. Rows are shaped like getPosInvoice plus a
    `transfer_meta` block.
    """
    me = frappe.session.user
    branch = getBranch()
    rows = frappe.db.sql(
        """
        SELECT
            pi.name, pi.invoice_printed, pi.grand_total, pi.restaurant_table,
            pi.cashier, pi.waiter, pi.net_total, pi.posting_time,
            pi.total_taxes_and_charges, pi.customer, pi.customer_name,
            pi.status, pi.mobile_number, pi.posting_date, pi.rounded_total,
            pi.order_type, pi.custom_order_status, pi.custom_terminal,
            pi.owner, pi.is_return, pi.return_against,
            pi.custom_charge_to_room, pi.custom_hotel_room,
            pi.custom_cancel_pending,
            pi.custom_order_contact_name, pi.custom_order_contact_mobile,
            pi.custom_ihotel_profile, pi.custom_transfer_status,
            t.name AS transfer_name, t.from_user AS transfer_from_user,
            t.requested_at AS transfer_requested_at,
            t.hop_number AS transfer_hop_number,
            fu.full_name AS transfer_from_full_name
        FROM `tabURY Invoice Transfer` AS t
        INNER JOIN `tabPOS Invoice` AS pi ON pi.name = t.invoice
        LEFT JOIN `tabUser` AS fu ON fu.name = t.from_user
        WHERE t.status = 'Pending'
          AND t.to_user = %(me)s
          AND t.branch = %(branch)s
          AND pi.docstatus = 0
          AND pi.status = 'Draft'
        ORDER BY t.requested_at DESC
        """,
        {"me": me, "branch": branch},
        as_dict=True,
    )
    for r in rows:
        r["transfer_meta"] = {
            "transfer": r.pop("transfer_name", None),
            "from_user": r.pop("transfer_from_user", None),
            "from_full_name": r.pop("transfer_from_full_name", None)
            or r.get("owner"),
            "requested_at": str(r.pop("transfer_requested_at", "") or ""),
            "hop_number": r.pop("transfer_hop_number", None),
        }
    return {"data": rows, "next": False}


@frappe.whitelist()
def get_incoming_transfer_count():
    """Count of Pending transfers addressed to the current user, for the
    Orders sidebar badge. Only counts ones whose invoice is still a
    live Draft."""
    me = frappe.session.user
    branch = getBranch()
    rows = frappe.db.sql(
        """
        SELECT COUNT(t.name) AS c
        FROM `tabURY Invoice Transfer` AS t
        INNER JOIN `tabPOS Invoice` AS pi ON pi.name = t.invoice
        WHERE t.status = 'Pending'
          AND t.to_user = %(me)s
          AND t.branch = %(branch)s
          AND pi.docstatus = 0
          AND pi.status = 'Draft'
        """,
        {"me": me, "branch": branch},
        as_dict=True,
    )
    return {"count": int(rows[0].c if rows else 0)}


@frappe.whitelist()
def approve_transfer(transfer):
    """Receiving cashier accepts a Pending transfer. Re-homes the draft
    to them (owner + cashier), clears the terminal so it surfaces on
    their Orders page, stamps the denormalized status, and marks the
    transfer Approved."""
    if not frappe.db.exists("URY Invoice Transfer", transfer):
        frappe.throw(
            _("Transfer '{0}' not found.").format(transfer),
            frappe.DoesNotExistError,
        )
    doc = frappe.get_doc("URY Invoice Transfer", transfer)
    if doc.status != "Pending":
        frappe.throw(
            _("This transfer has already been {0}.").format(doc.status.lower()),
            title=_("Already Resolved"),
        )
    me = frappe.session.user
    if me != doc.to_user and not _user_is_captain(me):
        frappe.throw(
            _(
                "Only the cashier this order was offered to (or a captain) "
                "can approve it."
            ),
            frappe.PermissionError,
            title=_("Not Allowed"),
        )
    inv = frappe.db.get_value(
        "POS Invoice", doc.invoice, ["status", "docstatus"], as_dict=True
    )
    if not inv or inv.docstatus != 0 or inv.status != "Draft":
        frappe.throw(
            _(
                "Order {0} is no longer an open draft and can't be transferred."
            ).format(doc.invoice),
            title=_("Order No Longer Transferable"),
        )

    target_full_name = (
        frappe.db.get_value("User", doc.to_user, "full_name") or doc.to_user
    )
    now_dt = frappe.utils.now_datetime()
    frappe.db.set_value(
        "POS Invoice",
        doc.invoice,
        {
            "owner": doc.to_user,
            "cashier": target_full_name,
            "custom_terminal": None,
            "posting_date": now_dt.date(),
            "posting_time": now_dt.time(),
            "custom_transfer_status": "Approved",
            "remarks": f"Transfer accepted by {doc.to_user} "
            f"(offered by {doc.from_user})",
        },
        update_modified=True,
    )
    frappe.db.set_value(
        "URY Invoice Transfer",
        doc.name,
        {"status": "Approved", "resolved_by": me, "resolved_at": now_dt},
        update_modified=True,
    )
    frappe.db.commit()
    return {"transfer": doc.name, "invoice": doc.invoice, "status": "Approved"}


@frappe.whitelist()
def reject_transfer(transfer, reason=None):
    """Receiving cashier declines a Pending transfer. The draft is
    re-homed to a branch captain (the 'captain queue') so the original
    sender — who may already have closed their shift — isn't stuck
    holding it."""
    if not frappe.db.exists("URY Invoice Transfer", transfer):
        frappe.throw(
            _("Transfer '{0}' not found.").format(transfer),
            frappe.DoesNotExistError,
        )
    doc = frappe.get_doc("URY Invoice Transfer", transfer)
    if doc.status != "Pending":
        frappe.throw(
            _("This transfer has already been {0}.").format(doc.status.lower()),
            title=_("Already Resolved"),
        )
    me = frappe.session.user
    if me != doc.to_user and not _user_is_captain(me):
        frappe.throw(
            _(
                "Only the cashier this order was offered to (or a captain) "
                "can reject it."
            ),
            frappe.PermissionError,
            title=_("Not Allowed"),
        )

    # Pick a captain for the queue: prefer the original sender if they're
    # a captain, else the first captain on the branch.
    captains = _get_captain_users_on_branch(doc.branch)
    captain_users = {c["user"] for c in captains}
    if doc.from_user in captain_users:
        queue_user = doc.from_user
    elif captains:
        queue_user = captains[0]["user"]
    else:
        frappe.throw(
            _(
                "No captain is configured on branch {0} to hold rejected "
                "orders. Add a URY Captain to the branch first."
            ).format(doc.branch),
            title=_("No Captain Available"),
        )

    queue_full_name = (
        frappe.db.get_value("User", queue_user, "full_name") or queue_user
    )
    now_dt = frappe.utils.now_datetime()
    note = f"Transfer rejected by {me}"
    if reason:
        note = f"{note}: {reason}"
    frappe.db.set_value(
        "POS Invoice",
        doc.invoice,
        {
            "owner": queue_user,
            "cashier": queue_full_name,
            "custom_terminal": None,
            "custom_transfer_status": "Rejected",
            "remarks": note,
        },
        update_modified=True,
    )
    transfer_note = (doc.transfer_note or "")
    transfer_note = f"{transfer_note}\n{note}".strip()
    frappe.db.set_value(
        "URY Invoice Transfer",
        doc.name,
        {
            "status": "Rejected",
            "resolved_by": me,
            "resolved_at": now_dt,
            "transfer_note": transfer_note,
        },
        update_modified=True,
    )
    frappe.db.commit()
    return {
        "transfer": doc.name,
        "invoice": doc.invoice,
        "status": "Rejected",
        "queued_to": queue_user,
    }


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
    limit = int(limit) + 1
    limit_start = int(limit_start)

    # A self-serve waiter's orders are already scoped to HER (owner OR
    # custom_waiter). They get their branch + terminal stamp from the table
    # / till she rang on, which need NOT match her own URY User branch — so
    # branch/terminal-filtering her was HIDING her own orders (the admin's
    # "waiter:" filter worked because it uses the admin's branch, where the
    # orders actually live). Skip both filters for a waiter, and don't
    # hard-fail if she isn't linked to a branch. 2026-07-15.
    session_waiter = _get_self_waiter_for_user()
    is_waiter = bool(session_waiter)

    if is_waiter:
        try:
            branch = getBranch()
        except Exception:
            branch = None
    else:
        branch = getBranch()

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
        # "Pending" = every unpaid draft (take-away AND dine-in table),
        # unlike "Draft"/"Unbilled" which split on invoice_printed +
        # restaurant_table. Used for the waiter's My Orders view: a
        # waiter doesn't bill, so the printed/unbilled distinction is
        # meaningless to her — she just wants "not yet paid" vs "paid".
        # 2026-07-15.
        "Pending": (
            "Draft",
            "AND (pi.custom_charge_to_room IS NULL OR pi.custom_charge_to_room = 0)",
        ),
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

    where_parts = ["pi.status = %s"]
    params = [db_status]
    if branch and not is_waiter:
        where_parts.insert(0, "pi.branch = %s")
        params.insert(0, branch)

    # Hide invoices that have been merged into another. The master
    # remains visible; only the dormant sources are filtered out.
    where_parts.append(
        "(pi.custom_merged_into IS NULL OR pi.custom_merged_into = '')"
    )

    if terminal and not is_waiter:
        # Defensive null fallback: orders that pre-date the
        # custom_terminal field (or that somehow slipped through
        # without a terminal stamp) still show up on every terminal of
        # their branch. The branch filter above keeps the scope
        # bounded — an Accra user never sees Tamale orders. Without
        # this fallback, historical orders disappear from the Orders
        # page entirely once per-terminal scoping is enabled. See
        # CLAUDE.md "Fixes log" 2026-04-09. Waiters are exempt (their
        # orders span terminals — see above).
        where_parts.append(
            "(pi.custom_terminal = %s OR pi.custom_terminal IS NULL OR pi.custom_terminal = '')"
        )
        params.append(terminal)
    if posting_date:
        where_parts.append("pi.posting_date = %s")
        params.append(posting_date)

    scope_clause, scope_params = _resolve_orders_scope(
        terminal, cashier, self_waiter=session_waiter
    )
    where_parts.append(scope_clause)
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
            pi.custom_cancel_pending,
            pi.custom_order_contact_name, pi.custom_order_contact_mobile,
            pi.custom_ihotel_profile, pi.custom_print_count, pi.custom_waiter,
            pi.cancel_reason,
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

    query_str = f"%{query.lower()}%"

    # Waiters are exempt from the branch + terminal filters (their orders
    # are stamped from the table/till they rang on, not their own URY User
    # branch). Same rationale as getPosInvoice. 2026-07-15.
    session_waiter = _get_self_waiter_for_user()
    is_waiter = bool(session_waiter)

    if is_waiter:
        try:
            branch = getBranch()
        except Exception:
            branch = None
    else:
        branch = getBranch()

    db_status = "Paid" if status == "Recently Paid" else status
    # Room Charges is a Draft-level pseudo-status; map it to Draft for
    # the DB query and let the extra WHERE clause filter by the custom
    # charge_to_room flag. See CLAUDE.md "Fixes log" 2026-04-12.
    if status == "Room Charges":
        db_status = "Draft"
    # "Pending" = all unpaid drafts (waiter My Orders). See getPosInvoice.
    if status == "Pending":
        db_status = "Draft"
    # Pending KOTs is also a Draft-level pseudo-status — docstatus=0
    # with at least one un-printed URY KOT child. See Phase B of the
    # 2026-04-16 print revamp.
    if status == "Pending KOTs":
        db_status = "Draft"
    where_parts = ["pi.status = %s"]
    params = [db_status]
    if branch and not is_waiter:
        where_parts.insert(0, "pi.branch = %s")
        params.insert(0, branch)

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

    if terminal and not is_waiter:
        # Same defensive null fallback as getPosInvoice — see
        # CLAUDE.md "Fixes log" 2026-04-09. Waiters exempt (2026-07-15).
        where_parts.append(
            "(pi.custom_terminal = %s OR pi.custom_terminal IS NULL OR pi.custom_terminal = '')"
        )
        params.append(terminal)
    if posting_date:
        where_parts.append("pi.posting_date = %s")
        params.append(posting_date)

    scope_clause, scope_params = _resolve_orders_scope(
        terminal, cashier, self_waiter=session_waiter
    )
    where_parts.append(scope_clause)
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
            pi.custom_cancel_pending,
            pi.custom_order_contact_name, pi.custom_order_contact_mobile,
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


def _resolve_terminal_bill_printer(pos_profile_doc, terminal):
    """Pick the bill printer for the requesting terminal.

    A POS Profile can carry a per-terminal bill-printer table
    (`custom_bill_printers`: terminal -> URY Printer). When the printing
    terminal has a row there, that printer is used so several terminals
    sharing one profile each print receipts to their OWN physical printer.
    Falls back to the single `custom_bill_printer` field when the terminal
    isn't listed (or no terminal was supplied). See CLAUDE.md "Fixes log"
    2026-06-10.
    """
    if terminal:
        for row in (pos_profile_doc.get("custom_bill_printers") or []):
            if row.get("terminal") == terminal and row.get("bill_printer"):
                return row.bill_printer
    return pos_profile_doc.get("custom_bill_printer") or None


# ---------------------------------------------------------------------------
# Waiter feature (2026-06-10)
# ---------------------------------------------------------------------------


def _get_self_waiter_for_user(user=None):
    """The URY Waiter this user rings orders AS, or None (2026-07-14).

    A "self-serve waiter" is a NON-elevated user (not Administrator /
    System Manager / URY Manager / URY Captain) who has the **URY Waiter**
    role AND is linked to a URY Waiter record (`URY Waiter.user`). For such
    a user the POS auto-assigns her own waiter to every order and hides the
    picker. Cashiers, captains, managers and admins get None — they pick the
    waiter as before. Returns {name, full_name, mobile_number} or None.
    """
    user = user or frappe.session.user
    if user == "Administrator":
        return None
    roles = set(frappe.get_roles(user))
    # Elevated roles always pick, even if somehow linked to a waiter.
    if roles & {"System Manager", "URY Manager", "URY Captain"}:
        return None
    if "URY Waiter" not in roles:
        return None
    return frappe.db.get_value(
        "URY Waiter",
        {"user": user, "disabled": 0},
        ["name", "full_name", "mobile_number"],
        as_dict=True,
    )


@frappe.whitelist()
def get_self_waiter():
    """Whitelisted wrapper around _get_self_waiter_for_user for the session
    user. Returns the linked waiter dict or None."""
    return _get_self_waiter_for_user()


@frappe.whitelist()
def get_waiters(query=None):
    """Active URY Waiters for the order-time picker. Optional name/mobile
    filter. Returns [{name, full_name, mobile_number}]."""
    or_filters = None
    if query:
        like = f"%{query.strip()}%"
        or_filters = {
            "full_name": ["like", like],
            "mobile_number": ["like", like],
            "name": ["like", like],
        }
    return frappe.get_all(
        "URY Waiter",
        filters={"disabled": 0},
        or_filters=or_filters,
        fields=["name", "full_name", "mobile_number"],
        order_by="full_name asc",
        limit_page_length=100,
    )


@frappe.whitelist()
def create_waiter(full_name, mobile_number=None):
    """Quick-add a waiter from the POS. Returns the created waiter row."""
    full_name = (full_name or "").strip()
    if not full_name:
        frappe.throw(_("Waiter name is required."), title=_("Invalid Waiter"))
    if frappe.db.exists("URY Waiter", full_name):
        frappe.throw(
            _("A waiter named '{0}' already exists.").format(full_name),
            title=_("Duplicate Waiter"),
        )
    doc = frappe.get_doc(
        {
            "doctype": "URY Waiter",
            "full_name": full_name,
            "mobile_number": (mobile_number or "").strip() or None,
        }
    )
    doc.insert()
    return {
        "name": doc.name,
        "full_name": doc.full_name,
        "mobile_number": doc.mobile_number,
    }


@frappe.whitelist()
def reassign_order_waiter(invoice, waiter):
    """Move a draft order to a different waiter — drag-and-drop on the
    Waiters page (cashier picked the wrong waiter). Stamps
    POS Invoice.custom_waiter. Only DRAFT (unpaid) orders can be
    reassigned; a plain cashier can only re-home their OWN orders, captains/
    managers/admins can re-home any. 2026-06-12.
    """
    if not invoice or not waiter:
        frappe.throw(_("Order and waiter are both required."))
    inv = frappe.db.get_value(
        "POS Invoice",
        invoice,
        ["docstatus", "status", "owner", "custom_waiter"],
        as_dict=True,
    )
    if not inv:
        frappe.throw(
            _("Order {0} not found.").format(invoice), title=_("Not Found")
        )
    if inv.docstatus != 0 or inv.status != "Draft":
        frappe.throw(
            _("Only unpaid (draft) orders can be moved to another waiter."),
            title=_("Order Not Editable"),
        )
    if not frappe.db.exists("URY Waiter", waiter):
        frappe.throw(
            _("Waiter '{0}' not found.").format(waiter),
            title=_("Invalid Waiter"),
        )
    roles = set(frappe.get_roles(frappe.session.user))
    is_captain = frappe.session.user == "Administrator" or bool(
        roles & {"System Manager", "URY Manager", "URY Captain"}
    )
    if not is_captain and inv.owner != frappe.session.user:
        frappe.throw(
            _("You can only move your own orders."),
            title=_("Not Permitted"),
        )
    if inv.custom_waiter == waiter:
        return {"invoice": invoice, "waiter": waiter, "changed": 0}
    frappe.db.set_value(
        "POS Invoice", invoice, "custom_waiter", waiter, update_modified=True
    )
    return {"invoice": invoice, "waiter": waiter, "changed": 1}


@frappe.whitelist()
def get_waiters_with_pending_orders(include_empty=0):
    """For the Waiters page: every active waiter plus their DRAFT (unpaid)
    POS Invoices, each with its items. Branch-scoped. Orders charged-to-room
    (iHotel) are excluded — they aren't pending payment.
    Returns [{name, full_name, mobile_number, orders: [...]}].

    SCOPE CHANGE (2026-07-16): this used to also filter `pi.owner =
    session.user` ("only orders the CURRENT cashier rang", added 2026-06-11).
    That made sense when cashiers rang every order on a waiter's behalf, but
    self-serve waiters (2026-07-14) own their own orders — so the owner
    filter hid every waiter-placed order from the cashier AND the captain,
    i.e. from exactly the people who use this page to collect the money and
    key in the payment. Now branch-scoped only.

    `include_empty`: when truthy, ALSO return active waiters that have no
    pending orders — needed so the drag-and-drop Waiters page can use every
    waiter as a drop target (move a mis-assigned order to a waiter who has
    no orders yet). Default 0 keeps the historical "only waiters with
    pending orders" behavior."""
    branch = getBranch()
    waiters = frappe.get_all(
        "URY Waiter",
        filters={"disabled": 0},
        fields=["name", "full_name", "mobile_number"],
        order_by="full_name asc",
    )
    drafts = frappe.db.sql(
        """
        SELECT pi.name, pi.custom_waiter AS waiter, pi.customer,
               pi.customer_name, pi.grand_total, pi.restaurant_table,
               pi.order_type, pi.invoice_printed, pi.creation
        FROM `tabPOS Invoice` pi
        WHERE pi.branch = %(branch)s
          AND pi.docstatus = 0
          AND pi.status = 'Draft'
          AND COALESCE(pi.custom_waiter, '') != ''
          AND (pi.custom_charge_to_room IS NULL OR pi.custom_charge_to_room = 0)
          AND (pi.custom_merged_into IS NULL OR pi.custom_merged_into = '')
        ORDER BY pi.creation DESC
        """,
        {"branch": branch},
        as_dict=True,
    )
    by_waiter = {}
    for d in drafts:
        d["items"] = frappe.get_all(
            "POS Invoice Item",
            filters={"parent": d["name"]},
            fields=["item_name", "qty", "rate", "amount"],
            order_by="idx asc",
        )
        d["creation"] = str(d.get("creation") or "")
        by_waiter.setdefault(d["waiter"], []).append(d)
    # Only surface waiters who actually have pending orders — unless
    # include_empty is set (drag-and-drop needs every waiter as a target).
    show_all = bool(int(include_empty or 0))
    return [
        {
            "name": w["name"],
            "full_name": w["full_name"],
            "mobile_number": w["mobile_number"],
            "orders": by_waiter.get(w["name"], []),
        }
        for w in waiters
        if show_all or by_waiter.get(w["name"])
    ]


@frappe.whitelist()
def get_waiter_pending_order_count():
    """Pending (Draft) orders that have a waiter — drives the Waiters navbar
    badge. Cheap COUNT, branch-scoped. Matches
    `get_waiters_with_pending_orders`: the per-cashier `owner` filter was
    dropped on 2026-07-16 because self-serve waiters own their own orders,
    which hid them from the cashier/captain who collects the payment."""
    branch = getBranch()
    row = frappe.db.sql(
        """
        SELECT COUNT(pi.name) AS c
        FROM `tabPOS Invoice` pi
        WHERE pi.branch = %(branch)s
          AND pi.docstatus = 0
          AND pi.status = 'Draft'
          AND COALESCE(pi.custom_waiter, '') != ''
          AND (pi.custom_charge_to_room IS NULL OR pi.custom_charge_to_room = 0)
          AND (pi.custom_merged_into IS NULL OR pi.custom_merged_into = '')
        """,
        {"branch": branch},
        as_dict=True,
    )
    return {"count": int(row[0].c if row else 0)}


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
        # Returns master switch (2026-06-05). Default OFF (field default
        # = 0) so a fresh / freshly-migrated profile keeps returns hidden
        # everywhere until an admin turns the feature on.
        enable_returns = int(pos_profiles.get("custom_enable_returns") or 0)
        # Per-invoice transfer hop cap (2026-06-05). Default 2 when the
        # field isn't set. 0 disables transfers entirely at shift close.
        raw_max_transfers = pos_profiles.get("custom_max_invoice_transfers")
        max_invoice_transfers = (
            2 if raw_max_transfers is None else int(raw_max_transfers or 0)
        )
        # Waiter feature (2026-06-10). When on, the React POS pops a waiter
        # picker at new-order creation.
        use_waiter = int(pos_profiles.get("custom_use_waiter") or 0)
        # Per-cashier bill reprint cap (2026-06-10). Default 3 when unset.
        raw_max_prints = pos_profiles.get("custom_max_bill_prints")
        max_bill_prints = (
            3 if raw_max_prints is None else int(raw_max_prints or 0)
        )
        ihotel_enabled = int(pos_profiles.get("custom_ihotel_enabled") or 0)
        ihotel_charge_type = pos_profiles.get("custom_ihotel_charge_type") or None
        shift_system_mode = pos_profiles.get("custom_shift_system_mode") or "Disabled"
        # Minimum screen width (px) to use the POS. 0/unset = no restriction.
        min_screen_width = int(pos_profiles.get("custom_min_screen_width") or 0)
        # Unified print routing (2026-04-16). Expose the new fields
        # so the React POS knows which print path to drive. The
        # resolver / routing logic all lives on the backend — the
        # frontend only needs the mode to pick QZ vs CUPS vs Disabled.
        print_mode = pos_profiles.get("custom_print_mode") or None
        # Per-terminal bill printer (2026-06-10): if this terminal is listed
        # in the profile's custom_bill_printers table, use its printer; else
        # fall back to the single custom_bill_printer.
        bill_printer = _resolve_terminal_bill_printer(pos_profiles, terminal)
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
        # A self-serve waiter is NOT the cashier — she only places orders.
        # Don't hand her id back as `cashier` (sync_order also guards this
        # server-side). The cashier is stamped when a real cashier prints/
        # bills the order. 2026-07-16.
        if _get_self_waiter_for_user():
            cashier = None

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
        # Whether that format actually EXISTS (2026-07-31). Frappe's
        # printview silently falls back to the Standard layout both when
        # the name is blank AND when it names a format that has been
        # renamed or deleted -- the two produce byte-identical output and
        # neither raises. Without this flag the POS cannot tell "no
        # format configured" from "configured, but pointing at nothing",
        # which is exactly the shape of "it isn't using my print format".
        "print_format_exists": bool(
            print_format and frappe.db.exists("Print Format", print_format)
        ),
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
        "custom_enable_returns": enable_returns,
        "custom_max_invoice_transfers": max_invoice_transfers,
        "custom_use_waiter": use_waiter,
        # When the logged-in user is a self-serve waiter (URY Waiter role +
        # linked URY Waiter, non-elevated), the POS auto-assigns her waiter
        # and hides the picker. None for cashiers/captains/managers/admins.
        "self_waiter": _get_self_waiter_for_user(),
        "custom_max_bill_prints": max_bill_prints,
        "custom_min_screen_width": min_screen_width,
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

    **Scope is the POS Profile — not the terminal, and not the user.**

    That is forced on us by ERPNext core, which is the authority here:
    ``POSOpeningEntry.check_open_pos_exists`` refuses to create a second
    entry whenever ``{pos_profile, status: "Open"}`` already matches —
    no user key, no terminal key. And ``check_user_already_assigned``
    additionally refuses to give one user a second open entry anywhere.
    So "one entry per terminal" and "one entry per cashier" are both
    *unsatisfiable* whenever several terminals share a profile: URY
    would keep prompting for an open that ERPNext will always reject.
    That was the open/close deadlock fixed on 2026-07-28 — see the
    CLAUDE.md "Fixes log" entry for the full loop.

    So the model is: **one open POS Opening Entry per POS Profile per
    shift.** Whoever arrives first (typically the captain) opens the
    day; every other cashier/waiter on any terminal of that profile
    just walks in. Per-invoice attribution is not lost — it rides on
    ``POS Invoice.owner`` + ``custom_terminal`` + ``cashier``.

    This is correct under BOTH deployment shapes: when each terminal
    has its own POS Profile, profile-scoping *is* terminal-scoping.

    ``custom_enable_multiple_cashier`` deliberately does NOT affect this
    check any more. It cannot: no flag can make ERPNext accept a second
    open entry on the same profile.

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

    # Per-terminal path. The terminal only tells us WHICH POS Profile
    # to scope against — the profile is the real unit of a shift.
    pos_profile = frappe.db.get_value(
        "URY POS Terminal", terminal, "pos_profile"
    )

    if not pos_profile:
        # Unconfigured terminal. Fall back to the branch-wide check
        # rather than asking for an open we can't scope.
        pos_opening_list = frappe.get_all(
            "POS Opening Entry",
            fields=["name"],
            filters={"branch": branchName, "status": "Open", "docstatus": 1},
            limit=1,
        )
        return 0 if pos_opening_list else 1

    pos_opening_list = frappe.get_all(
        "POS Opening Entry",
        fields=["name"],
        filters={
            "pos_profile": pos_profile,
            "status": "Open",
            "docstatus": 1,
        },
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
      * Created on or after the opening entry's creation — defensive
        against timestamp drift caused by backdated posting_date or
        pre-opening test data polluting the shift.

    That is the WHOLE scope. See the comment in the body for why there
    is deliberately no ``owner`` and no ``custom_terminal`` filter.

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

    # NO owner filter and NO terminal filter — deliberately. (2026-07-28)
    #
    # There is exactly ONE open entry per POS Profile (ERPNext's
    # check_open_pos_exists guarantees it), and it covers every cashier
    # on every terminal of that profile. Narrowing by `owner` or
    # `custom_terminal` would silently EXCLUDE the invoices rung by
    # everyone else / on the other tills — they would never be attached
    # to any closing entry, never consolidate, and quietly rot as
    # unconsolidated POS Invoices that then break the NEXT close.
    #
    # Both filters used to be here and both were orphan bugs on any
    # site running several terminals off one profile. ERPNext's own
    # `validate_pos_invoices` requirement that every invoice be owned by
    # the closing user is satisfied downstream instead, by the ownership
    # normalisation pass in `submit_pos_closing_entry` — which rehomes
    # `owner` to the opener and records the original ringer. That is the
    # right place for it: it keeps the SCOPE honest (everything on the
    # shift) and fixes ownership once, at the boundary.
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

    # Only drafts WITHOUT an active transfer actually block the close.
    # A draft is "in the transfer pipeline" (and so not blocking) when it
    # has a Pending transfer, or an Approved transfer to someone other
    # than the current user. An Approved transfer whose to_user is the
    # current user still blocks them — they accepted it, it's their draft
    # now. See submit_pos_closing_entry for the same logic + the
    # idempotency reasoning. CLAUDE.md "Fixes log" 2026-06-05.
    me = frappe.session.user
    excluded_drafts = _drafts_with_active_transfer([r["name"] for r in draft], me)
    blocking_draft = [r for r in draft if r["name"] not in excluded_drafts]

    draft_list = [
        {
            "name": row["name"],
            "customer": row.get("customer"),
            "customer_name": row.get("customer_name") or row.get("customer"),
            "grand_total": float(row.get("grand_total") or 0),
            "restaurant_table": row.get("restaurant_table"),
            "invoice_printed": int(row.get("invoice_printed") or 0),
        }
        for row in blocking_draft
    ]
    draft_grand_total = sum(r["grand_total"] for r in draft_list)

    # Unpaid drafts always escalate to a CAPTAIN / Manager at shift close,
    # whoever is closing (cashier OR captain). The captain then approves the
    # transfer from the Orders "Incoming Transfers" filter. (2026-06-11: this
    # used to be role-aware — a captain handed off to a cashier — but the
    # target is now always a captain so the responsible supervisor handles
    # leftover orders.) You can't transfer to yourself.
    roles = set(frappe.get_roles(me))
    captain_roles = {"Administrator", "System Manager", "URY Manager", "URY Captain"}
    is_captain = me == "Administrator" or bool(roles & captain_roles)
    transfer_candidates = _get_captain_users_on_branch(opening_doc.branch)
    transfer_candidates = [c for c in transfer_candidates if c["user"] != me]

    max_transfers = int(
        frappe.db.get_value(
            "POS Profile", opening_doc.pos_profile, "custom_max_invoice_transfers"
        )
        or 0
    )

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
        # Transfer flags. `can_transfer` is role-agnostic — anyone can
        # transfer when the profile allows it (max > 0). The targets are
        # always captains/managers now, so the frontend labels the picker
        # "Select a captain" regardless of who's closing. `is_captain` is
        # kept for back-compat / informational use.
        "is_captain": int(is_captain),
        "can_transfer": int(max_transfers > 0),
        "max_invoice_transfers": max_transfers,
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

    _require_shift_closer()

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

    # --- Transfer-before-close guard (reworked 2026-06-10) ------------
    # Anyone closing with unpaid drafts can hand them off. A regular
    # cashier transfers UP to a captain; a captain can transfer to any
    # cashier/captain on the branch. The receiver approves from the Orders
    # page "Incoming Transfers" filter — the invoice owner does NOT change
    # here, it changes on approval (see approve_transfer).
    #
    # A draft only BLOCKS the close when it has no active transfer:
    #   - a Pending transfer (already offered, awaiting the receiver), or
    #   - an Approved transfer to someone ELSE (already handed off).
    # An Approved transfer to the current user still blocks them — they
    # accepted it, it's their draft now. This is also the IDEMPOTENCY
    # guard: ending the shift twice never re-transfers, because the
    # second pass sees the existing Pending transfer and skips it.
    me = frappe.session.user

    excluded_drafts = _drafts_with_active_transfer([r["name"] for r in draft], me)
    blocking = [r for r in draft if r["name"] not in excluded_drafts]
    transfers_created = 0

    if blocking:
        # Unpaid drafts always escalate to a captain/manager at close,
        # whoever is closing (2026-06-11). Must match the candidate set the
        # preview offered.
        target_rows = _get_captain_users_on_branch(opening_doc.branch)
        target_label = _("a captain")
        candidates = {c["user"] for c in target_rows if c["user"] != me}

        if not transfer_to:
            names_str = ", ".join(r["name"] for r in blocking[:5])
            more = f" (+{len(blocking) - 5} more)" if len(blocking) > 5 else ""
            frappe.throw(
                _(
                    "You have {0} unpaid order(s) on this shift: {1}{2}. "
                    "Select {3} to transfer them to before closing."
                ).format(len(blocking), names_str, more, target_label),
                title=_("Transfer Required"),
            )
        if transfer_to == me:
            frappe.throw(
                _("You can't transfer orders to yourself."),
                title=_("Invalid Transfer Target"),
            )
        if transfer_to not in candidates:
            frappe.throw(
                _(
                    "Selected user {0} isn't a valid transfer target "
                    "({1}) on branch {2}."
                ).format(transfer_to, target_label, opening_doc.branch),
                title=_("Invalid Transfer Target"),
            )

        # Per-invoice hop cap. 0 disables transfers entirely.
        cap = int(
            frappe.db.get_value(
                "POS Profile",
                opening_doc.pos_profile,
                "custom_max_invoice_transfers",
            )
            or 0
        )
        if cap <= 0:
            frappe.throw(
                _(
                    "Invoice transfers are disabled for this POS Profile "
                    "(Max Invoice Transfers is 0). Pay or cancel the unpaid "
                    "orders before closing."
                ),
                title=_("Transfers Disabled"),
            )

        transfer_note = f"Offered by {me} on shift close ({opening_doc.name})"
        for row in blocking:
            inv = row["name"]
            # Idempotency: never create a second Pending transfer.
            if frappe.db.exists(
                "URY Invoice Transfer", {"invoice": inv, "status": "Pending"}
            ):
                continue
            hops = _transfer_hop_count(inv)
            if hops >= cap:
                frappe.throw(
                    _(
                        "Order {0} has already been transferred {1} time(s), "
                        "the maximum allowed for this profile. Pay or cancel "
                        "it instead."
                    ).format(inv, hops),
                    title=_("Transfer Limit Reached"),
                )
            transfer_doc = frappe.get_doc(
                {
                    "doctype": "URY Invoice Transfer",
                    "invoice": inv,
                    "status": "Pending",
                    "from_user": frappe.db.get_value("POS Invoice", inv, "owner"),
                    "to_user": transfer_to,
                    "branch": opening_doc.branch,
                    "opening_entry": opening_doc.name,
                    "requested_by": me,
                    "requested_at": frappe.utils.now_datetime(),
                    "hop_number": hops + 1,
                    "transfer_note": transfer_note,
                }
            )
            transfer_doc.insert(ignore_permissions=True)
            # Denormalized flag for the Orders page (audit + badge). The
            # invoice owner is NOT changed until the receiver approves.
            frappe.db.set_value(
                "POS Invoice",
                inv,
                {"custom_transfer_status": "Pending Incoming"},
                update_modified=True,
            )
            transfers_created += 1
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
    _validate_item_warehouses(paid, opening_doc.pos_profile)

    # Data repair: a corrupt `order_type` on a paid invoice (e.g. a phone
    # number that leaked into the field) makes ERPNext's consolidation
    # reject the merged Sales Invoice (order_type is a Select) and roll
    # the WHOLE close back — with a masked "Could not find Reference Name"
    # error on top. Normalize any out-of-range value to blank before the
    # consolidation reads it so the close goes through. See CLAUDE.md
    # "Fixes log" 2026-06-05.
    _repair_invalid_order_types(paid)

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

    # Soft gate on who closes the day (2026-07-29). Closing the day is
    # normally a captain's job — it's where cash is counted and the
    # shift's invoices are consolidated into the GL. But it is NOT
    # blocked for cashiers: with `custom_daily_pos_close` enabled, an
    # unclosed night blocks the NEXT day's trading entirely, so a hard
    # captain-only rule would take the whole outlet down whenever a
    # captain is away. Instead the cashier confirms in the UI and we
    # record the fact here, so a captain can review it the next morning
    # (filter POS Closing Entry on "Closed By Non-Captain").
    #
    # Resolved server-side from the SESSION user, never trusted from the
    # client — the frontend confirmation is a prompt, not the record.
    closing_doc.custom_closed_by_non_captain = 0 if _user_is_captain() else 1

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
    # Don't let a missing default outgoing Email Account block the close.
    # ERPNext's consolidation / notification path tries to send email on
    # submit; with no outgoing account configured Frappe raises
    # OutgoingEmailError ("Please setup default outgoing Email Account…")
    # mid-submit, which rolls the WHOLE close back. The cashier doesn't
    # care about the email — they just need to close the shift. When the
    # site has no usable outgoing account we mute emails for the duration
    # of the submit so the close goes through. Sites that DO have an
    # account keep emailing exactly as before (the mail just queues).
    # Catching the error after submit() can't help — the transaction is
    # already rolled back — so we have to PREVENT the send. See CLAUDE.md
    # "Fixes log" 2026-06-05.
    prev_mute_emails = frappe.flags.mute_emails
    if not _has_outgoing_email_account():
        frappe.flags.mute_emails = True

    # Force invoice consolidation to run SYNCHRONOUSLY during the close.
    # ERPNext enqueues consolidation in a background worker when the shift
    # has >= 10 invoices (pos_invoice_merge_log.consolidate_pos_invoices) —
    # if that background job fails (e.g. a Mode of Payment account problem)
    # the closing entry is marked "Failed", the shift stays OPEN, and the
    # cashier gets NO error: the dialog already reported success. Running it
    # inline means any error surfaces in THIS request so we can show it.
    #
    # We ALSO capture the GENUINE consolidation error. When consolidation
    # fails, ERPNext computes the real message via get_error_message(), then
    # calls closing_entry.set_status("Failed") — but the entry was just
    # rolled back, so set_status itself raises "Could not find Reference
    # Name: POS-CLO-…" and MASKS the real cause. We intercept
    # get_error_message to grab the real message and re-throw THAT instead
    # of the mask. Reversible — all restored in finally. (2026-06-11)
    import erpnext.accounts.doctype.pos_invoice_merge_log.pos_invoice_merge_log as _merge_mod

    _orig_enqueue_job = _merge_mod.enqueue_job
    _orig_get_error_message = _merge_mod.get_error_message
    _captured = {}

    def _run_consolidation_inline(job, **kwargs):
        return job(**kwargs)

    def _capturing_get_error_message(message):
        real = _orig_get_error_message(message)
        try:
            _captured["error"] = real
        except Exception:
            pass
        return real

    _merge_mod.enqueue_job = _run_consolidation_inline
    _merge_mod.get_error_message = _capturing_get_error_message
    try:
        closing_doc.insert(ignore_permissions=True)
        closing_doc.submit()
    except Exception as err:
        # Catch the consolidation-time cascade and re-throw with a
        # pointer to the most common root causes — Mode of Payment
        # account misconfig, missing customer fields, etc.
        real = _captured.get("error")
        if real and "could not find reference name" in str(err).lower():
            # The visible error is the set_status-on-rolled-back-entry mask;
            # surface the genuine consolidation failure we captured instead.
            real_str = real if isinstance(real, str) else str(real)
            try:
                frappe.log_error(
                    title="URY: shift close failed — real cause (unmasked)",
                    message="Masked by: {0}\n\nReal error:\n{1}".format(
                        str(err)[:500], real_str[:4000]
                    ),
                )
            except Exception:
                pass
            raise _wrap_close_error(Exception(real_str), opening_doc.company)
        raise _wrap_close_error(err, opening_doc.company)
    finally:
        _merge_mod.enqueue_job = _orig_enqueue_job
        _merge_mod.get_error_message = _orig_get_error_message
        frappe.flags.mute_emails = prev_mute_emails

    # Defensive: ERPNext's create_merge_logs catches some errors and marks
    # the closing entry "Failed" with an error_message. If that happened,
    # don't tell the cashier it closed — surface the real reason.
    try:
        closing_doc.reload()
    except Exception:
        pass
    if (closing_doc.get("status") or "") == "Failed":
        err_msg = (
            closing_doc.get("error_message")
            or "The shift could not be consolidated. Check the Error Log in the desk."
        )
        raise _wrap_close_error(Exception(err_msg), opening_doc.company)

    return {
        "name": closing_doc.name,
        "transfers_created": transfers_created,
        "transfer_to": transfer_to if transfers_created else None,
    }


def _has_outgoing_email_account():
    """True when the site has a usable default outgoing Email Account (or
    site-config SMTP). Used to decide whether to mute emails during the
    shift close so a missing account doesn't roll the whole close back.

    Defensive — any lookup failure is treated as "no account" so the
    caller mutes and the close still goes through.
    """
    try:
        if frappe.db.exists(
            "Email Account",
            {"default_outgoing": 1, "enable_outgoing": 1},
        ):
            return True
        conf = frappe.conf or {}
        return bool(conf.get("mail_server") or conf.get("smtp_server"))
    except Exception:
        return False


# Valid POS Invoice / Sales Invoice order_type Select options (URY's set).
# Blank is allowed. Anything else (a phone number that leaked into the
# field, a stale value, etc.) makes ERPNext's consolidation reject the
# merged Sales Invoice and roll the shift close back.
_VALID_ORDER_TYPES = (
    "",
    "Dine In",
    "Take Away",
    "Delivery",
    "Phone In",
    "Aggregators",
)


def _repair_invalid_order_types(paid_invoices):
    """Normalize any out-of-range `order_type` on the shift's paid
    invoices to blank before consolidation runs. Returns the list of
    ``(invoice, bad_value)`` tuples repaired (for audit).

    The set_value happens in the SAME transaction as the close, so when
    ``closing_doc.submit()`` later triggers consolidation it reads the
    corrected value. Blank is a valid Select option, so it passes the
    Sales Invoice validation that the corrupt value failed.
    """
    if not paid_invoices:
        return []
    names = [row["name"] for row in paid_invoices]
    rows = frappe.db.sql(
        """SELECT name, order_type FROM `tabPOS Invoice` WHERE name IN %(names)s""",
        {"names": tuple(names)},
        as_dict=True,
    )
    repaired = []
    for r in rows:
        if (r.order_type or "") not in _VALID_ORDER_TYPES:
            frappe.db.set_value(
                "POS Invoice", r.name, "order_type", "", update_modified=False
            )
            # CRITICAL: ERPNext's consolidation loads each POS Invoice via
            # `frappe.get_cached_doc("POS Invoice", …)` (pos_invoice_merge_log
            # on_submit) and copies its order_type onto the Sales Invoice via
            # map_doc. A raw `db.set_value` updates the DB row but leaves any
            # already-cached doc stale, so get_cached_doc would hand back the
            # OLD (corrupt) order_type and the close still fails. Invalidate
            # the cache so the consolidation re-reads the repaired value.
            frappe.clear_document_cache("POS Invoice", r.name)
            repaired.append((r.name, r.order_type))
    if repaired:
        # Audit trail — the original corrupt values, for later root-cause
        # work. Best-effort: never let logging block the close.
        try:
            frappe.log_error(
                message="Normalized invalid order_type to blank on shift "
                "close:\n"
                + "\n".join(f"{n}: {v!r}" for n, v in repaired),
                title="URY: repaired invalid POS Invoice order_type",
            )
        except Exception:
            pass
    return repaired


def _root_cause_message(err):
    """Walk an exception's __cause__/__context__ chain to the deepest
    cause and return its str(). ERPNext sometimes masks the genuine
    consolidation error behind a secondary failure (e.g. a Failed-status
    comment on a rolled-back closing entry raising LinkValidationError);
    the real cause sits at the bottom of the chain."""
    seen = set()
    cur = err
    root = err
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        root = cur
        cur = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
    return str(root)


def _validate_item_warehouses(paid_invoices, pos_profile):
    """When the POS Profile is in item-warehouse mode
    (`custom_use_pos_warehouse` OFF), every sold item must have a warehouse
    so consolidation can post its stock ledger entry. An item with no
    warehouse (its Item Defaults has no Default Warehouse for the company)
    blocks the close with a clear, item-named error so a manager fixes the
    item before the close proceeds. No-op in single-warehouse mode (the
    profile warehouse covers every item). See CLAUDE.md 2026-06-11.
    """
    if not paid_invoices or not pos_profile:
        return
    prof = frappe.db.get_value(
        "POS Profile",
        pos_profile,
        ["custom_use_pos_warehouse", "company"],
        as_dict=True,
    )
    if not prof:
        return
    # Default ON when unset → single warehouse, nothing to validate.
    if prof.custom_use_pos_warehouse is None or int(prof.custom_use_pos_warehouse or 0):
        return
    company = prof.company
    names = [row["name"] for row in paid_invoices]
    # Distinct STOCK items sold this shift (non-stock items don't post
    # stock, so they don't need a warehouse).
    item_rows = frappe.db.sql(
        """
        SELECT DISTINCT pii.item_code, pii.item_name
        FROM `tabPOS Invoice Item` AS pii
        INNER JOIN `tabItem` AS it ON it.name = pii.item_code
        WHERE pii.parent IN %(names)s
          AND it.is_stock_item = 1
        """,
        {"names": tuple(names)},
        as_dict=True,
    )
    missing = []
    for it in item_rows:
        wh = frappe.db.get_value(
            "Item Default",
            {"parent": it.item_code, "company": company},
            "default_warehouse",
        )
        if not wh:
            missing.append(it.item_name or it.item_code)
    if missing:
        missing = sorted(set(missing))
        listed = ", ".join(missing[:10])
        more = f" (+{len(missing) - 10} more)" if len(missing) > 10 else ""
        frappe.throw(
            _(
                "Cannot close this shift — these item(s) have no Default "
                "Warehouse set for company '{2}': {0}{1}. Ask a manager to "
                "open each Item in the desk → Item Defaults → set a Default "
                "Warehouse, then reopen the close dialog."
            ).format(listed, more, company),
            title=_("Item Warehouse Missing"),
        )


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

    # Check 2: mode of payment accounts on each invoice. The consolidated
    # Sales Invoice posts a GL entry to each payment's account, so a bad
    # account (missing / Receivable / group / disabled / wrong-company /
    # nonexistent) makes consolidation fail and rolls the whole close back.
    # We validate ALL of these up front so the cashier gets a precise
    # message naming the Mode of Payment + the exact problem, instead of a
    # silent failure or a cryptic GL cascade. (2026-06-11: was Receivable-only.)
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
    diag_rows = []  # full dump for the Error Log
    for row in payment_rows:
        mop = row.mode_of_payment or "(blank)"
        if not row.account:
            diag_rows.append(f"{mop}: <no account on payment row>")
            bad_mops.append(
                (
                    mop,
                    "no account is set — configure a Default Account for this "
                    "Mode of Payment (company '%s')" % company,
                )
            )
            continue
        acc = frappe.db.get_value(
            "Account",
            row.account,
            ["account_type", "is_group", "disabled", "company"],
            as_dict=True,
        )
        diag_rows.append(
            "{0}: account='{1}' type='{2}' is_group={3} disabled={4} company='{5}'".format(
                mop,
                row.account,
                (acc.account_type if acc else "?"),
                (acc.is_group if acc else "?"),
                (acc.disabled if acc else "?"),
                (acc.company if acc else "?"),
            )
        )
        if not acc:
            bad_mops.append((mop, f"account '{row.account}' does not exist"))
        elif acc.account_type == "Receivable":
            bad_mops.append(
                (
                    mop,
                    f"account '{row.account}' is a Receivable account (it needs "
                    "a party) — set it to a Bank or Cash account",
                )
            )
        elif acc.is_group:
            bad_mops.append(
                (
                    mop,
                    f"account '{row.account}' is a group account — you can't "
                    "post to a group; pick a ledger (non-group) Bank/Cash account",
                )
            )
        elif acc.disabled:
            bad_mops.append(
                (mop, f"account '{row.account}' is disabled — enable it or pick another")
            )
        elif acc.company and acc.company != company:
            bad_mops.append(
                (
                    mop,
                    f"account '{row.account}' belongs to company '{acc.company}', "
                    f"not '{company}'",
                )
            )
    if bad_mops:
        # Log the full account map so we can diagnose from the desk too.
        try:
            frappe.log_error(
                title="URY: shift close blocked — Mode of Payment account issue",
                message="Company: {0}\n\nProblems:\n{1}\n\nAll payment accounts:\n{2}".format(
                    company,
                    "\n".join(f"- {mop}: {reason}" for mop, reason in bad_mops),
                    "\n".join(diag_rows),
                ),
            )
        except Exception:
            pass
        lines = [f"- {mop}: {reason}" for mop, reason in bad_mops]
        frappe.throw(
            _(
                "Cannot close this shift — one or more Modes of Payment have a "
                "bad account for company '{0}':\n\n{1}\n\nOpen Accounting → "
                "Mode of Payment in the desk, fix each one's Default Account "
                "(a ledger Bank or Cash account for this company), save, then "
                "reopen the close dialog."
            ).format(company, "\n".join(lines)),
            title=_("Mode of Payment Account Issue"),
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
    # Unmask: when the top-level error is ERPNext's "Failed-status
    # comment on a rolled-back closing entry" cascade, the genuine cause
    # is deeper in the chain. Prefer it so the cashier sees the real
    # problem instead of "Could not find Reference Name: POS-CLO-…".
    root = _root_cause_message(err)
    if root and root != msg and "could not find reference name" in msg.lower():
        msg = root
    lower = msg.lower()

    if "order type cannot be" in lower or "should be one of" in lower:
        hint = _(
            "Hint: a paid invoice in this shift has an invalid Order Type "
            "(a corrupt value got into the field). This is normally "
            "auto-repaired on close — if you still see it, open the Error "
            "Log in the desk to find the invoice and reset its Order Type."
        )
    elif "customer is required against receivable account" in lower:
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

    Scoping mirrors ``posOpening()``: **the POS Profile is the unit**,
    because that is what ERPNext's ``check_open_pos_exists`` enforces.
    With ``terminal`` we resolve the terminal's profile and look for the
    single open entry on it; without ``terminal`` we fall back to the
    legacy branch-only lookup for the old Vue POS / Administrator paths.

    The response carries ownership metadata so callers never have to
    guess whose shift they are looking at:

    * ``is_mine`` — 1 when the entry belongs to the session user.
    * ``opened_by`` — the owner's full name (falls back to the user id).
    * ``same_terminal`` — 1 when it was opened on THIS terminal.

    That matters because a cashier must not be invited to close a
    colleague's shift; the dialog uses ``is_mine`` to decide whether to
    offer a Close button or a read-only "ask them to close it" card.
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
                "custom_terminal",
            ],
            order_by="period_start_date desc",
            limit=1,
        )
        if not rows:
            return None
        row = rows[0]
        row["is_mine"] = 1 if row.get("user") == frappe.session.user else 0
        row["opened_by"] = (
            frappe.db.get_value("User", row.get("user"), "full_name")
            or row.get("user")
        )
        row["same_terminal"] = (
            1 if terminal and row.get("custom_terminal") == terminal else 0
        )
        return row

    if not terminal:
        return _entry(
            {"branch": branch_name, "status": "Open", "docstatus": 1}
        )

    pos_profile = frappe.db.get_value(
        "URY POS Terminal", terminal, "pos_profile"
    )

    if not pos_profile:
        return _entry(
            {"branch": branch_name, "status": "Open", "docstatus": 1}
        )

    return _entry(
        {
            "pos_profile": pos_profile,
            "status": "Open",
            "docstatus": 1,
        }
    )


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

    Scoped to the POS Profile, matching ``posOpening()``. The
    ``terminal`` argument is accepted for call-site compatibility but no
    longer narrows the search: there is only ever one open entry per
    profile, so narrowing by terminal or by user would hide a genuinely
    unclosed previous day from everyone except the original opener.

    Response shape (used by the React POS opening dialog so it can
    deep-link directly to the unclosed entry instead of dumping the user
    on /app):
        {"status": "Success"}
        {"status": "Failed", "unclosed_entry": "POS-OPEN-..."}

    See CLAUDE.md "Fixes log" 2026-07-28 for context.
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

    # Match posOpening's scoping: the POS Profile is the unit. We must
    # NOT narrow by terminal or user here. Under the shared model a
    # single entry serves every terminal and every cashier on the
    # profile, so narrowing would report "nothing unclosed" to everyone
    # except the original opener — the exact blind spot that let a
    # previous day's shift stay open unnoticed.
    filters = {
        "posting_date": previous_day.date(),
        "status": "Open",
        "pos_profile": pos_profile,
        "docstatus": 1,
    }

    unclosed_pos_opening = frappe.db.exists("POS Opening Entry", filters)

    if unclosed_pos_opening:
        return {"status": "Failed", "unclosed_entry": unclosed_pos_opening}

    return {"status": "Success"}

@frappe.whitelist(allow_guest=True)
def _build_pu_print_jobs_for_kot(kot_doc, terminal=None):
    """Build QZ print jobs for one KOT in URY Production Unit mode.

    Reads the KOT's `production`'s `URY Printer Settings` rows that have
    `custom_kot_print = 1`, renders the KOT with each row's KOT print
    format (falling back to the doctype default when blank), and returns
    ``(jobs, reason)`` where jobs is a list of
    ``{printer, department, html, kot_name}`` dicts (``department`` carries
    the production name) and reason is a short string
    ("no_production" / "no_kot_printers" / "no_print_jobs") when the list
    is empty, else None.

    Per-terminal routing (2026-06-11): when ``terminal`` is supplied, only
    printer rows tagged for THAT terminal (`custom_terminal`) — plus
    untagged rows, which print on every terminal — fire. So a production
    with one printer per terminal only prints the current terminal's
    ticket. Shared by get_latest_kot (order-time auto-fire) and
    print_pending_kots_for_invoice (manual fire from the Orders
    "Pending KOTs" view). See CLAUDE.md "Fixes log" 2026-06-11.
    """
    production_name = getattr(kot_doc, "production", None)
    if not production_name:
        return [], "no_production"
    prod_printer_rows = frappe.get_all(
        "URY Printer Settings",
        fields=[
            "printer",
            "custom_kot_print_format",
            "custom_kot_print",
            "custom_block_takeaway_kot",
            "custom_terminal",
        ],
        filters={
            "parent": production_name,
            "parenttype": "URY Production Unit",
            "custom_kot_print": 1,
        },
        order_by="idx",
    )
    if not prod_printer_rows:
        return [], "no_kot_printers"

    # Per-terminal filtering: a row tagged with a terminal only prints on
    # that terminal; untagged rows print everywhere. Only applied when we
    # know the terminal (else keep all rows for back-compat).
    if terminal:
        prod_printer_rows = [
            r
            for r in prod_printer_rows
            if not r.get("custom_terminal")
            or r.get("custom_terminal") == terminal
        ]
        if not prod_printer_rows:
            return [], "no_printer_for_terminal"
    is_takeaway = (
        getattr(kot_doc, "table_takeaway", 0) == 1
        or not getattr(kot_doc, "restaurant_table", None)
    )
    jobs = []
    for row in prod_printer_rows:
        if row.custom_block_takeaway_kot and is_takeaway:
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
                title="URY PU KOT render failed",
                message=(
                    f"KOT {kot_doc.name} production={production_name} "
                    f"printer={row.printer} err={e}"
                ),
            )
            continue
        jobs.append(
            {
                "printer": row.printer,
                "department": production_name,
                "html": html,
                "kot_name": kot_doc.name,
            }
        )
    return jobs, ("no_print_jobs" if not jobs else None)


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
            ["qz_print", "custom_print_mode", "qz_host"],
            as_dict=True,
        ) or {}
        legacy_qz = int(profile_row.get("qz_print") or 0) == 1
        new_mode = profile_row.get("custom_print_mode") or ""
        new_qz = new_mode == "QZ Tray"
        # QZ websocket host. Empty ⇒ localhost (cashier's own machine).
        # A remote value = the LAN "print server" gateway so tablets that
        # can't run QZ themselves still reach a physical printer. The
        # frontend passes this to printKotWithQz so KOTs go to the same
        # gateway as the bill (2026-07-14).
        qz_host_val = profile_row.get("qz_host") or "localhost"

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
        # In PU mode ONLY production-matched KOTs print, to their
        # production's terminal printer. A production-less KOT prints
        # nothing — these aren't created for new orders anymore (see
        # process_items_for_kot) and we deliberately do NOT fall back to
        # Menu Course department routing, which would print an unwanted
        # default-format ticket. See CLAUDE.md 2026-06-11.
        if new_qz and kds_mode == "URY Production Unit":
            if not getattr(kot_doc, "production", None):
                return {
                    "debug": "pu_mode_no_production",
                    "pos_profile": pos_profile,
                    "kot_name": kot_doc.name,
                }
            kot_terminal = (
                frappe.db.get_value(
                    "POS Invoice", kot_doc.invoice, "custom_terminal"
                )
                if getattr(kot_doc, "invoice", None)
                else None
            )
            jobs, reason = _build_pu_print_jobs_for_kot(
                kot_doc, terminal=kot_terminal
            )
            if jobs:
                return {
                    "kot_name": kot_doc.name,
                    "pos_profile": pos_profile,
                    "kot_printed": kot_rows[0].kot_printed,
                    "production_unit_mode": 1,
                    "print_jobs": jobs,
                    "qz_host": qz_host_val,
                }
            return {
                "debug": f"pu_mode_{reason}",
                "pos_profile": pos_profile,
                "kot_name": kot_doc.name,
                "production": getattr(kot_doc, "production", None),
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
                    "qz_host": qz_host_val,
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
            "qz_host": qz_host_val,
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
        ["pos_profile", "order_type", "custom_terminal"],
        as_dict=True,
    )
    if not invoice_row:
        return {"invoice": invoice, "print_jobs": []}

    pos_profile = invoice_row.pos_profile
    order_type = invoice_row.order_type
    invoice_terminal = invoice_row.custom_terminal

    # QZ websocket host for this profile. Empty ⇒ localhost. A remote value
    # is the LAN print-server gateway (so tablets can print). The frontend
    # passes this to printKotWithQz so held KOTs fire to the same gateway as
    # the bill (2026-07-14).
    qz_host_val = (
        frappe.db.get_value("POS Profile", pos_profile, "qz_host") or "localhost"
    )

    kds_mode = (
        frappe.db.get_value(
            "POS Profile", pos_profile, "custom_kds_routing_mode"
        )
        or "Menu Course"
    )

    # URY Production Unit mode: build print jobs for every un-printed,
    # production-matched KOT so the cashier can re-fire them from the
    # Orders "Pending KOTs" view (e.g. when the order-time auto-print
    # didn't reach the printer). Each matched KOT prints to its
    # production's printer for THIS terminal, with the printer's KOT
    # format. A production-less KOT prints NOTHING — and any legacy one
    # (created before the fallback-KOT change) is marked printed so it
    # leaves the pending list instead of sitting there forever.
    # `production_unit_mode=1` tells the frontend to mark the whole KOT
    # printed after firing. See CLAUDE.md 2026-06-11.
    if kds_mode == "URY Production Unit":
        pu_kot_rows = frappe.get_all(
            "URY KOT",
            filters={
                "invoice": invoice,
                "kot_printed": 0,
                "docstatus": ["!=", 2],
            },
            fields=["name"],
            order_by="creation asc",
        )
        pu_print_jobs = []
        for row in pu_kot_rows:
            try:
                kot_doc = frappe.get_doc("URY KOT", row.name)
            except Exception as e:
                frappe.log_error(
                    title="URY print_pending_kots (PU) load KOT failed",
                    message=f"invoice={invoice} kot={row.name} err={e}",
                )
                continue
            if not getattr(kot_doc, "production", None):
                # Legacy production-less KOT — nothing to print; clear it
                # so it stops showing in the pending list.
                frappe.db.set_value(
                    "URY KOT", kot_doc.name, "kot_printed", 1,
                    update_modified=False,
                )
                continue
            jobs, _reason = _build_pu_print_jobs_for_kot(
                kot_doc, terminal=invoice_terminal
            )
            pu_print_jobs.extend(jobs)
        return {
            "invoice": invoice,
            "print_jobs": pu_print_jobs,
            "production_unit_mode": 1,
            "qz_host": qz_host_val,
        }

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

    return {"invoice": invoice, "print_jobs": print_jobs, "qz_host": qz_host_val}


@frappe.whitelist()
def get_pending_kot_count(terminal=None, posting_date=None, cashier=None):
    """Return the count of draft POS Invoices that still have at
    least one URY KOT with ``kot_printed = 0``.

    Feeds the live badge next to the "Pending KOTs" sidebar entry on
    the Orders page. Scoping follows the same rules as
    ``getPosInvoice``: branch (required), optional terminal, optional
    posting_date, and the cashier scope (``mine`` / ``all`` /
    specific user) via ``_resolve_orders_scope`` — so the badge counts
    the pending KOTs of the cashier who rang the orders, matching the
    Pending KOTs list. A cashier sees only their own; a captain can
    widen the scope from the sidebar's cashier picker (2026-06-11).

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

    # Scope to the cashier who rang the order (mine / all / specific).
    scope_clause, scope_params = _resolve_orders_scope(terminal, cashier)
    where_parts.append(scope_clause)
    params.extend(scope_params)

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
    """Get kitchen order status notifications for the current user.

    Scope matches the Orders "My Orders" list: a plain user sees their
    own served orders (owner); a self-serve waiter ALSO sees orders a
    cashier rang on her behalf (custom_waiter = her waiter record), so
    the served alert reaches her whether she or the cashier placed the
    order. 2026-07-15.
    """
    try:
        user = frappe.session.user

        self_waiter = _get_self_waiter_for_user(user)
        if self_waiter:
            owner_clause = "(pi.owner = %s OR pi.custom_waiter = %s)"
            owner_params = [user, self_waiter["name"]]
        else:
            owner_clause = "pi.owner = %s"
            owner_params = [user]

        # Get POS Invoices with custom_order_status = 'Served' AND custom_clear_from_notification = 0
        notifications = frappe.db.sql(f"""
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
            AND {owner_clause}
            AND pi.posting_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
            GROUP BY pi.name
            ORDER BY k.creation DESC
            LIMIT 50
        """, owner_params, as_dict=True)
        
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
            AND (pi.owner = %s OR pi.cashier = %s)
            AND pi.docstatus = 1
            GROUP BY pi.name
            ORDER BY pi.posting_time DESC
        """, (date, user, user), as_dict=True)

        # Attach the line items per invoice (for the "Itemized" view +
        # itemized print). One query for all of the day's invoices,
        # grouped by parent. get_all ignores DocType perms so a cashier
        # always sees their own invoices' items.
        invoice_names = [inv["name"] for inv in invoices]
        items_by_invoice = {}
        if invoice_names:
            item_rows = frappe.get_all(
                "POS Invoice Item",
                filters={"parent": ["in", invoice_names]},
                fields=["parent", "item_name", "qty", "rate", "amount"],
                order_by="parent asc, idx asc",
            )
            for r in item_rows:
                items_by_invoice.setdefault(r["parent"], []).append(
                    {
                        "item_name": r["item_name"],
                        "qty": r["qty"],
                        "rate": r["rate"],
                        "amount": r["amount"],
                    }
                )
        for inv in invoices:
            inv["items"] = items_by_invoice.get(inv["name"], [])

        # Get payment method totals - correct table name
        payment_totals = frappe.db.sql("""
            SELECT 
                p.mode_of_payment,
                SUM(p.base_amount) as total_amount
            FROM `tabPOS Invoice` pi
            JOIN `tabSales Invoice Payment` p ON p.parent = pi.name
            WHERE pi.posting_date = %s
            AND (pi.owner = %s OR pi.cashier = %s)
            AND pi.docstatus = 1
            GROUP BY p.mode_of_payment
            ORDER BY total_amount DESC
        """, (date, user, user), as_dict=True)
        
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
def get_waiter_sales(from_date=None, to_date=None, waiter=None):
    """Sales served by a waiter, for her own sales report in the POS.

    Scope: SUBMITTED POS Invoices whose ``custom_waiter`` is this waiter —
    that covers BOTH orders she rang herself and orders a cashier rang on
    her behalf. Returns are excluded, as are merged-source invoices (the
    master carries the combined total).

    Deliberately NOT branch-scoped: a waiter's orders are stamped with the
    branch of the table/till she rang on, which need not match her own URY
    User branch — branch-filtering her was what hid her orders before (see
    the 2026-07-15 round-5 fix).

    Waiter resolution:
      - A self-serve waiter always gets her OWN sales; the ``waiter`` arg is
        ignored so she can't read someone else's numbers.
      - An elevated user (Administrator / System Manager / URY Manager /
        URY Captain) may pass an explicit ``waiter`` to view that waiter's
        sales.
    2026-07-16.
    """
    self_waiter = _get_self_waiter_for_user()
    if self_waiter:
        waiter_name = self_waiter["name"]
    elif waiter and _user_can_see_admin_reports():
        waiter_name = waiter
    else:
        frappe.throw(
            _(
                "No waiter is linked to your user, so there are no waiter "
                "sales to show. Ask your manager to link your user on the "
                "{0} record."
            ).format(_("URY Waiter")),
            title=_("Not a Waiter"),
        )

    today = frappe.utils.today()
    from_date = from_date or today
    to_date = to_date or from_date
    if to_date < from_date:
        from_date, to_date = to_date, from_date

    rows = frappe.db.sql(
        """
        SELECT
            pi.name, pi.posting_date, pi.posting_time, pi.customer_name,
            pi.restaurant_table, pi.grand_total, pi.net_total, pi.status,
            pi.order_type,
            (
                SELECT COUNT(*) FROM `tabPOS Invoice Item` ii
                WHERE ii.parent = pi.name
            ) AS items_count
        FROM `tabPOS Invoice` pi
        WHERE pi.custom_waiter = %s
        AND pi.docstatus = 1
        AND (pi.is_return IS NULL OR pi.is_return = 0)
        AND pi.posting_date BETWEEN %s AND %s
        AND (pi.custom_merged_into IS NULL OR pi.custom_merged_into = '')
        ORDER BY pi.posting_date DESC, pi.posting_time DESC
        """,
        (waiter_name, from_date, to_date),
        as_dict=True,
    )

    order_count = len(rows)
    total_sales = sum(float(r.get("grand_total") or 0) for r in rows)

    # Per-day rollup so a multi-day range shows a daily breakdown.
    by_day = {}
    for r in rows:
        key = str(r["posting_date"])
        bucket = by_day.setdefault(
            key, {"posting_date": key, "order_count": 0, "total": 0.0}
        )
        bucket["order_count"] += 1
        bucket["total"] += float(r.get("grand_total") or 0)

    return {
        "waiter": waiter_name,
        "waiter_name": frappe.db.get_value("URY Waiter", waiter_name, "full_name")
        or waiter_name,
        "from_date": from_date,
        "to_date": to_date,
        "summary": {
            "order_count": order_count,
            "total_sales": total_sales,
            "average_order": (total_sales / order_count) if order_count else 0,
        },
        "by_day": sorted(
            by_day.values(), key=lambda x: x["posting_date"], reverse=True
        ),
        "invoices": rows,
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
def get_sales_by_cashier(from_date=None, to_date=None, terminal=None, group_by="cashier"):
    """Per-staff sales breakdown over a date range.

    `group_by` picks WHICH member of staff, and they are genuinely
    different questions on the same invoice:

      "cashier"  → `cashier` ON THE INVOICE, stamped when the bill is
                   printed/paid, i.e. who actually took the money.
      "waiter"   → `custom_waiter` ON THE INVOICE, the URY Waiter who
                   served the table.

    Both come off the invoice itself. Do NOT group on `owner`: that is
    whoever created the draft, which on a waiter-enabled site is the
    waiter, so a "by cashier" report grouped on it just repeats the
    waiter list.

    On a site that uses waiters these are routinely different people,
    so the report says which one it grouped on rather than leaving the
    reader to assume. Invoices with no waiter are grouped as
    "Unassigned" instead of being dropped — silently excluding them
    would make the waiter totals disagree with the cashier totals for
    no visible reason.

    Admin / captain / manager only. Branch-scoped; optional terminal
    filter so a captain can audit a single till.
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

    # Group on the fields the INVOICE itself carries, not on who happens
    # to own the document. `owner` is whoever created the draft, which on
    # a waiter-enabled site is the WAITER -- grouping "Sales by Cashier"
    # on it made both tabs show the same people. `cashier` is stamped
    # when the bill is actually printed/paid, which is the real
    # who-took-the-money. See CLAUDE.md "Fixes log" 2026-08-06.
    by_waiter = (group_by or "cashier").lower() == "waiter"
    if by_waiter:
        key_expr = "COALESCE(NULLIF(pi.custom_waiter, ''), '__unassigned__')"
        name_expr = "COALESCE(NULLIF(w.full_name, ''), NULLIF(pi.custom_waiter, ''), 'Unassigned')"
        join = "LEFT JOIN `tabURY Waiter` AS w ON w.name = pi.custom_waiter"
    else:
        key_expr = "COALESCE(NULLIF(pi.cashier, ''), '__unassigned__')"
        # `cashier` is a Data field that normally holds a user id, so the
        # join is only to prettify it. If it holds anything else the join
        # misses and the raw value is shown -- never a blank row.
        name_expr = "COALESCE(NULLIF(u.full_name, ''), NULLIF(pi.cashier, ''), 'Unassigned')"
        join = "LEFT JOIN `tabUser` AS u ON u.name = pi.cashier"

    sql = f"""
        SELECT
            {key_expr} AS user,
            {name_expr} AS full_name,
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
        {join}
        WHERE {" AND ".join(where_parts)}
        GROUP BY {key_expr}, {name_expr}
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
        "group_by": "waiter" if by_waiter else "cashier",
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


DAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def _resolve_pos_profile_for_branch(terminal=None, branch=None):
    """Resolve the active POS Profile for the current scope. Used by
    the shift schedule endpoint to read `custom_shift_system_mode`.
    Prefers the terminal's bound profile if a terminal is in play;
    falls back to the first non-disabled POS Profile on the branch.
    """
    if terminal:
        prof = frappe.db.get_value("URY POS Terminal", terminal, "pos_profile")
        if prof:
            return prof
    return frappe.db.get_value(
        "POS Profile", {"branch": branch, "disabled": 0}, "name"
    )


def _build_ury_shift_roster(branch, week_start, week_end):
    """Return a list of per-user roster rows for the URY Shift mode.

    Each row carries:
      {user, full_name, assignments: {Monday: {...}, Tuesday: {...}, ...}}

    Days with no assignment for that user are omitted from the
    `assignments` dict — the frontend renders them as "—".

    URY Shift Assignment carries `effective_from`/`effective_to`
    +`days_of_week` child table. Empty `days_of_week` means "every
    day of the week" (per the doctype docstring I wrote earlier).
    """
    # Pull every Active assignment that overlaps the week window.
    assignments = frappe.db.sql(
        """
        SELECT
            sa.name,
            sa.user,
            sa.shift,
            sa.effective_from,
            sa.effective_to,
            us.shift_name,
            us.start_time,
            us.end_time
        FROM `tabURY Shift Assignment` AS sa
        INNER JOIN `tabURY Shift` AS us ON us.name = sa.shift
        WHERE sa.status = 'Active'
          AND sa.branch = %s
          AND sa.effective_from <= %s
          AND (sa.effective_to IS NULL OR sa.effective_to >= %s)
        ORDER BY sa.user, us.start_time
        """,
        (branch, week_end, week_start),
        as_dict=True,
    )

    if not assignments:
        return []

    # Pull the days_of_week child rows for every assignment in one
    # bulk query. Empty list for an assignment => every day.
    assignment_names = [a["name"] for a in assignments]
    placeholders = ", ".join(["%s"] * len(assignment_names))
    day_rows = frappe.db.sql(
        f"""
        SELECT parent, day
        FROM `tabURY Shift Day`
        WHERE parent IN ({placeholders})
        """,
        tuple(assignment_names),
        as_dict=True,
    )
    days_by_assignment: dict = {}
    for r in day_rows:
        days_by_assignment.setdefault(r["parent"], set()).add(r["day"])

    # Pull full names for every user in one query.
    user_names = list({a["user"] for a in assignments if a.get("user")})
    full_name_map: dict = {}
    if user_names:
        ph = ", ".join(["%s"] * len(user_names))
        for r in frappe.db.sql(
            f"SELECT name, full_name FROM `tabUser` WHERE name IN ({ph})",
            tuple(user_names),
            as_dict=True,
        ):
            full_name_map[r["name"]] = r["full_name"]

    # Build per-user row keyed by user, then merge per-day cells.
    rows_by_user: dict = {}
    for a in assignments:
        user = a.get("user")
        if not user:
            continue
        days_for_assignment = days_by_assignment.get(a["name"]) or set(
            DAY_NAMES
        )
        cell = {
            "shift_name": a["shift_name"] or a["shift"],
            "shift": a["shift"],
            "start_time": _time_str(a["start_time"]),
            "end_time": _time_str(a["end_time"]),
            "assignment": a["name"],
        }
        row = rows_by_user.setdefault(
            user,
            {
                "user": user,
                "full_name": full_name_map.get(user) or user,
                "assignments": {},
            },
        )
        for day_name in days_for_assignment:
            # First-write-wins keeps each cell to one shift per day
            # for the table layout. If a user has two non-overlapping
            # shifts on the same day (rare), only the earlier-starting
            # one shows in the cell — the URY Shift Assignment overlap
            # validator already rejects time-overlapping conflicts so
            # this corner case is benign.
            row["assignments"].setdefault(day_name, cell)

    return sorted(
        rows_by_user.values(),
        key=lambda r: (r["full_name"] or "").lower(),
    )


def _build_hrms_shift_roster(branch, week_start, week_end):
    """Return a list of per-user roster rows for the HRMS Shift Type
    mode. Same shape as the URY builder.

    HRMS Shift Assignment is per-employee per-date-range (no per-day
    pattern), so we expand each assignment over the days it covers
    within the week window. Best-effort: if the HRMS app isn't
    installed (`Shift Assignment` doctype missing) we silently
    return [] so the report still loads.
    """
    if not frappe.db.exists("DocType", "Shift Assignment"):
        return []
    if not frappe.db.exists("DocType", "Shift Type"):
        return []

    # HRMS Shift Assignment is per-employee. Map employees on this
    # branch back to user_id so we can highlight the current user.
    employees = frappe.db.sql(
        """
        SELECT name, employee_name, user_id, branch
        FROM `tabEmployee`
        WHERE branch = %s
        """,
        (branch,),
        as_dict=True,
    )
    if not employees:
        return []

    employee_names = [e["name"] for e in employees]
    placeholders = ", ".join(["%s"] * len(employee_names))
    assignments = frappe.db.sql(
        f"""
        SELECT
            sa.employee,
            sa.shift_type,
            sa.start_date,
            sa.end_date,
            st.start_time,
            st.end_time
        FROM `tabShift Assignment` AS sa
        INNER JOIN `tabShift Type` AS st ON st.name = sa.shift_type
        WHERE sa.docstatus = 1
          AND sa.status = 'Active'
          AND sa.employee IN ({placeholders})
          AND sa.start_date <= %s
          AND (sa.end_date IS NULL OR sa.end_date >= %s)
        """,
        tuple(employee_names) + (week_end, week_start),
        as_dict=True,
    )

    employee_to_user = {
        e["name"]: e.get("user_id") or e["name"] for e in employees
    }
    employee_to_full = {
        e["name"]: e.get("employee_name") or e["name"] for e in employees
    }

    rows_by_user: dict = {}
    from datetime import timedelta as _td
    for a in assignments:
        emp = a["employee"]
        user = employee_to_user.get(emp) or emp
        full_name = employee_to_full.get(emp) or emp

        cell = {
            "shift_name": a["shift_type"],
            "shift": a["shift_type"],
            "start_time": _time_str(a["start_time"]),
            "end_time": _time_str(a["end_time"]),
            "assignment": None,
        }
        row = rows_by_user.setdefault(
            user,
            {"user": user, "full_name": full_name, "assignments": {}},
        )

        # Expand the assignment over the days it covers within the
        # week window.
        start = max(
            a["start_date"], frappe.utils.getdate(week_start)
        )
        end = (
            min(a["end_date"], frappe.utils.getdate(week_end))
            if a["end_date"]
            else frappe.utils.getdate(week_end)
        )
        cur = start
        while cur <= end:
            day_name = DAY_NAMES[cur.weekday()]
            row["assignments"].setdefault(day_name, cell)
            cur += _td(days=1)

    return sorted(
        rows_by_user.values(),
        key=lambda r: (r["full_name"] or "").lower(),
    )


def _time_str(t):
    """Render a Time field (datetime.time, timedelta, or str) as
    24-hour HH:MM for the schedule cell."""
    if t is None:
        return ""
    try:
        # datetime.time
        return t.strftime("%H:%M")
    except AttributeError:
        pass
    try:
        # timedelta — happens when MariaDB returns Time as interval
        total = int(t.total_seconds())
        h = total // 3600
        m = (total % 3600) // 60
        return f"{h:02d}:{m:02d}"
    except AttributeError:
        pass
    s = str(t)
    return s[:5] if len(s) >= 5 else s


@frappe.whitelist()
def get_shift_schedule(week_start=None, terminal=None):
    """Mon→Sun shift roster for the user's branch, driven by the
    POS Profile's ``custom_shift_system_mode``.

    Mode resolution:
      - "URY Shift" → reads URY Shift + URY Shift Assignment
      - "HRMS Shift Type" → reads Shift Type + Shift Assignment
        (returns empty when HRMS isn't installed)
      - "Disabled" or unset → returns empty

    Visible to every role: the user explicitly asked for "the user
    has to see everyone on that sheet too". The current session
    user is flagged via `is_me` so the frontend can highlight their
    row in the grid.

    See CLAUDE.md "Fixes log" 2026-04-16 — Reports batch 3.
    """
    from datetime import timedelta as _td

    branch = getBranch()
    pos_profile_name = _resolve_pos_profile_for_branch(terminal, branch)
    mode = "Disabled"
    if pos_profile_name:
        mode = (
            frappe.db.get_value(
                "POS Profile", pos_profile_name, "custom_shift_system_mode"
            )
            or "Disabled"
        )

    # Compute week window: snap requested date back to its Monday.
    today = frappe.utils.getdate(week_start) if week_start else frappe.utils.getdate()
    monday = today - _td(days=today.weekday())
    sunday = monday + _td(days=6)

    days = [
        {
            "day_name": DAY_NAMES[d],
            "date": str(monday + _td(days=d)),
        }
        for d in range(7)
    ]

    rows: list = []
    if mode == "URY Shift":
        rows = _build_ury_shift_roster(branch, str(monday), str(sunday))
    elif mode == "HRMS Shift Type":
        rows = _build_hrms_shift_roster(branch, str(monday), str(sunday))
    # Disabled / unknown modes leave rows = [].

    me = frappe.session.user
    for r in rows:
        r["is_me"] = r["user"] == me

    return {
        "mode": mode,
        "branch": branch,
        "pos_profile": pos_profile_name,
        "week_start": str(monday),
        "week_end": str(sunday),
        "days": days,
        "rows": rows,
        "current_user": me,
    }


@frappe.whitelist()
def get_shift_history(from_date=None, to_date=None, terminal=None):
    """Closed POS Closing Entry rows in a date window — the
    notice-board-style report the user wanted to print at end of
    day. Scope:
      - Cashier: own closed shifts only (`pce.user = session.user`).
      - Admin / Captain / Manager: every closed shift on the branch.

    Each row carries the cashier identity, opening + closing
    timestamps, total invoice count + grand totals, and the per-MoP
    payment reconciliation rows from the POS Closing Entry Detail
    child table. The frontend renders them as one table per shift
    with an aggregated payment summary below for the print view.

    Date window applies to ``period_end_date`` (when the shift was
    closed), not posting_date — admins typically think "show me the
    shifts that closed in this window".
    """
    from_date, to_date = _reports_date_range(from_date, to_date)
    branch = getBranch()
    is_admin = _user_can_see_admin_reports()

    where_parts = [
        "pce.docstatus = 1",
        "pp.branch = %s",
        "DATE(pce.period_end_date) BETWEEN %s AND %s",
    ]
    params = [branch, from_date, to_date]
    if not is_admin:
        # Cashier scope: only their own shifts.
        where_parts.append("pce.user = %s")
        params.append(frappe.session.user)
    if terminal:
        # POS Closing Entry doesn't carry custom_terminal directly;
        # filter by the linked opening entry's terminal instead.
        where_parts.append(
            "pce.pos_opening_entry IN ("
            "  SELECT name FROM `tabPOS Opening Entry` "
            "  WHERE custom_terminal = %s OR custom_terminal IS NULL OR custom_terminal = ''"
            ")"
        )
        params.append(terminal)

    closing_rows = frappe.db.sql(
        f"""
        SELECT
            pce.name,
            pce.user,
            COALESCE(u.full_name, pce.user) AS full_name,
            pce.pos_opening_entry,
            pce.pos_profile,
            pce.period_start_date,
            pce.period_end_date,
            pce.grand_total,
            pce.net_total,
            pce.total_quantity,
            pce.posting_date
        FROM `tabPOS Closing Entry` AS pce
        INNER JOIN `tabPOS Profile` AS pp ON pp.name = pce.pos_profile
        LEFT JOIN `tabUser` AS u ON u.name = pce.user
        WHERE {" AND ".join(where_parts)}
        ORDER BY pce.period_end_date DESC
        """,
        tuple(params),
        as_dict=True,
    )

    if not closing_rows:
        return {
            "from_date": from_date,
            "to_date": to_date,
            "branch": branch,
            "terminal": terminal or None,
            "scope": "branch" if is_admin else "user",
            "shifts": [],
            "summary": {
                "shift_count": 0,
                "grand_total": 0,
                "net_total": 0,
                "by_mode": [],
            },
        }

    # Pull every payment reconciliation row in one query, group by
    # parent (closing entry name). Avoids N+1 across the shifts.
    closing_names = [r["name"] for r in closing_rows]
    placeholders = ", ".join(["%s"] * len(closing_names))
    payment_rows = frappe.db.sql(
        f"""
        SELECT
            parent,
            mode_of_payment,
            opening_amount,
            expected_amount,
            closing_amount,
            difference
        FROM `tabPOS Closing Entry Detail`
        WHERE parent IN ({placeholders})
        ORDER BY idx
        """,
        tuple(closing_names),
        as_dict=True,
    )

    # Also pull invoice counts per closing entry. POS Invoice
    # Reference is the standard ERPNext child table on POS Closing
    # Entry that lists which invoices are in the close.
    invoice_count_rows = frappe.db.sql(
        f"""
        SELECT parent, COUNT(name) AS cnt
        FROM `tabPOS Invoice Reference`
        WHERE parent IN ({placeholders})
        GROUP BY parent
        """,
        tuple(closing_names),
        as_dict=True,
    )
    invoice_count_map = {r["parent"]: int(r["cnt"]) for r in invoice_count_rows}

    payments_by_close: dict = {}
    for p in payment_rows:
        payments_by_close.setdefault(p["parent"], []).append(
            {
                "mode_of_payment": p["mode_of_payment"],
                "opening_amount": float(p.get("opening_amount") or 0),
                "expected_amount": float(p.get("expected_amount") or 0),
                "closing_amount": float(p.get("closing_amount") or 0),
                "difference": float(p.get("difference") or 0),
            }
        )

    shifts = []
    for r in closing_rows:
        shifts.append(
            {
                "name": r["name"],
                "user": r["user"],
                "full_name": r["full_name"],
                "pos_opening_entry": r["pos_opening_entry"],
                "pos_profile": r["pos_profile"],
                "period_start_date": str(r["period_start_date"] or ""),
                "period_end_date": str(r["period_end_date"] or ""),
                "posting_date": str(r["posting_date"] or ""),
                "grand_total": float(r.get("grand_total") or 0),
                "net_total": float(r.get("net_total") or 0),
                "total_quantity": float(r.get("total_quantity") or 0),
                "invoice_count": invoice_count_map.get(r["name"], 0),
                "payments": payments_by_close.get(r["name"], []),
            }
        )

    # Cross-shift summary: for the print view's "Payment
    # Reconciliation Summary" section. Aggregates every shift in
    # the window's expected_amount per MoP — what the cashiers
    # collectively SHOULD have collected — plus the variance.
    by_mode: dict = {}
    for s in shifts:
        for p in s["payments"]:
            agg = by_mode.setdefault(
                p["mode_of_payment"],
                {
                    "mode_of_payment": p["mode_of_payment"],
                    "opening_amount": 0.0,
                    "expected_amount": 0.0,
                    "closing_amount": 0.0,
                    "difference": 0.0,
                },
            )
            agg["opening_amount"] += p["opening_amount"]
            agg["expected_amount"] += p["expected_amount"]
            agg["closing_amount"] += p["closing_amount"]
            agg["difference"] += p["difference"]

    return {
        "from_date": from_date,
        "to_date": to_date,
        "branch": branch,
        "terminal": terminal or None,
        "scope": "branch" if is_admin else "user",
        "shifts": shifts,
        "summary": {
            "shift_count": len(shifts),
            "grand_total": sum(s["grand_total"] for s in shifts),
            "net_total": sum(s["net_total"] for s in shifts),
            "by_mode": sorted(by_mode.values(), key=lambda x: x["mode_of_payment"]),
        },
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
def get_payment_splits_report(from_date=None, to_date=None, terminal=None):
    """Surface every paid POS Invoice that was settled with two or
    more payment rows in the date window — i.e. anything where the
    Split Bill flow OR a multi-mode single-payer settlement was used.

    Admin / captain only. We can't distinguish "Split Bill" (multiple
    payers, same payment dialog flow) from "single payer with mixed
    modes" purely from the saved data — both produce N>1 rows in
    `tabSales Invoice Payment` after collapsePayers groups by mode.
    For reporting we treat them the same: any invoice with > 1
    payment row is a "split payment".

    Each event row carries the invoice metadata plus the per-mode
    breakdown so the UI can render `Cash 30.00 + Card 20.00` style
    summaries inline.
    """
    if not _user_can_see_admin_reports():
        frappe.throw(
            _("You don't have permission to see split-payment reports."),
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

    invoices = frappe.db.sql(
        f"""
        SELECT
            pi.name,
            pi.posting_date,
            pi.posting_time,
            pi.owner,
            COALESCE(u.full_name, pi.owner) AS owner_full_name,
            pi.customer,
            pi.customer_name,
            pi.grand_total,
            pi.restaurant_table,
            pi.custom_terminal,
            pi.is_return,
            (
                SELECT COUNT(p.name)
                FROM `tabSales Invoice Payment` AS p
                WHERE p.parent = pi.name
            ) AS payment_count
        FROM `tabPOS Invoice` AS pi
        LEFT JOIN `tabUser` AS u ON u.name = pi.owner
        WHERE {" AND ".join(where_parts)}
          AND (
            SELECT COUNT(p2.name)
            FROM `tabSales Invoice Payment` AS p2
            WHERE p2.parent = pi.name
          ) > 1
        ORDER BY pi.posting_date DESC, pi.posting_time DESC
        """,
        tuple(params),
        as_dict=True,
    )

    if not invoices:
        return {
            "from_date": from_date,
            "to_date": to_date,
            "branch": branch,
            "terminal": terminal or None,
            "rows": [],
            "summary": {
                "count": 0,
                "total_amount": 0,
                "by_mode": [],
            },
        }

    invoice_names = [r["name"] for r in invoices]
    placeholders = ", ".join(["%s"] * len(invoice_names))
    payment_rows = frappe.db.sql(
        f"""
        SELECT parent, mode_of_payment, amount, base_amount
        FROM `tabSales Invoice Payment`
        WHERE parent IN ({placeholders})
        ORDER BY idx
        """,
        tuple(invoice_names),
        as_dict=True,
    )

    payments_by_invoice: dict = {}
    for p in payment_rows:
        # Skip zero-amount rows — they appear when a cashier added a
        # mode but zeroed it before submitting; not interesting.
        if not (float(p.get("amount") or 0)):
            continue
        payments_by_invoice.setdefault(p["parent"], []).append(
            {
                "mode_of_payment": p["mode_of_payment"],
                "amount": float(p["amount"] or 0),
            }
        )

    rows = []
    by_mode_totals: dict = {}
    grand_total_sum = 0.0
    for inv in invoices:
        payments = payments_by_invoice.get(inv["name"], [])
        # The N>1 SQL filter counts ALL rows; if we filtered out
        # zero-amount rows above and there's now <2 left, this isn't
        # a meaningful split — skip it.
        if len(payments) < 2:
            continue
        rows.append(
            {
                "name": inv["name"],
                "posting_date": str(inv["posting_date"] or ""),
                "posting_time": _time_str(inv["posting_time"]),
                "owner": inv["owner"],
                "owner_full_name": inv["owner_full_name"],
                "customer": inv["customer"],
                "customer_name": inv["customer_name"] or inv["customer"],
                "grand_total": float(inv["grand_total"] or 0),
                "restaurant_table": inv["restaurant_table"],
                "custom_terminal": inv["custom_terminal"],
                "is_return": int(inv.get("is_return") or 0),
                "payment_count": len(payments),
                "payments": payments,
            }
        )
        grand_total_sum += float(inv["grand_total"] or 0)
        for p in payments:
            agg = by_mode_totals.setdefault(
                p["mode_of_payment"],
                {"mode_of_payment": p["mode_of_payment"], "amount": 0.0, "count": 0},
            )
            agg["amount"] += p["amount"]
            agg["count"] += 1

    return {
        "from_date": from_date,
        "to_date": to_date,
        "branch": branch,
        "terminal": terminal or None,
        "rows": rows,
        "summary": {
            "count": len(rows),
            "total_amount": grand_total_sum,
            "by_mode": sorted(
                by_mode_totals.values(),
                key=lambda r: r["amount"],
                reverse=True,
            ),
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

    # Group invoices into one row per shift-close event. The natural
    # event key is (opening_entry, from_cashier, new_cashier) — every
    # invoice transferred during the same shift close shares all three.
    # Within a group we surface the latest transfer_time as the event
    # timestamp, count + total amount in the header, and the per-invoice
    # rows in `invoices` so the frontend can render an expandable
    # details panel.
    events_by_key: dict = {}
    for row in rows:
        key = (
            row.get("opening_entry") or "",
            row.get("from_cashier") or "?",
            row.get("new_cashier") or "?",
        )
        ev = events_by_key.setdefault(
            key,
            {
                "opening_entry": row.get("opening_entry"),
                "from_cashier": row.get("from_cashier"),
                "from_cashier_full_name": row.get("from_cashier_full_name"),
                "to_cashier": row.get("new_cashier"),
                "to_cashier_full_name": row.get("new_cashier_full_name"),
                "transfer_time": row.get("transfer_time"),
                "count": 0,
                "total_amount": 0.0,
                "custom_terminal": row.get("custom_terminal"),
                "invoices": [],
            },
        )
        # Keep the latest transfer_time as the event timestamp.
        rt = row.get("transfer_time")
        if rt and (not ev["transfer_time"] or rt > ev["transfer_time"]):
            ev["transfer_time"] = rt
        ev["count"] += 1
        ev["total_amount"] += float(row.get("grand_total") or 0)
        ev["invoices"].append(
            {
                "name": row.get("name"),
                "customer": row.get("customer"),
                "customer_name": row.get("customer_name") or row.get("customer"),
                "restaurant_table": row.get("restaurant_table"),
                "posting_date": str(row.get("posting_date") or ""),
                "status": row.get("status"),
                "docstatus": row.get("docstatus"),
                "grand_total": float(row.get("grand_total") or 0),
                "custom_terminal": row.get("custom_terminal"),
            }
        )

    # Stable sort: latest events first.
    events = sorted(
        events_by_key.values(),
        key=lambda e: e.get("transfer_time") or "",
        reverse=True,
    )
    for ev in events:
        ev["transfer_time"] = str(ev["transfer_time"] or "")

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
        "events": events,
        # Flat per-invoice list kept around for backwards compat with
        # any caller that still wants the un-grouped view.
        "rows": rows,
        "summary": {
            "event_count": len(events),
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

    Two gates, evaluated in order:
      1. Master switch `custom_enable_returns` on the POS Profile
         (default 0 = OFF). When off, NOBODY can return — not even a
         captain. The Return feature is hidden everywhere and the
         backend rejects every return request until an admin turns it
         on. See CLAUDE.md "Fixes log" 2026-06-05 (returns master
         toggle).
      2. When returns are enabled, `custom_restrict_returns_to_captain`
         (default 1) decides whether cashiers can return their own
         orders or only captains/managers/admins can. Returns are
         sensitive (refunds + stock reversal), so this stays
         conservative out of the box.
    """
    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    captain_roles = {"Administrator", "System Manager", "URY Manager", "URY Captain"}
    is_captain = user == "Administrator" or bool(roles & captain_roles)

    # Gate 1: master switch. Default OFF when the field isn't set yet
    # (fresh install hasn't migrated). Returns stay hidden until enabled.
    enabled = 0
    if pos_profile_name:
        enabled = int(
            frappe.db.get_value(
                "POS Profile", pos_profile_name, "custom_enable_returns"
            )
            or 0
        )
    if not enabled:
        return False, is_captain

    # Gate 2: captain restriction. Default ON when the field isn't set.
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



# ---------------------------------------------------------------------------
# Settings page: KOT routing coverage audit
# ---------------------------------------------------------------------------


def _user_can_manage_settings(user=None):
    """Gate for the POS Settings page. Administrator / System Manager /
    URY Manager only — deliberately EXCLUDES URY Captain, which is a
    floor-ops role. Mirrored by `canAccessSettings` in the frontend's
    role-utils; this is the authoritative check.
    """
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    roles = set(frappe.get_roles(user))
    return bool(roles & {"System Manager", "URY Manager"})


@frappe.whitelist()
def get_kot_coverage_audit(terminal=None):
    """Report which menu item groups will NOT produce a KOT.

    Why this exists: in **URY Production Unit** KDS mode, an item whose
    `item_group` matches no production unit gets **no KOT at all** — it is
    dropped on purpose so a drink doesn't raise a spurious kitchen chit
    (see `process_items_for_kot`). The cost is that an item group nobody
    remembered to attach to a production unit vanishes SILENTLY: it bills
    correctly, prints on the receipt, and never reaches any kitchen or bar
    screen. No error, no log line.

    That is exactly what happened on a live site: a `BEER DRINKS` group was
    never added to the Bar unit, so every beer ever sold was invisible to
    the bar — noticed only by accident months later. This endpoint turns
    that into something an admin can check in ten seconds, BEFORE service,
    instead of discovering it from a customer complaint.

    In **Menu Course** mode unmatched items fall into a fallback KOT and
    are department-split downstream, so nothing is lost. The audit says so
    rather than raising false alarms.

    Returns a per-item-group breakdown with a `covered` flag, the
    production unit(s) each group routes to, and a `sample_items` list so
    the admin can recognise what a group actually contains.
    """
    if not _user_can_manage_settings():
        frappe.throw(
            _("Only an administrator or manager can view POS settings."),
            frappe.PermissionError,
            title=_("Permission Denied"),
        )

    branch_name = getBranch()
    pos_profile = None
    if terminal:
        pos_profile = frappe.db.get_value(
            "URY POS Terminal", terminal, "pos_profile"
        )
    if not pos_profile:
        pos_profile = frappe.db.get_value(
            "POS Profile", {"branch": branch_name, "disabled": 0}, "name"
        )

    kds_mode = (
        frappe.db.get_value("POS Profile", pos_profile, "custom_kds_routing_mode")
        if pos_profile
        else None
    ) or "Menu Course"

    # --- Production units and the item groups they claim -------------
    productions = []
    group_to_productions = {}
    for unit in frappe.get_all(
        "URY Production Unit", filters={"branch": branch_name}, fields=["name"]
    ):
        groups = frappe.get_all(
            "URY Production Item Groups",
            filters={"parent": unit.name, "parenttype": "URY Production Unit"},
            pluck="item_group",
        )
        groups = [g for g in groups if g]
        productions.append({"production": unit.name, "item_groups": sorted(groups)})
        for g in groups:
            group_to_productions.setdefault(g, []).append(unit.name)

    # --- Every item group actually reachable from this branch's menus --
    restaurant = frappe.db.get_value(
        "URY Restaurant", {"branch": branch_name}, "name"
    )
    menu_names = set()
    if restaurant:
        from ury.ury.hooks.ury_pos_profile import _collect_menus_for_restaurant

        try:
            menu_names = _collect_menus_for_restaurant(restaurant)
        except Exception:
            menu_names = set()

    item_codes = []
    if menu_names:
        item_codes = frappe.get_all(
            "URY Menu Item",
            filters={"parenttype": "URY Menu", "parent": ("in", list(menu_names))},
            pluck="item",
        )
    item_codes = sorted({c for c in item_codes if c})

    groups = []
    if item_codes:
        rows = frappe.get_all(
            "Item",
            filters={"name": ("in", item_codes), "disabled": 0},
            fields=["name", "item_name", "item_group"],
        )
        by_group = {}
        for r in rows:
            by_group.setdefault(r.item_group or "(no item group)", []).append(r)
        for group_name in sorted(by_group):
            members = by_group[group_name]
            routed_to = group_to_productions.get(group_name, [])
            groups.append(
                {
                    "item_group": group_name,
                    "item_count": len(members),
                    "covered": 1 if routed_to else 0,
                    "productions": sorted(routed_to),
                    "sample_items": [
                        m.item_name or m.name for m in members[:5]
                    ],
                }
            )

    uncovered = [g for g in groups if not g["covered"]]
    return {
        "branch": branch_name,
        "pos_profile": pos_profile,
        "restaurant": restaurant,
        "kds_routing_mode": kds_mode,
        # Only PU mode silently drops unmatched items. Menu Course mode
        # bundles them into a fallback KOT, so a gap there is harmless.
        "drops_unmatched_items": 1 if kds_mode == "URY Production Unit" else 0,
        "menus_checked": sorted(menu_names),
        "productions": productions,
        "item_groups": groups,
        "uncovered_count": len(uncovered),
        "uncovered_item_total": sum(g["item_count"] for g in uncovered),
        "total_item_groups": len(groups),
        "total_items": len(item_codes),
    }


# ══════════════════════════════════════════════════════════════════════
#  Settings › Menu & Prices  (2026-08-06)
# ══════════════════════════════════════════════════════════════════════
#
# Manage a menu's items and their prices from the POS instead of the
# desk. Admin / manager only — every endpoint below re-checks
# `_user_can_manage_settings`, which deliberately excludes URY Captain.
#
# ⚠ THE COST THAT SHAPES THIS API. `URY Menu.on_update` calls
# `make_price_list()`, which DELETES every Item Price for the menu's
# price list and re-inserts one per row. On a 440-line menu that is 440
# deletes and 440 inserts — per save. So the write endpoints are
# deliberately BULK: the UI collects edits and commits them in one call,
# rather than saving per row and rebuilding the price list on every
# keystroke.
#
# ⚠ AND THE ONE THAT SURPRISES PEOPLE. `URY Menu.validate()` copies
# `Item.standard_rate` into any row whose rate is blank, on every save.
# So "clear this price" does not stick for an item that has a standard
# rate — it comes back. `blocked_by_standard_rate` is returned so the UI
# can say so instead of silently appearing to lose the edit.


def _settings_menu_or_throw(menu):
    if not _user_can_manage_settings():
        frappe.throw(
            _("Only an administrator or {0} can manage menus.").format(
                _("URY Manager")
            ),
            title=_("Not Permitted"),
        )
    if not menu or not frappe.db.exists("URY Menu", menu):
        frappe.throw(
            _("{0} '{1}' not found.").format(_("URY Menu"), menu or ""),
            title=_("Not Found"),
        )
    return frappe.get_doc("URY Menu", menu)


@frappe.whitelist()
def get_menus_for_settings():
    """Every menu, with how many items it holds and how many are unpriced."""
    if not _user_can_manage_settings():
        frappe.throw(_("Not permitted."), title=_("Not Permitted"))

    menus = frappe.get_all(
        "URY Menu", fields=["name", "branch", "enabled", "price_list"], order_by="name"
    )
    counts = frappe.db.sql(
        """SELECT parent,
                  COUNT(*) AS total,
                  SUM(CASE WHEN IFNULL(rate, 0) = 0 THEN 1 ELSE 0 END) AS unpriced
           FROM `tabURY Menu Item`
           WHERE parenttype = 'URY Menu'
           GROUP BY parent""",
        as_dict=True,
    )
    by_menu = {r.parent: r for r in counts}
    for m in menus:
        row = by_menu.get(m.name)
        m["item_count"] = int(row.total) if row else 0
        m["unpriced_count"] = int(row.unpriced or 0) if row else 0
    return menus


@frappe.whitelist()
def get_menu_items_for_settings(menu):
    """Rows on a menu, plus each item's standard_rate.

    `standard_rate` is returned because it is what `validate()` will
    write into a blank rate — the UI needs it to warn honestly.
    """
    doc = _settings_menu_or_throw(menu)
    codes = [r.item for r in doc.items if r.item]
    std = {}
    if codes:
        std = {
            r.name: r.standard_rate
            for r in frappe.get_all(
                "Item",
                filters={"name": ["in", codes]},
                fields=["name", "standard_rate"],
            )
        }

    return {
        "menu": doc.name,
        "branch": doc.branch,
        "price_list": doc.price_list,
        "items": [
            {
                "row": r.name,
                "item": r.item,
                "item_name": r.item_name,
                "course": r.course,
                "rate": flt(r.rate),
                "disabled": int(r.disabled or 0),
                "special_dish": int(r.special_dish or 0),
                "standard_rate": flt(std.get(r.item) or 0),
            }
            for r in doc.items
        ],
        "courses": frappe.get_all("URY Menu Course", pluck="name", order_by="name"),
    }


@frappe.whitelist()
def save_menu_item_rates(menu, updates):
    """Apply a batch of {item: rate} edits in ONE save.

    Bulk on purpose — see the note at the top of this section: each save
    rebuilds the whole price list, so per-row saving would be brutal on
    a large menu.
    """
    doc = _settings_menu_or_throw(menu)
    updates = json.loads(updates) if isinstance(updates, str) else (updates or {})
    if not updates:
        return {"menu": doc.name, "updated": 0}

    changed, blocked = 0, []
    for row in doc.items:
        if row.item not in updates:
            continue
        new_rate = flt(updates[row.item])
        if flt(row.rate) == new_rate:
            continue
        row.rate = new_rate
        changed += 1
        # Clearing a price does not stick when the Item carries a
        # standard_rate: validate() puts it straight back.
        if not new_rate:
            std = flt(frappe.db.get_value("Item", row.item, "standard_rate"))
            if std:
                blocked.append({"item": row.item, "standard_rate": std})

    if changed:
        doc.save()
        frappe.db.commit()

    return {
        "menu": doc.name,
        "updated": changed,
        "blocked_by_standard_rate": blocked,
    }


@frappe.whitelist()
def remove_menu_items(menu, items):
    """Drop rows from a menu. One save for the whole batch."""
    doc = _settings_menu_or_throw(menu)
    items = json.loads(items) if isinstance(items, str) else (items or [])
    wanted = set(items)
    if not wanted:
        return {"menu": doc.name, "removed": 0}

    keep = [r for r in doc.items if r.item not in wanted]
    removed = len(doc.items) - len(keep)
    if not removed:
        return {"menu": doc.name, "removed": 0}

    doc.items = keep
    for idx, row in enumerate(doc.items, start=1):
        row.idx = idx
    doc.save()
    frappe.db.commit()
    return {"menu": doc.name, "removed": removed, "remaining": len(doc.items)}


@frappe.whitelist()
def add_menu_items(menu, items, course=None):
    """Add items to a menu. Already-present items are skipped, not
    duplicated — a menu with the same item twice prices unpredictably."""
    doc = _settings_menu_or_throw(menu)
    items = json.loads(items) if isinstance(items, str) else (items or [])
    if not items:
        return {"menu": doc.name, "added": 0}

    if course and not frappe.db.exists("URY Menu Course", course):
        frappe.throw(
            _("{0} '{1}' not found.").format(_("URY Menu Course"), course),
            title=_("Not Found"),
        )

    present = {r.item for r in doc.items if r.item}
    added, skipped = 0, 0
    for code in items:
        if code in present:
            skipped += 1
            continue
        if not frappe.db.exists("Item", code):
            skipped += 1
            continue
        doc.append(
            "items",
            {
                "item": code,
                "item_name": frappe.db.get_value("Item", code, "item_name"),
                "course": course or None,
            },
        )
        present.add(code)
        added += 1

    if added:
        doc.save()
        frappe.db.commit()
    return {
        "menu": doc.name,
        "added": added,
        "skipped": skipped,
        "total": len(doc.items),
    }


@frappe.whitelist()
def search_items_for_menu(menu, query=None, item_group=None, limit=50):
    """Items NOT already on this menu, for the add-item picker."""
    doc = _settings_menu_or_throw(menu)
    on_menu = [r.item for r in doc.items if r.item]

    filters = {"disabled": 0}
    if item_group:
        filters["item_group"] = item_group
    if on_menu:
        filters["name"] = ["not in", on_menu]

    or_filters = None
    if query:
        or_filters = [
            ["name", "like", f"%{query}%"],
            ["item_name", "like", f"%{query}%"],
        ]

    return frappe.get_all(
        "Item",
        filters=filters,
        or_filters=or_filters,
        fields=["name", "item_name", "item_group", "standard_rate"],
        order_by="item_name",
        limit_page_length=int(limit or 50),
    )


@frappe.whitelist()
def get_item_groups_for_menu():
    """Item groups that actually contain sellable items, for the picker
    filter. Leaf groups only — a parent group holds nothing itself."""
    if not _user_can_manage_settings():
        frappe.throw(_("Not permitted."), title=_("Not Permitted"))
    return frappe.db.sql_list(
        """SELECT DISTINCT item_group FROM `tabItem`
           WHERE disabled = 0 AND IFNULL(item_group, '') != ''
           ORDER BY item_group"""
    )


@frappe.whitelist()
def get_course_sales(from_date=None, to_date=None, terminal=None):
    """Covers — sales by menu course, with the items inside each course.

    Answers "how is each course selling, and what within it?" in ONE
    call: a course row carries how many bills contained it, how many
    units went out and what it took, and nests the items that make it
    up so the UI can drill down without a second round-trip.

    TWO THINGS THAT WOULD SKEW THIS IF IGNORED:

    * An item can appear on SEVERAL menus (default, per-room,
      per-order-type). Joining POS Invoice Item straight to URY Menu
      Item would multiply a line once per menu it appears on and
      inflate every figure. The join therefore goes through a
      GROUP BY subquery that collapses each item to ONE course.
    * `bill_count` is COUNT(DISTINCT invoice), not a row count. Two
      lines of the same course on one bill is one bill, not two — and
      "number of sales" read as a row count would overstate a busy
      table.

    Returns will (`is_return = 1`) contribute negative amounts, so a
    refunded dish reduces its course rather than inflating it.
    """
    if not _user_can_see_admin_reports():
        frappe.throw(
            _("You don't have permission to see this report."),
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

    # One course per item — see the docstring. MIN() is an arbitrary but
    # STABLE pick when an item is on two menus under different courses,
    # so the report doesn't shuffle between runs.
    sql = f"""
        SELECT
            COALESCE(NULLIF(mi.course, ''), 'Uncategorised') AS course,
            pii.item_code                                    AS item_code,
            MAX(pii.item_name)                               AS item_name,
            COUNT(DISTINCT pi.name)                          AS bill_count,
            SUM(COALESCE(pii.qty, 0))                        AS qty,
            SUM(COALESCE(pii.amount, 0))                     AS amount
        FROM `tabPOS Invoice Item` AS pii
        INNER JOIN `tabPOS Invoice` AS pi ON pi.name = pii.parent
        LEFT JOIN (
            SELECT item, MIN(course) AS course
            FROM `tabURY Menu Item`
            GROUP BY item
        ) AS mi ON mi.item = pii.item_code
        WHERE {" AND ".join(where_parts)}
        GROUP BY course, pii.item_code
        ORDER BY course ASC, amount DESC
    """
    rows = frappe.db.sql(sql, tuple(params), as_dict=True)

    courses = {}
    for r in rows:
        c = courses.setdefault(
            r["course"],
            {
                "course": r["course"],
                "bill_count": 0,
                "qty": 0.0,
                "amount": 0.0,
                "item_count": 0,
                "items": [],
            },
        )
        c["items"].append(
            {
                "item_code": r["item_code"],
                "item_name": r["item_name"],
                # How many separate bills this item appeared on — i.e.
                # how many times it was ordered.
                "bill_count": int(r["bill_count"] or 0),
                "qty": float(r["qty"] or 0),
                "amount": float(r["amount"] or 0),
            }
        )
        c["qty"] += float(r["qty"] or 0)
        c["amount"] += float(r["amount"] or 0)
        c["item_count"] += 1

    # A course's bill_count must be counted across the WHOLE course, not
    # summed from its items — the same bill can hold three items of one
    # course and would otherwise be counted three times.
    course_bills = frappe.db.sql(
        f"""
        SELECT COALESCE(NULLIF(mi.course, ''), 'Uncategorised') AS course,
               COUNT(DISTINCT pi.name) AS bill_count
        FROM `tabPOS Invoice Item` AS pii
        INNER JOIN `tabPOS Invoice` AS pi ON pi.name = pii.parent
        LEFT JOIN (
            SELECT item, MIN(course) AS course
            FROM `tabURY Menu Item`
            GROUP BY item
        ) AS mi ON mi.item = pii.item_code
        WHERE {" AND ".join(where_parts)}
        GROUP BY course
        """,
        tuple(params),
        as_dict=True,
    )
    for row in course_bills:
        if row["course"] in courses:
            courses[row["course"]]["bill_count"] = int(row["bill_count"] or 0)

    ordered = sorted(courses.values(), key=lambda c: c["amount"], reverse=True)
    total_amount = sum(c["amount"] for c in ordered)
    for c in ordered:
        c["percentage"] = round(c["amount"] / total_amount * 100, 1) if total_amount else 0

    return {
        "from_date": from_date,
        "to_date": to_date,
        "branch": branch,
        "terminal": terminal or None,
        "courses": ordered,
        "totals": {
            "amount": total_amount,
            "qty": sum(c["qty"] for c in ordered),
            "course_count": len(ordered),
        },
    }
