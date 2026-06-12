import json

import frappe
from ury.ury_pos.api import getBranch
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
    
    # Update linked POS Invoice status
    try:
        invoice = frappe.db.get_value("URY KOT", name, "invoice")
        
        if invoice and frappe.db.exists("POS Invoice", invoice):
            # Get invoice owner to send notification to specific user
            invoice_owner = frappe.db.get_value("POS Invoice", invoice, "owner")
            
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
                # Publish realtime notification to specific user
                frappe.publish_realtime(
                    event="order_served_notification",
                    message=notification_data[0],
                    user=invoice_owner
                )
            
            frappe.logger().info(f"Updated POS Invoice {invoice} to Served from KOT {name}")
        
        frappe.db.commit()
        
    except Exception as e:
        frappe.log_error(f"Error updating invoice status: {str(e)}", "Serve KOT Error")
        pass


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
def served_kot_list():
    today = frappe.utils.now()
    branch = getBranch()
    kot_alert_time = frappe.db.get_value(
        "POS Profile", {"branch": branch}, "custom_kot_warning_time"
    )
    daily_order_number = frappe.db.get_value(
        "POS Profile", {"branch": branch}, "custom_reset_order_number_daily"
    )
    three_hours_ago = frappe.utils.add_to_date(today, hours=-3)
    audio_alert = frappe.db.get_value(
        "POS Profile", {"branch": branch}, "custom_kot_alert"
    )
    kotList = frappe.get_list(
        "URY KOT",
        fields=["name"],
        filters={
            "order_status": "Served",
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
    print(kotList,"kotList..................")
    KOT = []
    for kot in kotList:
        kotdoc = frappe.get_doc("URY KOT", kot.name)
        print(kot.name,".................kotdoc")
        invoice=frappe.db.get_value("URY KOT",kot.name,"invoice")
        print(invoice,".....................invoice")
        kotjson = json.loads(frappe.as_json(kotdoc))
        KOT.append(kotjson)
    return {
        "KOT": KOT,
        "Branch": branch,
        "kot_alert_time": kot_alert_time,
        "audio_alert": audio_alert,
        "daily_order_number":daily_order_number
    }

