import json

import frappe
from frappe import _
from ury.ury_pos.api import getBranch, _get_self_waiter_for_user
from frappe.utils import get_datetime


# Function to set order status in a KOT document
@frappe.whitelist()
def serve_kot(name, time):
    current_time = get_datetime()
    creation_time = frappe.db.get_value("URY KOT", name, "creation")

    production_time = current_time - creation_time
    production_time_minutes = production_time.total_seconds() / 60
    
    # Update KOT fields
    frappe.db.set_value("URY KOT", name, "start_time_serv", time)
    frappe.db.set_value("URY KOT", name, "production_time", production_time_minutes)
    frappe.db.set_value("URY KOT", name, "order_status", "Served")
    # Sortable served timestamp — `start_time_serv` is a locale time STRING
    # ("3:45:12 PM") so it can't order the served list. 2026-07-16.
    frappe.db.set_value("URY KOT", name, "served_at", current_time)
    
    # Update linked POS Invoice status
    try:
        invoice = frappe.db.get_value("URY KOT", name, "invoice")
        
        if invoice and frappe.db.exists("POS Invoice", invoice):
            # Get invoice owner + waiter so the "served" alert reaches
            # everyone who owns the order: the user who rang it (owner)
            # AND the waiter it was rung for (custom_waiter → linked
            # User). When a cashier rings on a waiter's behalf, owner is
            # the cashier and custom_waiter is the waiter — both must be
            # notified. 2026-07-15.
            invoice_row = frappe.db.get_value(
                "POS Invoice",
                invoice,
                ["owner", "custom_waiter"],
                as_dict=True,
            ) or {}
            invoice_owner = invoice_row.get("owner")
            waiter_record = invoice_row.get("custom_waiter")
            waiter_user = (
                frappe.db.get_value("URY Waiter", waiter_record, "user")
                if waiter_record
                else None
            )

            # Update POS Invoice custom_order_status to Served
            frappe.db.set_value(
                "POS Invoice",
                invoice,
                "custom_order_status",
                "Served",
                update_modified=False
            )
            
            # Get notification details
            notification_data = frappe.db.sql("""
                SELECT 
                    pi.name as invoice,
                    pi.customer_name,
                    pi.restaurant_table,
                    pi.grand_total,
                    k.name as kot_name,
                    GROUP_CONCAT(
                        CONCAT(ki.item_name, ' x', ki.qty) 
                        ORDER BY ki.idx 
                        SEPARATOR ', '
                    ) as items_list,
                    COUNT(DISTINCT ki.name) as items_count
                FROM `tabPOS Invoice` pi
                LEFT JOIN `tabURY KOT` k ON k.invoice = pi.name
                LEFT JOIN `tabURY KOT Items` ki ON ki.parent = k.name
                WHERE pi.name = %s
                GROUP BY pi.name
            """, (invoice,), as_dict=True)
            
            if notification_data:
                # Publish to the owner AND (when different) the waiter's
                # linked user, so both the cashier who rang it and the
                # waiter it was rung for get the served alert in real time.
                recipients = set()
                if invoice_owner:
                    recipients.add(invoice_owner)
                if waiter_user:
                    recipients.add(waiter_user)
                for recipient in recipients:
                    frappe.publish_realtime(
                        event="order_served_notification",
                        message=notification_data[0],
                        user=recipient,
                    )
            
            frappe.logger().info(f"Updated POS Invoice {invoice} to Served from KOT {name}")
        
        frappe.db.commit()
        
    except Exception as e:
        frappe.log_error(f"Error updating invoice status: {str(e)}", "Serve KOT Error")
        pass


