"""Migrate existing POS Profile print config to the new unified
Printers & Routing fields (2026-04-16).

Two-stage migration:

**Stage 1 — create URY Printer records from legacy sources.**
URY's new `URY Printer` doctype replaces `Network Printer Settings`
as the link target for the POS Profile printer fields. For any
legacy `Network Printer Settings` doc referenced by a POS Profile
(via custom_table_order_printer / custom_parcel_order_printer, or
via the printer_settings child table), we create a matching URY
Printer record with the same name, description, server_ip, and
port. Idempotent — skips if a URY Printer with that name already
exists.

**Stage 2 — populate the new POS Profile fields from the legacy ones.**
For each POS Profile whose `custom_print_mode` is still unset:

  - `custom_print_mode` -> "QZ Tray" if `qz_print == 1`, else
    "CUPS (Direct)".
  - `custom_bill_printer` <- first row of `printer_settings` with
    `bill == 1`, else `custom_table_order_printer`.
  - `custom_kitchen_kot_printer` <- `custom_table_order_printer`.
  - `custom_parcel_kot_printer` <- `custom_parcel_order_printer`.
  - `custom_bar_kot_printer` -> stays empty (admin picks post-migrate).
  - Routes + fallback inherit their field defaults.

The values we write are URY Printer names (not Network Printer
Settings names) since the link target is now URY Printer. Stage 1
guarantees that every referenced legacy name has a matching URY
Printer record so the Link field validates cleanly.

Both stages are idempotent — the patch is safe to re-run.

Guarded with `frappe.db.has_column` so a missing column (column not
yet created via DocType sync) degrades to a no-op instead of
crashing the migrate.

See CLAUDE.md "Fixes log" 2026-04-16 (print revamp Round 1).
"""

import frappe


REQUIRED_COLUMNS = [
    "custom_print_mode",
    "custom_bill_printer",
    "custom_kitchen_kot_printer",
    "custom_parcel_kot_printer",
]


def _ensure_ury_printer(nps_name):
    """Create a URY Printer record mirroring a Network Printer
    Settings doc, if one doesn't already exist with the same name.

    Returns (name, created) where ``created`` is True if the record
    was inserted on this call, False if it already existed or the
    lookup failed. ``name`` is None if we couldn't produce a valid
    URY Printer reference (failed insert).
    """
    if not nps_name:
        return (None, False)
    if frappe.db.exists("URY Printer", nps_name):
        return (nps_name, False)
    try:
        nps = frappe.db.get_value(
            "Network Printer Settings",
            nps_name,
            ["server_ip", "port", "printer_name"],
            as_dict=True,
        )
    except Exception:
        nps = None
    # If Network Printer Settings doesn't have the record, we still
    # create a URY Printer with just the name — the POS Profile
    # referenced this string, so the admin clearly intended for it
    # to exist.
    doc = frappe.get_doc(
        {
            "doctype": "URY Printer",
            "printer_name": nps_name,
            "server_ip": (nps.server_ip if nps else None) or "localhost",
            "port": (nps.port if nps else None) or 631,
            "description": (
                f"Auto-created from Network Printer Settings on 2026-04-16 "
                f"print migration. Original CUPS printer name: "
                f"{(nps.printer_name if nps else nps_name)}"
            ),
        }
    )
    doc.flags.ignore_permissions = True
    try:
        doc.insert()
    except Exception as e:
        print(
            f"[URY] migrate_print_config: failed to auto-create URY Printer "
            f"'{nps_name}': {e}"
        )
        return (None, False)
    return (nps_name, True)


def execute():
    # Defensive: skip the whole patch if any of the new columns
    # didn't get created by DocType sync (shouldn't happen, but a
    # mis-ordered patches.txt should not blow up migrate).
    for col in REQUIRED_COLUMNS:
        if not frappe.db.has_column("POS Profile", col):
            print(
                f"[URY] migrate_print_config: column '{col}' missing on POS Profile — skipping."
            )
            return

    if not frappe.db.exists("DocType", "URY Printer"):
        print(
            "[URY] migrate_print_config: URY Printer doctype missing — "
            "skipping (run migrate again after DocType sync)."
        )
        return

    profiles = frappe.get_all(
        "POS Profile",
        fields=[
            "name",
            "qz_print",
            "custom_print_mode",
            "custom_table_order_printer",
            "custom_parcel_order_printer",
        ],
    )

    updated = 0
    skipped = 0
    printers_created = 0

    for p in profiles:
        # Skip profiles that already have the new config set.
        if p.custom_print_mode:
            skipped += 1
            continue

        new_mode = "QZ Tray" if (p.qz_print or 0) else "CUPS (Direct)"

        # Pick a bill printer from the legacy printer_settings child
        # table (Network Printer Settings name).
        bill_row = frappe.db.sql(
            """
            SELECT printer
            FROM `tabURY Printer Settings`
            WHERE parent = %s
              AND parenttype = 'POS Profile'
              AND (bill = 1 OR bill IS NULL)
            ORDER BY idx
            LIMIT 1
            """,
            (p.name,),
            as_dict=True,
        )
        legacy_bill = (
            (bill_row[0].printer if bill_row else None)
            or p.custom_table_order_printer
            or p.custom_parcel_order_printer
            or None
        )

        legacy_kitchen = p.custom_table_order_printer
        if not legacy_kitchen:
            kot_row = frappe.db.sql(
                """
                SELECT printer
                FROM `tabURY Printer Settings`
                WHERE parent = %s
                  AND parenttype = 'POS Profile'
                  AND custom_kot_print = 1
                ORDER BY idx
                LIMIT 1
                """,
                (p.name,),
                as_dict=True,
            )
            if kot_row:
                legacy_kitchen = kot_row[0].printer

        legacy_parcel = p.custom_parcel_order_printer

        # Stage 1: ensure URY Printer records exist for each legacy name.
        bill_printer_ury, bill_created = _ensure_ury_printer(legacy_bill)
        kitchen_printer_ury, kitchen_created = _ensure_ury_printer(legacy_kitchen)
        parcel_printer_ury, parcel_created = _ensure_ury_printer(legacy_parcel)
        printers_created += sum(
            1 for c in (bill_created, kitchen_created, parcel_created) if c
        )

        # Stage 2: write the new fields.
        frappe.db.set_value(
            "POS Profile",
            p.name,
            {
                "custom_print_mode": new_mode,
                "custom_bill_printer": bill_printer_ury,
                "custom_kitchen_kot_printer": kitchen_printer_ury,
                "custom_parcel_kot_printer": parcel_printer_ury,
                # Bar stays blank — admin decides post-migrate.
                # Routes + fallback inherit their default values.
            },
            update_modified=False,
        )
        updated += 1

    if updated or skipped or printers_created:
        frappe.db.commit()
        print(
            f"[URY] migrate_print_config: {updated} POS Profiles migrated, "
            f"{skipped} already had new config, "
            f"{printers_created} URY Printer records auto-created from "
            f"legacy Network Printer Settings references."
        )
