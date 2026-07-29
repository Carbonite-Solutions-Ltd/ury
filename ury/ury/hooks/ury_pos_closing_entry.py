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
"""


def before_save(doc, method):
    pass


def validate(doc, method):
    pass
