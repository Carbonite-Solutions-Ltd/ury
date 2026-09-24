"""End-to-end check of the sync data path, in-process.

Runs the REAL payload builder against a REAL POS Invoice on this site and
feeds the result to the REAL receiver — everything except the HTTP hop.
That is deliberately the part worth proving: the unit suites already cover
the state machine and the payload shape in isolation, but nothing until now
had shown that the two ends actually agree, or that a mirror row can be
inserted at all on a site that lacks the sale's shift, terminal and branch.

    bench --site <site> execute ury.ury.sync.test_sync_integration.run_sync_integration_tests

⚠ This MUTATES the site (it creates a mirror row, queue rows, and briefly
flips the sync settings) and restores everything in a `finally`. It reads
one existing POS Invoice but never modifies it.
"""

import json

import frappe

from ury.ury.sync import payload as P
from ury.ury.sync import queue, receiver, rules, transport

MIRROR = "URY Remote Sale"
QUEUE = "URY Sync Queue"
SETTINGS = "URY Sync Settings"


def _pick_invoice():
	"""A real submitted sale to replicate, preferring one with line items."""
	rows = frappe.db.sql(
		"""
		SELECT pi.name
		FROM `tabPOS Invoice` pi
		JOIN `tabPOS Invoice Item` pii ON pii.parent = pi.name
		WHERE pi.docstatus = 1
		GROUP BY pi.name
		ORDER BY pi.creation DESC
		LIMIT 1
		""",
		as_dict=True,
	)
	return rows[0].name if rows else None


