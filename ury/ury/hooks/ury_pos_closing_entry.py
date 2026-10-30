"""Doc-event hooks for POS Closing Entry.

Deliberately almost empty. Read this before adding anything back.

Three gates used to live here and all three are gone on purpose:

* ``sub_pos_close_check`` — the "every sub cashier must close before the
  main cashier may close" gate. Deleted 2026-04-08 with the rest of the
  captain/sub-cashier model.

* ``calculate_closing_amount`` — rolled a ``Sub POS Closing`` record's
  amounts into the main closing entry, and **hard-threw** ``"No Sub POS
  Closing entries found between the given dates"`` when there wasn't
  one. Deleted 2026-07-28. It made closing *impossible* on any profile
  with ``custom_enable_multiple_cashier`` ticked, because nothing can
  create the record it demanded: the React POS has no Sub POS Closing
  screen at all, and ``Sub POS Closing`` is not in any URY role's
  permissions, so a cashier could not create one even from the desk.
  That throw was the "there is no sub opening" error users hit when
  they tried to escape the opening deadlock — it turned a recoverable
  situation into a locked-out POS. Its own logic was broken besides:
  it read ``custom_closing_amount`` (never populated by URY's closing
  flow, so real counted cash was overwritten with 0), it only ever
  looked at ``sub_pos_closing[0]`` so extra sub cashiers were dropped,
  and its date filters (``posting_date <=`` combined with
  ``period_start_date >=``) described an unbounded window across other
  profiles and companies.

* ``validate_cashier`` — blocked "sub cashiers" from closing. Deleted
  2026-07-28. It keyed off ``custom_main_cashier``, deprecated since
  2026-04-08, and was broken anyway: it assigned ``cashier`` inside the
  loop instead of collecting a set, so only the LAST non-main user in
  ``applicable_for_users`` was ever blocked. Whether you were stopped
  depended on child-table row order.

If a per-cashier close restriction is ever wanted again, express it as
a role check (``URY Captain`` / ``URY Manager``) — not as a scan of
``applicable_for_users`` — and put it in front of the close in
``ury.ury_pos.api.submit_pos_closing_entry`` where the error can reach
the cashier's dialog, not in a validate hook where it aborts a
partially-committed close.

See CLAUDE.md "Fixes log" 2026-07-28.

A guard WAS added here on 2026-10-29 — see
``refuse_close_that_orphans_invoices`` below. It is the only thing in this
module that does anything.
"""

import frappe
from frappe import _


# Roles that may close from the desk even when it would orphan invoices.
#
# Break-glass, deliberately. With ``custom_daily_pos_close`` on, an unclosed
# night blocks the NEXT day's trading entirely, so there has to be SOME way
# to force a close through when the POS path itself is broken — otherwise a
# refusal here could take a whole outlet off the air. Same reasoning as the
# close permission gate (2026-08-05), which keeps Administrator / System
# Manager for exactly this reason. Do not remove these without providing
# another route out.
DESK_CLOSE_OVERRIDE_ROLES = ("System Manager",)


def _may_force_desk_close(user=None):
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    roles = set(frappe.get_roles(user))
    return any(role in roles for role in DESK_CLOSE_OVERRIDE_ROLES)


