"""Build the wire payload for one sale.

`to_payload` is deliberately PURE — it takes plain dicts and returns a
plain dict, so the shape can be unit-tested without a site. `build` is the
thin I/O wrapper that reads the document and hands it over.

PAYLOAD_VERSION exists so the receiver can stay compatible with a branch
that has not been updated yet. A branch site may well be running an older
build than the cloud: it is a box in a restaurant, behind NAT, on a link
that barely works. Assume version skew rather than hoping against it.
"""

import json

import frappe

PAYLOAD_VERSION = 1

#: Header fields copied verbatim from the POS Invoice.
_HEADER_FIELDS = (
	"branch",
	"pos_profile",
	"posting_date",
	"posting_time",
	"customer",
	"customer_name",
	"order_type",
	"restaurant_table",
	"status",
	"is_return",
	"net_total",
	"total_taxes_and_charges",
	"discount_amount",
	"grand_total",
	"paid_amount",
)

_ITEM_FIELDS = (
	"item_code",
	"item_name",
	"course",
	"item_group",
	"qty",
	"stock_qty",
	"rate",
	"amount",
)


def to_payload(invoice, items, payments, source_site):
	"""Pure: shape a sale into the wire format.

	`invoice` / `items` / `payments` are plain dicts and lists of dicts.
	Missing keys are tolerated — an older or newer branch build may not
	carry every field, and a sale that arrives with a blank waiter is far
	better than one that does not arrive at all.
	"""
	name = invoice.get("name")
	header = {field: invoice.get(field) for field in _HEADER_FIELDS}

	header.update(
		{
			"payload_version": PAYLOAD_VERSION,
			"source_site": source_site,
			"invoice_name": name,
			"remote_key": remote_key(source_site, name),
			# Renamed on the way out: `owner` is a Frappe builtin and would
			# be overwritten on insert at the far end.
			"raised_by": invoice.get("owner"),
			"terminal": invoice.get("custom_terminal"),
			"waiter": invoice.get("custom_waiter"),
			"cashier": invoice.get("cashier"),
			"no_of_pax": _as_int(invoice.get("no_of_pax")),
			"on_account_amount": invoice.get("custom_on_account_amount") or 0,
		}
	)

	header["items"] = [
		{field: row.get(field) for field in _ITEM_FIELDS}
		| {"comment": row.get("comment")}
		for row in (items or [])
	]
	header["payments_json"] = json.dumps(
		[
			{
				"mode_of_payment": row.get("mode_of_payment"),
				"amount": row.get("amount"),
			}
			for row in (payments or [])
		],
		default=str,
	)
	return header


def remote_key(source_site, invoice_name):
	"""The mirror's primary key.

	Scoped by site so two branches cannot collide even if the per-branch
	invoice prefixes were never configured — and so re-delivering the same
	sale is a no-op rather than a duplicate.
	"""
	return f"{source_site}|{invoice_name}"


def _as_int(value):
	"""`no_of_pax` is a Data field on POS Invoice (an Int on Sales Invoice —
	a long-standing legacy mismatch), so it arrives as a string."""
	try:
		return int(float(value or 0))
	except (TypeError, ValueError):
		return 0


def build(reference_doctype, reference_name):
	"""Read the document and return its payload."""
	if reference_doctype != "POS Invoice":
		frappe.throw(f"URY sync cannot build a payload for {reference_doctype}")

	doc = frappe.get_doc(reference_doctype, reference_name)
	return to_payload(
		doc.as_dict(),
		[row.as_dict() for row in (doc.get("items") or [])],
		[row.as_dict() for row in (doc.get("payments") or [])],
		source_site=frappe.local.site,
	)
