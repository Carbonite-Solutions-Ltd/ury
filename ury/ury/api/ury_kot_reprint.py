import frappe
from frappe.utils import cint
from frappe.utils.print_format import print_by_server



@frappe.whitelist()
def reprint_kot(invoice_number):
    """Reprint the KOT for a given POS Invoice.

    Resolution order (2026-04-16):
      1. **New unified config** — if POS Profile.custom_print_mode is
         set, resolve the target printer from the Food KOT route
         (custom_food_kot_route -> custom_kitchen_kot_printer). For
         takeaway orders, use the takeaway route. This way reprints
         honor the same routing the first print used.
      2. **Legacy path** — fall back to the old
         custom_table_order_printer / custom_parcel_order_printer
         per order type. Preserved for sites that haven't migrated.
    """
    try:
        pos_profile, restaurant_table, order_type = frappe.db.get_value(
            "POS Invoice", invoice_number, ["pos_profile", "restaurant_table", "order_type"]
        )
        if not pos_profile:
            frappe.throw(f"POS Profile not found for Invoice {invoice_number}.")

        pos_profile_doc = frappe.get_cached_doc("POS Profile", pos_profile)

        enable_kot_reprint = pos_profile_doc.get("custom_enable_kot_reprint")
        kot_print_format = pos_profile_doc.get("custom_reprint_kot_format")

        if not cint(enable_kot_reprint):
            frappe.throw("KOT Reprint is disabled in POS Profile.")
        if not kot_print_format:
            frappe.throw("No KOT Reprint Print Format is set in POS Profile.")

        # ---- New unified config path ----
        mode = pos_profile_doc.get("custom_print_mode")
        if mode and mode != "Disabled":
            # Route the food KOT via the same helper the live print
            # path uses so reprints and live prints always agree.
            from ury.ury.api.ury_print import _resolve_printer_for_department

            printer = _resolve_printer_for_department(
                pos_profile_doc, "Food", order_type=order_type
            )
            if not printer:
                frappe.throw(
                    "No printer is assigned for reprinting KOT. "
                    "Open the POS Profile's 'Printers & Routing' section "
                    "and set the Kitchen KOT Printer or Bill Printer."
                )
            print_kot(printer, invoice_number, kot_print_format)
            return "Success"

        # ---- Legacy path ----
        table_order_printer = pos_profile_doc.get("custom_table_order_printer")
        parcel_order_printer = pos_profile_doc.get("custom_parcel_order_printer")
        printer = table_order_printer if order_type == "Dine In" else parcel_order_printer

        if not printer:
            frappe.throw("No printer is assigned for reprinting KOT.")

        print_kot(printer, invoice_number, kot_print_format)
        return "Success"

    except Exception as e:
        error_message = f"KOT Reprint Error for Invoice {invoice_number}: {str(e)}"
        frappe.log_error(error_message, "KOT Reprint Error")
        frappe.throw("An unexpected error occurred while reprinting KOT. Please check logs.")


def print_kot(printer,docname, kot_print_format):
    try:
        print_by_server("POS Invoice",docname, printer, kot_print_format)
    except Exception as e:
        frappe.log_error(f"KOT Reprint Error: {e}")