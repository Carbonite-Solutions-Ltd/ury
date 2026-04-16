import frappe
from frappe import _
import os
import tempfile
import traceback

# Safe import for cups
try:
    import cups
except ImportError:
    cups = None

from frappe.www.printview import validate_print_permission

logger = frappe.logger("pos_printing")

def _get_qz_status(pos_profile):
    """
    Helper to check if QZ Print is enabled for the given POS Profile.
    Returns True if QZ is enabled, False otherwise.
    """
    if not pos_profile:
        return False
    
    return frappe.db.get_value("POS Profile", pos_profile, "qz_print") == 1

def _print_as_text(conn, printer_name, doc_obj, doctype, name):
    """Print document as plain text template (CUPS Only)"""
    try:
        text_content = ""
        
        # ========== KOT-SPECIFIC TEMPLATE ==========
        if doctype == "URY KOT":
            text_content = f"""
{'=' * 50}
{'KITCHEN ORDER TICKET'.center(50)}
{'=' * 50}
KOT #: {doc_obj.name}
Time: {doc_obj.creation}
Table: {doc_obj.get('restaurant_table', 'N/A')}
Order Type: {doc_obj.get('order_type', 'Dine In')}
Customer: {doc_obj.get('customer_name', 'N/A')}
{'-' * 50}
{'ITEMS'.center(50)}
{'-' * 50}
"""
            # KOT items
            if hasattr(doc_obj, 'items'):
                for item in doc_obj.items:
                    if isinstance(item, dict):
                        item_name = item.get('item_name', '')
                        qty = item.get('qty', 0)
                        notes = item.get('notes')
                        item_variant = item.get('item_variant')
                    else:
                        item_name = getattr(item, 'item_name', '')
                        qty = getattr(item, 'qty', 0)
                        notes = getattr(item, 'notes', None)
                        item_variant = getattr(item, 'item_variant', None)
                    
                    display_name = (item_name[:27] + '...') if len(item_name) > 30 else item_name
                    text_content += f"\n{qty:<5.1f} x {display_name:<30}\n"
                    
                    if notes:
                        text_content += f"  NOTE: {notes[:40]}\n"
                    if item_variant:
                        text_content += f"  Variant: {item_variant}\n"
            
            text_content += f"""
{'-' * 50}
Special Instructions: {doc_obj.get('special_instructions', 'None')}
{'-' * 50}
Urgent: {'YES' if doc_obj.get('is_urgent') else 'NO'}
Course: {doc_obj.get('course', 'Main')}
{'-' * 50}
"""

        # ========== INVOICE TEMPLATE ==========
        else:
            text_content = f"""
{'=' * 50}
{'INVOICE'.center(50)}
{'=' * 50}
Invoice: {doc_obj.name}
Date: {doc_obj.posting_date} {doc_obj.posting_time}
Customer: {doc_obj.customer_name if hasattr(doc_obj, 'customer_name') else doc_obj.customer}
Table: {doc_obj.get('restaurant_table', 'Take Away') or 'Take Away'}
Order Type: {doc_obj.get('order_type', 'N/A')}
Waiter: {doc_obj.get('waiter', 'N/A')}
{'-' * 50}
{'ITEMS'.center(50)}
{'-' * 50}
"""
            if hasattr(doc_obj, 'items'):
                text_content += f"{'Qty':<5} {'Item':<30} {'Rate':>10} {'Amount':>12}\n"
                text_content += f"{'-' * 57}\n"
                
                for item in doc_obj.items:
                    if isinstance(item, dict):
                        item_name = item.get('item_name', '')
                        qty = item.get('qty', 0)
                        rate = item.get('rate', 0)
                        amount = item.get('amount', 0)
                    else:
                        item_name = getattr(item, 'item_name', '')
                        qty = getattr(item, 'qty', 0)
                        rate = getattr(item, 'rate', 0)
                        amount = getattr(item, 'amount', 0)
                    
                    display_name = (item_name[:27] + '...') if len(item_name) > 30 else item_name
                    text_content += f"{qty:<5.1f} {display_name:<30} {float(rate):>10.2f} {float(amount):>12.2f}\n"
            
            text_content += f"""
{'-' * 50}
{'TOTALS'.center(50)}
{'-' * 50}
"""
            if hasattr(doc_obj, 'net_total'):
                val = doc_obj.net_total
                net_total = float(val) if val else 0.0
                text_content += f"Net Total: {net_total:>40.2f}\n"
            
            if hasattr(doc_obj, 'total_taxes_and_charges'):
                val = doc_obj.total_taxes_and_charges
                tax = float(val) if val else 0.0
                text_content += f"Tax: {tax:>44.2f}\n"
            
            if hasattr(doc_obj, 'grand_total'):
                val = doc_obj.grand_total
                grand_total = float(val) if val else 0.0
                text_content += f"{'=' * 50}\n"
                text_content += f"GRAND TOTAL: {grand_total:>37.2f}\n"
                text_content += f"{'=' * 50}\n"
            
            text_content += "\nThank you for your business!\n"
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write(text_content)
            file_path = f.name
        
        try:
            conn.printFile(printer_name, file_path, name, {})
            return {"status": "success", "message": "Printed text successfully"}
        finally:
            if os.path.exists(file_path):
                os.unlink(file_path)
        
    except Exception as e:
        logger.error(f"Text Print Error: {traceback.format_exc()}")
        return {"status": "error", "message": f"Failed to print text: {str(e)}"}


