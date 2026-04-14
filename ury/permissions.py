"""URY role-permission baseline.

The React POS calls a mix of whitelisted methods (which run as the
session user and check perms on the docs they touch) and direct
``frappe.client.get`` / ``createDoc`` / ``updateDoc`` calls. Either way,
the session user needs the right DocPerm row on the relevant doctype
or every action 403s.

URY's two operational roles — ``URY Cashier`` and ``URY Captain`` —
are URY-specific and don't get permissions on standard ERPNext doctypes
(POS Profile, POS Invoice, Customer, Item, etc.) by default. Sites that
also gave their cashiers a generic role like "Sales User" worked by
accident; sites that have a clean role list (just URY Cashier or URY
Captain) hit a wall on the first POS Profile read.

This module is the canonical baseline: a list of (role, doctype, perms)
tuples and a setup function that idempotently creates ``Custom DocPerm``
rows for any combinations that don't already exist. Wired into both
``after_install`` and ``after_migrate`` via [ury/install.py](ury/install.py),
so existing sites get caught up on every ``bench migrate``.

Idempotency rules:
- If a Custom DocPerm or built-in DocPerm already exists for a given
  (doctype, role, permlevel=0), this function leaves it alone — even
  if its values differ from what we'd insert. That's intentional so
  admins who customised perms (e.g. "URY Cashier can't cancel POS
  Invoices") aren't fighting the migrate.
- New (doctype, role) combinations get a fresh Custom DocPerm row with
  the values defined here.

See CLAUDE.md "Fixes log" 2026-04-09 ("URY Captain hit a 403 on POS
Profile") for the bug that triggered this module.
"""

import frappe
from frappe import _

# ───────────────────────────────────────────────────────────────────
# Permission templates
# ───────────────────────────────────────────────────────────────────

# Read-only doctypes the POS reads but never writes through the SDK.
# Whitelisted backend methods that touch these still need read perm at
# the doc-fetch step inside the method.
READ_ONLY_DOCTYPES = [
    "POS Profile",
    "POS Settings",
    "URY Restaurant",
    "URY Menu",
    "URY Menu Item",
    "URY Menu Course",
    "URY Table",
    "URY Room",
    "URY POS Terminal",
    "Branch",
    "Mode of Payment",
    "Currency",
    "Item",
    "Item Price",
    "Price List",
    "Sales Taxes and Charges Template",
    "Company",
    "Customer Group",
    "Territory",
    # Shift system (added 2026-04-14). Cashiers need read access to
    # see their own assigned shift in the React POS banner. Captains
    # and Managers get write access via the captain extras list below.
    "URY Shift",
    "URY Shift Assignment",
]

# Doctypes the POS creates / updates / submits. Each entry includes the
# perm flags appropriate for "regular cashier operation".
WRITE_DOCTYPES = [
    (
        "Customer",
        {"read": 1, "write": 1, "create": 1, "select": 1, "report": 1},
    ),
    (
        "POS Invoice",
        {
            "read": 1,
            "write": 1,
            "create": 1,
            "submit": 1,
            "select": 1,
            "print": 1,
            "report": 1,
        },
    ),
    (
        "POS Opening Entry",
        {"read": 1, "write": 1, "create": 1, "submit": 1, "select": 1},
    ),
    (
        "POS Closing Entry",
        {"read": 1, "write": 1, "create": 1, "submit": 1, "select": 1},
    ),
    # Sales Invoice + POS Invoice Merge Log are needed for the close-
    # shift consolidation chain. When a POS Closing Entry is submitted,
    # ERPNext's `consolidate_pos_invoices` hook creates a POS Invoice
    # Merge Log for each customer and that merge log on submit creates
    # a Sales Invoice by merging the POS Invoice rows. Both steps run
    # under the calling user's permission context — so URY Cashier /
    # Captain / Manager must be able to create + submit both. Without
    # these, closing a shift throws "No permission for Sales Invoice"
    # and rolls back with a confusing cascade of link errors (the
    # partial closing entry tries to add a Failed-status comment on a
    # doc that was never inserted). See CLAUDE.md "Fixes log"
    # 2026-04-10.
    (
        "Sales Invoice",
        {
            "read": 1,
            "write": 1,
            "create": 1,
            "submit": 1,
            "select": 1,
            "print": 1,
            "report": 1,
        },
    ),
    (
        "POS Invoice Merge Log",
        {"read": 1, "write": 1, "create": 1, "submit": 1, "select": 1},
    ),
    (
        "URY KOT",
        {"read": 1, "write": 1, "create": 1, "submit": 1, "select": 1},
    ),
    (
        "URY Order Merge Log",
        {"read": 1, "write": 1, "create": 1, "select": 1, "report": 1},
    ),
    (
        "URY Table Merge Log",
        {"read": 1, "write": 1, "create": 1, "select": 1, "report": 1},
    ),
]

