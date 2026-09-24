"""Cloud → branch replication of master data.

The mirror image of `queue`/`transport`, which carry finished sales UP. This
carries the records a branch needs in order to TRADE down: item groups, tax
templates, items, menus and customers.

Without it a branch server is a liability rather than an asset — every price
change, new dish or tax revision would have to be keyed into every branch by
hand, and the branches would drift apart within a week.

── The rule that keeps this safe ────────────────────────────────────────
**Every record type has exactly one authoritative writer.** Masters are
written at head office and flow down; transactions are written at the branch
and flow up. Never both directions for one doctype. A branch edit to a master
is overwritten on the next pull, and that is the intended behaviour, not a
bug — it is what stops two sites disagreeing about what a dish costs.

── Why tax templates are the point ──────────────────────────────────────
Browser-only offline was rejected because ERPNext resolves each line's
`item_tax_rate` server-side from Item Tax Templates walking the Item Group
tree. A branch server only computes the SAME tax as head office if those
templates are present and current. So `Item Tax Template`, `Tax Category` and
`Sales Taxes and Charges Template` are not incidental entries in the list
below — they are the reason the list exists.

── ⚠ Item Price and Price List are deliberately NOT replicated ──────────
They are REGENERATED on the branch: `URY Menu.on_update` calls
`make_price_list()`, which deletes every Item Price for the menu's price list
and re-inserts one per row. Replicating them as well would give those rows two
writers racing each other, and the loser would silently be whichever ran last.
Sync the menu; let the branch derive its own prices from it. This is the
subtlest decision in the module — do not "complete" the list by adding them.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from ury.ury.sync import queue, transport

MASTERS_VERSION = 1
STATE_DOCTYPE = "URY Master Sync State"

# The epoch used when a doctype has never been pulled. Any real `modified` is
# greater, so the first run takes everything.
EPOCH = "1900-01-01 00:00:00"

# How many rows per doctype per HTTP call, and how many calls per doctype per
# run. The page loop exists so a branch that has been offline for a week
# catches up in one run instead of trickling 200 rows every 15 minutes.
PAGE_SIZE = 200
MAX_PAGES = 25

# ⚠ ORDER IS LOAD-BEARING — dependencies first.
# An Item referencing an Item Group that has not arrived yet fails validation,
# and a URY Menu referencing an absent URY Menu Course does the same. Adding a
# doctype here means thinking about where it belongs, not appending it.
MASTER_DOCTYPES = [
	"Item Group",
	"Tax Category",
	"Item Tax Template",
	"Sales Taxes and Charges Template",
	"Item",
	"URY Menu Course",
	"URY Menu",
	"Customer Group",
	"Territory",
	"Customer",
]

# Stripped before a document is applied. `modified` is handled separately and
# for a specific reason — see `_apply_one`.
_VOLATILE_FIELDS = (
	"creation",
	"modified",
	"modified_by",
	"owner",
	"_user_tags",
	"_comments",
	"_assign",
	"_liked_by",
)


# ── Pure helpers (no network, no site) ──────────────────────────────────


def is_allowed(doctype):
	return doctype in MASTER_DOCTYPES


def ordered_doctypes(requested=None):
	"""Return the requested doctypes in dependency order, dropping anything
	not on the allowlist.

	Filtering through MASTER_DOCTYPES rather than sorting the request is what
	makes the order impossible to get wrong from the calling side.
	"""
	if not requested:
		return list(MASTER_DOCTYPES)
	wanted = set(requested)
	return [dt for dt in MASTER_DOCTYPES if dt in wanted]


def next_watermark(rows, current=None):
	"""Highest `modified` seen, or the current watermark if nothing moved.

	Rows are exported ordered by `modified` ascending, so the last one is the
	high-water mark — but max() is used rather than [-1] so a caller that
	reorders or filters cannot silently rewind the watermark and re-pull the
	same rows forever.
	"""
	stamps = [r.get("modified") for r in (rows or []) if r.get("modified")]
	if not stamps:
		return current
	highest = max(str(s) for s in stamps)
	if current and str(current) >= highest:
		return current
	return highest


def sanitise(doc_dict):
	"""Strip volatile bookkeeping, recursively through child rows.

	Child `name`s are dropped too, so child tables are rebuilt on apply rather
	than matched row by row. Masters are small and nothing references a menu
	line by name across sites, so a clean rebuild is simpler and cannot leave
	half-updated children behind.
	"""
	out = {}
	for key, value in (doc_dict or {}).items():
		if key in _VOLATILE_FIELDS:
			continue
		if isinstance(value, list):
			rows = []
			for row in value:
				if not isinstance(row, dict):
					continue
				child = {
					k: v
					for k, v in row.items()
					if k not in _VOLATILE_FIELDS and k != "name"
				}
				rows.append(child)
			out[key] = rows
		else:
			out[key] = value
	return out


# ── Cloud side ──────────────────────────────────────────────────────────


def _assert_is_cloud_site():
	"""A branch must not serve masters.

	Same shape as the receiver's guard, for the same reason: a misconfigured
	pair would otherwise replicate in a circle, and whichever site saved last
	would win — which is precisely the multi-master situation the design rules
	out.
	"""
	if queue.is_enabled():
		frappe.throw(
			_(
				"This site has outbound sync enabled, so it is a branch and cannot "
				"serve master data. Only the cloud site should."
			),
			title=_("Not A Master Source"),
		)


@frappe.whitelist()
def export_changes(since=None, limit=None):
	"""CLOUD side. Return allowlisted masters changed since the caller's
	watermarks.

	`since` is a {doctype: modified} map. Anything the caller asks for that is
	not on MASTER_DOCTYPES is ignored — a branch holding head-office API
	credentials must not be able to pull arbitrary doctypes with them.
	"""
	_assert_is_cloud_site()

	if isinstance(since, str):
		since = frappe.parse_json(since)
	since = since if isinstance(since, dict) else {}
	limit = max(1, min(int(limit or PAGE_SIZE), 500))

	payload = {}
	for doctype in MASTER_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			# The cloud may legitimately not have a doctype this branch knows
			# about (different app versions). Skip rather than fail the run.
			continue

		watermark = since.get(doctype) or EPOCH
		names = frappe.get_all(
			doctype,
			filters={"modified": (">", watermark)},
			order_by="modified asc",
			limit=limit,
			pluck="name",
		)

		rows = []
		for name in names:
			doc = frappe.get_doc(doctype, name).as_dict()
			row = sanitise(doc)
			# Carried separately from the applied fields: the branch needs it
			# to advance its watermark, but must NOT write it. See _apply_one.
			row["modified"] = str(doc.get("modified"))
			rows.append(row)

		payload[doctype] = rows

	return {
		"status": "ok",
		"masters_version": MASTERS_VERSION,
		"site": frappe.local.site,
		"doctypes": payload,
	}


# ── Branch side ─────────────────────────────────────────────────────────


def _state(doctype):
	name = frappe.db.exists(STATE_DOCTYPE, {"master_doctype": doctype})
	if name:
		return frappe.get_doc(STATE_DOCTYPE, name)
	doc = frappe.get_doc(
		{"doctype": STATE_DOCTYPE, "master_doctype": doctype, "last_modified": None}
	)
	doc.insert(ignore_permissions=True)
	return doc


def watermarks():
	"""{doctype: last pulled `modified`} for every allowlisted doctype."""
	rows = frappe.get_all(
		STATE_DOCTYPE, fields=["master_doctype", "last_modified"]
	)
	known = {r.master_doctype: str(r.last_modified) for r in rows if r.last_modified}
	return {dt: known.get(dt, EPOCH) for dt in MASTER_DOCTYPES}


def _apply_one(doctype, row):
	"""Insert or update one master, keeping the cloud's name.

	⚠ `modified` is removed before applying, and this is not cosmetic. Writing
	a foreign `modified` onto a document and then saving it makes Frappe
	believe the row changed underneath us and raise TimestampMismatchError
	("Document has been modified after you have opened it"). The branch keeps
	its own `modified`; the cloud's value lives only in the watermark.

	The branch's own hooks DO run. That is deliberate: a URY Menu arriving here
	should rebuild this branch's price list exactly as if an administrator had
	saved it locally. `flags.ury_master_sync` is set so a hook can opt out if
	one ever needs to.
	"""
	payload = dict(row)
	payload.pop("modified", None)
	name = payload.get("name")
	if not name:
		raise ValueError(f"{doctype} row has no name")

	payload["doctype"] = doctype

	if frappe.db.exists(doctype, name):
		doc = frappe.get_doc(doctype, name)
		doc.update(payload)
	else:
		doc = frappe.get_doc(payload)
		doc.name = name
		doc.flags.name_set = True

	doc.flags.ignore_permissions = True
	doc.flags.ury_master_sync = True
	doc.save(ignore_permissions=True)
	return doc.name


def apply_rows(doctype, rows):
	"""Apply a page of masters. Returns (applied, errors).

	Each row is isolated: one unimportable record must not abandon the rest of
	the page, or a single bad master would stall every branch indefinitely.
	"""
	applied, errors = 0, []
	for row in rows or []:
		savepoint = f"ury_master_{applied}"
		try:
			frappe.db.savepoint(savepoint)
			_apply_one(doctype, row)
			applied += 1
		except Exception as exc:
			frappe.db.rollback(save_point=savepoint)
			errors.append(f"{row.get('name')}: {exc}")
			frappe.log_error(
				title="URY masters: could not apply a record",
				message=f"{doctype} {row.get('name')}\n\n{frappe.get_traceback()}",
			)
	return applied, errors


def pull():
	"""BRANCH side. Pull every allowlisted master changed since last time.

	Scheduled, and safe to run by hand. Returns a per-doctype summary.

	Inert unless URY Sync Settings.enabled is on, the same master switch the
	outbound queue uses — a site that never turns sync on is never touched by
	any of this.
	"""
	if not queue.is_enabled():
		return {"status": "disabled"}

	settings = queue.get_settings()
	summary = {}

	for doctype in MASTER_DOCTYPES:
		state = _state(doctype)
		mark = str(state.last_modified) if state.last_modified else EPOCH
		total, errors = 0, []

		for _page in range(MAX_PAGES):
			try:
				response = transport.fetch_masters(
					settings, {doctype: mark}, PAGE_SIZE
				)
			except transport.RemoteMethodMissing as exc:
				# The cloud has no masters endpoint at all — an ExPOS version
				# gap, not a per-doctype problem. Every remaining doctype would
				# fail identically, so stop after ONE round trip rather than
				# ten. On a poor link that difference is the whole point.
				frappe.log_error(
					title="URY masters: remote does not support master sync",
					message=str(exc),
				)
				return {
					"status": "unsupported",
					"detail": str(exc),
					"summary": summary,
				}
			except Exception as exc:
				errors.append(str(exc))
				break

			rows = (response.get("doctypes") or {}).get(doctype) or []
			if not rows:
				break

			applied, page_errors = apply_rows(doctype, rows)
			total += applied
			errors.extend(page_errors)

			advanced = next_watermark(rows, mark)
			if advanced == mark:
				# Nothing moved the watermark forward. Stop rather than ask
				# for the same page again until MAX_PAGES — that would be a
				# tight loop against the cloud for no benefit.
				break
			mark = advanced
			frappe.db.commit()

			if len(rows) < PAGE_SIZE:
				break

		state.last_modified = mark if mark != EPOCH else None
		state.last_pulled_at = now_datetime()
		state.rows_pulled = (state.rows_pulled or 0) + total
		state.last_error = ("; ".join(errors))[:1000] if errors else None
		state.save(ignore_permissions=True)
		frappe.db.commit()

		summary[doctype] = {"applied": total, "errors": len(errors)}

	return {"status": "ok", "summary": summary}


def run_masters_pull():
	"""Readable wrapper for `bench --site <branch> execute
	ury.ury.sync.masters.run_masters_pull`."""
	result = pull()
	if result.get("status") == "disabled":
		print("\n  Sync is disabled on this site — nothing pulled.\n")
		return result
	if result.get("status") == "unsupported":
		print("\n=== ExPOS masters pull ===")
		print("  The cloud site does not support master sync.")
		print(f"  {result.get('detail')}")
		print("  → Deploy an ExPOS build containing ury/ury/sync/masters.py to")
		print("    the cloud site, then run bench --site <cloud> migrate.\n")
		return result

	print("\n=== ExPOS masters pull ===")
	for doctype, stats in (result.get("summary") or {}).items():
		flag = "  " if not stats["errors"] else " !"
		print(f"{flag} {doctype:34} applied {stats['applied']:>5}  errors {stats['errors']}")
	print()
	return result