def _update_kot_status(kot_name):
    """Update KOT printed status safely"""
    try:
        if not frappe.db.exists("URY KOT", kot_name):
            return

        meta = frappe.get_meta("URY KOT")
        if meta.has_field("kot_printed"):
            frappe.db.set_value("URY KOT", kot_name, "kot_printed", 1, update_modified=False)
        elif meta.has_field("printed"):
            frappe.db.set_value("URY KOT", kot_name, "printed", 1, update_modified=False)
    except Exception:
        logger.error(f"Failed to update KOT status for {kot_name}")


@frappe.whitelist()
def network_printing(doctype, name, printer_setting, print_format=None, doc=None, no_letterhead=0, file_path=None, is_kot=False):
    """
    Standard Server-Side CUPS Printing.
    NOTE: This does NOT handle QZ Tray logic. That is handled in the wrappers.
    """
    try:
        if not cups:
            return {"status": "error", "message": "CUPS module not installed on server"}

        if not frappe.db.exists("Network Printer Settings", printer_setting):
            return {"status": "error", "message": f"Printer setting '{printer_setting}' not found"}

        print_settings = frappe.get_doc("Network Printer Settings", printer_setting)

        try:
            cups.setServer(print_settings.server_ip)
            cups.setPort(print_settings.port)
            conn = cups.Connection()
        except Exception as e:
            return {"status": "error", "message": f"Connection to printer failed: {str(e)}"}

        doc_obj = frappe.get_doc(doctype, name) if not doc else doc
        
        # 1. HTML/PDF Printing
        if print_format:
            try:
                html = frappe.get_print(
                    doctype=doctype,
                    name=name,
                    print_format=print_format,
                    doc=doc_obj,
                    no_letterhead=no_letterhead
                )
                from frappe.utils.pdf import get_pdf
                pdf_content = get_pdf(html)
                
                with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.pdf') as f:
                    f.write(pdf_content)
                    pdf_file_path = f.name
                
                try:
                    conn.printFile(print_settings.printer_name, pdf_file_path, f"{name} - {print_format}", {})
                    if os.path.exists(pdf_file_path):
                        os.unlink(pdf_file_path)
                    
                    if doctype == "URY KOT":
                        _update_kot_status(name)
                        
                    return {"status": "success", "message": "Printed PDF successfully"}
                except Exception as e:
                    if os.path.exists(pdf_file_path):
                        os.unlink(pdf_file_path)
                    raise e 
            except Exception as e:
                logger.error(f"PDF Print failed for {print_format}, falling back to text. Error: {e}")
        
        # 2. Fallback Text Printing
        return _print_as_text(conn, print_settings.printer_name, doc_obj, doctype, name)
            
    except Exception as e:
        logger.error(f"Network Printing Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def select_network_printer(pos_profile, invoice_id):
    """
    Called by JS to decide how to print an invoice.
    """
    # 1. CHECK QZ STATUS FIRST
    if _get_qz_status(pos_profile):
        # If QZ is enabled, we DO NOT print here. 
        # We return a specific status so the JS knows to run the QZ logic.
        return {"status": "qz_enabled", "message": "Client will handle printing"}

    # 2. Proceed with CUPS Logic
    table = frappe.db.get_value("POS Invoice", invoice_id, "restaurant_table")
    print_format = frappe.db.get_value("POS Profile", pos_profile, "print_format")
    
    printer_setting_name = None

    if table:
        room = frappe.db.get_value("URY Table", table, "restaurant_room")
        printer_setting_name = frappe.db.get_value(
            "URY Printer Settings", 
            {"parent": room, "bill": 1}, 
            "printer"
        )

    if not printer_setting_name:
        printer_setting_name = frappe.db.get_value(
            "URY Printer Settings", 
            {"parent": pos_profile, "bill": 1}, 
            "printer"
        )

    if printer_setting_name:
        return network_printing(
            "POS Invoice", invoice_id, printer_setting_name, print_format
        )
    
    return {"status": "error", "message": "No suitable printer found configuration"}


@frappe.whitelist()
def qz_print_update(invoice):
    """
    Called by JS AFTER QZ Tray successfully prints, or to update status.
    """
    try:
        table = frappe.db.get_value("POS Invoice", invoice, "restaurant_table")
        
        frappe.db.set_value("POS Invoice", invoice, "invoice_printed", 1, update_modified=False)
        
        if frappe.db.get_value("POS Invoice", invoice, "invoice_printed") != 1:
             return {"status": "Failure"}

        if table:
             frappe.db.set_value(
                "URY Table",
                table,
                {"occupied": 0, "latest_invoice_time": None},
                update_modified=True
            )

             if frappe.db.get_value("URY Table", table, "occupied") != 0:
                 return {"status": "Failure"}

             # If this table is the master of an active table merge,
             # the merge has served its purpose (the combined order has
             # been printed and is on its way to payment). Auto-unmerge
             # so the source tables come back into the grid as Available.
             # See CLAUDE.md "Fixes log" 2026-04-11.
             from ury.ury_pos.api import auto_unmerge_table_if_active
             auto_unmerge_table_if_active(table)

        return {"status": "Success"}

    except Exception as e:
        frappe.log_error(title="Print Update Fail", message=traceback.format_exc())
        return {"status": "Failure"}


@frappe.whitelist()
def print_pos_page(doctype, name, print_format):
    """
    Endpoint to trigger printing. 
    If QZ is enabled, it returns 'qz_enabled' so JS takes over.
    If QZ is disabled, it prints via CUPS.
    """
    logger.debug(f"print_pos_page called for {name}")
    
    try:
        # Fetch POS Profile from the Invoice
        pos_profile = frappe.db.get_value(doctype, name, "pos_profile")
        
        # 1. CHECK QZ STATUS
        if _get_qz_status(pos_profile):
            # QZ is ON. We do NOT print from server.
            # We return success/qz status so the JS knows to proceed with client-side print.
            return {"status": "qz_enabled", "message": "QZ Enabled, Handled by Client"}

        # 2. CUPS PRINTING (Legacy/Server-side)
        printer_settings = frappe.get_all('Network Printer Settings', limit=1)
        if not printer_settings:
            return {"status": "error", "message": "No printer configured"}
        
        printer_setting = printer_settings[0]['name']
        
        result = network_printing(
            doctype=doctype,
            name=name,
            printer_setting=printer_setting,
            print_format=print_format
        )
        
        # UI Realtime updates (Only needed for Server side print usually)
        restaurant_table, branch = frappe.db.get_value(
            "POS Invoice", name, ["restaurant_table", "branch"]
        )
        
        if branch:
            print_channel = f"print_{branch}"
            frappe.publish_realtime(print_channel, {
                "data": {"name": name, "doctype": doctype, "print_format": print_format}
            })
        
        # Update Status (Since server handled the print)
        if frappe.db.get_value("POS Invoice", name, "invoice_printed") == 0:
            frappe.db.set_value("POS Invoice", name, "invoice_printed", 1)

            if restaurant_table:
                frappe.db.set_value(
                    "URY Table",
                    restaurant_table,
                    {"occupied": 0, "latest_invoice_time": None},
                )

                # Auto-unmerge if this table was a merge master. See
                # CLAUDE.md "Fixes log" 2026-04-11.
                from ury.ury_pos.api import auto_unmerge_table_if_active
                auto_unmerge_table_if_active(restaurant_table)

        return result
            
    except Exception as e:
        frappe.log_error(f"print_pos_page error: {str(e)}", "Print Error")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def qz_certificate():
    return frappe.get_site_config().get("qz_cert")


@frappe.whitelist()
def signature_promise():
    return frappe.get_site_config().get("qz_private_key")


@frappe.whitelist()
def print_kot_on_create(doc, method=None):
    """
    Auto-print KOT. 
    If QZ is enabled, publish realtime event for client-side printing.
    Otherwise use CUPS server-side printing.
    """
    try:
        if isinstance(doc, str):
            kot_name = doc
            kot = frappe.get_doc("URY KOT", kot_name)
        else:
            kot = doc
            kot_name = doc.name
        
        pos_profile = kot.pos_profile
        
        # 1. CHECK QZ STATUS
        if _get_qz_status(pos_profile):
            # Get printer settings for this POS Profile
            printer_settings = frappe.get_all(
                "URY Printer Settings",
                filters={
                    "parent": pos_profile, 
                    "parentfield": "printer_settings", 
                    "custom_kot_print": 1
                },
                fields=["name", "printer", "custom_kot_print_format"]
            )
            
            if not printer_settings:
                return {"status": "error", "message": "No KOT printer configured"}
            
            # Publish realtime event with printer details
            frappe.publish_realtime(
                event="ury_kot_created",
                message={
                    "kot_name": kot_name,
                    "pos_profile": pos_profile,
                    "printers": printer_settings
                },
                user=frappe.session.user
            )
            
            logger.info(f"Published KOT event for {kot_name} to {len(printer_settings)} printer(s)")
            return {"status": "qz_enabled", "message": f"KOT event published for {len(printer_settings)} printer(s)"}

        # 2. CUPS PRINTING (unchanged)
        if not pos_profile:
            return {"status": "error", "message": "No POS Profile configured"}
        
        printer_settings = frappe.get_all(
            "URY Printer Settings",
            filters={
                "parent": pos_profile, 
                "parentfield": "printer_settings", 
                "custom_kot_print": 1
            },
            fields=["name", "printer", "custom_kot_print_format"]
        )
        
        if not printer_settings:
            return {"status": "error", "message": "No KOT printer configured"}
        
        results = []
        success_count = 0

        for setting in printer_settings:
            printer = setting.get("printer")
            fmt = setting.get("custom_kot_print_format")
            
            if not printer: continue
            
            res = network_printing(
                doctype="URY KOT",
                name=kot_name,
                printer_setting=printer,
                print_format=fmt,
                doc=kot
            )
            
            status = res.get("status") if isinstance(res, dict) else "unknown"
            if status == "success":
                success_count += 1

            results.append({
                "printer": printer,
                "status": status,
                "message": res.get("message") if isinstance(res, dict) else str(res)
            })
        
        if success_count > 0:
            _update_kot_status(kot_name)
        
        return {
            "status": "success",
            "message": f"KOT printed to {success_count} printer(s)",
            "results": results
        }
        
    except Exception as e:
        frappe.log_error(f"KOT Print Error: {str(e)}", "KOT Print Error")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def get_kot_printers(pos_profile):
    return frappe.get_all(
        "URY Printer Settings",
        filters={"parent": pos_profile, "custom_kot_print": 1},
        fields=["name", "printer", "custom_kot_print_format"]
    )


def update_invoice_status_on_kot_change(doc, method=None):
    """
    Hook function to update POS Invoice status when KOT status changes to Served.
    Called on every URY KOT update.
    """
    try:
        # Only proceed if order_status is "Served"
        if doc.order_status != "Served":
            return
        
        # Check if invoice field exists and has a value
        if not doc.invoice:
            logger.info(f"KOT {doc.name} has no linked invoice")
            return
        
        # Check if the POS Invoice exists
        if not frappe.db.exists("POS Invoice", doc.invoice):
            logger.warning(f"POS Invoice {doc.invoice} not found for KOT {doc.name}")
            return
        
        # Get current status to avoid unnecessary updates
        current_status = frappe.db.get_value("POS Invoice", doc.invoice, "custom_order_status")
        
        if current_status == "Served":
            logger.info(f"POS Invoice {doc.invoice} already marked as Served")
            return
        
        # Update the custom_order_status field
        frappe.db.set_value(
            "POS Invoice", 
            doc.invoice, 
            "custom_order_status", 
            "Served",
            update_modified=False
        )
        frappe.db.commit()
        
        logger.info(f"✅ Updated POS Invoice {doc.invoice} status to Served (from KOT {doc.name})")
        
    except Exception as e:
        logger.error(f"Error updating invoice status for KOT {doc.name}: {traceback.format_exc()}")
        frappe.log_error(
            f"Failed to update POS Invoice status from KOT {doc.name}: {str(e)}",
            "KOT Invoice Status Update Error"
        )


# ---------------------------------------------------------------------
# Unified print routing (2026-04-16)
# ---------------------------------------------------------------------
#
# Round 1 of the print revamp replaces the scattered per-order-type and
# per-venue printer fields on POS Profile with a single "Printers &
# Routing" config block. The resolver below reads that config, classifies
# each KOT item by department (via its URY Menu Course.custom_department),
# and returns a list of (printer, filtered_items) pairs that the caller
# should print.
#
# Design decisions:
#
# - **Department lives on URY Menu Course**, not per item. One tagging
#   site, all items in that course inherit.
# - **Mixed KOTs are split per department**. A KOT with 2 Beers + 1
#   Burger produces two print jobs: beers -> bar printer, burger ->
#   kitchen printer. Each station only sees its items. The same Print
#   Format is reused — we pass a filtered in-memory copy of the KOT
#   doc to frappe.get_print(), not a different format.
# - **Backwards compat**. When the new custom_print_mode is empty or
#   the new printer fields are blank, the resolver falls back to the
#   legacy custom_table_order_printer / custom_parcel_order_printer
#   / printer_settings child table. Existing installs keep working
#   until their admin opens the POS Profile and saves the new config.
# - **Fallback-if-offline**. When a target printer is missing OR the
#   actual print call fails, behavior is controlled by
#   custom_print_fallback_mode. Default = "Fallback to Bill Printer"
#   which re-routes the items to the bill printer with a header like
#   "DRINKS - BAR OFFLINE" so the bar staff sees the order even if
#   their station printer is down.
#
# See CLAUDE.md "Fixes log" 2026-04-16 (print revamp Round 1).


_DEPT_FOOD = "Food"
_DEPT_DRINKS = "Drinks"
_DEPT_OTHER = "Other"


def _get_course_department_map():
    """Return a dict of {course_name: department} for all URY Menu
    Courses. Cached per request via frappe.local.flags to avoid an
    N+1 fetch when classifying many KOT items.
    """
    cache = getattr(frappe.local, "_ury_course_dept_cache", None)
    if cache is not None:
        return cache
    rows = frappe.get_all(
        "URY Menu Course",
        fields=["name", "custom_department"],
    )
    out = {r.name: (r.custom_department or _DEPT_FOOD) for r in rows}
    frappe.local._ury_course_dept_cache = out
    return out


def _classify_kot_item_department(item):
    """Return the department string for a single KOT item.

    The URY KOT Items child has a `course` field populated at KOT
    creation from the URY Menu Item's course. We look up the course
    in the department map. Unknown/missing course defaults to Food.
    """
    course = getattr(item, "course", None) or getattr(item, "item_group", None)
    if not course:
        return _DEPT_FOOD
    dept_map = _get_course_department_map()
    return dept_map.get(course, _DEPT_FOOD)


def _split_kot_items_by_department(kot_doc):
    """Bucket a KOT's items into {department: [items]}.

    Items with no department tag default to Food. Returns a dict
    keyed by department name; only departments that actually have
    items are present in the output.
    """
    buckets = {}
    for item in (kot_doc.items or []):
        dept = _classify_kot_item_department(item)
        buckets.setdefault(dept, []).append(item)
    return buckets


def _resolve_printer_for_department(pos_profile_doc, department, order_type=None):
    """Given a POS Profile doc (already loaded) and a department
    (Food / Drinks / Other), return the Network Printer Settings
    name that should print that department's items.

    Routing rules (read from the new custom_print_* fields):
      - Drinks  -> custom_drinks_kot_route (Bar | Kitchen | Bill)
      - Food    -> custom_food_kot_route (Kitchen | Bar | Bill)
      - Other   -> falls back to the Food route
      - Takeaway order type overrides Food -> Parcel/Kitchen via
        custom_takeaway_kot_route

    Each route value maps to a printer field:
      Bar     -> custom_bar_kot_printer
      Kitchen -> custom_kitchen_kot_printer
      Bill    -> custom_bill_printer
      Parcel  -> custom_parcel_kot_printer

    If the selected printer is empty, falls through to Bill.
    """
    if department == _DEPT_DRINKS:
        route = pos_profile_doc.get("custom_drinks_kot_route") or "Bar"
    elif department == _DEPT_FOOD:
        # For takeaway orders, override to the takeaway route.
        if order_type and order_type.lower() in ("take away", "takeaway", "parcel"):
            takeaway_route = pos_profile_doc.get("custom_takeaway_kot_route") or "Parcel"
            if takeaway_route == "Parcel":
                return (
                    pos_profile_doc.get("custom_parcel_kot_printer")
                    or pos_profile_doc.get("custom_kitchen_kot_printer")
                    or pos_profile_doc.get("custom_bill_printer")
                    or None
                )
            # else fall through to Kitchen
            route = "Kitchen"
        else:
            route = pos_profile_doc.get("custom_food_kot_route") or "Kitchen"
    else:
        # Other (dessert, misc) — route with food.
        route = pos_profile_doc.get("custom_food_kot_route") or "Kitchen"

    route_to_field = {
        "Bar": "custom_bar_kot_printer",
        "Kitchen": "custom_kitchen_kot_printer",
        "Bill": "custom_bill_printer",
        "Parcel": "custom_parcel_kot_printer",
    }
    field = route_to_field.get(route, "custom_kitchen_kot_printer")
    printer = pos_profile_doc.get(field)
    # Cascade fallback: if the preferred printer is empty, fall
    # through Kitchen -> Bill so there's always SOMETHING.
    if not printer and field != "custom_bill_printer":
        printer = (
            pos_profile_doc.get("custom_kitchen_kot_printer")
            or pos_profile_doc.get("custom_bill_printer")
        )
    return printer


def resolve_kot_print_plan(kot_doc, pos_profile_name, order_type=None):
    """Build the list of (printer_name, items, fallback_note) tuples
    that the KOT should print. Each tuple represents one print job.

    Returns a list of dicts with keys::

        {
            "printer": <Network Printer Settings name or None>,
            "department": "Food" | "Drinks" | "Other",
            "items": [<filtered KOT item rows>],
            "fallback": None | "<original printer went offline, now bill>",
        }

    When the new config (custom_print_mode) is unset, falls back to
    the legacy `printer_settings` child table and per-order-type
    fields — the caller passes each plan entry to the existing
    `print_by_server()` / `network_printing()` helper as before.

    `kot_doc` may be a frappe Document OR a dict-like. `pos_profile_name`
    must be a string. `order_type` is the POS Invoice order type if
    known (used for the Takeaway route override).
    """
    if not pos_profile_name:
        return []

    pos_profile_doc = frappe.get_cached_doc("POS Profile", pos_profile_name)
    mode = pos_profile_doc.get("custom_print_mode")

    # Backwards compat: when the new config isn't set yet, skip the
    # new resolver entirely. The caller will fall back to the legacy
    # multi_print_kot path.
    if not mode or mode == "Disabled":
        return []

    buckets = _split_kot_items_by_department(kot_doc)
    plan = []
    for dept, items in buckets.items():
        if not items:
            continue
        printer = _resolve_printer_for_department(
            pos_profile_doc, dept, order_type=order_type
        )
        plan.append(
            {
                "printer": printer,
                "department": dept,
                "items": items,
                "fallback": None,
            }
        )
    return plan


def apply_print_fallback(plan_entry, pos_profile_doc):
    """Given a plan entry whose primary printer is missing or has
    failed, apply the POS Profile's fallback mode.

    Returns a (should_print, printer, header) tuple:
      - should_print: bool — whether to attempt to print at all
      - printer: Network Printer Settings name or None
      - header: optional string prepended to the print format payload
        (e.g. "DRINKS - BAR OFFLINE") so the receiving printer knows
        it's handling a re-routed order

    Modes:
      - "Fallback to Bill Printer" (default) — route to the bill
        printer with a loud header identifying the intended department.
      - "Fail Silently" — drop the print job, no toast, no log.
      - "Fail with Alert" — don't print, but the caller should raise
        a user-visible error via realtime / toast so the cashier knows.
    """
    mode = pos_profile_doc.get("custom_print_fallback_mode") or "Fallback to Bill Printer"
    department = plan_entry.get("department", _DEPT_FOOD)

    if mode == "Fail Silently":
        return (False, None, None)
    if mode == "Fail with Alert":
        return (False, None, None)

    # Default / "Fallback to Bill Printer"
    bill_printer = pos_profile_doc.get("custom_bill_printer")
    if not bill_printer:
        return (False, None, None)
    # Header is a plain-text marker the print format can inspect via
    # doc.flags.fallback_header (set by the caller before rendering)
    # or that gets prepended to the text-template fallback.
    target_label = department.upper()
    header = f"{target_label} - TARGET PRINTER OFFLINE"
    return (True, bill_printer, header)


def ury_print_via_cups(
    ury_printer_name,
    doctype,
    doc_name,
    print_format=None,
    doc=None,
    no_letterhead=0,
):
    """Print a doc via CUPS, reading server_ip/port/printer_name from
    a URY Printer record instead of Frappe's Network Printer Settings.

    Required for the new print routing path — Frappe's
    ``frappe.utils.print_format.print_by_server`` hard-requires a
    Network Printer Settings doc (which in turn requires a reachable
    CUPS server just to CREATE a record — the catch-22 that drove
    URY's switch to a URY-owned printer doctype). This helper
    replicates ``print_by_server``'s core behavior: resolve the
    printer config, connect to CUPS, render the doc to PDF, print
    the file.

    Returns (ok, err_msg). Callers in the new path (multi_print_kot
    new branch) use this instead of ``print_by_server``. The legacy
    path still calls ``print_by_server`` because its data lives in
    ``URY Printer Settings`` child rows that still point at
    Network Printer Settings.

    Raises nothing — all exceptions (missing printer, unreachable
    CUPS, failed PDF render, CUPS IPPError) are caught and returned
    as the second tuple element so the caller can apply the
    POS Profile's ``custom_print_fallback_mode`` policy.

    See CLAUDE.md "Fixes log" 2026-04-16 (print revamp Round 1).
    """
    if not ury_printer_name:
        return (False, "no printer configured")

    try:
        printer_doc = frappe.get_cached_doc("URY Printer", ury_printer_name)
    except frappe.DoesNotExistError:
        return (False, f"URY Printer '{ury_printer_name}' not found")

    if printer_doc.get("disabled"):
        return (False, f"URY Printer '{ury_printer_name}' is disabled")

    try:
        import cups  # local import — pycups may be missing on QZ-only deployments
    except ImportError:
        return (
            False,
            "pycups is not installed — see install.py:_check_cups_dependency",
        )

    server_ip = printer_doc.get("server_ip") or "localhost"
    port = int(printer_doc.get("port") or 631)
    cups_printer_name = printer_doc.get("printer_name") or ury_printer_name

    try:
        cups.setServer(server_ip)
        cups.setPort(port)
        conn = cups.Connection()
    except Exception as e:
        return (False, f"CUPS connect failed ({server_ip}:{port}): {e}")

    # Render the doc to a PDF temp file.
    import os
    import tempfile
    from PyPDF2 import PdfWriter  # Frappe's print_by_server uses this too

    try:
        output = PdfWriter()
        output = frappe.get_print(
            doctype,
            doc_name,
            print_format,
            doc=doc,
            no_letterhead=no_letterhead,
            as_pdf=True,
            output=output,
        )
        fd, file_path = tempfile.mkstemp(
            prefix=f"ury-kot-{frappe.generate_hash(length=6)}-",
            suffix=".pdf",
        )
        os.close(fd)
        with open(file_path, "wb") as f:
            output.write(f)
    except Exception as e:
        return (False, f"PDF render failed: {e}")

    try:
        conn.printFile(cups_printer_name, file_path, doc_name, {})
    except Exception as e:
        return (False, f"CUPS print failed ({cups_printer_name}): {e}")
    finally:
        # Best-effort cleanup of the temp PDF.
        try:
            os.remove(file_path)
        except Exception:
            pass

    return (True, None)