@frappe.whitelist()
def reinstate_kot(name):
    """Undo a serve — the kitchen marked a KOT served by mistake (2026-07-16).

    Puts the KOT back on the board and withdraws the "food ready" alert from
    the waiter by clearing the invoice's `custom_order_status`. An invoice can
    carry several KOTs, so any un-serve clears the invoice-level Served flag —
    it goes back to Served when the kitchen serves again.
    """
    if not frappe.db.exists("URY KOT", name):
        frappe.throw(_("KOT {0} not found.").format(name), title=_("Not Found"))
    if frappe.db.get_value("URY KOT", name, "order_status") != "Served":
        frappe.throw(
            _("This order isn't marked served."), title=_("Nothing to Undo")
        )

    frappe.db.set_value(
        "URY KOT",
        name,
        {
            "order_status": "Ready For Prepare",
            "served_at": None,
            "start_time_serv": None,
            "production_time": 0,
        },
        update_modified=False,
    )

    invoice = frappe.db.get_value("URY KOT", name, "invoice")
    if invoice and frappe.db.exists("POS Invoice", invoice):
        # Withdraw the waiter's "ready" alert.
        frappe.db.set_value(
            "POS Invoice",
            invoice,
            {"custom_order_status": "", "custom_clear_from_notification": 0},
            update_modified=False,
        )
    frappe.db.commit()

    branch = frappe.db.get_value("URY KOT", name, "branch")
    if branch:
        frappe.publish_realtime(
            event=f"kot_update_{branch}_All",
            message={"kot": name, "reinstated": 1},
            after_commit=True,
        )
    return {"kot": name, "status": "Ready For Prepare"}


# ============================================================
# Kitchen -> waiter change requests (2026-07-16)
# ------------------------------------------------------------
# The kitchen can't always cook an order as rung (out of stock, can't
# honour a special instruction). Instead of silently changing it, the
# kitchen raises a TEXT request; the KOT goes ON HOLD ("Awaiting
# Confirmation", Serve disabled on the KDS) and the waiter is alerted.
# She checks with the customer, edits the order normally if they agree,
# then Confirms — or Rejects, which means "cook it as originally
# ordered". The kitchen never edits quantities or prices, so the invoice
# is never touched by this flow.
# ============================================================


def _kot_waiter_name(invoice):
    """Friendly waiter name for the KDS card badge, or None (2026-07-16)."""
    if not invoice:
        return None
    waiter = frappe.db.get_value("POS Invoice", invoice, "custom_waiter")
    if not waiter:
        return None
    return frappe.db.get_value("URY Waiter", waiter, "full_name") or waiter


def _kot_notify_users(invoice):
    """Users who should be alerted about this invoice: the owner (whoever
    rang it) plus the waiter it was rung for. Mirrors serve_kot."""
    row = frappe.db.get_value(
        "POS Invoice", invoice, ["owner", "custom_waiter"], as_dict=True
    ) or {}
    recipients = set()
    if row.get("owner"):
        recipients.add(row["owner"])
    waiter_record = row.get("custom_waiter")
    if waiter_record:
        waiter_user = frappe.db.get_value("URY Waiter", waiter_record, "user")
        if waiter_user:
            recipients.add(waiter_user)
    return recipients


def _kot_kds_targets(kot, production):
    """The KDS screen targets this KOT appears on, so a realtime ping can
    reach the right kitchen screens (2026-07-23). URY Production Unit mode →
    its production unit; Menu Course mode (`production` is NULL) → the
    departments of its items (course → custom_department, default "Food")."""
    if production:
        return {production}
    targets = set()
    for row in frappe.get_all(
        "URY KOT Items", filters={"parent": kot}, fields=["course"]
    ):
        dept = None
        if row.get("course"):
            dept = frappe.db.get_value(
                "URY Menu Course", row["course"], "custom_department"
            )
        targets.add(dept or "Food")
    return targets


@frappe.whitelist()
def request_kot_change(kot, message, item=None):
    """Kitchen raises a change request → KOT goes on hold, waiter alerted."""
    message = (message or "").strip()
    if not message:
        frappe.throw(_("Please describe the change you need."), title=_("Empty Request"))
    if not frappe.db.exists("URY KOT", kot):
        frappe.throw(_("KOT {0} not found.").format(kot), title=_("Not Found"))

    invoice = frappe.db.get_value("URY KOT", kot, "invoice")
    now_dt = frappe.utils.now_datetime()
    frappe.db.set_value(
        "URY KOT",
        kot,
        {
            "change_status": "Awaiting Confirmation",
            "change_request": message,
            "change_item": item or None,
            "change_requested_by": frappe.session.user,
            "change_requested_at": now_dt,
            "change_resolved_by": None,
            "change_resolved_at": None,
        },
        update_modified=False,
    )
    frappe.db.commit()

    payload = {
        "kot": kot,
        "invoice": invoice,
        "item": item,
        "message": message,
        "requested_by": frappe.session.user,
    }
    for recipient in _kot_notify_users(invoice):
        frappe.publish_realtime(
            event="kot_change_request", message=payload, user=recipient
        )
    return {"kot": kot, "status": "Awaiting Confirmation"}