def refuse_close_that_orphans_invoices(doc):
    """Refuse a close that would leave unconsolidated invoices behind.

    ⚠ THE BUG THIS EXISTS FOR — found on the client's data 2026-10-28, and it
    is a silent one that cost real money.

    URY's own close (``ury.ury_pos.api.submit_pos_closing_entry``) scopes the
    invoices it attaches by **pos_profile + unconsolidated**, with no owner
    and no timestamp window, precisely so a bill that missed its own shift's
    close can still be swept up later. It then REHOMES each invoice's
    ``owner`` to the opener so ERPNext's ``validate_pos_invoices`` accepts
    them.

    ERPNext's native ``make_closing_entry_from_opening`` — what a POS Closing
    Entry built **from the desk** uses — does neither. Its
    ``build_invoice_query`` filters on **BOTH**::

        (owner == closing user)
        AND Timestamp(posting_date, posting_time) BETWEEN period_start AND period_end

    So a desk close silently drops every invoice rung by anyone other than
    the closing user, *and* everything outside the posting-time window, from
    the attached list AND the totals — no error, nothing in the Error Log.
    On a shift where several cashiers rang sales (the normal case here: the
    backlog below was rung by 8+ people) a desk close is structurally
    incapable of sweeping it, whichever cashier runs it. That is exactly why
    URY has the rehome pass and the owner-free scope.

    On the client's site that produced, over two days:

      * POS-CLO-2026-00103 — attached 19 invoices, ₵4,250
      * POS-CLO-2026-00104 — attached **0** invoices, ₵0, and still Submitted

    while **151 submitted POS Invoices worth ₵69,085** sat unconsolidated on
    that one profile, their revenue never reaching the GL. Every close up to
    00102 had gone through the POS and swept 37–88 invoices each.

    ⚠ AND THE BACKLOG ITSELF WAS NOT CREATED BY A DESK CLOSE — corrected
    2026-10-30. All 151 carry URY's own ``"Originally rung by …; ownership
    normalized on shift close"`` remark, so a **POS** close reached them,
    rehomed their owners and **committed that**, then failed before
    consolidating. Everything after the rehome rolled back (closing entry,
    merge logs, Sales Invoices, the auto-replenishment Work Orders, even the
    naming series) while the rehome survived, because it commits on its own.
    The reported failure mode is a **gateway timeout** — gunicorn runs with
    ``-t 120`` on that box and consolidation is forced INLINE on purpose
    (2026-06-11), so a close big enough to exceed it dies and rolls back,
    and every retry rolls back again.

    Do NOT read ``creation`` vs ``period_end_date`` as proof of which path
    ran. ERPNext's helper also sets ``period_end_date = get_datetime()``, so
    a match means "inserted when the period was stamped" (which URY always
    does, in one transaction) but a mismatch only means it was not — a desk
    form held open overnight does that too.

    So: refuse, and point at the POS, which already does the right thing. We
    deliberately do NOT sweep the missing invoices in here. Doing that would
    mean someone pressing Submit on a desk form silently consolidates weeks
    of trading inline — a very large, surprising action from a small-looking
    button. Refusing is reversible; a wrong sweep is not.

    Fires only on submit (``docstatus == 1``), so a draft can still be
    created and inspected from the desk. Administrator / System Manager pass
    through — see ``DESK_CLOSE_OVERRIDE_ROLES``.
    """
    # Draft saves are fine — only the submit actually orphans anything, and
    # blocking the draft would stop anyone inspecting the entry in the desk.
    if doc.docstatus != 1:
        return

    if not doc.get("pos_profile"):
        return

    if _may_force_desk_close():
        return

    # Imported here, not at module scope: ury_pos.api is a large module and
    # this hook is loaded for every POS Closing Entry save.
    from ury.ury_pos.api import orphaned_unconsolidated_invoices

    attached = [row.pos_invoice for row in (doc.get("pos_invoices") or [])]
    orphans, total = orphaned_unconsolidated_invoices(doc.pos_profile, attached)
    if not orphans:
        return

    sample = ", ".join(row["name"] for row in orphans[:5])
    if len(orphans) > 5:
        sample += f" (+{len(orphans) - 5} more)"

    frappe.throw(
        _(
            "{0} submitted invoices totalling {1} on {2} '{3}' have not been "
            "consolidated, and this closing entry would leave them out — "
            "their revenue would never reach the accounts.\n\n"
            "Close the shift from the POS instead. The POS close sweeps every "
            "unconsolidated bill on the profile, including ones from earlier "
            "shifts.\n\n"
            "Affected: {4}"
        ).format(
            len(orphans),
            frappe.format_value(total, {"fieldtype": "Currency"}),
            _("POS Profile"),
            doc.pos_profile,
            sample,
        ),
        title=_("Close From The POS, Not The Desk"),
    )


def before_save(doc, method=None):
    pass


def validate(doc, method=None):
    refuse_close_that_orphans_invoices(doc)
