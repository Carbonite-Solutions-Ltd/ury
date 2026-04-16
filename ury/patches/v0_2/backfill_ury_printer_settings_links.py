"""Ensure every existing `URY Printer Settings` child row has a
matching `URY Printer` record so the child table's Link field
validates cleanly after we flipped its `options` from
`Network Printer Settings` to `URY Printer` (2026-04-16 Round 1B —
URY Production Unit printer wiring).

Background:
  - The child doctype `URY Printer Settings` is used as a Table on
    three parents: POS Profile, URY Production Unit, and URY Room.
  - Its `printer` field used to Link to `Network Printer Settings`.
  - We repointed it at `URY Printer` so admins can pick from the
    same pool as the unified POS Profile printer fields and avoid
    the pycups catch-22 on cloud-hosted deployments.
  - Existing rows reference legacy `Network Printer Settings` names;
    those need matching `URY Printer` records or the form fails to
    validate.

What this patch does:
  For every distinct (non-empty) value in the `printer` column of
  `tabURY Printer Settings`, ensure a `URY Printer` record exists
  with that name. If the legacy `Network Printer Settings` record
  exists with the same name, copy its `server_ip` / `port` /
  `printer_name` into the new URY Printer. Otherwise create a bare
  record with sensible defaults (localhost / 631 / the name itself
  as the CUPS printer name).

Idempotent — skips rows that already have a matching URY Printer.
Guarded with `frappe.db.has_column("tabURY Printer Settings", "printer")`
and `frappe.db.exists("DocType", "URY Printer")` so a mis-ordered
patches.txt degrades to a no-op instead of crashing migrate.

See CLAUDE.md "Fixes log" 2026-04-16 (print revamp Round 1 / Phase D
URY Production Unit printer wiring).
"""

import frappe


def _ensure_ury_printer(legacy_name):
    """Idempotent URY Printer creation. Same contract as the v0_2
    migrate_print_config helper — if a URY Printer with that name
    already exists, return (name, False). Otherwise try to clone
    from Network Printer Settings or create a bare record.
    """
    if not legacy_name:
        return (None, False)
    if frappe.db.exists("URY Printer", legacy_name):
        return (legacy_name, False)

    nps = None
    try:
        if frappe.db.exists("Network Printer Settings", legacy_name):
            nps = frappe.db.get_value(
                "Network Printer Settings",
                legacy_name,
                ["server_ip", "port", "printer_name"],
                as_dict=True,
            )
    except Exception:
        nps = None

    doc = frappe.get_doc(
        {
            "doctype": "URY Printer",
            "printer_name": legacy_name,
            "server_ip": (nps.server_ip if nps else None) or "localhost",
            "port": (nps.port if nps else None) or 631,
            "description": (
                "Auto-created during URY Printer Settings backfill "
                "(2026-04-16 Phase D). Original reference: "
                f"{(nps.printer_name if nps else legacy_name)}"
            ),
        }
    )
    doc.flags.ignore_permissions = True
    try:
        doc.insert()
    except Exception as e:
        print(
            f"[URY] backfill_ury_printer_settings_links: failed to "
            f"auto-create URY Printer '{legacy_name}': {e}"
        )
        return (None, False)
    return (legacy_name, True)


def execute():
    if not frappe.db.exists("DocType", "URY Printer"):
        print(
            "[URY] backfill_ury_printer_settings_links: URY Printer "
            "doctype missing — skipping."
        )
        return
    if not frappe.db.has_column("URY Printer Settings", "printer"):
        print(
            "[URY] backfill_ury_printer_settings_links: "
            "`URY Printer Settings.printer` column missing — skipping."
        )
        return

    rows = frappe.db.sql(
        """
        SELECT DISTINCT printer
        FROM `tabURY Printer Settings`
        WHERE printer IS NOT NULL AND printer != ''
        """,
        as_dict=True,
    )

    created = 0
    already = 0
    for row in rows:
        _, was_created = _ensure_ury_printer(row.printer)
        if was_created:
            created += 1
        else:
            already += 1

    if created or already:
        frappe.db.commit()
        print(
            f"[URY] backfill_ury_printer_settings_links: "
            f"{created} URY Printer records auto-created, "
            f"{already} already existed (or had no legacy NPS match)."
        )