def _update_item_note(kot, item_name, note):
    """Point the special instruction at BOTH the KOT item (what the kitchen
    reads) and the matching POS Invoice item (what the bill/record keeps),
    so they can't drift. Best-effort: a missing row is skipped."""
    if not item_name:
        return
    note = (note or "").strip()
    for row in frappe.get_all(
        "URY KOT Items",
        filters={"parent": kot, "item_name": item_name},
        fields=["name"],
    ):
        frappe.db.set_value(
            "URY KOT Items", row["name"], "comments", note, update_modified=False
        )
    invoice = frappe.db.get_value("URY KOT", kot, "invoice")
    if invoice:
        for row in frappe.get_all(
            "POS Invoice Item",
            filters={"parent": invoice, "item_name": item_name},
            fields=["name"],
        ):
            frappe.db.set_value(
                "POS Invoice Item", row["name"], "comment", note,
                update_modified=False,
            )


@frappe.whitelist()
def respond_kot_change(kot, action, note=None, item_note=None):
    """Waiter answers a kitchen change request (2026-07-16).

    `action`:
      - ``confirm`` — customer agreed to what the kitchen proposed.
      - ``update``  — waiter revised the SPECIAL REQUEST for the item (and
        may add a note back). Deliberately only touches the instruction —
        never quantities, items or price; re-ringing the order is the
        cashier's job.
      - ``cancel``  — customer no longer wants it. This cancels the KITCHEN
        order only; the card leaves the board once the kitchen accepts.
        Cancelling the INVOICE stays a captain action (`cancel_order`).

    Every outcome leaves the KOT waiting on the kitchen to Accept, so the
    cook always sees what came back before the card clears.
    """
    action = (action or "").strip().lower()
    if action not in ("confirm", "update", "cancel"):
        frappe.throw(_("Invalid action."), title=_("Bad Request"))
    current = frappe.db.get_value("URY KOT", kot, "change_status")
    if current != "Awaiting Confirmation":
        frappe.throw(
            _("This request has already been resolved."),
            title=_("Already Resolved"),
        )

    status_map = {
        "confirm": "Confirmed",
        "update": "Updated",
        "cancel": "Cancelled",
    }
    new_status = status_map[action]

    if action == "update":
        _update_item_note(
            kot, frappe.db.get_value("URY KOT", kot, "change_item"), item_note
        )

    frappe.db.set_value(
        "URY KOT",
        kot,
        {
            "change_status": new_status,
            "change_response": (note or "").strip() or None,
            "change_resolved_by": frappe.session.user,
            "change_resolved_at": frappe.utils.now_datetime(),
        },
        update_modified=False,
    )
    frappe.db.commit()

    # Tell the kitchen screens so the card updates immediately — no reload
    # (2026-07-23). The KDS subscribes per screen to
    # `kot_change_resolved_<branch>_<target>`, where target is the production
    # unit (URY Production Unit mode) or the item's department (Menu Course
    # mode), plus an "All" channel. The previous code pinged
    # `kot_update_<branch>_All` with just the KOT name, which the new-KOT
    # socket handler mis-read as a fresh card — and it never reached a
    # specific production screen at all, so the kitchen had to reload.
    branch = frappe.db.get_value("URY KOT", kot, "branch")
    production = frappe.db.get_value("URY KOT", kot, "production")
    msg = {"kot": kot, "status": new_status, "by": frappe.session.user}
    if branch:
        frappe.publish_realtime(
            event=f"kot_change_resolved_{branch}_All",
            message=msg,
            after_commit=True,
        )
        for target in _kot_kds_targets(kot, production):
            frappe.publish_realtime(
                event=f"kot_change_resolved_{branch}_{target}",
                message=msg,
                after_commit=True,
            )
    # Legacy global event kept for any other listener.
    frappe.publish_realtime(
        event="kot_change_resolved", message=msg, after_commit=True
    )
    return {"kot": kot, "status": new_status}


