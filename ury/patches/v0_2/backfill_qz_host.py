"""Backfill `POS Profile.qz_host` to 'localhost' for existing
profiles that have a null/empty value.

The `qz_host` custom field was shipped years ago without a default,
which meant admins had to manually type 'localhost' on every profile
— and most didn't. The React POS's `printOrder` then threw
"QZ host is not set on this POS Profile" when the cashier clicked
Print Invoice because the field was null.

The 2026-04-16 fix added `"default": "localhost"` to both
`custom_field.json` and `setup.py`, but Frappe's `create_custom_fields`
only applies defaults on FIELD creation — existing rows with a
null value keep the null. This patch walks every POS Profile with
a null/empty `qz_host` and stamps 'localhost'.

Idempotent: only touches null/empty values. Safe to re-run.

See CLAUDE.md "Fixes log" 2026-04-16 (print revamp Round 1).
"""

import frappe


def execute():
    if not frappe.db.has_column("POS Profile", "qz_host"):
        print(
            "[URY] backfill_qz_host: qz_host column missing on POS Profile — "
            "skipping."
        )
        return

    profiles = frappe.db.sql(
        """
        SELECT name
        FROM `tabPOS Profile`
        WHERE qz_host IS NULL OR qz_host = ''
        """,
        as_dict=True,
    )

    updated = 0
    for p in profiles:
        frappe.db.set_value(
            "POS Profile",
            p.name,
            "qz_host",
            "localhost",
            update_modified=False,
        )
        updated += 1

    if updated:
        frappe.db.commit()
        print(
            f"[URY] backfill_qz_host: {updated} POS Profile(s) stamped "
            f"with qz_host='localhost'."
        )
    else:
        print("[URY] backfill_qz_host: no profiles needed updating.")
