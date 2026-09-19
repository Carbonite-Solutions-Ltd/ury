# Copyright (c) 2026, Tridotstech and contributors
# For license information, please see license.txt

"""Bar stock handover report for the KDS Served page.

WHY A "BAR SESSION" AND NOT THE POS SHIFT
-----------------------------------------
Outlets routinely leave POS Opening Entries open for days, so a shift is not a
reliable boundary for "what happened on my watch". Instead the barman OPENS THE
BAR on the KDS when he takes over. That moment is the boundary, and the stock
snapshot taken then is what he is accountable for. Opening a new session
auto-closes the previous one, so nothing breaks when somebody forgets to close.

WHY BIN QUANTITY ALONE IS WRONG
-------------------------------
A POS Invoice posts NO stock ledger entries. ERPNext defers them to the
consolidated Sales Invoice created at shift close (verified on this site:
`tabStock Ledger Entry` holds rows for Sales Invoice / Stock Entry / Stock
Reconciliation and NONE for POS Invoice). So `Bin.actual_qty` still counts
drinks that left the shelf hours ago. Everything here therefore works in
PHYSICAL terms:

    physical = Bin.actual_qty - (sold on invoices not yet consolidated)

WHY "SOLD" IS DERIVED AND NOT COUNTED FROM TIMESTAMPS
-----------------------------------------------------
The obvious approach - sum invoice lines created after the session opened -
cannot work: `sync_order` clears and rebuilds `invoice.items` on every edit, so
a line's `creation` is reset whenever the tab is touched. A tab opened before
the handover and added to afterwards would be attributed entirely to one side
or the other, and the error would land in the new barman's expected count.

So both ends are measured physically and the movement is derived:

    expected on hand = physical now
    sold / used      = opening - expected on hand

That always adds up, needs no attribution, and is self-correcting: a
consolidation mid-session lowers Bin and the unposted figure by the same
amount, leaving `expected` untouched. A stock receipt into the bar's warehouse
during the session legitimately shows as a NEGATIVE "sold" (stock went up).
`rung_item_count` in the summary is the cross-check straight off the bills.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from ury.ury.api.ury_kds_access import require_unit_access

from ury.ury.doctype.ury_order.ury_order import (
    _get_warehouse_tree,
    _pick_outlet_warehouse,
)


# ---------------------------------------------------------------- helpers


def _get_unit(production):
    """The URY Production Unit doc, or a clean error."""
    if not production or production == "All":
        frappe.throw(
            _("Pick a specific production unit to use the stock report."),
            title=_("No Production Unit"),
        )
    if not frappe.db.exists("URY Production Unit", production):
        frappe.throw(
            _("Production unit {0} was not found.").format(production),
            title=_("Unit Not Found"),
        )
    require_unit_access(production)
    return frappe.get_doc("URY Production Unit", production)


def _assert_bar(unit):
    """Only Bar units get the stock report (URY Production Unit.unit_type)."""
    if (unit.get("unit_type") or "Kitchen") != "Bar":
        frappe.throw(
            _(
                "{0} is not a Bar unit. Set its Unit Type to 'Bar' in the desk to use "
                "the stock report."
            ).format(unit.name),
            title=_("Not A Bar"),
        )


def _unit_item_codes(unit):
    """Enabled stock items in this unit's item groups.

    Item groups are how a production unit is already defined (they drive KOT
    routing), so the stock sheet is exactly the set of products this unit is
    responsible for. Non-stock items are skipped - there is nothing to count.
    """
    groups = [r.item_group for r in (unit.get("item_groups") or []) if r.item_group]
    if not groups:
        return []

    return frappe.get_all(
        "Item",
        filters={"item_group": ("in", groups), "is_stock_item": 1, "disabled": 0},
        fields=["name as item_code", "item_name", "item_group", "stock_uom"],
        order_by="item_group asc, item_name asc",
    )


def _unit_context(unit):
    """(company, cost_center, fixed_warehouse) for this unit."""
    company = cost_center = None
    if unit.pos_profile:
        row = frappe.db.get_value(
            "POS Profile",
            unit.pos_profile,
            ["company", "cost_center", "warehouse", "custom_use_pos_warehouse"],
            as_dict=True,
        )
        if row:
            company = row.company
            cost_center = row.cost_center
            # In single-warehouse mode every sale posts to the till's
            # warehouse, so the bar's stock is there and nowhere else.
            if row.custom_use_pos_warehouse and row.warehouse:
                return company, cost_center, row.warehouse
    return company, cost_center, unit.get("warehouse") or None


def _resolve_warehouses(item_codes, company, cost_center, fixed_warehouse):
    """{item_code: warehouse}, resolved the way a sale on this till resolves it.

    Reuses `_pick_outlet_warehouse` - the same pure function `sync_order` uses -
    so the stock we report is the stock the sale will actually deduct. Bulk:
    one query for the defaults and one warehouse tree, instead of two per item.
    """
    if fixed_warehouse:
        return {code: fixed_warehouse for code in item_codes}
    if not company or not item_codes:
        return {}

    defaults = {
        r.parent: r.default_warehouse
        for r in frappe.get_all(
            "Item Default",
            filters={"parent": ("in", item_codes), "company": company},
            fields=["parent", "default_warehouse"],
        )
    }
    if not cost_center:
        return {code: defaults.get(code) for code in item_codes}

    tree = _get_warehouse_tree(company)
    return {
        code: _pick_outlet_warehouse(defaults.get(code), cost_center, tree)
        for code in item_codes
    }


def _bin_qty(warehouse_by_item):
    """{item_code: Bin.actual_qty} for each item's own resolved warehouse."""
    pairs = [(c, w) for c, w in warehouse_by_item.items() if w]
    if not pairs:
        return {}

    rows = frappe.get_all(
        "Bin",
        filters={
            "item_code": ("in", [c for c, _w in pairs]),
            "warehouse": ("in", sorted({w for _c, w in pairs})),
        },
        fields=["item_code", "warehouse", "actual_qty"],
    )
    wanted = set(pairs)
    return {
        r.item_code: flt(r.actual_qty)
        for r in rows
        if (r.item_code, r.warehouse) in wanted
    }