@frappe.whitelist()
def kitchen_ack_change(kot):
    """Kitchen acknowledges whatever the waiter sent back (2026-07-16).

    Confirmed / Updated → the change fields clear and the card comes off
    hold so the cook carries on. Cancelled → the card leaves the board:
    `order_status` becomes "Cancelled by Waiter", which matches neither the
    active board's "Ready For Prepare" filter nor the served list's
    "Served", so it simply drops out (order_status is a free-text Data
    field, so this needs no schema change).
    """
    status = frappe.db.get_value("URY KOT", kot, "change_status")
    if status not in ("Confirmed", "Updated", "Cancelled"):
        frappe.throw(
            _("There's nothing waiting to be accepted on this order."),
            title=_("Nothing to Accept"),
        )

    updates = {
        "change_status": "",
        "change_request": None,
        "change_item": None,
        "change_response": None,
        "change_requested_by": None,
        "change_requested_at": None,
        "change_resolved_by": None,
        "change_resolved_at": None,
    }
    if status == "Cancelled":
        updates["order_status"] = "Cancelled by Waiter"

    frappe.db.set_value("URY KOT", kot, updates, update_modified=False)
    frappe.db.commit()
    return {"kot": kot, "accepted": status}


@frappe.whitelist()
def get_kitchen_change_requests():
    """Pending kitchen change requests for the current user (the invoice
    owner OR the waiter it was rung for). Drives the Alerts page + badge."""
    user = frappe.session.user
    self_waiter = _get_self_waiter_for_user(user)

    clause = "pi.owner = %(user)s"
    params = {"user": user}
    if self_waiter:
        clause = "(pi.owner = %(user)s OR pi.custom_waiter = %(waiter)s)"
        params["waiter"] = self_waiter["name"]

    return frappe.db.sql(
        f"""
        SELECT k.name AS kot, k.change_request, k.change_item,
               k.change_requested_by, k.change_requested_at,
               k.invoice, pi.customer_name, pi.restaurant_table,
               pi.grand_total
        FROM `tabURY KOT` k
        JOIN `tabPOS Invoice` pi ON pi.name = k.invoice
        WHERE k.change_status = 'Awaiting Confirmation'
          AND k.docstatus != 2
          AND {clause}
        ORDER BY k.change_requested_at DESC
        LIMIT 50
        """,
        params,
        as_dict=True,
    )


# Function to mark it as verified by a user in cancel type KOT
@frappe.whitelist()
def confirm_cancel_kot(name, user):
    frappe.db.set_value("URY KOT", name, "verified", 1)
    frappe.db.set_value("URY KOT", name, "verified_by", user)


@frappe.whitelist(allow_guest=True)
def get_site_name():
    return {"site_name": frappe.local.site}

MENU_COURSE_TARGETS = {"Food", "Drinks", "Other", "All"}


