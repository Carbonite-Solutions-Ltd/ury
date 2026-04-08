"""Backfill `pos_profile` on existing URY POS Terminal records.

Before the terminal ↔ POS Profile binding (phase-1 revamp, 2026-04-08),
the POS backend picked "any POS Profile whose branch matches the user's
branch" — undefined behaviour when a branch had multiple profiles.

Now ``URY POS Terminal.pos_profile`` is the source of truth. This patch
copies the single POS Profile from each terminal's branch onto the
terminal record so that installs upgrading from the old behaviour don't
suddenly lose their POS Profile resolution.

Rules:
- If a terminal already has ``pos_profile`` set → leave it alone.
- If a terminal's branch has exactly one non-disabled POS Profile → copy
  its name to the terminal.
- If a terminal's branch has zero POS Profiles → skip; the admin will
  see the "Terminal Not Configured" error at POS load time and fix it.
- If a terminal's branch has multiple POS Profiles → skip and log; the
  admin has to disambiguate manually (which is the whole point of this
  schema change — the old "pick the first one" behaviour was the bug).

Safe to re-run. Idempotent.
"""

import frappe


def execute():
    # Defensive guard: this patch MUST run under [post_model_sync] in
    # patches.txt because it depends on the `pos_profile` column being
    # present on `tabURY POS Terminal`. If the column is somehow missing
    # (mis-ordered patches.txt, bench without model sync, broken upgrade),
    # skip the backfill gracefully rather than crash the whole migration.
    if not frappe.db.has_column("URY POS Terminal", "pos_profile"):
        print(
            "[URY] backfill_terminal_pos_profile: `pos_profile` column not "
            "yet present on tabURY POS Terminal — skipping. Re-run "
            "`bench migrate` after the DocType sync completes."
        )
        return

    terminals = frappe.get_all(
        "URY POS Terminal",
        fields=["name", "branch", "pos_profile"],
    )

    backfilled = 0
    skipped_no_branch = 0
    skipped_zero_profiles = 0
    skipped_multiple_profiles = []

    for t in terminals:
        if t.pos_profile:
            continue

        if not t.branch:
            skipped_no_branch += 1
            continue

        profiles = frappe.get_all(
            "POS Profile",
            filters={"branch": t.branch, "disabled": 0},
            fields=["name"],
        )

        if len(profiles) == 0:
            skipped_zero_profiles += 1
            continue

        if len(profiles) > 1:
            skipped_multiple_profiles.append(
                {
                    "terminal": t.name,
                    "branch": t.branch,
                    "candidates": [p.name for p in profiles],
                }
            )
            continue

        frappe.db.set_value(
            "URY POS Terminal",
            t.name,
            "pos_profile",
            profiles[0].name,
            update_modified=False,
        )
        backfilled += 1

    if backfilled:
        frappe.db.commit()

    print(
        f"[URY] backfill_terminal_pos_profile: "
        f"{backfilled} backfilled, "
        f"{skipped_no_branch} skipped (no branch), "
        f"{skipped_zero_profiles} skipped (no POS Profile on branch), "
        f"{len(skipped_multiple_profiles)} skipped (multiple candidates)"
    )

    if skipped_multiple_profiles:
        print(
            "[URY] These terminals need manual attention — their branch has "
            "multiple POS Profiles and the patch can't pick one automatically. "
            "Open each terminal in the desk and set its POS Profile:"
        )
        for s in skipped_multiple_profiles:
            print(
                f"  - {s['terminal']} (branch {s['branch']}): "
                f"candidates = {s['candidates']}"
            )
