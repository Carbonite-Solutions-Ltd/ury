"""Cloud-side endpoint that accepts a sale from a branch site.

Runs on the CLOUD site, called by each branch's `transport.push_sale`.

Two things it must never do: fail on state this site does not have (the
branch's terminal, shift or even branch record may not exist here), and
create a duplicate when a branch re-sends a sale it already delivered.
Both are handled by writing into the hook-free `URY Remote Sale` mirror,
keyed on `<source site>|<invoice name>`.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from ury.ury.sync import payload as payload_builder

MIRROR_DOCTYPE = "URY Remote Sale"


@frappe.whitelist()
def receive_sale(payload):
	"""Accept one sale. Idempotent.

	Returns `{"status": "accepted", ...}` or `{"status": "rejected", ...}`.

	The distinction is load-bearing: `transport.classify_failure` treats an
	explicit rejection as PERMANENT and stops retrying, and treats
	everything else as transient and retries forever. So this must only
	reject a payload that genuinely cannot ever be stored — never a
	transient condition on this side, or the branch will abandon a real
	sale.
	"""
	_assert_not_a_branch_site()

	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	if not isinstance(payload, dict):
		return _reject("Payload is not an object")

	key = payload.get("remote_key")
	invoice_name = payload.get("invoice_name")
	source_site = payload.get("source_site")
	if not invoice_name or not source_site:
		return _reject("Payload is missing invoice_name or source_site")
	if not key:
		key = payload_builder.remote_key(source_site, invoice_name)

	version = frappe.utils.cint(payload.get("payload_version") or 1)
	if version > payload_builder.PAYLOAD_VERSION:
		# The branch is NEWER than this site. Refusing would strand its
		# sales, so accept and record what we can — the fields we do not
		# understand are simply ignored.
		frappe.log_error(
			title="URY sync: branch is newer than cloud",
			message=(
				f"{source_site} sent payload version {version}; this site "
				f"understands {payload_builder.PAYLOAD_VERSION}. Stored anyway. "
				"Update the cloud site."
			),
		)

	existing = frappe.db.exists(MIRROR_DOCTYPE, key)
	if existing:
		return {
			"status": "accepted",
			"remote_key": key,
			"duplicate": 1,
		}

	try:
		doc = frappe.get_doc(_to_document(payload, key))
		doc.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		# Two deliveries raced. Idempotent by definition.
		return {"status": "accepted", "remote_key": key, "duplicate": 1}
	except Exception as exc:
		# Anything else is treated as TRANSIENT (we raise rather than
		# reject) so the branch keeps the sale and tries again. Rejecting
		# here would lose it permanently.
		frappe.log_error(
			title="URY sync: failed to store remote sale",
			message=f"{key}\n\n{frappe.get_traceback()}",
		)
		frappe.throw(_("Could not store sale: {0}").format(exc))

	return {"status": "accepted", "remote_key": key, "duplicate": 0}


@frappe.whitelist()
def ping():
	"""Answer "is this a usable cloud site for ExPOS sync?"

	Called by a branch's connection test, never by the delivery path.

	⚠ This deliberately REPORTS problems instead of throwing them. An
	earlier instinct was to reuse `_assert_not_a_branch_site()` here, which
	would have made a misconfigured remote look identical to an unreachable
	one — the test would say "something is wrong" where it could have said
	"that site is itself a branch and will refuse your sales." Diagnosing is
	the entire job of this endpoint, so every check returns a field.

	Reaching this at all already proves four things the caller cannot
	otherwise distinguish: the site is up, the credentials are valid, ExPOS
	is installed, and this app is new enough to contain the sync module.
	"""
	mirror_ready = bool(frappe.db.exists("DocType", MIRROR_DOCTYPE))

	sync_enabled = 0
	try:
		settings = frappe.get_cached_doc("URY Sync Settings")
		sync_enabled = 1 if settings.get("enabled") else 0
	except Exception:
		# No settings doctype yet (ExPOS installed but not migrated). Not an
		# error here — `mirror_ready` is what the caller acts on.
		pass

	return {
		"ok": 1,
		"app": "ury",
		"site": frappe.local.site,
		"payload_version": payload_builder.PAYLOAD_VERSION,
		"mirror_doctype_ready": int(mirror_ready),
		"sync_enabled": sync_enabled,
		# The one field a branch actually needs: may I send you sales?
		"can_receive": int(mirror_ready and not sync_enabled),
	}


def _assert_not_a_branch_site():
	"""A site that pushes must not also receive.

	Otherwise a misconfigured pair would bounce sales back and forth. The
	settings doctype already refuses a remote URL pointing at itself; this
	is the same guard from the other end.
	"""
	try:
		settings = frappe.get_cached_doc("URY Sync Settings")
	except Exception:
		return
	if settings.get("enabled"):
		frappe.throw(
			_(
				"This site has outbound sync enabled, so it is a branch site and "
				"cannot also receive sales. Only the cloud site should receive."
			),
			title=_("Not A Receiving Site"),
		)


def _to_document(payload, key):
	"""Map the wire payload onto the mirror doctype."""
	doc = {
		"doctype": MIRROR_DOCTYPE,
		"remote_key": key,
		"received_at": now_datetime(),
	}
	for field in (
		"invoice_name", "source_site", "branch", "pos_profile", "terminal",
		"status", "is_return", "posting_date", "posting_time", "payload_version",
		"customer", "customer_name", "order_type", "restaurant_table",
		"waiter", "cashier", "raised_by", "no_of_pax",
		"net_total", "total_taxes_and_charges", "discount_amount",
		"grand_total", "paid_amount", "on_account_amount", "payments_json",
	):
		if field in payload:
			doc[field] = payload.get(field)

	doc["items"] = [
		{
			"doctype": "URY Remote Sale Item",
			"item_code": row.get("item_code"),
			"item_name": row.get("item_name"),
			"course": row.get("course"),
			"item_group": row.get("item_group"),
			"qty": row.get("qty"),
			"stock_qty": row.get("stock_qty"),
			"rate": row.get("rate"),
			"amount": row.get("amount"),
			"comment": row.get("comment"),
		}
		for row in (payload.get("items") or [])
	]
	return doc


def _reject(reason):
	"""A payload that can never be stored, however many times it is sent."""
	frappe.log_error(title="URY sync: payload rejected", message=reason)
	return {"status": "rejected", "reason": reason}