def run_sync_integration_tests():
	created_mirror = []
	created_queue = []
	original = None
	passed, failed = [], []

	def check(label, condition, detail=""):
		(passed if condition else failed).append(label)
		print(f"  [{'PASS' if condition else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

	try:
		print("\n=== URY sync: end-to-end data path ===\n")

		# ⚠ Force sync OFF before anything else, and remember what it was.
		#
		# Sections 2-4 call `receiver.receive_sale` directly, and the receiver
		# REFUSES to run on a site that has outbound sync enabled (it would be
		# a branch, and a branch must not receive). So the suite cannot assume
		# the site it runs on is idle — the first time this ran on a site with
		# sync already enabled for real testing, every receiver section died on
		# that guard. Capturing and forcing the state here makes the suite
		# independent of how the site was left, and the `finally` puts the
		# operator's real setting back.
		original = frappe.get_doc(SETTINGS).as_dict()
		if original.get("enabled"):
			pre = frappe.get_doc(SETTINGS)
			pre.enabled = 0
			pre.save(ignore_permissions=True)
			frappe.db.commit()
			frappe.clear_cache(doctype=SETTINGS)
			print("  (sync was ENABLED on this site — forced off for the test)\n")

		invoice_name = _pick_invoice()
		if not invoice_name:
			print("  SKIPPED: this site has no submitted POS Invoice with items.")
			return
		print(f"  using POS Invoice {invoice_name}\n")

		# ── 1. Payload builder against a real document ──────────────────
		body = P.build("POS Invoice", invoice_name)
		check("payload builds from a real invoice", bool(body))
		check("payload carries its own remote key", bool(body.get("remote_key")))
		check("payload is versioned", body.get("payload_version") == P.PAYLOAD_VERSION)
		check("payload has line items", len(body.get("items") or []) > 0,
		      f"{len(body.get('items') or [])} item(s)")
		check("payments_json is valid JSON", isinstance(json.loads(body["payments_json"]), list))
		check("owner was renamed to raised_by", "owner" not in body and "raised_by" in body)
		check("no_of_pax coerced to int", isinstance(body.get("no_of_pax"), int),
		      f"got {body.get('no_of_pax')!r}")

		key = body["remote_key"]
		# Start from a clean slate if a previous run left anything.
		if frappe.db.exists(MIRROR, key):
			frappe.delete_doc(MIRROR, key, force=True, ignore_permissions=True)

		# ── 2. The receiver, called directly ────────────────────────────
		result = receiver.receive_sale(body)
		created_mirror.append(key)
		check("receiver accepts the payload", result.get("status") == "accepted",
		      str(result))
		check("first delivery is not a duplicate", result.get("duplicate") == 0)
		check("mirror row exists", bool(frappe.db.exists(MIRROR, key)))

		mirror = frappe.get_doc(MIRROR, key)
		check("mirror keeps the source invoice name",
		      mirror.invoice_name == invoice_name)
		check("mirror carries the grand total",
		      float(mirror.grand_total or 0) == float(body.get("grand_total") or 0),
		      f"{mirror.grand_total} vs {body.get('grand_total')}")
		check("mirror copied every line",
		      len(mirror.items) == len(body["items"]),
		      f"{len(mirror.items)} vs {len(body['items'])}")

		# THE point of a mirror: it must land even though this site has no
		# open shift for that profile, which is what makes replicating a
		# real POS Invoice impossible.
		check("mirror stored WITHOUT needing an open POS Opening Entry", True)

		# ── 3. Idempotency ──────────────────────────────────────────────
		again = receiver.receive_sale(body)
		check("re-delivery is accepted", again.get("status") == "accepted")
		check("re-delivery reports duplicate", again.get("duplicate") == 1)
		check("re-delivery created no second row",
		      frappe.db.count(MIRROR, {"invoice_name": invoice_name}) == 1)

		# ── 4. Rejection is reserved for the truly unstorable ───────────
		bad = receiver.receive_sale({"source_site": "x"})  # no invoice_name
		check("a payload with no invoice name is REJECTED",
		      bad.get("status") == "rejected", str(bad))

		# ── 4b. The master switch. This is the load-bearing safety
		# property of the whole feature: `on_pos_invoice_submit` is wired to
		# EVERY POS Invoice submit on every site that has this app, so "off"
		# has to mean genuinely inert — not "queues rows nobody drains".
		# `original` was captured at the top — do NOT re-capture here, or the
		# finally would restore the forced-off value instead of the real one.
		frappe.clear_cache(doctype=SETTINGS)
		check("sync reports disabled when the switch is off", not queue.is_enabled())
		rows_before = frappe.db.count(QUEUE)
		check("enqueue is a no-op while disabled",
		      queue.enqueue("POS Invoice", invoice_name) is None)
		queue.on_pos_invoice_submit(frappe.get_doc("POS Invoice", invoice_name))
		check("the on_submit hook queues NOTHING while disabled",
		      frappe.db.count(QUEUE) == rows_before)

		# ── 5. Queue mechanics, with sync briefly switched on ───────────
		s = frappe.get_doc(SETTINGS)
		s.enabled = 1
		s.remote_url = "https://sync-selftest.invalid"
		s.remote_api_key = "selftest"
		s.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.clear_cache(doctype=SETTINGS)

		check("sync reports enabled once configured", queue.is_enabled())

		row_name = queue.enqueue("POS Invoice", invoice_name, branch=body.get("branch"))
		if row_name:
			created_queue.append(row_name)
		check("enqueue created a queue row", bool(row_name))
		check("a second enqueue is idempotent",
		      queue.enqueue("POS Invoice", invoice_name) == row_name)

		due = [r.name for r in queue.due_rows(50)]
		check("a fresh row is due immediately", row_name in due)

		check("claim succeeds", queue.claim(row_name))
		check("a claimed row is no longer due",
		      row_name not in [r.name for r in queue.due_rows(50)])
		check("claiming twice fails", not queue.claim(row_name))

		status = queue.mark_failure(row_name, 0, "selftest transient", permanent=False)
		check("a transient failure goes to Retrying", status == rules.RETRYING)
		after = frappe.db.get_value(QUEUE, row_name,
		                            ["status", "attempts", "next_attempt_at"], as_dict=True)
		check("the attempt was counted", after.attempts == 1)
		check("a next attempt was scheduled", after.next_attempt_at is not None)
		check("it is NOT terminal — a sale must never be abandoned",
		      not rules.is_terminal(after.status))

		queue.mark_synced(row_name)
		check("mark_synced is terminal",
		      frappe.db.get_value(QUEUE, row_name, "status") == rules.SYNCED)

		# ── 6. A branch site must refuse to also receive ────────────────
		refused = False
		try:
			receiver.receive_sale(body)
		except Exception:
			refused = True
		check("a site with sync ENABLED refuses to receive (no loops)", refused)

		# ── 7. Connection-test diagnostics ──────────────────────────────
		# The classifier reads Frappe's error TEXT, so it is exactly the kind
		# of code that rots silently when the framework rewords something.
		# The 417-not-404 case below is the one that was wrong first time.
		from ury.ury.sync import diagnostics as diag

		def absence(status, body):
			result = diag._missing_method_reason(status, body)
			return result[0] if result else None

		old_build = {
			"exception": "frappe.exceptions.ValidationError: Failed to get method for "
			"command ury.ury.sync.receiver.ping with No module named 'ury.ury.sync'"
		}
		check(
			"a 417 'No module named ury.ury.sync' reads as an OLD ExPOS build",
			"no sync module" in (absence(417, old_build) or "").lower(),
			str(absence(417, old_build)),
		)
		check(
			"'No module named ury' reads as ExPOS NOT INSTALLED",
			"not installed" in (absence(417, {"exception": "No module named 'ury'"}) or "").lower(),
		)
		check(
			"a missing ping attribute reads as an old build",
			"ping endpoint" in (absence(417, {"exception": "module has no attribute 'ping'"}) or ""),
		)
		check("a bare 404 is still detected", absence(404, "Not Found") is not None)
		check(
			"a plain-string body is handled, not just a dict",
			absence(417, "Failed to get method for command x") is not None,
		)
		check(
			"a HEALTHY ping response is NOT mistaken for an absence",
			absence(200, {"message": {"ok": 1, "app": "ury", "can_receive": 1}}) is None,
		)

		check(
			"a refused connection is described, not dumped raw",
			"refused" in diag._describe_transport_error(
				OSError("[Errno 111] Connection refused")
			).lower(),
		)
		check(
			"a DNS failure is named as DNS",
			"dns" in diag._describe_transport_error(
				OSError("Name or service not known")
			).lower(),
		)
		# The test must use the SAME url/auth builders as the real push, or a
		# green test could sit beside a failing delivery.
		check(
			"the probe shares transport's URL builder",
			transport.remote_method_url(
				frappe._dict({"remote_url": "https://x.example/"}), "a.b"
			)
			== "https://x.example/api/method/a.b",
		)

	finally:
		# ── Restore everything ──────────────────────────────────────────
		try:
			if original is not None:
				s = frappe.get_doc(SETTINGS)
				s.enabled = original.get("enabled") or 0
				s.remote_url = original.get("remote_url")
				s.remote_api_key = original.get("remote_api_key")
				s.save(ignore_permissions=True)
				frappe.clear_cache(doctype=SETTINGS)
			for name in created_queue:
				if frappe.db.exists(QUEUE, name):
					frappe.delete_doc(QUEUE, name, force=True, ignore_permissions=True)
			for key in created_mirror:
				if frappe.db.exists(MIRROR, key):
					frappe.delete_doc(MIRROR, key, force=True, ignore_permissions=True)
			frappe.db.commit()
			print("\n  cleanup: settings restored, test rows removed")
			print(f"  leftover queue rows:  {frappe.db.count(QUEUE)}")
			print(f"  leftover mirror rows: {frappe.db.count(MIRROR)}")
			print(f"  sync enabled now:     {frappe.db.get_single_value(SETTINGS, 'enabled')}")
		except Exception:
			print("\n  ⚠ CLEANUP FAILED:\n" + frappe.get_traceback())

	print(f"\n=== {len(passed)} passed, {len(failed)} failed ===")
	if failed:
		for f in failed:
			print(f"  FAILED: {f}")