@frappe.whitelist()
def kot_list(target=None):
    """Return the KOT list the Mosaic KDS should render.

    ``target`` is the URL path segment (``/Mosaic/<target>``). Its
    meaning depends on the POS Profile's ``custom_kds_routing_mode``:

      - **URY Production Unit** mode: ``target`` must be a real
        URY Production Unit name (or ``All``). The backend returns
        every branch KOT and the frontend filters client-side via
        ``v-if="kot.production === production"``.

      - **Menu Course** mode: ``target`` must be ``Food``, ``Drinks``,
        ``Other``, or ``All``. The backend filters each KOT's
        ``kot_items`` rows by their course's ``custom_department`` and
        only returns KOTs that still carry at least one matching item.

    If the target is not valid for the active mode, returns
    ``{"error": "...", "KOT": []}`` so the frontend can render a
    clear "not found" message instead of a blank board.
    """
    today = frappe.utils.now()
    branch = getBranch()
    pos_profile_name = frappe.db.get_value("POS Profile", {"branch": branch}, "name")
    kot_alert_time = frappe.db.get_value(
        "POS Profile", pos_profile_name, "custom_kot_warning_time"
    )
    service_policy_time = frappe.db.get_value(
        "POS Profile", pos_profile_name, "custom_service_policy_time"
    )
    daily_order_number = frappe.db.get_value(
        "POS Profile", pos_profile_name, "custom_reset_order_number_daily"
    )
    three_hours_ago = frappe.utils.add_to_date(today, hours=-3)
    audio_alert = frappe.db.get_value(
        "POS Profile", pos_profile_name, "custom_kot_alert"
    )

    kds_mode = (
        frappe.db.get_value(
            "POS Profile", {"branch": branch}, "custom_kds_routing_mode"
        )
        or "Menu Course"
    )

    # Validate target against the active mode. Empty target is allowed
    # (legacy /Mosaic/ root) — treated like "All".
    if target:
        if kds_mode == "Menu Course":
            if target not in MENU_COURSE_TARGETS:
                return {
                    "error": (
                        f"'{target}' is not a valid Menu Course screen. "
                        f"Use one of: {', '.join(sorted(MENU_COURSE_TARGETS))}. "
                        "(Or switch your POS Profile to 'ExPos Production Unit' "
                        "routing mode to route by Production Unit name.)"
                    ),
                    "KOT": [],
                    "Branch": branch,
                    "kds_routing_mode": kds_mode,
                }
        else:  # URY Production Unit mode
            if target != "All" and not frappe.db.exists(
                "URY Production Unit", target
            ):
                return {
                    "error": (
                        f"Production Unit '{target}' does not exist. "
                        "Create it under ExPos → ExPos Production Unit, or use "
                        "'All' to show every production unit on one screen."
                    ),
                    "KOT": [],
                    "Branch": branch,
                    "kds_routing_mode": kds_mode,
                }

    kotList = frappe.get_list(
        "URY KOT",
        fields=["name"],
        filters={
            "order_status": "Ready For Prepare",
            "branch": branch,
            "type": [
                "in",
                [
                    "New Order",
                    "Order Modified",
                    "Duplicate",
                    "Cancelled",
                    "Partially cancelled",
                ],
            ],
            "docstatus": 1,
            "verified": 0,
            "creation": (">=", three_hours_ago),
        },
        order_by="creation desc",
    )

    now_dt = frappe.utils.now_datetime()
    KOT = []
    for kot in kotList:
        kotdoc = frappe.get_doc("URY KOT", kot.name)
        kotjson = json.loads(frappe.as_json(kotdoc))
        # Server-computed elapsed seconds since the KOT was created. Both
        # sides of the subtraction are in the system timezone, so this is
        # correct regardless of the KDS browser's timezone — the client
        # just ticks forward from this base. Fixes the Mosaic timer that
        # stuck at 00:00 when the server tz was ahead of the browser
        # (creation parsed as browser-local went negative). See CLAUDE.md.
        kotjson["elapsed_seconds"] = max(
            0,
            int((now_dt - frappe.utils.get_datetime(kotdoc.creation)).total_seconds()),
        )

        if kds_mode == "Menu Course" and target and target != "All":
            # Per-department item filter. Walk the KOT's kot_items and
            # keep only the rows whose course classifies into this
            # target department. Using the same helper the print
            # resolver uses so the KDS and the printer agree on what
            # belongs where.
            from ury.ury.api.ury_print import (
                _classify_kot_item_department,
            )
            filtered_rows = [
                row
                for row in kotjson.get("kot_items", [])
                if _classify_kot_item_department(frappe._dict(row))
                == target
            ]
            if not filtered_rows:
                continue
            kotjson["kot_items"] = filtered_rows
            # Stamp the target so the Vue client's kot.production ===
            # production filter passes.
            kotjson["production"] = target
        elif kds_mode == "Menu Course" and target == "All":
            # No filter, but still stamp production so client filter
            # passes when the URL's target is "All".
            kotjson["production"] = "All"

        # Waiter badge on the KDS card (2026-07-16).
        kotjson["waiter_name"] = _kot_waiter_name(kotjson.get("invoice"))
        KOT.append(kotjson)

    return {
        "KOT": KOT,
        "Branch": branch,
        "kot_alert_time": kot_alert_time,
        "service_policy_time": service_policy_time,
        "audio_alert": audio_alert,
        "daily_order_number": daily_order_number,
        "kds_routing_mode": kds_mode,
    }


