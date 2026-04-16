"""Backfill `POS Profile.custom_kot_naming_series` for existing
profiles that have a null/empty value.

This field was shipped in `custom_field.json` originally without a
default, which meant every new POS Profile silently broke KOT auto-
creation — the first order triggered a
`KOT Naming Series is mandatory for the auto creation of KOT.
Ensure it is configured in the POS Profile: <name>` error from
`ury_kot_generate.py:346` and no KOT record was created.

The fix (2026-04-16): add `"default": "KOT-.YYYY.-.####"` to both
`custom_field.json` and `setup.py`. Frappe's `create_custom_fields`
picks up the new default on the next migrate BUT only applies it
to newly-created rows — existing rows keep their empty value. This
patch walks every POS Profile with a null/empty
`custom_kot_naming_series` and stamps the default so the fix
retroactively applies to existing installs.

Idempotent: only touches profiles whose value is currently
null/empty. Safe to re-run. Guarded with `frappe.db.has_column`
so a mis-ordered `patches.txt` degrades to a no-op instead of
crashing migrate.

See CLAUDE.md "Fixes log" 2026-04-16 (print revamp Round 1 / QZ wiring).
"""

import frappe


DEFAULT_NAMING_SERIES = "KOT-.YYYY.-.####"


def execute():
    if not frappe.db.has_column("POS Profile", "custom_kot_naming_series"):
        print(
            "[URY] backfill_kot_naming_series: column missing on POS Profile — "
            "skipping (the custom field hasn't been created yet)."
        )
        return

    # Find POS Profiles with a null or empty naming series.
    profiles = frappe.db.sql(
        """
        SELECT name
        FROM `tabPOS Profile`
        WHERE custom_kot_naming_series IS NULL
           OR custom_kot_naming_series = ''
        """,
        as_dict=True,
    )

    updated = 0
    for p in profiles:
        frappe.db.set_value(
            "POS Profile",
            p.name,
            "custom_kot_naming_series",
            DEFAULT_NAMING_SERIES,
            update_modified=False,
        )
        updated += 1

    if updated:
        frappe.db.commit()
        print(
            f"[URY] backfill_kot_naming_series: {updated} POS Profile(s) "
            f"stamped with '{DEFAULT_NAMING_SERIES}'."
        )
    else:
        print(
            "[URY] backfill_kot_naming_series: no profiles needed updating."
        )
