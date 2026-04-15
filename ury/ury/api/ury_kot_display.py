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

@frappe.whitelist()
def kot_list(target=None):
    """Return the KOT list the URYMosaic KDS should render.

    ``target`` is the URL path segment (``/URYMosaic/<target>``). Its
    meaning depends on the POS Profile's ``custom_kds_routing_mode``:

      - **URY Production Unit** mode (legacy): ``target`` is a
        Production Unit name. The backend returns EVERY branch KOT
        and the frontend filters client-side via
        ``v-if="kot.production === production"``. Behavior unchanged
        from before the 2026-04-16 revamp.

      - **Menu Course** mode (default after the revamp): ``target``
        is a department — ``Food``, ``Drinks``, ``Other``, or ``All``.
        In this mode orders produce a SINGLE KOT per order (see
        ``process_items_for_kot``), so we filter the KOT's
        ``kot_items`` child rows by their course's
        ``custom_department`` and only return KOTs that still carry
        at least one matching item after filtering. ``All`` means no
        filter — useful for single-screen setups. We also stamp
        ``kot.production = target`` on each returned KOT so the Vue
        client's existing ``production`` filter still works unmodified.

    See CLAUDE.md "Fixes log" 2026-04-16 (print revamp Round 1 /
    Phase C KDS routing mode).
    """
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

    kds_mode = (
        frappe.db.get_value(
            "POS Profile", {"branch": branch}, "custom_kds_routing_mode"
        )
        or "Menu Course"
    )

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

    KOT = []
    for kot in kotList:
        kotdoc = frappe.get_doc("URY KOT", kot.name)
        kotjson = json.loads(frappe.as_json(kotdoc))

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
        "audio_alert": audio_alert,
        "daily_order_number": daily_order_number,
        "kds_routing_mode": kds_mode,
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

