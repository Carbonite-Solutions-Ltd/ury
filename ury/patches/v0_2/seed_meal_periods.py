"""Seed the default meal-period windows and retire the item-based child.

The report shipped item-based on 2026-08-23 and was changed to TIME-based
on 2026-08-24 at the client's request. This patch:

  1. Drops the now-unused `URY Meal Period Item` child doctype. It only
     ever existed for a day and no site put data in it, but leaving an
     orphan doctype behind makes the schema confusing.
  2. Seeds Breakfast / Lunch / Dinner with the client's hours, so the
     report works the moment it is deployed instead of dumping every bill
     into "Outside service hours" until someone configures it.

Idempotent: existing records are left exactly as they are, so a site that
has already tuned its windows is never overwritten.
"""

import frappe

DEFAULTS = (
	("Breakfast", "06:00:00", "11:30:00", 1),
	("Lunch", "11:31:00", "16:00:00", 2),
	("Dinner", "16:01:00", "22:00:00", 3),
)


def execute():
	if not frappe.db.exists("DocType", "URY Meal Period"):
		# Mis-ordered patches.txt, or the doctype hasn't synced yet.
		# Degrade to a noisy no-op rather than crashing the migration.
		print("[URY] URY Meal Period not present yet — skipping meal-period seed.")
		return

	# 1. retire the item-based child doctype
	if frappe.db.exists("DocType", "URY Meal Period Item"):
		try:
			frappe.delete_doc("DocType", "URY Meal Period Item", force=1, ignore_permissions=True)
			print("[URY] removed the obsolete URY Meal Period Item doctype.")
		except Exception:
			frappe.log_error(frappe.get_traceback(), "URY: could not drop URY Meal Period Item")

	# 2. seed the windows, without touching anything already configured
	created = 0
	# A site that has configured even one period is left alone entirely —
	# seeding into a half-built set could overlap windows they chose.
	if frappe.db.count("URY Meal Period"):
		print("[URY] meal periods already configured — nothing seeded.")
		return

	for name, start, end, order in DEFAULTS:
		doc = frappe.new_doc("URY Meal Period")
		doc.meal_period = name
		doc.start_time = start
		doc.end_time = end
		doc.display_order = order
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		created += 1

	frappe.db.commit()
	print(f"[URY] seeded {created} meal periods (Breakfast / Lunch / Dinner).")
