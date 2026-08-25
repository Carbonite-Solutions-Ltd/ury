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
                        -- `URY KOT Items` has NO `qty` column: the field is
                        -- `quantity`, and it is a Data field, not a number.
                        -- This threw (1054) on EVERY serve, and the bare
                        -- except below swallowed it -- so the invoice was
                        -- marked Served but the waiter's "food ready" alert
                        -- was never published. 333 times on live before it
                        -- was spotted. Same trap as the KOT print format,
                        -- 2026-06-12.
                        CONCAT(ki.item_name, ' x', ki.quantity)
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

    # Tell the POS too (2026-08-24). Clearing `custom_order_status` above
    # is only half the job: `serve_kot` PUSHES `order_served_notification`
    # to the invoice owner and the waiter's user, but the un-serve pushed
    # nothing to them — it only pinged the kitchen board. So the waiter's
    # Orders list kept its "Served" badge until she happened to refetch,
    # which is exactly what was reported. Mirror serve_kot's recipients.
    if invoice:
        for recipient in _kot_notify_users(invoice):
            frappe.publish_realtime(
                event="order_unserved_notification",
                message={"invoice": invoice, "kot": name},
                user=recipient,
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
            k.cancel_status                     AS cancel_status,
            k.cancel_scope                      AS cancel_scope,
            k.cancel_reason                     AS cancel_reason,
            k.cancel_items                      AS cancel_items,
            k.cancel_requested_by               AS cancel_requested_by,
            k.cancel_requested_at               AS cancel_requested_at,
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



# ══════════════════════════════════════════════════════════════════════
#  Cancellation grace window + POS → kitchen cancellation handshake
#  (2026-07-31)
# ══════════════════════════════════════════════════════════════════════
#
# THE PROBLEM THIS SOLVES. Cancelling an order used to leave the kitchen
# guessing. `cancel_order` raised a "CNCL-" chit and cancelled the
# originals, but (a) the whole call sat inside `try/except: pass`, so any
# failure in that chain was silent and the card simply stayed on the
# board, (b) the chit itself is `type = "Cancelled"`, which the board
# query explicitly INCLUDES, so a new card appeared and lingered for the
# full 3-hour window with nobody required to acknowledge it, and (c) the
# reason lived on the invoice's `cancel_reason` and never reached the
# cook at all.
#
# THE MODEL. Time decides who is in charge:
#
#   within the grace window   the food has not started. Cancelling
#                             DELETES the ticket outright - the card
#                             vanishes, no chit, nobody is interrupted.
#
#   after the grace window    the food may already be on the pass. A
#                             captain can only REQUEST cancellation, with
#                             a reason, and the kitchen must Accept before
#                             anything is removed. The order is LOCKED
#                             meanwhile so the POS and the kitchen cannot
#                             disagree about what was actually served.
#
# The window is read from the URY Production Unit first and the POS
# Profile second. The profile fallback is load-bearing rather than
# decorative: in Menu Course KDS mode a KOT has NO production unit at
# all, so a unit-only setting could never fire and the feature would
# silently do nothing on those sites.
#
# This is deliberately a SEPARATE field set from `change_status` and
# friends. That is the opposite direction (kitchen asks the waiter) and
# the two can legitimately be in flight on the same KOT at once.

DEFAULT_CANCEL_GRACE_MINUTES = 2

# order_status the KDS board filters on. A cancelled ticket is parked on
# a value that matches neither the active board ("Ready For Prepare") nor
# the served list ("Served"), so it simply drops out. order_status is a
# free-text Data field, so this needs no schema change - the same trick
# `kitchen_ack_change` already uses for "Cancelled by Waiter".
CANCELLED_BY_CAPTAIN = "Cancelled by Captain"


def _profile_grace_minutes(pos_profile):
    """POS Profile fallback window, or None.

    Guarded with has_column because a site that has pulled the code but
    not yet run `bench migrate` would otherwise throw on every cancel.
    """
    if not pos_profile:
        return None
    if not frappe.db.has_column("POS Profile", "custom_cancel_grace_minutes"):
        return None
    value = frappe.db.get_value(
        "POS Profile", pos_profile, "custom_cancel_grace_minutes"
    )
    return int(value) if value else None


def _unit_grace_minutes(production):
    """URY Production Unit window, or None. Wins over the profile."""
    if not production:
        return None
    if not frappe.db.has_column("URY Production Unit", "cancel_grace_minutes"):
        return None
    value = frappe.db.get_value(
        "URY Production Unit", production, "cancel_grace_minutes"
    )
    return int(value) if value else None


def _pick_grace_minutes(unit_minutes, profile_minutes):
    """Unit setting wins, profile is the fallback, 2 if neither.

    0/blank at either level means "not set", NOT "no grace". A zero
    window would send every single cancellation through a kitchen
    round-trip, which is not a thing anyone configures on purpose -
    whereas leaving a field at its 0 default is something everyone does.

    Pure so the precedence can be tested without a database.
    """
    return unit_minutes or profile_minutes or DEFAULT_CANCEL_GRACE_MINUTES


def _grace_expired(created, now, grace_minutes):
    """Has the window closed? Pure, so the boundary is testable.

    Strictly greater-than: a ticket exactly ON the boundary is still
    inside its window. The difference only matters for one instant, but
    the rule should be stated rather than fallen into.
    """
    return (now - created).total_seconds() / 60.0 > grace_minutes


def _cancel_grace_minutes(kot):
    """Minutes this ticket may be deleted outright before the kitchen
    has to be asked."""
    return _pick_grace_minutes(
        _unit_grace_minutes(kot.get("production")),
        _profile_grace_minutes(kot.get("pos_profile")),
    )


def _kot_needs_kitchen_ack(kot, now=None):
    """True when this ticket is past its grace window, so cancelling it
    has to go through the kitchen instead of just deleting it."""
    # A served ticket is out of the kitchen's hands whatever the clock
    # says - the food reached the customer, so the kitchen is told
    # regardless. (It is also the only way a sub-grace ticket can be
    # served, but the rule stands on its own merit.)
    if (kot.get("order_status") or "") == "Served":
        return True

    now = now or frappe.utils.now_datetime()
    return _grace_expired(
        get_datetime(kot.get("creation")), now, _cancel_grace_minutes(kot)
    )


def _live_kots_for_invoice(invoice):
    """Submitted, not-yet-cancelled tickets for this invoice.

    Excludes Duplicate (a reprint - cancelling it means nothing) and
    Cancelled / Partially cancelled (already chits about a cancellation).
    """
    return frappe.get_all(
        "URY KOT",
        filters={
            "invoice": invoice,
            "docstatus": 1,
            "type": ("in", ("New Order", "Order Modified")),
            "order_status": ("not in", (CANCELLED_BY_CAPTAIN, "Cancelled by Waiter")),
        },
        fields=[
            "name",
            "creation",
            "production",
            "pos_profile",
            "order_status",
            "cancel_status",
            "branch",
        ],
    )


def _publish_cancel_to_kds(kot_row, event):
    """Ping the KDS screens this ticket appears on so the cancellation
    panel shows without waiting for the 30s poll.

    Targeted per screen via the same helper the change-request loop uses:
    an untargeted publish gets scoped by Frappe to the CALLING user's own
    room, which is the captain's browser - precisely not the kitchen.
    """
    try:
        branch = kot_row.get("branch") or frappe.db.get_value(
            "URY KOT", kot_row["name"], "branch"
        )
        if not branch:
            return
        for target in _kot_kds_targets(kot_row["name"], kot_row.get("production")):
            frappe.publish_realtime(
                f"{event}_{branch}_{target}", {"kot": kot_row["name"]}
            )
    except Exception:
        # Never let a realtime hiccup roll back the cancellation itself.
        # Worst case the board picks it up on the next poll.
        frappe.log_error(
            frappe.get_traceback(), "URY: KDS cancel publish failed"
        )


def _require_captain():
    """Cancelling after the grace window is a captain/manager call.

    Mirrors the gate in `cancel_order` - the POS hides the control for a
    cashier, and this is the half that actually enforces it.
    """
    if frappe.session.user == "Administrator":
        return
    roles = set(frappe.get_roles(frappe.session.user))
    if not (roles & {"System Manager", "URY Manager", "URY Captain"}):
        frappe.throw(
            _("Only a captain or manager can cancel an order."),
            title=_("Not Permitted"),
        )


@frappe.whitelist()
def get_order_cancel_state(invoice):
    """What the POS needs to know before offering a cancel control.

    Returns `mode`:
      "delete"   every live ticket is still inside its grace window, so
                 cancelling removes it outright.
      "request"  at least one ticket is past it - cancelling needs a
                 reason and the kitchen's acceptance.
      "pending"  a request is already in flight; the order is locked.
      "none"     nothing is on the kitchen at all (no KOTs), so this is
                 a plain invoice cancellation.

    `grace_expires_in` is the seconds left on the SHORTEST remaining
    window, so the POS can show a live countdown and flip the button
    from Delete to Request without the cashier having to reload.
    """
    kots = _live_kots_for_invoice(invoice)
    if not kots:
        return {"invoice": invoice, "mode": "none", "kots": []}

    if any((k.get("cancel_status") or "") == "Awaiting Kitchen" for k in kots):
        pending = [k for k in kots if (k.get("cancel_status") or "") == "Awaiting Kitchen"]
        first = frappe.db.get_value(
            "URY KOT",
            pending[0]["name"],
            ["cancel_reason", "cancel_scope", "cancel_requested_by", "cancel_requested_at"],
            as_dict=True,
        )
        return {
            "invoice": invoice,
            "mode": "pending",
            "pending_count": len(pending),
            "reason": (first or {}).get("cancel_reason"),
            "scope": (first or {}).get("cancel_scope"),
            "requested_by": (first or {}).get("cancel_requested_by"),
            "requested_at": (first or {}).get("cancel_requested_at"),
        }

    now = frappe.utils.now_datetime()
    remaining = []
    needs_ack = False
    for kot in kots:
        if _kot_needs_kitchen_ack(kot, now=now):
            needs_ack = True
        else:
            grace = _cancel_grace_minutes(kot)
            elapsed = (now - get_datetime(kot["creation"])).total_seconds()
            remaining.append(max(0, int(grace * 60 - elapsed)))

    return {
        "invoice": invoice,
        "mode": "request" if needs_ack else "delete",
        "kot_count": len(kots),
        # None once anything has expired - there is no countdown left to
        # show, the decision is already made.
        "grace_expires_in": min(remaining) if remaining and not needs_ack else None,
    }


def request_order_cancellation(invoice, reason, kots=None):
    """Park a whole-order cancellation on every live ticket and lock the
    order. Called by `cancel_order` once it finds the grace window shut.
    """
    if not (reason or "").strip():
        frappe.throw(
            _("Give a reason - the kitchen is being asked to bin food that may already be cooking."),
            title=_("Reason Required"),
        )

    kots = kots if kots is not None else _live_kots_for_invoice(invoice)
    if not kots:
        return {"invoice": invoice, "requested": 0}

    stamp = {
        "cancel_status": "Awaiting Kitchen",
        "cancel_scope": "Order",
        "cancel_reason": reason.strip(),
        "cancel_items": None,
        "cancel_requested_by": frappe.session.user,
        "cancel_requested_at": frappe.utils.now(),
        "cancel_accepted_by": None,
        "cancel_accepted_at": None,
    }
    for kot in kots:
        frappe.db.set_value("URY KOT", kot["name"], stamp, update_modified=False)
        _publish_cancel_to_kds(kot, "kot_cancel_requested")

    frappe.db.set_value(
        "POS Invoice", invoice, "custom_cancel_pending", 1, update_modified=False
    )
    frappe.db.commit()
    return {"invoice": invoice, "requested": len(kots), "mode": "request"}


def _kots_carrying_items(invoice, item_codes):
    """Map item_code → the live KOT names that actually contain it.

    An order's items are split across tickets (per production unit, or
    per course department), so "cancel 2x Fanta" has to find the BAR's
    ticket and leave the kitchen's alone.
    """
    if not item_codes:
        return {}
    live = {k["name"]: k for k in _live_kots_for_invoice(invoice)}
    if not live:
        return {}
    rows = frappe.get_all(
        "URY KOT Items",
        filters={"parent": ("in", list(live)), "item": ("in", list(item_codes))},
        fields=["parent", "item"],
    )
    carried = {}
    for row in rows:
        carried.setdefault(row["item"], set()).add(row["parent"])
    return carried


def _finalize_invoice_cancellation(invoice, reason):
    """Actually cancel the invoice once the kitchen has signed off.

    Implemented with direct db writes rather than importing
    `ury_order.cancel_order`: that module imports this one's siblings and
    a back-import would be circular. These are the same six writes it
    performs, minus the KOT handling, which the caller has already done.
    """
    table = frappe.db.get_value("POS Invoice", invoice, "restaurant_table")
    if table:
        frappe.db.set_value(
            "URY Table", table, {"occupied": 0, "latest_invoice_time": None}
        )

    frappe.db.sql(
        "UPDATE `tabPOS Invoice Item` SET docstatus = 2 WHERE parent = %s", (invoice,)
    )
    frappe.db.set_value(
        "POS Invoice",
        invoice,
        {
            "docstatus": 2,
            "status": "Cancelled",
            "cancel_reason": reason,
            "custom_cancel_pending": 0,
        },
        update_modified=False,
    )


@frappe.whitelist()
def kitchen_accept_cancellation(kot):
    """The kitchen signs off on a cancellation it was asked to make.

    Whole-order scope: this ticket leaves the board, and once EVERY
    ticket on the invoice has been accepted the order itself is
    cancelled. The last screen to accept is what releases it - a two-unit
    order cancelled while the bar has acknowledged but the kitchen has
    not is still, correctly, a live order.

    Item scope: the listed lines come off this ticket and off the
    invoice; the card stays with what is left, unless nothing is.
    """
    row = frappe.db.get_value(
        "URY KOT",
        kot,
        ["name", "invoice", "cancel_status", "cancel_scope", "cancel_reason", "cancel_items", "production", "branch"],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("That ticket no longer exists."), title=_("Not Found"))
    if (row.cancel_status or "") != "Awaiting Kitchen":
        frappe.throw(
            _("There's no cancellation waiting on this ticket."),
            title=_("Nothing to Accept"),
        )

    invoice = row.invoice
    reason = row.cancel_reason or ""

    accepted = {
        "cancel_status": "Accepted",
        "cancel_accepted_by": frappe.session.user,
        "cancel_accepted_at": frappe.utils.now(),
    }

    if (row.cancel_scope or "Order") == "Items":
        removals = json.loads(row.cancel_items or "[]")
        _apply_item_removal(invoice, removals, kot_name=kot)
        # The request is spent - clear it so the card reads normally
        # again. The ticket itself carries on being cooked.
        frappe.db.set_value(
            "URY KOT",
            kot,
            dict(accepted, cancel_status="", cancel_scope=None, cancel_reason=None, cancel_items=None),
            update_modified=False,
        )
        remaining = frappe.db.count("URY KOT Items", {"parent": kot})
        if not remaining:
            frappe.db.set_value(
                "URY KOT", kot, "order_status", CANCELLED_BY_CAPTAIN, update_modified=False
            )
    else:
        frappe.db.set_value(
            "URY KOT",
            kot,
            dict(accepted, order_status=CANCELLED_BY_CAPTAIN),
            update_modified=False,
        )

    # Release the invoice only when nothing is still waiting on a screen.
    still_waiting = frappe.db.count(
        "URY KOT",
        {
            "invoice": invoice,
            "docstatus": 1,
            "cancel_status": "Awaiting Kitchen",
        },
    )
    finalized = 0
    if not still_waiting:
        if (row.cancel_scope or "Order") == "Items":
            frappe.db.set_value(
                "POS Invoice", invoice, "custom_cancel_pending", 0, update_modified=False
            )
        else:
            _finalize_invoice_cancellation(invoice, reason)
            finalized = 1

    frappe.db.commit()
    return {
        "kot": kot,
        "invoice": invoice,
        "scope": row.cancel_scope or "Order",
        "still_waiting": still_waiting,
        "order_cancelled": finalized,
    }


def _apply_item_removal(invoice, removals, kot_name=None):
    """Pull the requested quantities off the ticket AND the invoice.

    Both sides move together on purpose. Taking the line off the KOT
    alone would leave the customer billed for food nobody is cooking;
    taking it off the invoice alone would leave the cook making
    something nobody is paying for.
    """
    from frappe.utils import flt

    wanted = {}
    for entry in removals or []:
        code = entry.get("item_code") or entry.get("item")
        if not code:
            continue
        wanted[code] = wanted.get(code, 0) + flt(entry.get("quantity") or entry.get("qty") or 0)
    if not wanted:
        return

    # ── invoice side FIRST ──
    # Order matters. If the invoice save fails (a stale POS Opening
    # Entry is the usual culprit, and it throws on ANY POS Invoice save)
    # we must not already have stripped the lines off the ticket: the
    # kitchen would stop cooking food the customer is still being billed
    # for. Doing the throwing half first means a failure leaves both
    # sides untouched and the whole acceptance aborts cleanly.
    doc = frappe.get_doc("POS Invoice", invoice)
    invoice_open = doc.docstatus == 0

    if invoice_open:
        keep, leftover = _plan_item_removal(doc.items, wanted)

        if leftover and any(v > 0 for v in leftover.values()):
            # Asked to pull more than the bill actually carries. Not
            # fatal -- the intent is unambiguous -- but log it, because
            # it means the POS and the invoice had drifted.
            frappe.log_error(
                f"Invoice {invoice}: asked to cancel more than was billed: {leftover}",
                "URY: item cancellation over-asked",
            )

        if not keep:
            # Every line pulled is a cancelled order, not a zero-value
            # invoice -- ERPNext will not save one without items anyway.
            _finalize_invoice_cancellation(invoice, _("All items cancelled"))
        else:
            # Always save: _plan_item_removal mutates qty in place on a
            # partially-pulled row, so an unchanged row COUNT does not
            # mean an unchanged invoice.
            doc.items = keep
            for idx, item in enumerate(doc.items, start=1):
                item.idx = idx
            doc.flags.ury_kitchen_accepted_removal = True
            try:
                doc.save(ignore_permissions=True)
            except Exception:
                frappe.throw(
                    _(
                        "Couldn't take those items off the bill, so the "
                        "cancellation was not applied and nothing has "
                        "changed. The underlying error was: {0}"
                    ).format(str(frappe.get_traceback(with_context=False))[-300:]),
                    title=_("Cancellation Not Applied"),
                )
    # A submitted invoice is settled -- there is nothing to pull off the
    # bill, but the kitchen should still stop cooking, so fall through.

    # ── ticket side ──
    if kot_name:
        for row in frappe.get_all(
            "URY KOT Items",
            filters={"parent": kot_name},
            fields=["name", "item", "quantity"],
        ):
            if row["item"] not in wanted:
                continue
            # URY KOT Items.quantity is a Data field holding a string,
            # not a Float - hence flt() rather than arithmetic on it.
            left = flt(row["quantity"]) - wanted[row["item"]]
            if left > 0:
                frappe.db.set_value(
                    "URY KOT Items", row["name"], "quantity", str(left), update_modified=False
                )
            else:
                frappe.delete_doc(
                    "URY KOT Items", row["name"], force=1, ignore_permissions=True
                )


def _plan_item_removal(items, wanted):
    """Work out which invoice lines survive, and by how much.

    Pure: takes the current rows and a {item_code: qty_to_pull} map,
    returns (rows_to_keep, unfulfilled_budget). Splitting this out keeps
    the arithmetic -- partial pulls, quantities spread across duplicate
    rows, over-asking -- testable without standing up an invoice.

    Mutates the qty on a partially-pulled row, which is what the caller
    wants, but decides nothing about saving.
    """
    from frappe.utils import flt

    keep, budget = [], dict(wanted)
    for item in items:
        take = budget.get(item.item_code, 0)
        if take <= 0:
            keep.append(item)
            continue
        if take >= flt(item.qty):
            # Whole line goes; carry any excess to the next row with the
            # same item code (an order can list the same item twice).
            budget[item.item_code] = take - flt(item.qty)
            continue
        item.qty = flt(item.qty) - take
        budget[item.item_code] = 0
        keep.append(item)
    return keep, budget


@frappe.whitelist()
def request_item_cancellation(invoice, items, reason=None):
    """Captain pulls specific lines off a live order.

    Inside the grace window the lines simply go. Past it the affected
    tickets are parked as "Awaiting Kitchen" with the reason, and the
    lines only come off once the kitchen accepts.
    """
    _require_captain()

    removals = json.loads(items) if isinstance(items, str) else (items or [])
    if not removals:
        frappe.throw(_("Pick at least one item to cancel."), title=_("Nothing Selected"))

    codes = {e.get("item_code") or e.get("item") for e in removals}
    codes.discard(None)
    carried = _kots_carrying_items(invoice, codes)
    affected = sorted({name for names in carried.values() for name in names})

    if not affected:
        # Never reached a kitchen (no KOT carries it), so there is
        # nothing to ask and nobody to tell.
        _apply_item_removal(invoice, removals)
        frappe.db.commit()
        return {"invoice": invoice, "mode": "delete", "kots": []}

    live = {k["name"]: k for k in _live_kots_for_invoice(invoice)}
    now = frappe.utils.now_datetime()
    past_grace = [n for n in affected if _kot_needs_kitchen_ack(live[n], now=now)]

    if not past_grace:
        for name in affected:
            _apply_item_removal(invoice, removals, kot_name=name)
            _publish_cancel_to_kds(live[name], "kot_cancel_requested")
        frappe.db.commit()
        return {"invoice": invoice, "mode": "delete", "kots": affected}

    if not (reason or "").strip():
        frappe.throw(
            _("Give a reason - the kitchen is being asked to bin food that may already be cooking."),
            title=_("Reason Required"),
        )

    payload = json.dumps(
        [
            {
                "item_code": e.get("item_code") or e.get("item"),
                "item_name": e.get("item_name"),
                "quantity": e.get("quantity") or e.get("qty"),
            }
            for e in removals
        ]
    )
    for name in past_grace:
        frappe.db.set_value(
            "URY KOT",
            name,
            {
                "cancel_status": "Awaiting Kitchen",
                "cancel_scope": "Items",
                "cancel_reason": reason.strip(),
                "cancel_items": payload,
                "cancel_requested_by": frappe.session.user,
                "cancel_requested_at": frappe.utils.now(),
                "cancel_accepted_by": None,
                "cancel_accepted_at": None,
            },
            update_modified=False,
        )
        _publish_cancel_to_kds(live[name], "kot_cancel_requested")

    frappe.db.set_value(
        "POS Invoice", invoice, "custom_cancel_pending", 1, update_modified=False
    )
    frappe.db.commit()
    return {"invoice": invoice, "mode": "request", "kots": past_grace}