def _sold_qty(pos_profile, item_codes, unconsolidated_only=False, since=None):
    """{item_code: qty sold}, in STOCK uom.

    `stock_qty` (not `qty`) because a bar sells a glass out of a bottle, and
    Bin counts bottles. Returns reduce the figure naturally: a return invoice
    carries negative quantities.

    Scoped to the outlet's POS Profile, not just the branch - two outlets
    (Airport / Sitout) can share one branch and each has its own stock.
    Cancelled invoices and merged-away source invoices are excluded; open
    tabs (drafts) are INCLUDED, because the drink has left the shelf whether
    or not it has been paid for.
    """
    if not item_codes or not pos_profile:
        return {}

    conditions = [
        "pi.docstatus < 2",
        "pi.pos_profile = %(pos_profile)s",
        "(pi.custom_merged_into IS NULL OR pi.custom_merged_into = '')",
        "pii.item_code IN %(items)s",
    ]
    params = {
        "pos_profile": pos_profile,
        "items": tuple(item_codes),
    }
    if unconsolidated_only:
        conditions.append(
            "(pi.consolidated_invoice IS NULL OR pi.consolidated_invoice = '')"
        )
    if since:
        conditions.append("pi.creation >= %(since)s")
        params["since"] = since

    # Every value is parameterised; the clauses themselves are literals.
    rows = frappe.db.sql(
        """
        SELECT pii.item_code AS item_code, SUM(pii.stock_qty) AS qty
        FROM `tabPOS Invoice Item` pii
        JOIN `tabPOS Invoice` pi ON pi.name = pii.parent
        WHERE {where}
        GROUP BY pii.item_code
        """.format(where=" AND ".join(conditions)),
        params,
        as_dict=True,
    )
    return {r.item_code: flt(r.qty) for r in rows}


def _physical_qty(item_codes, warehouse_by_item, pos_profile):
    """{item_code: what should be on the shelf right now}.

    Bin, minus everything already sold on invoices that have not been
    consolidated (and so have not yet been deducted from Bin).
    """
    on_hand = _bin_qty(warehouse_by_item)
    unposted = _sold_qty(pos_profile, item_codes, unconsolidated_only=True)
    return {
        code: flt(on_hand.get(code, 0)) - flt(unposted.get(code, 0))
        for code in item_codes
    }, on_hand, unposted