@frappe.whitelist()
def get_late_orders():
    """Return KOTs whose elapsed time exceeds the POS Profile's
    Average Service Policy Time and that are still pending.

    Shape mirrors ``get_kitchen_notifications`` so the React POS
    Notifications panel can render it with the same card layout.
    """
    branch = getBranch()
    policy_minutes = (
        frappe.db.get_value(
            "POS Profile", {"branch": branch}, "custom_service_policy_time"
        )
        or 0
    )
    if not policy_minutes:
        return {"policy_minutes": 0, "orders": []}

    cutoff = frappe.utils.add_to_date(
        frappe.utils.now_datetime(), minutes=-int(policy_minutes)
    )
    three_hours_ago = frappe.utils.add_to_date(
        frappe.utils.now_datetime(), hours=-3
    )

    rows = frappe.db.sql(
        """
        SELECT
            k.name                              AS kot_name,
            k.invoice                           AS invoice,
            k.restaurant_table                  AS restaurant_table,
            k.order_no                          AS order_no,
            k.production                        AS production,
            k.creation                          AS kot_creation,
            k.user                              AS waiter,
            k.type                              AS kot_type,
            pi.customer_name                    AS customer_name,
            pi.grand_total                      AS grand_total,
            pi.posting_date                     AS posting_date,
            pi.posting_time                     AS posting_time,
            pi.owner                            AS owner,
            GROUP_CONCAT(
                CONCAT(ki.item_name, ' x', CAST(ki.quantity AS CHAR))
                ORDER BY ki.idx SEPARATOR ', '
            )                                   AS items_list,
            COUNT(DISTINCT ki.name)             AS items_count
        FROM `tabURY KOT` k
        LEFT JOIN `tabPOS Invoice` pi ON pi.name = k.invoice
        LEFT JOIN `tabURY KOT Items` ki ON ki.parent = k.name
        WHERE k.branch = %(branch)s
          AND k.docstatus = 1
          AND k.order_status = 'Ready For Prepare'
          AND k.verified = 0
          AND k.type IN (
              'New Order', 'Order Modified',
              'Duplicate', 'Cancelled', 'Partially cancelled'
          )
          AND k.creation <= %(cutoff)s
          AND k.creation >= %(three_hours_ago)s
        GROUP BY k.name
        ORDER BY k.creation ASC
        LIMIT 100
        """,
        {
            "branch": branch,
            "cutoff": cutoff,
            "three_hours_ago": three_hours_ago,
        },
        as_dict=True,
    )

    now_ts = frappe.utils.now_datetime()
    for row in rows:
        creation = frappe.utils.get_datetime(row["kot_creation"])
        elapsed_min = (now_ts - creation).total_seconds() / 60.0
        row["elapsed_minutes"] = int(elapsed_min)
        row["over_by_minutes"] = max(0, int(elapsed_min - policy_minutes))

    return {
        "policy_minutes": int(policy_minutes),
        "orders": rows,
    }


