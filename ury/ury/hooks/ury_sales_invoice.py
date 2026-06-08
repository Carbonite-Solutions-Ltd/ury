import frappe


def before_insert(doc, method):
    sales_invoice_naming(doc, method)

def on_update(doc,method):
    aggregator_unpaid(doc,method)


def before_submit(doc, method):
    allow_zero_valuation_on_pos_stock(doc, method)


def allow_zero_valuation_on_pos_stock(doc, method):
    """Let POS / consolidated stock items with no valuation rate post
    their stock ledger entries instead of blocking the shift close.

    ERPNext defers a POS Invoice's stock ledger entries to the
    CONSOLIDATED Sales Invoice created at shift close. When a menu item
    is stock-tracked but has no valuation rate (common for restaurant
    menu items that don't carry an inventory cost), the consolidated
    invoice's on_submit stock posting throws:

        "Valuation Rate for the Item X is required ..." /
        "Row #N: Item X has zero rate but 'Allow Zero Valuation Rate'
         is not enabled."

    which rolls the WHOLE close back. We enable allow_zero_valuation_rate
    on each item row of a POS / consolidated invoice so the stock entry
    posts at zero cost rather than blocking the close.

    Scope is deliberately narrow:
      - Only fires for POS-side invoices (`is_consolidated` or `is_pos`)
        that actually move stock (`update_stock`). Manual / purchase /
        non-stock Sales Invoices are untouched.
      - It's a NO-OP for items that already have a valuation rate — the
        flag only takes effect when the rate would otherwise be zero.

    See CLAUDE.md "Fixes log" 2026-06-05.
    """
    if not (doc.get("is_consolidated") or doc.get("is_pos")):
        return
    if not doc.get("update_stock"):
        return
    for item in (doc.items or []):
        if not item.get("allow_zero_valuation_rate"):
            item.allow_zero_valuation_rate = 1


def sales_invoice_naming(doc, method):
    if not doc.is_pos:
        return
    
    if not doc.pos_profile:
        return
    
    pos_profile = frappe.db.get_value(
        "POS Profile", 
        doc.pos_profile, 
        ["restaurant_prefix", "restaurant"], 
        as_dict=True
    )

    if not pos_profile:
        frappe.throw(f"POS Profile '{doc.pos_profile}' does not exist. Please select a valid POS Profile.")
    
    restaurant = pos_profile.get("restaurant")

    if pos_profile.get("restaurant_prefix") == 1 and restaurant:
        if doc.order_type == "Aggregators":
            
            # Get the aggregator series prefix
            aggregator_series_prefix = frappe.db.get_value(
                "URY Restaurant", 
                restaurant, 
                "aggregator_series_prefix"
            )
            
            if aggregator_series_prefix: 
                doc.naming_series = "SINV-" +  aggregator_series_prefix
                
            else: 
                # Fallback to invoice_series_prefix if aggregator_series_prefix is not available            
                doc.naming_series = "SINV-" + frappe.db.get_value("URY Restaurant", restaurant, "invoice_series_prefix")
                      
        else:
            # Use invoice_series_prefix for non-aggregator orders
            doc.naming_series = "SINV-" + frappe.db.get_value(
                "URY Restaurant", restaurant, "invoice_series_prefix"
            )
            
            
def aggregator_unpaid(doc,method):
    if doc.order_type == "Aggregators" and frappe.db.get_value("Branch", doc.branch , "custom_make_unpaid") == 1 :
        doc.is_pos = 0
        
        
def remove_tax(doc,method):
    
    if doc.order_type == "Aggregators" and frappe.db.get_value("Branch", doc.branch , "custom_no_taxes") == 1 :

        doc.taxes_and_charges = None
        
        doc.taxes.clear()
       # Manually adjust totals
        # doc.total_taxes_and_charges = 0
        # doc.grand_total = doc.base_grand_total = doc.net_total
        # doc.outstanding_amount = doc.grand_total - doc.paid_amount
        # doc.run_method("validate")

        