# ---------------------------------------------------------- report maths


def build_report_rows(snapshot, physical, show_all=False):
    """Join the opening snapshot to what is physically there now. PURE.

    `snapshot` - the session's rows (item_code, item_name, item_group,
    stock_uom, opening_qty). `physical` - {item_code: qty now}.

    Kept free of the database so every arithmetic case is unit-tested:
    see test_ury_bar_stock.py.
    """
    rows = []
    for line in snapshot:
        code = line.get("item_code")
        opening = flt(line.get("opening_qty"))
        expected = flt(physical.get(code, 0))
        sold = opening - expected

        if not show_all and not opening and not expected and not sold:
            continue

        rows.append(
            {
                "item_code": code,
                "item_name": line.get("item_name") or code,
                "item_group": line.get("item_group"),
                "stock_uom": line.get("stock_uom"),
                "opening_qty": opening,
                "sold_qty": sold,
                "expected_qty": expected,
                "is_negative": 1 if expected < 0 else 0,
            }
        )
    return rows


def summarise_rows(rows):
    """Headline COUNTS for the sheet. PURE.

    Deliberately counts and never sums quantities: a bar's lines are in
    different units (bottles, glasses, kg), so a total quantity would be a
    meaningless number - the first draft produced "total opening 182,096"
    by adding bottles to glasses. What a handover actually needs to know is
    how many lines moved and how many look wrong.
    """
    return {
        "line_count": len(rows),
        "moved_count": sum(1 for r in rows if r["sold_qty"]),
        "negative_count": sum(1 for r in rows if r["is_negative"]),
    }


# ------------------------------------------------------------ endpoints


@frappe.whitelist()
def get_bar_session_state(production=None):
    """Is this a Bar unit, and is a session open? Drives the KDS prompt."""
    unit = _get_unit(production)
    unit_type = unit.get("unit_type") or "Kitchen"
    if unit_type != "Bar":
        return {"production": unit.name, "unit_type": unit_type, "is_bar": 0}

    session = frappe.db.get_value(
        "URY Bar Session",
        {"production_unit": unit.name, "status": "Open"},
        ["name", "opened_by", "opened_at"],
        as_dict=True,
    )
    if session:
        session["opened_by_name"] = (
            frappe.db.get_value("User", session.opened_by, "full_name")
            or session.opened_by
        )

    return {
        "production": unit.name,
        "unit_type": unit_type,
        "is_bar": 1,
        "session": session,
        "item_count": len(_unit_item_codes(unit)),
    }


@frappe.whitelist(methods=["POST"])
def open_bar_session(production=None, notes=None):
    """Take over the bar: snapshot the stock and start a new session.

    Any session still open for this unit is closed first - people forget, and
    a stale open session would make the next handover meaningless.
    """
    unit = _get_unit(production)
    _assert_bar(unit)

    items = _unit_item_codes(unit)
    if not items:
        frappe.throw(
            _(
                "{0} has no item groups with stock items, so there is nothing to count. "
                "Add the bar's item groups to the production unit in the desk."
            ).format(unit.name),
            title=_("Nothing To Count"),
        )

    company, cost_center, fixed_warehouse = _unit_context(unit)
    codes = [i.item_code for i in items]
    warehouses = _resolve_warehouses(codes, company, cost_center, fixed_warehouse)
    _, on_hand, unposted = _physical_qty(codes, warehouses, unit.pos_profile)

    previous = frappe.get_all(
        "URY Bar Session",
        filters={"production_unit": unit.name, "status": "Open"},
        pluck="name",
    )
    now = now_datetime()
    for name in previous:
        frappe.db.set_value(
            "URY Bar Session",
            name,
            {"status": "Closed", "closed_by": frappe.session.user, "closed_at": now},
            update_modified=False,
        )

    session = frappe.new_doc("URY Bar Session")
    session.production_unit = unit.name
    session.status = "Open"
    session.pos_profile = unit.pos_profile
    session.branch = unit.branch
    session.company = company
    session.opened_by = frappe.session.user
    session.opened_at = now
    session.notes = notes
    for item in items:
        system_qty = flt(on_hand.get(item.item_code, 0))
        sold_not_posted = flt(unposted.get(item.item_code, 0))
        session.append(
            "items",
            {
                "item_code": item.item_code,
                "item_name": item.item_name,
                "item_group": item.item_group,
                "stock_uom": item.stock_uom,
                "warehouse": warehouses.get(item.item_code),
                "system_qty": system_qty,
                "unposted_sold_qty": sold_not_posted,
                "opening_qty": system_qty - sold_not_posted,
            },
        )
    session.insert(ignore_permissions=True)
    frappe.db.commit()

    return {
        "session": session.name,
        "opened_at": str(session.opened_at),
        "item_count": len(items),
        "closed_previous": previous,
    }