@frappe.whitelist()
def served_kot_list(production=None):
    today = frappe.utils.now()
    branch = getBranch()
    kot_alert_time = frappe.db.get_value(
        "POS Profile", {"branch": branch}, "custom_kot_warning_time"
    )
    daily_order_number = frappe.db.get_value(
        "POS Profile", {"branch": branch}, "custom_reset_order_number_daily"
    )
    audio_alert = frappe.db.get_value(
        "POS Profile", {"branch": branch}, "custom_kot_alert"
    )

    # Reinstate config (2026-07-23): per URY Production Unit. When this KDS
    # screen maps to a real production unit, honour its `enable_reinstate`
    # + `reinstate_window_hours`. A department (Menu Course mode) / "All" /
    # a missing unit falls back to the default: enabled, 3-hour window. The
    # `reinstate_enabled` flag lets the KDS hide the Recently Served tab.
    reinstate_enabled = 1
    window_hours = 3
    if (
        production
        and production != "All"
        and frappe.db.exists("URY Production Unit", production)
    ):
        cfg = frappe.db.get_value(
            "URY Production Unit",
            production,
            ["enable_reinstate", "reinstate_window_hours"],
            as_dict=True,
        )
        if cfg:
            # Default the check to ON for pre-existing units (null field).
            reinstate_enabled = (
                1 if cfg.enable_reinstate is None else int(cfg.enable_reinstate)
            )
            # 0/blank falls back to the 3-hour default.
            window_hours = int(cfg.reinstate_window_hours or 0) or 3

    if not reinstate_enabled:
        return {
            "KOT": [],
            "Branch": branch,
            "kot_alert_time": kot_alert_time,
            "audio_alert": audio_alert,
            "daily_order_number": daily_order_number,
            "reinstate_enabled": 0,
            "reinstate_window_hours": window_hours,
        }

    window_ago = frappe.utils.add_to_date(today, hours=-window_hours)

    # Production/department scoping (2026-07-23): AIRTIGHT — a KOT served in
    # the kitchen must NOT show on the bar screen's reinstate list. Mirrors
    # get_served_summary. "All"/no production stays branch-wide.
    #   - URY Production Unit mode: each KOT carries `production`, filter on it.
    #   - Menu Course mode: `production` is NULL on the KOT and the screen is a
    #     department, so show a KOT only when it has an item in that department
    #     (course -> custom_department, default "Food").
    kds_mode = (
        frappe.db.get_value(
            "POS Profile", {"branch": branch}, "custom_kds_routing_mode"
        )
        or "Menu Course"
    )
    scope_sql = ""
    scope_params = {}
    if production and production != "All":
        if kds_mode == "URY Production Unit":
            scope_sql = " AND production = %(kds_production)s"
            scope_params["kds_production"] = production
        else:
            scope_sql = (
                " AND EXISTS (SELECT 1 FROM `tabURY KOT Items` ki "
                "LEFT JOIN `tabURY Menu Course` mc ON mc.name = ki.course "
                "WHERE ki.parent = `tabURY KOT`.name "
                "AND COALESCE(NULLIF(mc.custom_department, ''), 'Food') "
                "= %(kds_dept)s)"
            )
            scope_params["kds_dept"] = production

    # Window + ordering are both on WHEN IT WAS SERVED, not when the KOT was
    # created (2026-07-16). Rows served before `served_at` existed fall back
    # to creation. The window is the production unit's configured hours
    # (default 3, 2026-07-23). `scope_sql` + its values are parameterised.
    kotList = frappe.db.sql(
        f"""
        SELECT name
        FROM `tabURY KOT`
        WHERE order_status = 'Served'
          AND branch = %(branch)s
          AND docstatus = 1
          AND verified = 0
          AND type IN ('New Order', 'Order Modified', 'Duplicate',
                       'Cancelled', 'Partially cancelled')
          AND COALESCE(served_at, creation) >= %(since)s
          {scope_sql}
        ORDER BY COALESCE(served_at, creation) DESC
        LIMIT 100
        """,
        {"branch": branch, "since": window_ago, **scope_params},
        as_dict=True,
    )
    KOT = []
    for kot in kotList:
        kotdoc = frappe.get_doc("URY KOT", kot.name)
        kotjson = json.loads(frappe.as_json(kotdoc))
        kotjson["waiter_name"] = _kot_waiter_name(kotjson.get("invoice"))
        KOT.append(kotjson)
    return {
        "KOT": KOT,
        "Branch": branch,
        "kot_alert_time": kot_alert_time,
        "audio_alert": audio_alert,
        "daily_order_number": daily_order_number,
        "reinstate_enabled": 1,
        "reinstate_window_hours": window_hours,
    }