# Captain-extras: things a captain may legitimately need to do that a
# cashier shouldn't. Right now this is empty — the per-cashier order
# scoping is enforced server-side via _resolve_orders_scope, not via
# DocPerms. Left as a hook for future extras.
CAPTAIN_EXTRA_WRITE_DOCTYPES: list[tuple[str, dict]] = [
    # Cancel permission on POS Invoice — captain can void a cashier's
    # mistake without involving a manager.
    (
        "POS Invoice",
        {"cancel": 1},
    ),
    # Shift system: captains can create / edit shift templates AND
    # assign them to cashiers. Cashiers stay read-only on both
    # doctypes (they only see their own shift in the banner).
    (
        "URY Shift",
        {"read": 1, "write": 1, "create": 1, "select": 1, "report": 1},
    ),
    (
        "URY Shift Assignment",
        {"read": 1, "write": 1, "create": 1, "select": 1, "report": 1},
    ),
]

ROLES = ("URY Cashier", "URY Captain", "URY Manager")


# ───────────────────────────────────────────────────────────────────
# Public entry point
# ───────────────────────────────────────────────────────────────────


def ensure_role_permissions():
    """Idempotently create Custom DocPerm rows so URY Cashier / URY
    Captain / URY Manager have the perms they need to use the POS.
    Runs from after_install + after_migrate.
    """
    inserted = 0
    skipped = 0

    for role in ROLES:
        for doctype in READ_ONLY_DOCTYPES:
            if _ensure_perm(role, doctype, {"read": 1, "select": 1}):
                inserted += 1
            else:
                skipped += 1
        for doctype, perms in WRITE_DOCTYPES:
            if _ensure_perm(role, doctype, perms):
                inserted += 1
            else:
                skipped += 1

    # Captain extras (and managers, who are effectively super-captains).
    for role in ("URY Captain", "URY Manager"):
        for doctype, perms in CAPTAIN_EXTRA_WRITE_DOCTYPES:
            if _ensure_perm(role, doctype, perms, merge_with_existing=True):
                inserted += 1
            else:
                skipped += 1

    if inserted:
        frappe.db.commit()

    print(
        f"[URY] ensure_role_permissions: {inserted} new perm rows, "
        f"{skipped} already existed."
    )
    return {"inserted": inserted, "skipped": skipped}


# ───────────────────────────────────────────────────────────────────
# Internals
# ───────────────────────────────────────────────────────────────────


def _ensure_perm(
    role: str,
    doctype: str,
    perms: dict,
    permlevel: int = 0,
    merge_with_existing: bool = False,
) -> bool:
    """Upsert a Custom DocPerm row for (doctype, role, permlevel).
    Returns True if a row was inserted or updated, False if no change.

    Behaviour change on 2026-04-09: previously this skipped existing
    Custom DocPerm rows entirely (to preserve admin tweaks). That meant
    sites with a stale row stuck on read=0 stayed broken even after
    migrate. New behaviour: if a row exists but is missing any of the
    requested flags, set those flags. Existing flags that aren't in
    `perms` are preserved (so admins who added extra flags don't lose
    them). If a built-in DocPerm already grants the role, no Custom
    row is created (built-ins take priority).
    """
    if not frappe.db.exists("DocType", doctype):
        print(f"[URY perms] skipping unknown doctype: {doctype}")
        return False

    builtin_exists = frappe.db.exists(
        "DocPerm",
        {"parent": doctype, "role": role, "permlevel": permlevel},
    )
    if builtin_exists and not merge_with_existing:
        return False

    custom_perm_name = frappe.db.exists(
        "Custom DocPerm",
        {"parent": doctype, "role": role, "permlevel": permlevel},
    )

    if custom_perm_name:
        # Upsert: set any flags from `perms` that don't already match.
        existing = frappe.get_doc("Custom DocPerm", custom_perm_name)
        changed = False
        for key, value in perms.items():
            if value and not getattr(existing, key, 0):
                setattr(existing, key, value)
                changed = True
        if changed:
            existing.flags.ignore_permissions = True
            existing.save()
            frappe.clear_cache(doctype=doctype)
            print(
                f"[URY perms] updated existing row: {role} on {doctype} "
                f"({list(perms.keys())})"
            )
            return True
        return False

    # Fresh insert.
    perm_doc = frappe.get_doc(
        {
            "doctype": "Custom DocPerm",
            "parent": doctype,
            "parenttype": "DocType",
            "parentfield": "permissions",
            "role": role,
            "permlevel": permlevel,
            **perms,
        }
    )
    perm_doc.flags.ignore_permissions = True
    perm_doc.insert()
    frappe.clear_cache(doctype=doctype)
    print(f"[URY perms] inserted new row: {role} on {doctype}")
    return True
