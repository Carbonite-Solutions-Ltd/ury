"""Backfill `custom_terminal` on existing POS Opening Entry rows.

Before the per-terminal opening-entry revamp (2026-04-08), opening
entries were branch-scoped — they had no concept of "which terminal
this drawer belongs to". This patch tries to retroactively associate
each existing entry with a single terminal so reports / posOpening
checks under the new model don't lose track of historical entries.

Rules:
- If the opening entry already has `custom_terminal` → leave alone.
- Look at `tabURY POS Terminal` rows for `(branch=entry.branch,
  pos_profile=entry.pos_profile, disabled=0)`.
  - 0 matches → skip and log (admin needs to set it manually OR
    create a terminal). The entry will still be visible in the desk;
    only the new per-terminal `posOpening` checks will treat it as
    not-stamped.
  - 1 match → stamp it.
  - >1 matches → skip and log the candidates so the admin can
    disambiguate. We refuse to guess.
- Idempotent. Safe to re-run.

Defensive `frappe.db.has_column` guard so a mis-ordered patches.txt
degrades to a noisy no-op rather than a fatal crash.
"""

import frappe


def execute():
    if not frappe.db.has_column("POS Opening Entry", "custom_terminal"):
        print(
            "[URY] backfill_opening_entry_terminal: `custom_terminal` "
            "column not present on tabPOS Opening Entry — skipping. "
            "Re-run after fixtures sync."
        )
        return

    if not frappe.db.has_column("URY POS Terminal", "pos_profile"):
        print(
            "[URY] backfill_opening_entry_terminal: `pos_profile` column "
            "not present on tabURY POS Terminal — skipping. The terminal "
            "↔ POS Profile binding patch must run first."
        )
        return

    rows = frappe.get_all(
        "POS Opening Entry",
        filters={"custom_terminal": ["in", ["", None]]},
        fields=["name", "branch", "pos_profile"],
    )

    backfilled = 0
    skipped_no_profile = 0
    skipped_no_branch = 0
    skipped_no_match = 0
    skipped_multi_match = []

    for r in rows:
        if not r.pos_profile:
            skipped_no_profile += 1
            continue
        if not r.branch:
            skipped_no_branch += 1
            continue

        terminals = frappe.get_all(
            "URY POS Terminal",
            filters={
                "branch": r.branch,
                "pos_profile": r.pos_profile,
                "disabled": 0,
            },
            pluck="name",
        )

        if len(terminals) == 0:
            skipped_no_match += 1
            continue
        if len(terminals) > 1:
            skipped_multi_match.append(
                {
                    "entry": r.name,
                    "branch": r.branch,
                    "pos_profile": r.pos_profile,
                    "candidates": terminals,
                }
            )
            continue

        frappe.db.set_value(
            "POS Opening Entry",
            r.name,
            "custom_terminal",
            terminals[0],
            update_modified=False,
        )
        backfilled += 1

    if backfilled:
        frappe.db.commit()

    print(
        f"[URY] backfill_opening_entry_terminal: "
        f"{backfilled} backfilled, "
        f"{skipped_no_profile} skipped (no pos_profile on entry), "
        f"{skipped_no_branch} skipped (no branch on entry), "
        f"{skipped_no_match} skipped (no terminal matches branch+profile), "
        f"{len(skipped_multi_match)} skipped (multiple terminals match)."
    )

    if skipped_multi_match:
        print(
            "[URY] These opening entries need manual attention — their "
            "branch+profile matches more than one terminal and the patch "
            "can't pick one automatically. Open each entry in the desk "
            "and set its 'Terminal' field:"
        )
        for s in skipped_multi_match:
            print(
                f"  - {s['entry']} (branch={s['branch']}, "
                f"pos_profile={s['pos_profile']}): "
                f"candidates = {s['candidates']}"
            )