@frappe.whitelist(methods=["POST"])
def close_bar_session(production=None, notes=None):
    """Close the open session (handing over). Idempotent."""
    unit = _get_unit(production)
    _assert_bar(unit)

    name = frappe.db.get_value(
        "URY Bar Session", {"production_unit": unit.name, "status": "Open"}, "name"
    )
    if not name:
        return {"closed": 0, "message": _("The bar is not open.")}

    values = {
        "status": "Closed",
        "closed_by": frappe.session.user,
        "closed_at": now_datetime(),
    }
    if notes:
        values["notes"] = notes
    frappe.db.set_value("URY Bar Session", name, values, update_modified=False)
    frappe.db.commit()
    return {"closed": 1, "session": name}


@frappe.whitelist()
def get_bar_stock_report(production=None, session=None, show_all=0):
    """The handover sheet: opening stock, what moved, what should be left."""
    unit = _get_unit(production)
    _assert_bar(unit)
    show_all = frappe.utils.cint(show_all)

    if session:
        if not frappe.db.exists("URY Bar Session", session):
            frappe.throw(_("Session {0} was not found.").format(session))
        session_doc = frappe.get_doc("URY Bar Session", session)
    else:
        name = frappe.db.get_value(
            "URY Bar Session",
            {"production_unit": unit.name, "status": "Open"},
            "name",
        ) or frappe.db.get_value(
            "URY Bar Session",
            {"production_unit": unit.name},
            "name",
            order_by="opened_at desc",
        )
        if not name:
            return {"has_session": 0, "production": unit.name}
        session_doc = frappe.get_doc("URY Bar Session", name)

    snapshot = [
        {
            "item_code": r.item_code,
            "item_name": r.item_name,
            "item_group": r.item_group,
            "stock_uom": r.stock_uom,
            "opening_qty": r.opening_qty,
        }
        for r in session_doc.items
    ]
    codes = [r["item_code"] for r in snapshot]
    warehouses = {r.item_code: r.warehouse for r in session_doc.items}
    physical, _on_hand, _unposted = _physical_qty(
        codes, warehouses, session_doc.pos_profile
    )

    rows = build_report_rows(snapshot, physical, show_all=show_all)
    totals = summarise_rows(rows)
    # Straight off the bills - a sanity check on the derived "sold" column.
    # A COUNT of items, not a quantity: quantities are in mixed units.
    rung = _sold_qty(session_doc.pos_profile, codes, since=session_doc.opened_at)

    return {
        "has_session": 1,
        "production": unit.name,
        "session": session_doc.name,
        "status": session_doc.status,
        "opened_at": str(session_doc.opened_at),
        "opened_by": session_doc.opened_by,
        "opened_by_name": frappe.db.get_value("User", session_doc.opened_by, "full_name")
        or session_doc.opened_by,
        "closed_at": str(session_doc.closed_at) if session_doc.closed_at else None,
        "closed_by_name": (
            frappe.db.get_value("User", session_doc.closed_by, "full_name")
            or session_doc.closed_by
        )
        if session_doc.closed_by
        else None,
        "generated_at": str(now_datetime()),
        "generated_by": frappe.db.get_value("User", frappe.session.user, "full_name")
        or frappe.session.user,
        "show_all": show_all,
        "hidden_count": len(snapshot) - len(rows),
        "rung_item_count": sum(1 for v in rung.values() if flt(v)),
        "rows": rows,
        "totals": totals,
    }
