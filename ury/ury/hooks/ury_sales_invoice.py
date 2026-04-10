import frappe

# Import folio helpers so Sales Invoice (POS Sales Invoice mode) can also post room charges
from ury.ury.hooks.ury_pos_invoice import (
    validate_folio_charge_details,
    apply_room_charge_payment,
    post_folio_charge,
    reverse_folio_charge,
)


def before_insert(doc, method):
    sales_invoice_naming(doc, method)


def validate(doc, method):
    # Only validate folio fields when this Sales Invoice came from POS
    if doc.is_pos:
        validate_folio_charge_details(doc, method)


def before_submit(doc, method):
    # Settle the outstanding amount via "Room Charge" so the partial-payment
    # guard in ERPNext does not block submission.
    if doc.is_pos:
        apply_room_charge_payment(doc)


def on_submit(doc, method):
    # Post the F&B charge to the guest folio when Sales Invoice mode is active in POS
    if doc.is_pos:
        post_folio_charge(doc, method)


def on_cancel(doc, method):
    # Reverse the folio charge on cancellation (creates a negative line for audit trail)
    if doc.is_pos:
        reverse_folio_charge(doc, method)


def on_update(doc, method):
    aggregator_unpaid(doc, method)
    
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

        

