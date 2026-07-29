import frappe
import os
import click
from frappe import _

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def after_install():
    create_custom_fields(get_custom_fields())
    
def before_uninstall():
	delete_custom_fields(get_custom_fields())
 
def get_custom_fields():
	"""URY specific custom fields that need to be added to the masters in ERPNext"""
	return {
     	"Contact": [
				{
					# Compatibility shim: ERPNext's get_default_contact (party.py)
					# still filters/orders by Contact.is_billing_contact, but this
					# Frappe version dropped that column — so every POS Invoice save
					# blew up with "Unknown column 'tabContact.is_billing_contact'".
					# Re-add it as a hidden, read-only no-op Check so the ERPNext
					# query resolves. See CLAUDE.md "Fixes log".
					"fieldname": "is_billing_contact",
					"fieldtype": "Check",
					"label": "Is Billing Contact",
					"insert_after": "is_primary_contact",
					"default": "0",
					"hidden": 1,
					"read_only": 1,
					"no_copy": 1,
					"description": "Compatibility field re-added by ExPOS so ERPNext's get_default_contact query works (Frappe dropped this column from Contact).",
					"translatable": 0,
				},
			],
     	"URY Printer Settings": [
				{
					"fieldname": "custom_terminal",
					"fieldtype": "Link",
					"label": "Terminal",
					"options": "URY POS Terminal",
					"insert_after": "printer",
					"in_list_view": 1,
					"depends_on": "eval:doc.parenttype=='URY Production Unit'",
					"description": "When set, this printer only fires for KOTs of orders rung on this terminal. Leave blank to print on every terminal.",
					"translatable": 0,
				},
			],
     	"POS Invoice": [
				{
					"fieldname": "mobile_number",
					"fieldtype": "Data",
					"fetch_from": "customer.mobile_number",
					"label": "Mobile Number",
					"insert_after": "customer_name",
					"translatable": 0,
				},
				{
					"fieldname": "order_info",
					"fieldtype": "Section Break",
					"label": "Order Info",
					"insert_after": "return_against",
				},
				{
					"fieldname": "order_type",
					"fieldtype": "Select",
					"default": "Dine In",
					"label": "Order Type",
					"options": "\nDine In\nTake Away\nDelivery\nPhone In\nAggregators",
					"insert_after": "order_info",
					"translatable": 0
				},
				{
					"fieldname": "waiter",
					"fieldtype": "Data",
					"label": "Waiter",
					"read_only": 0,
					"insert_after": "order_type",
					"translatable": 0
				},
				{
					"fieldname": "column_break_rwbwf",
					"fieldtype": "Column Break",
					"insert_after": "waiter"
				},
				{
					"fieldname": "no_of_pax",
					"fieldtype": "Data",
					"label": "Pax",
					"insert_after": "column_break_rwbwf",
					"read_only": 0,
					"translatable": 0
				},
				{
					"fieldname": "cashier",
					"fieldtype": "Data",
					"label": "Cashier",
					"insert_after": "no_of_pax",
					"read_only": 0,
					"translatable": 0
				},
				{
					"fieldname": "invoice_printed",
					"fieldtype": "Check",
					"label": "Invoice Printed",
					"insert_after": "cashier",
					"read_only": 1,
				},
				{
					"fieldname": "invoice_created",
					"fieldtype": "Check",
					"label": "Invoice Created",
					"insert_after": "invoice_printed",
					"read_only": 0,
					"hidden": 1,
				},
				{
					"fieldname": "restaurant_info",
					"fieldtype": "Section Break",
					"label": "Restaurant Info",
					"insert_after": "invoice_created",
				},
				{
					"fieldname": "restaurant",
					"fieldtype": "Link",
					"insert_after": "restaurant_info",
					"label": "Restaurant",
					"options": "URY Restaurant",
					"read_only": 0,
				},
				{
					"fieldname": "branch",
					"fieldtype": "Link",
					"insert_after": "restaurant",
					"label": "Branch",
					"options": "Branch",
					"read_only": 0,
				},
				{
					"fieldname": "restaurant_table",
					"fieldtype": "Link",
					"insert_after": "branch",
					"label": "Restaurant Table",
					"options": "URY Table",
					"read_only": 0,
				},
				# Terminal stamping field. Mirrors the custom_field.json
				# fixture entry but lives here so create_custom_fields()
				# (called from after_install + after_migrate) can ensure
				# the column exists on existing sites that already had
				# URY installed before the field shipped. Without this,
				# fixtures only get imported on initial install and
				# pre-existing sites silently lose the column —
				# `invoice.custom_terminal = ...` becomes a no-op write.
				# See CLAUDE.md "Fixes log" 2026-04-09.
				{
					"fieldname": "custom_terminal",
					"fieldtype": "Link",
					"insert_after": "restaurant_table",
					"label": "Terminal",
					"options": "URY POS Terminal",
					"read_only": 1,
					"in_standard_filter": 1,
					"print_hide_if_no_value": 1,
					"description": "Physical terminal (till) that rang this invoice. Stamped automatically from the React POS session.",
				},
				# Set when this invoice has been merged into another
				# (the master). Hidden from the Orders page list. Cleared
				# on unmerge. See CLAUDE.md "Fixes log" 2026-04-09 (merge
				# orders feature).
				{
					"fieldname": "custom_merged_into",
					"fieldtype": "Link",
					"insert_after": "custom_terminal",
					"label": "Merged Into",
					"options": "POS Invoice",
					"read_only": 1,
					"in_standard_filter": 1,
					"print_hide": 1,
					"print_hide_if_no_value": 1,
					"description": "Set when this invoice has been merged into another (the master). Hidden from the Orders page list. Cleared on unmerge.",
				},
				# Offline order queue de-duplication (Phase B, 2026-07-21).
				# A client-generated key stamped on a new POS Invoice so a
				# queued offline order replayed on reconnect is returned
				# instead of created twice. sync_order checks this before
				# creating anything. Hidden internal field. Dual-sourced here
				# + custom_field.json so pre-existing installs get the column.
				{
					"fieldname": "custom_idempotency_key",
					"fieldtype": "Data",
					"insert_after": "custom_terminal",
					"label": "Idempotency Key",
					"read_only": 1,
					"no_copy": 1,
					"hidden": 1,
					"print_hide": 1,
					"search_index": 1,
					"description": "Client-generated key for the offline order queue. Ensures a queued order replayed on reconnect is not created twice.",
					"translatable": 0,
				},
				# iHotel integration — "charged draft" fields. When the
				# cashier picks "Charge to Room" in the Payment dialog,
				# the backend writes a Folio Charge row on the matching
				# open iHotel Profile and stamps these three fields on
				# the POS Invoice. The invoice stays docstatus=0 forever
				# so it doesn't double-post at shift close — iHotel's
				# own checkout flow posts the actual accounting when the
				# guest settles. See CLAUDE.md "Fixes log" 2026-04-12.
				{
					"fieldname": "custom_charge_to_room",
					"fieldtype": "Check",
					"insert_after": "custom_merged_into",
					"label": "Charged to Hotel Room",
					"default": "0",
					"read_only": 1,
					"in_standard_filter": 1,
					"print_hide": 1,
					"description": "Set when this invoice has been charged to a hotel guest's room. Stays docstatus=0 (charged draft) and is excluded from shift-close consolidation.",
				},
				{
					"fieldname": "custom_hotel_room",
					"fieldtype": "Link",
					"insert_after": "custom_charge_to_room",
					"label": "Hotel Room",
					"options": "Room",
					"read_only": 1,
					"in_standard_filter": 1,
					"depends_on": "eval:doc.custom_charge_to_room",
					"description": "iHotel room this invoice is charged against.",
				},
				{
					"fieldname": "custom_ihotel_profile",
					"fieldtype": "Link",
					"insert_after": "custom_hotel_room",
					"label": "iHotel Profile",
					"options": "iHotel Profile",
					"read_only": 1,
					"depends_on": "eval:doc.custom_charge_to_room",
					"description": "iHotel Profile the folio charge was written onto.",
				},
				# Optional transaction / reference id for non-cash payments
				# (card, mobile money, bank transfer). Entered by the cashier
				# in the Payment dialog when a non-cash mode is used. 2026-07-16.
				{
					"fieldname": "custom_transaction_id",
					"fieldtype": "Data",
					"insert_after": "custom_ihotel_profile",
					"label": "Transaction ID",
					"in_standard_filter": 1,
					"description": "Reference / transaction id for a non-cash payment (card, mobile money, bank transfer). Optional, entered by the cashier at payment time.",
				},
				# Invoice-transfer workflow (2026-06-05). Denormalized flag
				# on the draft so the Orders page can cheaply filter
				# "Pending Incoming" transfers. Written only inside a
				# transfer transition (create / approve / reject) alongside
				# the URY Invoice Transfer record that is the source of
				# truth. See ury_pos/api.py transfer endpoints.
				{
					"fieldname": "custom_transfer_status",
					"fieldtype": "Select",
					"insert_after": "custom_ihotel_profile",
					"label": "Transfer Status",
					"options": "\nPending Incoming\nApproved\nRejected",
					"read_only": 1,
					"in_standard_filter": 1,
					"print_hide": 1,
					"print_hide_if_no_value": 1,
					"description": "Set when this draft is part of an invoice-transfer workflow. 'Pending Incoming' means a captain has offered it to the current owner and is awaiting approval; 'Approved'/'Rejected' record the resolution. Source of truth is the URY Invoice Transfer doctype.",
				},
				# Waiter feature (2026-06-10). Selected URY Waiter stamped on
				# the order when POS Profile.custom_use_waiter is on.
				{
					"fieldname": "custom_waiter",
					"fieldtype": "Link",
					"insert_after": "custom_transfer_status",
					"label": "Waiter",
					"options": "URY Waiter",
					"read_only": 1,
					"in_standard_filter": 1,
					"description": "The waiter assigned to this order (when the POS Profile uses waiters). Stamped at order creation; shown on the Waiters page.",
				},
				# Bill reprint count (2026-06-10). Incremented each print by
				# qz_print_update; capped per cashier by POS Profile.custom_max_bill_prints.
				{
					"fieldname": "custom_print_count",
					"fieldtype": "Int",
					"insert_after": "custom_waiter",
					"label": "Print Count",
					"default": "0",
					"read_only": 1,
					"non_negative": 1,
					"description": "How many times this bill has been printed. Drives the per-cashier reprint cap (POS Profile.custom_max_bill_prints).",
				},
				{
					"fieldname": "column_break_gd1mq",
					"fieldtype": "Column Break",
					"insert_after": "custom_ihotel_profile",
				},
				{
					"fieldname": "arrived_time",
					"fieldtype": "Time",
					"insert_after": "column_break_gd1mq",
					"label": "Arrived Time"
				},
				{
					"fieldname": "total_spend_time",
					"fieldtype": "Time",
					"insert_after": "arrived_time",
					"label": "Total Spend Time"
				}
				],

		"Sales Invoice": [
					{
					"fieldname": "mobile_number",
					"fieldtype": "Data",
					"fetch_from": "customer.mobile_number",
					"label": "Mobile Number",
					"insert_after": "customer_name",
					"translatable": 0,
				},
				{
					"fieldname": "order_info",
					"fieldtype": "Section Break",
					"label": "Order Info",
					"insert_after": "return_against",
				},
				{
					"fieldname": "order_type",
					"fieldtype": "Select",
					"default": "Dine In",
					# fetch_from MUST stay blank. order_type is set by the
					# order flow / consolidation map_doc, NOT fetched from the
					# customer. A stray `fetch_from="customer.mobile_number"`
					# here (copy-pasted from the mobile_number field) put the
					# customer's phone number into order_type during shift-
					# close consolidation, failing the Select validation and
					# blocking every close. Setting "" explicitly so
					# create_custom_fields CLEARS it on existing sites that
					# already had the bad value stamped. See CLAUDE.md "Fixes
					# log" 2026-06-05.
					"fetch_from": "",
					"label": "Order Type",
					"options": "\nDine In\nTake Away\nDelivery\nPhone In\nAggregators",
					"insert_after": "order_info",
					"translatable": 0
				},
				{
					"fieldname": "waiter",
					"fieldtype": "Data",
					"label": "Waiter",
					"read_only": 0,
					"insert_after": "order_type",
					"translatable": 0
				},
				{
					"fieldname": "column_break_rwbwf",
					"fieldtype": "Column Break",
					"insert_after": "waiter"
				},
				{
					"fieldname": "no_of_pax",
					"fieldtype": "Data",
					"label": "Pax",
					"insert_after": "column_break_rwbwf",
					"read_only": 0,
					"translatable": 0
				},
				{
					"fieldname": "cashier",
					"fieldtype": "Data",
					"label": "Cashier",
					"insert_after": "no_of_pax",
					"read_only": 0,
					"translatable": 0
				},
				{
					"fieldname": "restaurant_info",
					"fieldtype": "Section Break",
					"label": "Restaurant Info",
					"insert_after": "invoice_created",
				},
				{
					"fieldname": "restaurant",
					"fieldtype": "Link",
					"insert_after": "restaurant_info",
					"label": "Restaurant",
					"options": "URY Restaurant",
					"read_only": 0,
				},
				{
					"fieldname": "branch",
					"fieldtype": "Link",
					"insert_after": "restaurant",
					"label": "Branch",
					"options": "Branch",
					"read_only": 0,
				},
				{
					"fieldname": "restaurant_table",
					"fieldtype": "Link",
					"insert_after": "branch",
					"label": "Restaurant Table",
					"options": "URY Table",
					"read_only": 0,
				},
				{
					"fieldname": "column_break_gd1mq",
					"fieldtype": "Column Break",
					"insert_after": "restaurant_table",
				},
				{
					"fieldname": "arrived_time",
					"fieldtype": "Time",
					"insert_after": "column_break_gd1mq",
					"label": "Arrived Time"
				},
				{
					"fieldname": "total_spend_time",
					"fieldtype": "Time",
					"insert_after": "arrived_time",
					"label": "Total Spend Time"
				}
				],

		"Warehouse": [
			{
				"fieldname": "custom_cost_center",
				"fieldtype": "Link",
				"options": "Cost Center",
				"label": "Cost Center (Outlet)",
				"insert_after": "company",
				"in_standard_filter": 1,
				"description": "The outlet this warehouse belongs to. In item-warehouse mode the POS uses the till's cost centre to pick which of a category's per-outlet warehouses a sale deducts from.",
			}
		],

		"POS Profile": [
			{
				# Declared here (not just in custom_field.json) purely so the
				# DESCRIPTION reaches sites that installed URY before it was
				# written — fixtures are install-only, setup.py runs on every
				# migrate. The field itself has existed for a long time; this
				# entry deliberately omits `default` so create_custom_fields
				# cannot clobber whatever an admin already set.
				"fieldname": "custom_enable_multiple_cashier",
				"fieldtype": "Check",
				"label": "Enable Multiple Cashier",
				"insert_after": "custom_multiple_cashier_configuration",
				"description": "Legacy flag — it does NOT control who may open or close the POS. There is always exactly ONE open POS Opening Entry per POS Profile (enforced by ERPNext), created by whoever starts the day; every other cashier or waiter on any terminal of this profile simply joins it, with no entry of their own. Per-order attribution is kept on each invoice (owner, terminal, cashier). Ticking this box now only affects bill-print routing. Safe to leave unticked.",
				"translatable": 0,
			},
			{
				"fieldname": "custom_use_pos_warehouse",
				"fieldtype": "Check",
				"label": "Use Single POS Warehouse",
				"default": "1",
				"insert_after": "warehouse",
				"description": "ON: all sold items post stock to the POS Profile's Warehouse above (the Warehouse field is required). OFF: the Warehouse is hidden and each item posts to its own Default Warehouse (Item > Item Defaults) at shift close; an item with no warehouse blocks the close.",
				"translatable": 0,
			},
			{
				"fieldname": "custom_min_screen_width",
				"fieldtype": "Int",
				"label": "Minimum Screen Width (px)",
				"insert_after": "custom_use_pos_warehouse",
				"non_negative": 1,
				"description": "Smallest screen width (in pixels) allowed to use the POS. On a narrower screen the cashier sees a 'Desktop Only' notice. LEAVE BLANK or 0 for NO restriction — the POS then works at any screen size. Example: 1000. (Note: this is the browser's viewport width, which shrinks when the browser is zoomed in or not maximized.)",
				"translatable": 0,
			},
			{
				"fieldname": "restaurant_info",
				"fieldtype": "Section Break",
				"label": "Restaurant Info",
				"insert_after": "company_address",
			},
			{
				"fieldname": "restaurant",
				"fieldtype": "Link",
				"insert_after": "restaurant_info",
				"label": "Restaurant",
				"options": "URY Restaurant",
			},
			{
				"fieldname": "column_break_c10ag",
				"fieldtype": "Column Break",
				"insert_after": "restaurant",
			},
			{
				"fetch_from": "restaurant.branch" ,
				"fieldname": "branch",
				"fieldtype": "Link",
				"insert_after": "column_break_c10ag",
				"label": "Branch",
				"options": "Branch"
			},
			{
				"fieldname": "printer_info",
				"fieldtype": "Section Break",
				"label": "Printer Info",
				"insert_after": "branch",
			},
			{
				"depends_on": "eval:doc.qz_print != 1" , 
				"fieldname": "printer_settings",
				"fieldtype": "Table",
				"insert_after": "printer_info",
				"label": "Printer Settings",
				"options": "URY Printer Settings"
			},
			{
				"fieldname": "qz_print",
				"fieldtype": "Check",
				"label": "QZ Print",
				"insert_after": "printer_settings"
			},
			{
				"depends_on": "qz_print",
				"fieldname": "qz_host",
				"fieldtype": "Data",
				"insert_after": "qz_print",
				"label": "QZ Host",
				"default": "localhost",
				"description": "QZ Tray websocket host. Leave as 'localhost' when QZ Tray runs on the cashier's own PC (the usual desktop setup). Set this to the LAN IP of a machine running QZ Tray as a 'print server' (e.g. 192.168.1.50) so tablets — which can't run QZ Tray themselves — can print to a networked printer. Both the bill and the KOTs are sent to this host. A non-localhost host connects over secure WSS (port 8181), which needs QZ Tray's certificate trusted on the tablet.",
				"translatable": 0,
			},
			# Shift hours / shift system fields. Same dual-source-of-truth
			# fix — in custom_field.json AND here so existing sites pick
			# them up via after_migrate. See CLAUDE.md "Fixes log"
			# 2026-04-09 + 2026-04-14 (URY Shift system added).
			{
				"fieldname": "custom_shift_system_mode",
				"fieldtype": "Select",
				"insert_after": "qz_host",
				"label": "Shift System Mode",
				"default": "Disabled",
				"options": "Disabled\nURY Shift\nHRMS Shift Type",
				"description": "How to gate POS Opening Entry creation. \"Disabled\" falls back to the legacy Shift Length (Hours) reminder. \"ExPOS Shift\" uses ExPOS Shift Assignment + ExPOS Shift records to enforce a per-user start/end window. \"HRMS Shift Type\" uses ERPNext HRMS Shift Type + Shift Assignment via the Employee linked to the user (requires hrms app installed).",
			},
			{
				"fieldname": "custom_shift_hours",
				"fieldtype": "Int",
				"insert_after": "custom_shift_system_mode",
				"label": "Shift Length (Hours)",
				"default": "0",
				"non_negative": 1,
				"depends_on": "eval:!doc.custom_shift_system_mode || doc.custom_shift_system_mode == 'Disabled'",
				"description": "Legacy mode only. Length of a single shift in hours. Hidden when Shift System Mode is set to ExPOS Shift or HRMS Shift Type.",
			},
			{
				"fieldname": "custom_block_orders_after_shift_end",
				"fieldtype": "Check",
				"insert_after": "custom_shift_hours",
				"label": "Block Orders After Shift End",
				"default": "0",
				"depends_on": "eval:(doc.custom_shift_hours > 0) && (!doc.custom_shift_system_mode || doc.custom_shift_system_mode == 'Disabled')",
				"description": "When the shift length is exceeded, also block new orders until the cashier closes the shift.",
			},
			# Restrict the merge-orders button to captains only. When
			# checked, only URY Captain / URY Manager / Administrator
			# users see the merge button on the Orders page; when
			# unchecked, cashiers can merge their own orders too.
			# See CLAUDE.md "Fixes log" 2026-04-09 (merge orders feature).
			{
				"fieldname": "custom_restrict_merge_to_captain",
				"fieldtype": "Check",
				"insert_after": "custom_block_orders_after_shift_end",
				"label": "Restrict Merge Orders to Captain",
				"default": "0",
				"description": "When checked, only ExPOS Captain / ExPOS Manager / Administrator users can merge orders on this terminal.",
			},
			# Per-profile escape hatch for the "no stock in warehouse"
			# blocker on Payment. When checked, the on_update hook walks
			# every URY Menu Item linked to the profile's restaurant and
			# flips Item.allow_negative_stock = 1 on each Item master that
			# has is_stock_item = 1. Unchecking reverses the flip on the
			# same set. See CLAUDE.md "Fixes log" 2026-04-10.
			{
				"fieldname": "custom_allow_negative_stock_on_menu_items",
				"fieldtype": "Check",
				"insert_after": "custom_restrict_merge_to_captain",
				"label": "Allow Negative Stock on Menu Items",
				"default": "0",
				"description": "When checked, every stock-tracked item on this profile's restaurant menus is allowed to go negative on stock. Saving the profile walks all menus tied to the restaurant and flips Item.allow_negative_stock on each Item master. Unchecking reverses the flip. Note: this is a per-Item flag, so two POS Profiles sharing the same item will fight (last save wins).",
			},
			# Restrict the Return Orders button to captains by default.
			# Returns are sensitive (they refund money + reverse stock),
			# so the default is ON — only captains/managers/admins can
			# issue returns. Flip to OFF to let cashiers return their
			# own orders. See CLAUDE.md "Fixes log" 2026-04-10.
			{
				"fieldname": "custom_restrict_returns_to_captain",
				"fieldtype": "Check",
				"insert_after": "custom_allow_negative_stock_on_menu_items",
				"label": "Restrict Returns to Captain",
				"default": "1",
				"description": "When checked (default), only ExPOS Captain / ExPOS Manager / Administrator users can issue returns from the Orders page right panel. Flip to OFF to let cashiers return their own orders too.",
			},
			# Returns master switch (2026-06-05). OFF by default - the
			# Return Orders feature is hidden everywhere and the backend
			# rejects return requests until an admin turns this on.
			# Evaluated BEFORE custom_restrict_returns_to_captain.
			{
				"fieldname": "custom_enable_returns",
				"fieldtype": "Check",
				"insert_after": "custom_restrict_returns_to_captain",
				"label": "Enable Returns",
				"default": "0",
				"description": "Master switch for the Return Orders feature on the Orders page. OFF by default - returns are hidden everywhere and the backend rejects return requests. Turn ON to allow returns (still subject to 'Restrict Returns to Captain').",
			},
			# Per-invoice transfer hop cap (2026-06-05). How many times a
			# single unpaid order may be transferred between cashiers at
			# shift close. 0 disables transfers entirely. See the
			# URY Invoice Transfer workflow in ury_pos/api.py.
			{
				"fieldname": "custom_max_invoice_transfers",
				"fieldtype": "Int",
				"insert_after": "custom_enable_returns",
				"label": "Max Invoice Transfers",
				"default": "2",
				"description": "How many times a single unpaid order may be transferred between cashiers at shift close (per-invoice hop count). 0 disables transfers entirely - captains must pay/cancel instead. Each approved transfer consumes one hop.",
			},
			# Waiter feature (2026-06-10). When ON, the React POS pops a
			# waiter picker when the cashier creates a NEW order; the chosen
			# waiter is stamped on the invoice (POS Invoice.custom_waiter).
			{
				"fieldname": "custom_use_waiter",
				"fieldtype": "Check",
				"insert_after": "custom_max_invoice_transfers",
				"label": "Use Waiter",
				"default": "0",
				"description": "When ON, the POS asks the cashier to pick a waiter (ExPOS Waiter) when creating a new order. The waiter is stamped on the order and shown on the Waiters page.",
			},
			# Bill reprint cap (2026-06-10). Total times a CASHIER can print
			# one bill. Captains/Managers/Admins are unlimited.
			{
				"fieldname": "custom_max_bill_prints",
				"fieldtype": "Int",
				"insert_after": "custom_use_waiter",
				"label": "Max Bill Prints (Cashier)",
				"default": "3",
				"non_negative": 1,
				"description": "Total times a cashier may print one bill (counts the first print). After this many the reprint button hides for cashiers. 0 = only the first print. Captains/Managers/Admins can always reprint.",
			},
			# Geofence feature. Master switch + company coordinates +
			# default radius. When enabled, the React POS asks for
			# browser geolocation on login and blocks users outside the
			# allowed radius (per-user override OR company coords,
			# depending on the URY User row's custom_use_company_location
			# flag). See CLAUDE.md "Fixes log" 2026-04-10.
			{
				"fieldname": "custom_geofence_section",
				"fieldtype": "Section Break",
				"insert_after": "custom_restrict_returns_to_captain",
				"label": "Geofence",
				"collapsible": 1,
			},
			{
				"fieldname": "custom_geofence_enabled",
				"fieldtype": "Check",
				"insert_after": "custom_geofence_section",
				"label": "Enable Geofence",
				"default": "0",
				"description": "Master switch. When off, no location check is performed on login and the React POS never requests geolocation permission.",
			},
			{
				"fieldname": "custom_company_latitude",
				"fieldtype": "Float",
				"insert_after": "custom_geofence_enabled",
				"label": "Company Latitude",
				"precision": "6",
				"depends_on": "eval:doc.custom_geofence_enabled",
				"description": "Use the Get Current Location button to capture this device's current GPS position.",
			},
			{
				"fieldname": "custom_company_longitude",
				"fieldtype": "Float",
				"insert_after": "custom_company_latitude",
				"label": "Company Longitude",
				"precision": "6",
				"depends_on": "eval:doc.custom_geofence_enabled",
			},
			{
				"fieldname": "custom_geofence_radius_meters",
				"fieldtype": "Int",
				"insert_after": "custom_company_longitude",
				"label": "Geofence Radius (m)",
				"default": "200",
				"non_negative": 1,
				"depends_on": "eval:doc.custom_geofence_enabled",
				"description": "Default allowed distance in meters. Per-user overrides live on the Branch's ExPOS Users table.",
			},
			# Table-merge unmerge-with-new-orders escape hatch. When the
			# cashier merges tables and then rings new orders on the
			# master, the default behaviour is to block the unmerge
			# (unmerging would strand those new orders on a non-existent
			# table). Flipping this check ON lets the cashier unmerge
			# anyway; the UI prompts them to assign each post-merge
			# order to a destination table. See CLAUDE.md "Fixes log"
			# 2026-04-11.
			{
				"fieldname": "custom_allow_unmerge_after_new_orders",
				"fieldtype": "Check",
				"insert_after": "custom_geofence_radius_meters",
				"label": "Allow Table Unmerge After New Orders",
				"default": "0",
				"description": "When checked, cashiers can unmerge tables even after new orders have been placed on the merged master. The unmerge UI asks them to assign each post-merge order to a destination table.",
			},
			# iHotel integration — when enabled, cashiers can charge a
			# POS order to a hotel guest's room instead of taking
			# cash/card. The charge is written as a Folio Charge row on
			# the matching open iHotel Profile; the POS Invoice itself
			# stays docstatus=0 forever (a "charged draft") so it
			# doesn't double-post at shift close. See CLAUDE.md
			# "Fixes log" 2026-04-12.
			{
				"fieldname": "custom_ihotel_section",
				"fieldtype": "Section Break",
				"insert_after": "custom_allow_unmerge_after_new_orders",
				"label": "iHotel Integration",
				"collapsible": 1,
			},
			{
				"fieldname": "custom_ihotel_enabled",
				"fieldtype": "Check",
				"insert_after": "custom_ihotel_section",
				"label": "Enable iHotel Integration",
				"default": "0",
				"description": "When checked, cashiers can charge orders to a hotel guest's room via the iHotel app.",
			},
			{
				"fieldname": "custom_ihotel_charge_type",
				"fieldtype": "Link",
				"insert_after": "custom_ihotel_enabled",
				"label": "iHotel Charge Type",
				"options": "Charge Type",
				"depends_on": "eval:doc.custom_ihotel_enabled",
				"mandatory_depends_on": "eval:doc.custom_ihotel_enabled",
				"description": "Charge Type used on the iHotel Profile's folio row when charging to room.",
			},
			# KOT naming series default (2026-04-16). This field was
			# shipped in custom_field.json years ago without a default,
			# which meant every new POS Profile silently broke KOT
			# creation until an admin set it manually. Ships via
			# setup.py too per the dual-source-of-truth rule so
			# existing sites pick up the default on next migrate.
			# A backfill patch populates the value for profiles that
			# still have a null/empty value.
			{
				"fieldname": "custom_kot_naming_series",
				"fieldtype": "Data",
				"insert_after": "custom_kot_settings",
				"label": "ExPOS KOT Naming Series",
				"default": "KOT-.YYYY.-.####",
				"description": "Frappe naming-series pattern for auto-generated KOT docs. Default produces KOT-2026-0001, KOT-2026-0002, etc.",
			},
			# Print configuration (2026-04-16 unified print round). Replaces
			# the legacy printer_settings child table + custom_table_order_printer
			# + custom_parcel_order_printer. The backend reads these first and
			# falls back to the legacy fields when empty so existing installs
			# keep working until their admin opens the POS Profile and saves.
			# See CLAUDE.md "Fixes log" 2026-04-16.
			{
				"fieldname": "custom_print_routing_section",
				"fieldtype": "Section Break",
				"insert_after": "custom_reprint_kot_format",
				"label": "Printers & Routing",
				"collapsible": 1,
				"description": "Unified print configuration. Replaces the legacy printer_settings and per-order-type printer fields.",
			},
			{
				"fieldname": "custom_print_mode",
				"fieldtype": "Select",
				"insert_after": "custom_print_routing_section",
				"label": "Print Mode",
				"options": "QZ Tray\nCUPS (Direct)\nDisabled",
				"default": "QZ Tray",
				"description": "QZ Tray (cloud-hosted Frappe default — prints via the browser). CUPS Direct (server-side, only for self-hosted). Disabled.",
			},
			{
				"fieldname": "custom_bill_printer",
				"fieldtype": "Link",
				"insert_after": "custom_print_mode",
				"label": "Bill Printer",
				"options": "URY Printer",
				"depends_on": "eval:doc.custom_print_mode != 'Disabled'",
				"mandatory_depends_on": "eval:doc.custom_print_mode != 'Disabled'",
				"description": "The default printer that prints the receipt/bill. Used when a terminal has no per-terminal printer below.",
			},
			{
				"fieldname": "custom_bill_printers",
				"fieldtype": "Table",
				"insert_after": "custom_bill_printer",
				"label": "Per-Terminal Bill Printers",
				"options": "URY Terminal Bill Printer",
				"depends_on": "eval:doc.custom_print_mode != 'Disabled'",
				"description": "Optional. Map each terminal to its own bill printer. When the printing terminal is listed here, its receipts print to that printer instead of the single Bill Printer above — so several terminals sharing this profile can each print to their own physical printer. Terminals not listed fall back to the Bill Printer above.",
			},
			{
				"fieldname": "custom_kitchen_kot_printer",
				"fieldtype": "Link",
				"insert_after": "custom_bill_printer",
				"label": "Kitchen KOT Printer",
				"options": "URY Printer",
				"depends_on": "eval:doc.custom_print_mode != 'Disabled' && doc.custom_kds_routing_mode != 'URY Production Unit'",
				"description": "The printer in the kitchen (food KOT target). Falls back to Bill when empty. Hidden in ExPOS Production Unit mode — routing is set on each ExPOS Production Unit's Printers table instead.",
			},
			{
				"fieldname": "custom_bar_kot_printer",
				"fieldtype": "Link",
				"insert_after": "custom_kitchen_kot_printer",
				"label": "Bar KOT Printer",
				"options": "URY Printer",
				"depends_on": "eval:doc.custom_print_mode != 'Disabled' && doc.custom_kds_routing_mode != 'URY Production Unit'",
				"description": "The printer at the bar (drinks KOT target). Falls back to Kitchen, then Bill. Hidden in ExPOS Production Unit mode.",
			},
			{
				"fieldname": "custom_parcel_kot_printer",
				"fieldtype": "Link",
				"insert_after": "custom_bar_kot_printer",
				"label": "Parcel KOT Printer",
				"options": "URY Printer",
				"depends_on": "eval:doc.custom_print_mode != 'Disabled' && doc.custom_kds_routing_mode != 'URY Production Unit'",
				"description": "The printer for parcel/takeaway KOTs. Falls back to Kitchen. Hidden in ExPOS Production Unit mode.",
			},
			{
				"fieldname": "custom_drinks_kot_route",
				"fieldtype": "Select",
				"insert_after": "custom_parcel_kot_printer",
				"label": "Drinks KOT Route",
				"options": "Bar\nKitchen\nBill",
				"default": "Bar",
				"depends_on": "eval:doc.custom_print_mode != 'Disabled' && doc.custom_kds_routing_mode != 'URY Production Unit'",
				"description": "Where drinks-department KOTs print. Drinks items are detected via ExPOS Menu Course's Department. Hidden in ExPOS Production Unit mode.",
			},
			{
				"fieldname": "custom_food_kot_route",
				"fieldtype": "Select",
				"insert_after": "custom_drinks_kot_route",
				"label": "Food KOT Route",
				"options": "Kitchen\nBar\nBill",
				"default": "Kitchen",
				"depends_on": "eval:doc.custom_print_mode != 'Disabled' && doc.custom_kds_routing_mode != 'URY Production Unit'",
				"description": "Where food-department KOTs print. Defaults to Kitchen. Hidden in ExPOS Production Unit mode.",
			},
			{
				"fieldname": "custom_takeaway_kot_route",
				"fieldtype": "Select",
				"insert_after": "custom_food_kot_route",
				"label": "Takeaway KOT Route",
				"options": "Parcel\nKitchen",
				"default": "Parcel",
				"depends_on": "eval:doc.custom_print_mode != 'Disabled' && doc.custom_kds_routing_mode != 'URY Production Unit'",
				"description": "Where parcel/takeaway KOTs print. Fallback to Kitchen if the Parcel printer is empty. Hidden in ExPOS Production Unit mode.",
			},
			{
				"fieldname": "custom_print_fallback_mode",
				"fieldtype": "Select",
				"insert_after": "custom_takeaway_kot_route",
				"label": "Print Fallback Mode",
				"options": "Fallback to Bill Printer\nFail Silently\nFail with Alert",
				"default": "Fallback to Bill Printer",
				"depends_on": "eval:doc.custom_print_mode != 'Disabled'",
				"description": "What happens when a KOT's target printer is offline.",
			},
			{
				"fieldname": "custom_auto_print_drinks_kot",
				"fieldtype": "Check",
				"insert_after": "custom_print_fallback_mode",
				"label": "Auto-print Drinks KOT on Order",
				"default": "0",
				"depends_on": "eval:doc.custom_print_mode != 'Disabled' && doc.custom_kds_routing_mode != 'URY Production Unit'",
				"description": "When off (default), Drinks KOTs are held until the cashier prints the bill at payment time. When on, drinks auto-print at order time like food. Hidden in ExPOS Production Unit mode.",
			},
			{
				"fieldname": "custom_kds_routing_mode",
				"fieldtype": "Select",
				"insert_after": "custom_auto_print_drinks_kot",
				"label": "KDS Routing Mode",
				"options": "Menu Course\nURY Production Unit",
				"default": "Menu Course",
				"depends_on": "eval:doc.custom_print_mode != 'Disabled'",
				"description": "Controls how URYMosaic groups KOTs into screens. Menu Course (default): one KOT per order, split by item course department; KDS URL is /URYMosaic/Food|Drinks|Other|All. ExPOS Production Unit: legacy multi-KOT-per-order flow split by Production Unit; KDS URL is /URYMosaic/<production-name>.",
			},
			{
				"fieldname": "custom_service_policy_time",
				"fieldtype": "Int",
				"insert_after": "custom_kds_routing_mode",
				"label": "Average Service Policy Time (minutes)",
				"default": "15",
				"non_negative": 1,
				"description": "The average time (in minutes) taken to serve a customer. Orders that pass this time are flagged as late: the KDS card turns red and the order shows up in the cashier's Late Orders notifications.",
			},
		],
		"URY Menu Course": [
			{
				"fieldname": "custom_department",
				"fieldtype": "Select",
				"insert_after": "custom_serving_priority",
				"label": "Department",
				"options": "Food\nDrinks\nOther",
				"default": "Food",
				"in_list_view": 1,
				"in_standard_filter": 1,
				"description": "Classifies this course for print routing. Drinks → Bar printer, Food → Kitchen printer, Other → Bill.",
			},
		],
  
		"POS Closing Entry": [
			{
				# Soft gate on who closes the day (2026-07-29). Stamped
				# server-side by submit_pos_closing_entry. Dual-sourced here
				# as well as in custom_field.json because fixtures are
				# install-only — without this, sites that already have URY
				# would never get the column and the write would silently
				# become a no-op. See CLAUDE.md "Gotchas".
				"fieldname": "custom_closed_by_non_captain",
				"fieldtype": "Check",
				"label": "Closed By Non-Captain",
				"insert_after": "user",
				"default": "0",
				"read_only": 1,
				"no_copy": 1,
				"print_hide": 1,
				"in_standard_filter": 1,
				"description": "Set automatically when the day was closed by someone without a captain/manager role. Closing is normally a captain's job, but it is deliberately NOT blocked for cashiers - with Daily POS Close enabled an unclosed night would block the next day's trading entirely. Filter on this to review who closed.",
				"translatable": 0,
			},
		],
		"POS Opening Entry": [
			{
				"fieldname": "restaurant_info",
				"fieldtype": "Section Break",
				"label": "Restaurant Info",
				"insert_after": "user",
			},
			{
				"fieldname": "restaurant",
				"fieldtype": "Link",
				"insert_after": "restaurant_info",
				"label": "Restaurant",
				"options": "URY Restaurant",
				"reqd": 1
			},
			{
				"fieldname": "column_break_e3dky",
				"fieldtype": "Column Break",
				"insert_after": "restaurant",
			},
			{
				"fieldname": "branch",
				"fieldtype": "Link",
				"insert_after": "column_break_e3dky",
				"label": "Branch",
				"options": "Branch",
				"reqd": 1
			},
			# Same dual-source-of-truth fix as POS Invoice.custom_terminal —
			# this entry exists in custom_field.json but pre-existing
			# installs need create_custom_fields to ensure the column.
			# See CLAUDE.md "Fixes log" 2026-04-09.
			{
				"fieldname": "custom_terminal",
				"fieldtype": "Link",
				"insert_after": "branch",
				"label": "Terminal",
				"options": "URY POS Terminal",
				"read_only": 1,
				"in_standard_filter": 1,
				"in_list_view": 1,
				"description": "Physical terminal (till) this opening entry belongs to.",
			},
		],

		"Price List": [
			{
				"fieldname": "restaurant_menu",
				"fieldtype": "Link",
				"options": "URY Menu",
				"label": "Restaurant Menu",
				"insert_after": "currency",
			}
		],
  
		"Branch": [
			# Label rebranded from "User" to "ExPOS Users" so the section
			# heading on the Branch form is unambiguous (Frappe already
			# has its own User DocType, so just "User" is confusing).
			# `create_custom_fields` updates the existing field on the
			# next migrate. See CLAUDE.md "Brand naming" + "Fixes log"
			# 2026-04-09.
			{
				"fieldname": "user",
				"fieldtype": "Table",
				"options": "URY User",
				"label": "ExPOS Users",
				"insert_after": "branch",
				"reqd": 1
			}
		],

		"Customer": [
			{
				"fieldname": "mobile_number",
				"fieldtype": "Data",
				"label": "Mobile Number",
				"insert_after": "customer_name",
				"translatable": 0,
				"reqd": 1
			},
		],

		"POS Invoice Item": [
			{
				"fieldname": "comment",
				"fieldtype": "Data",
				"label": "Comment",
				"insert_after": "description",
				"translatable": 0
			}
		],
     
    }
 
def delete_custom_fields(custom_fields):
    for doctype, fields in custom_fields.items():
        frappe.db.delete(
			"Custom Field",
			{
				"fieldname": ("in", [field["fieldname"] for field in fields]),
				"dt": doctype,
			},
		)
        
        frappe.clear_cache(doctype=doctype)
 
 
    