@frappe.whitelist()
def get_served_summary(production=None, date=None):
    """Aggregate items SERVED (sold) for a production/department on a day.

    Powers the KDS "Served" tab end-of-day summary: per-item quantities
    ("20 Coke", "10 Jollof Rice"), a per-waiter breakdown, and grand totals
    — printable for accounting (2026-07-23).

    Scope mirrors served_kot_list (branch + served state) but over the FULL
    day (`DATE(served_at) = date`), not the 3-hour board window. `production`
    is interpreted per the POS Profile's routing mode:
      - URY Production Unit mode: a real production unit (or "All"). Filter
        KOTs by `k.production`.
      - Menu Course mode: a department (Food/Drinks/Other/All). `k.production`
        is NULL there, so filter per-item by the item's course department
        (URY Menu Course.custom_department, defaulting to "Food" to match
        _classify_kot_item_department).

    Counts served KOTs of type New Order + Order Modified (the items that
    actually went out) — excludes Duplicate reprints and Cancelled tickets
    to avoid double/over-counting. `URY KOT Items.quantity` is a Data string,
    so it's CAST to a number.
    """
    branch = getBranch()
    if not date:
        date = frappe.utils.nowdate()

    kds_mode = (
        frappe.db.get_value(
            "POS Profile", {"branch": branch}, "custom_kds_routing_mode"
        )
        or "Menu Course"
    )

    conditions = [
        "k.order_status = 'Served'",
        "k.branch = %(branch)s",
        "k.docstatus = 1",
        "k.verified = 0",
        "k.type IN ('New Order', 'Order Modified')",
        "DATE(k.served_at) = %(date)s",
    ]
    params = {"branch": branch, "date": date}
    join_course = ""

    if production and production != "All":
        if kds_mode == "URY Production Unit":
            conditions.append("k.production = %(production)s")
            params["production"] = production
        else:
            join_course = (
                "LEFT JOIN `tabURY Menu Course` mc ON mc.name = ki.course"
            )
            conditions.append(
                "COALESCE(NULLIF(mc.custom_department, ''), 'Food') = %(dept)s"
            )
            params["dept"] = production

    # `where`/`join_course` are built only from the hardcoded clauses above;
    # every value (branch/date/production/dept) is parameterised → no injection.
    where = " AND ".join(conditions)

    item_rows = frappe.db.sql(
        f"""
        SELECT ki.item_name AS item_name,
               SUM(CAST(ki.quantity AS DECIMAL(18,2))) AS total_qty
        FROM `tabURY KOT` k
        JOIN `tabURY KOT Items` ki ON ki.parent = k.name
        {join_course}
        WHERE {where}
        GROUP BY ki.item_name
        ORDER BY total_qty DESC, ki.item_name ASC
        """,
        params,
        as_dict=True,
    )

    waiter_rows = frappe.db.sql(
        f"""
        SELECT COALESCE(w.full_name, 'Unassigned') AS waiter,
               ki.item_name AS item_name,
               SUM(CAST(ki.quantity AS DECIMAL(18,2))) AS total_qty
        FROM `tabURY KOT` k
        JOIN `tabURY KOT Items` ki ON ki.parent = k.name
        {join_course}
        LEFT JOIN `tabPOS Invoice` pi ON pi.name = k.invoice
        LEFT JOIN `tabURY Waiter` w ON w.name = pi.custom_waiter
        WHERE {where}
        GROUP BY waiter, ki.item_name
        ORDER BY waiter ASC, total_qty DESC, ki.item_name ASC
        """,
        params,
        as_dict=True,
    )

    ticket_row = frappe.db.sql(
        f"""
        SELECT COUNT(DISTINCT k.name) AS n
        FROM `tabURY KOT` k
        JOIN `tabURY KOT Items` ki ON ki.parent = k.name
        {join_course}
        WHERE {where}
        """,
        params,
        as_dict=True,
    )

    items = [
        {"item_name": r.item_name, "total_qty": float(r.total_qty or 0)}
        for r in item_rows
    ]
    total_qty = sum(i["total_qty"] for i in items)

    by_waiter = {}
    for r in waiter_rows:
        w = by_waiter.setdefault(
            r.waiter, {"waiter": r.waiter, "total_qty": 0.0, "items": []}
        )
        qty = float(r.total_qty or 0)
        w["items"].append({"item_name": r.item_name, "qty": qty})
        w["total_qty"] += qty
    by_waiter_list = sorted(by_waiter.values(), key=lambda x: -x["total_qty"])

    return {
        "date": str(date),
        "production": production or "All",
        "kds_mode": kds_mode,
        "branch": branch,
        "items": items,
        "by_waiter": by_waiter_list,
        "total_qty": total_qty,
        "distinct_items": len(items),
        "ticket_count": ticket_row[0].n if ticket_row else 0,
    }

