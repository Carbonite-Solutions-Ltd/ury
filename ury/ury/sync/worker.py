"""Scheduled jobs that drain the sync queue.

Wired in `hooks.py` under `scheduler_events`. BOTH return immediately when
sync is disabled, which is the default — so these existing on a site costs
one cached settings read a minute and nothing else.

Mirrors the shape already specified for `gra_evat`'s queue
(docs/gra-evat/06-app-design.md §5.6): a frequent sender plus a slower
sweeper that repairs what the sender could not.
"""

import frappe

from ury.ury.sync import payload as payload_builder
from ury.ury.sync import queue, rules, transport


def process_queue():
	"""Every minute: send the rows that are due, oldest first."""
	if not queue.is_enabled():
		return

	settings = queue.get_settings()
	batch = queue.due_rows(settings.batch_size or 20)
	if not batch:
		return

	for row in batch:
		# Atomic: if another pass already took this row, skip it rather than
		# sending the same sale twice.
		if not queue.claim(row.name):
			continue
		frappe.db.commit()

		try:
			body = payload_builder.build(row.reference_doctype, row.reference_name)
			transport.push_sale(body, settings)
			queue.mark_synced(row.name)
			transport.record_outcome(settings)
		except transport.PermanentRejection as exc:
			queue.mark_failure(row.name, row.attempts, str(exc), permanent=True)
			transport.record_outcome(settings, error=exc)
			frappe.log_error(
				title="URY sync: sale rejected by remote",
				message=f"{row.reference_doctype} {row.reference_name}\n\n{exc}",
			)
		except Exception as exc:
			queue.mark_failure(row.name, row.attempts, str(exc), permanent=False)
			transport.record_outcome(settings, error=exc)
		finally:
			# Commit per row: a crash halfway through a batch must not undo
			# the rows that already went out.
			frappe.db.commit()


def sweep():
	"""Every 15 minutes: repair and report.

	Three jobs, in order of how badly each one bites:
	  1. Reclaim rows whose worker died — nothing else picks up `Sending`.
	  2. Queue submitted sales that have no row at all, which catches any
	     path that bypassed the doc event (a desk edit, an import, a hook
	     that was disabled when the sale was made). Without this, sync is
	     only as reliable as the hook.
	  3. Alert on rows that have been failing long enough to matter.
	"""
	if not queue.is_enabled():
		return

	reclaimed = queue.reclaim_stale()
	backfilled = backfill_missing()
	alerting = count_alerting()

	if reclaimed or backfilled or alerting:
		frappe.logger("ury.sync").info(
			f"sweep: reclaimed={reclaimed} backfilled={backfilled} alerting={alerting}"
		)

	if alerting:
		_raise_alert(alerting)


def backfill_missing(limit=200):
	"""Queue submitted POS Invoices that have no queue row.

	Deliberately bounded and only looks at sales created since sync was
	switched on — enabling sync on a site with years of history must not
	enqueue the entire back catalogue.
	"""
	settings = queue.get_settings()
	since = settings.get("creation")
	rows = frappe.db.sql(
		"""
		SELECT pi.name, pi.branch
		FROM `tabPOS Invoice` pi
		LEFT JOIN `tabURY Sync Queue` q
		       ON q.reference_doctype = 'POS Invoice'
		      AND q.reference_name = pi.name
		WHERE pi.docstatus = 1
		  AND pi.creation >= %s
		  AND q.name IS NULL
		ORDER BY pi.creation ASC
		LIMIT %s
		""",
		(since, int(limit)),
		as_dict=True,
	)
	for row in rows:
		queue.enqueue("POS Invoice", row.name, branch=row.branch)
	return len(rows)


def count_alerting():
	"""How many rows are worth telling someone about."""
	return frappe.db.count(
		"URY Sync Queue", {"status": rules.FAILED}
	) + frappe.db.count(
		"URY Sync Queue",
		{"status": rules.RETRYING, "attempts": [">=", rules.ALERT_AFTER_ATTEMPTS]},
	)


def _raise_alert(count):
	"""Log it, and notify the configured role if there is one.

	Best-effort: a failed notification must never break the sweeper, or one
	misconfigured email account would stop rows being reclaimed.
	"""
	message = (
		f"{count} sale(s) have not reached the cloud site. "
		"Check URY Sync Queue for rows in Failed, or Retrying with a high "
		"attempt count."
	)
	frappe.log_error(title="URY sync: sales not reaching the cloud", message=message)

	settings = queue.get_settings()
	role = settings.get("alert_role") if settings else None
	if not role:
		return
	try:
		recipients = frappe.get_all(
			"Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent"
		)
		for user in set(recipients):
			frappe.publish_realtime(
				"ury_sync_alert", {"message": message}, user=user
			)
	except Exception:
		frappe.log_error(title="URY sync: alert delivery failed")
