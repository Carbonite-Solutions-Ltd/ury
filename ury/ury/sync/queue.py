"""Queue operations for branch -> cloud sync.

The decisions live in `rules.py` (pure, unit-tested without a bench); this
module is the I/O around them. Nothing here talks to the network — that is
`transport.py`.

EVERYTHING in this module is a no-op while `URY Sync Settings.enabled` is
off, which is the default. Installing this app on an existing site must not
change its behaviour in any way until somebody deliberately switches sync
on.
"""

import frappe
from frappe.utils import now_datetime

from ury.ury.sync import rules

SETTINGS_DOCTYPE = "URY Sync Settings"
QUEUE_DOCTYPE = "URY Sync Queue"


def get_settings():
	"""The settings singleton, or None if sync isn't installed/ready.

	Tolerates the doctype not existing yet: this is called from a doc event,
	so it can run mid-migration on a site that hasn't synced the new
	doctypes. A missing doctype simply means "sync is off".
	"""
	try:
		return frappe.get_cached_doc(SETTINGS_DOCTYPE)
	except Exception:
		return None


def is_enabled():
	"""Master switch. False unless sync is installed, on, and configured."""
	settings = get_settings()
	if not settings or not settings.get("enabled"):
		return False
	# An enabled-but-unconfigured site would queue rows that can never be
	# delivered. Treat it as off until there is somewhere to send to.
	return bool(settings.get("remote_url"))


def enqueue(reference_doctype, reference_name, branch=None):
	"""Queue one document for delivery. Idempotent, and silent when off.

	Deliberately ONE row per document for its whole life. A submitted POS
	Invoice is effectively immutable, so a second row could only ever
	re-send the same content; and a duplicate row would mean the cloud
	receives the same sale twice. If a doctype ever needs genuine update
	replication, that wants an explicit `operation` field rather than a
	second row.
	"""
	if not is_enabled():
		return None

	existing = frappe.db.get_value(
		QUEUE_DOCTYPE,
		{"reference_doctype": reference_doctype, "reference_name": reference_name},
		"name",
	)
	if existing:
		return existing

	row = frappe.get_doc(
		{
			"doctype": QUEUE_DOCTYPE,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"branch": branch,
			"status": rules.QUEUED,
			"attempts": 0,
		}
	)
	row.insert(ignore_permissions=True)
	return row.name


def due_rows(limit):
	"""Rows a worker should try now, oldest first.

	`next_attempt_at IS NULL` is how a freshly queued row says "immediately",
	matching `rules.is_due`.
	"""
	return frappe.db.sql(
		"""
		SELECT name, reference_doctype, reference_name, attempts
		FROM `tabURY Sync Queue`
		WHERE status IN (%s, %s)
		  AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
		ORDER BY creation ASC
		LIMIT %s
		""",
		(rules.QUEUED, rules.RETRYING, now_datetime(), int(limit)),
		as_dict=True,
	)


def claim(row_name):
	"""Take ownership of a row. True only if WE took it.

	Uses `SELECT ... FOR UPDATE` to lock the row, check its status and
	update it inside one transaction. A concurrent claimer blocks at the
	SELECT until we commit, then reads `Sending` and correctly returns
	False. Same primitive Frappe itself uses for naming series
	(`frappe/model/naming.py`, `getseries`).

	⚠ Two earlier versions of this were both wrong, in opposite ways, and
	both are worth remembering:

	  1. Reading `frappe.db._cursor.rowcount` after a conditional UPDATE.
	     Correct in behaviour, but a PRIVATE attribute — read it as
	     always-zero and the queue stalls forever, always-nonzero and every
	     row double-sends.
	  2. A conditional UPDATE followed by reading the status back. This
	     looks safe and is not: if another worker already holds the row,
	     the UPDATE matches nothing but the read-back still sees `Sending`,
	     so the second claimer ALSO returns True — precisely the
	     double-send the claim exists to prevent. Caught by
	     `test_sync_integration`'s "claiming twice fails".

	Note this remains an optimisation, not the guarantee: the receiver is
	idempotent (keyed `<site>|<invoice>`), so even if two workers somehow
	both sent, head office books the sale once.
	"""
	locked = frappe.db.sql(
		"""
		SELECT status FROM `tabURY Sync Queue`
		WHERE name = %s
		FOR UPDATE
		""",
		(row_name,),
		as_dict=True,
	)
	if not locked or not rules.is_claimable(locked[0].status):
		return False

	stamp = now_datetime()
	frappe.db.sql(
		"""
		UPDATE `tabURY Sync Queue`
		SET status = %s, claimed_at = %s, modified = %s
		WHERE name = %s
		""",
		(rules.SENDING, stamp, stamp, row_name),
	)
	return True


def mark_synced(row_name):
	frappe.db.set_value(
		QUEUE_DOCTYPE,
		row_name,
		{
			"status": rules.SYNCED,
			"synced_at": now_datetime(),
			"last_error": None,
		},
		update_modified=False,
	)


def mark_failure(row_name, attempts, error, permanent=False):
	"""Record a failed send and schedule (or don't) the next attempt."""
	status, next_at = rules.decide_after_failure(
		attempts + 1, permanent=permanent, now=now_datetime()
	)
	frappe.db.set_value(
		QUEUE_DOCTYPE,
		row_name,
		{
			"status": status,
			"attempts": attempts + 1,
			"next_attempt_at": next_at,
			"last_error": (error or "")[:1000],
		},
		update_modified=False,
	)
	return status


def reclaim_stale(threshold_seconds=None):
	"""Return rows whose worker died back to Retrying.

	Nothing else will ever pick up a `Sending` row, so without this one
	crashed or restarted worker strands its claimed sales permanently.
	"""
	threshold = threshold_seconds or rules.STALE_SENDING_SECONDS
	rows = frappe.db.sql(
		"""
		SELECT name, attempts
		FROM `tabURY Sync Queue`
		WHERE status = %s
		  AND claimed_at IS NOT NULL
		  AND TIMESTAMPDIFF(SECOND, claimed_at, %s) >= %s
		""",
		(rules.SENDING, now_datetime(), threshold),
		as_dict=True,
	)
	for row in rows:
		mark_failure(
			row.name,
			row.attempts,
			"Worker stopped mid-send; row reclaimed by the sweeper.",
			permanent=False,
		)
	return len(rows)


def on_pos_invoice_submit(doc, method=None):
	"""doc_event: queue a completed sale for the cloud.

	Wrapped so a sync problem can NEVER block a sale. A cashier being unable
	to take payment because a reporting feature misbehaved would be a far
	worse failure than a sale arriving at head office late — and the
	sweeper's backfill catches anything this misses anyway.
	"""
	try:
		if doc.get("is_return"):
			# Returns are reflected by the return invoice itself, which is
			# also a submitted POS Invoice and gets queued on its own.
			pass
		enqueue("POS Invoice", doc.name, branch=doc.get("branch"))
	except Exception:
		frappe.log_error(
			title="URY sync: failed to queue a sale",
			message=f"POS Invoice {doc.get('name')}\n\n{frappe.get_traceback()}",
		)
