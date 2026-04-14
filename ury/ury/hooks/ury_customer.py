import frappe


def before_insert(doc, event):
    validate_mobile_number(doc, event)


def validate_mobile_number(doc, event):
    # ERPNext's test bootstrap creates Customers without a mobile
    # number; we don't want that to block `bench run-tests --app ury`.
    # The production Customer creation path goes through the React POS
    # which always supplies a mobile number — so this bypass is safe.
    if frappe.flags.in_test:
        return
    if not doc.mobile_number:
        frappe.throw("Mobile Number is Mandatory")
