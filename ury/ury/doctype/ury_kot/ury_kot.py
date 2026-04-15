# Copyright (c) 2023, Tridz Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
import requests
import json
import traceback
from frappe.utils.print_format import print_by_server
from frappe.model.document import Document


class URYKOT(Document):
    def on_submit(self):
        self.multi_print_kot()
        self.kotDisplayRealtime()

    def before_submit(self):
        self.userSetting()


    # Function for printing multiple KOTs.
    def multi_print_kot(self):
        """Print this KOT on the right printer(s).

        Resolution order (2026-04-16):
          1. **New unified config** — if the POS Profile's
             `custom_print_mode` is set (not "Disabled"), use the
             `resolve_kot_print_plan` helper to split items by
             department and route each subset to its configured
             printer. Mixed KOTs (food + drinks) produce multiple
             print jobs, each with a filtered in-memory copy of the
             KOT doc so each station sees only its items.
          2. **Legacy path** — when the new config is empty, fall
             back to the old `URY Printer Settings` child table on
             POS Profile / URY Production Unit / URY Room. The old
             code is preserved below unchanged so existing sites
             keep working until they migrate.

        Errors: the old `except: pass` that swallowed every printer
        failure is gone. Each print attempt is wrapped in its own
        try/except that logs via `frappe.log_error` AND publishes a
        realtime event so the React POS can surface it as a toast.
        The `custom_print_fallback_mode` on POS Profile decides what
        to do when a specific printer fails:

          - "Fallback to Bill Printer" (default): re-route the items
            to the bill printer with a "<DEPT> - <TARGET> OFFLINE"
            header so the intended station still sees the order.
          - "Fail Silently": drop the job.
          - "Fail with Alert": drop the job + loud toast.
        """
        from ury.ury.api.ury_print import (
            resolve_kot_print_plan,
            apply_print_fallback,
            filter_plan_for_auto_print,
            record_printed_departments,
        )

        pos_profile = self.pos_profile

        # Skip server-side printing entirely in QZ Tray mode. The
        # frontend's kot-listener polls `get_latest_kot` and fires
        # QZ for each plan entry — running server-side CUPS on top
        # of that causes duplicate prints (and server-side CUPS is
        # unreachable on cloud-hosted Frappe anyway). CUPS Direct
        # mode still takes the full path below.
        print_mode = frappe.db.get_value(
            "POS Profile", pos_profile, "custom_print_mode"
        )
        if print_mode == "QZ Tray":
            return

        # KDS routing mode gate. When the admin picked "URY Production
        # Unit" for this profile, skip the new department-based plan
        # entirely — it would route to the POS Profile's
        # custom_kitchen/bar/parcel fields which the admin doesn't
        # use in PU mode. Fall through to the legacy path below which
        # reads each URY Production Unit's `printer_settings` child
        # table. See CLAUDE.md "Fixes log" 2026-04-16 Phase D fix.
        kds_mode = (
            frappe.db.get_value(
                "POS Profile", pos_profile, "custom_kds_routing_mode"
            )
            or "Menu Course"
        )

        order_type = None
        if getattr(self, "invoice", None):
            order_type = frappe.db.get_value(
                "POS Invoice", self.invoice, "order_type"
            )

        if kds_mode == "URY Production Unit":
            plan = []
        else:
            plan = resolve_kot_print_plan(
                self, pos_profile_name=pos_profile, order_type=order_type
            )

        # New path: the unified config had `custom_print_mode` set.
        if plan:
            pos_profile_doc = frappe.get_cached_doc("POS Profile", pos_profile)
            # Auto-print policy: default holds Drinks. Cashier fires
            # held KOTs at bill-print time via the Print Invoice button.
            plan = filter_plan_for_auto_print(plan, pos_profile_doc)
            if not plan:
                return
            # The print format to use — read from the first row of
            # URY Printer Settings as a compat shim if the new config
            # doesn't carry its own format field (it currently doesn't).
            legacy_first = frappe.db.get_value(
                "URY Printer Settings",
                {"parent": pos_profile, "parenttype": "POS Profile", "custom_kot_print": 1},
                "custom_kot_print_format",
            )
            kot_print_format = legacy_first or None

            successfully_printed_depts = []
            for entry in plan:
                printer = entry["printer"]
                dept = entry["department"]
                items = entry["items"]

                # Build a filtered copy of self with only this
                # department's items. We mutate a shallow clone so
                # the in-memory self isn't disturbed. Note: URY KOT's
                # child table is `kot_items`, NOT the generic `items`.
                filtered_doc = frappe.copy_doc(self)
                filtered_doc.kot_items = items
                # Stamp a flag the print format can read to show the
                # department in the KOT header.
                filtered_doc.flags.kot_department = dept

                if printer:
                    ok, err_msg = _try_print_kot(
                        filtered_doc, printer, kot_print_format
                    )
                    if ok:
                        successfully_printed_depts.append(dept)
                        continue

                    # Printer was configured but failed.
                    frappe.log_error(
                        title="URY KOT print failed",
                        message=(
                            f"KOT {self.name} department={dept} "
                            f"printer={printer} err={err_msg}"
                        ),
                    )
                    _publish_print_failure(self, dept, printer, err_msg)

                # No printer OR print failed — apply fallback policy.
                should_fallback, fallback_printer, header = apply_print_fallback(
                    entry, pos_profile_doc
                )
                if not should_fallback:
                    continue
                filtered_doc.flags.fallback_header = header
                fb_ok, _fb_err = _try_print_kot(
                    filtered_doc, fallback_printer, kot_print_format
                )
                if fb_ok:
                    successfully_printed_depts.append(dept)

            # Record what actually printed so get_latest_kot + the
            # pending-KOT UI know which departments are still held.
            if successfully_printed_depts:
                record_printed_departments(self.name, successfully_printed_depts)
            return

        # ---- Legacy path: old custom_print_mode isn't set yet. ----
        # Also the path that runs in URY Production Unit mode: the
        # new unified config returns an empty plan (because
        # resolve_kot_print_plan uses the course-department split
        # which only makes sense in Menu Course mode), so we fall
        # through here and read the production's printer_settings
        # child table. The child's `printer` field now points at
        # URY Printer (repointed 2026-04-16 Phase D), so the helper
        # below routes through `ury_print_via_cups` instead of
        # Frappe's `print_by_server` — that keeps the Production
        # Unit path cloud-compatible (pycups catch-22 free) and
        # consistent with the Menu Course path.
        def print_kot(printer, kot_print_format):
            """Legacy / URY Production Unit print helper. Routes
            through the URY Printer CUPS layer.
            """
            if not printer:
                return
            from ury.ury.api.ury_print import ury_print_via_cups
            ok, err_msg = ury_print_via_cups(
                printer,
                "URY KOT",
                self.name,
                print_format=kot_print_format,
                doc=self,
            )
            if not ok:
                frappe.log_error(
                    title="URY KOT production-unit print failed",
                    message=(
                        f"KOT {self.name} printer={printer} err={err_msg}"
                    ),
                )

        pos_kot_printers = frappe.db.get_all(
            "URY Printer Settings",
            fields=["printer", "custom_kot_print_format","custom_kot_print"],
            filters={"parent": self.pos_profile, "custom_kot_print": 1,"parenttype":"POS Profile"},
            order_by="idx"
        )

        pos_print_flag = True
        if self.production:
            production_unit_printers = frappe.get_all(
                "URY Printer Settings",
                fields=["printer", "custom_kot_print_format","custom_kot_print","custom_block_takeaway_kot"],
                filters={"parent": self.production, "custom_kot_print": 1,"parenttype":"URY Production Unit"},
                order_by="idx"
            )

            # If production unit printer is specified, print KOT in production printer
            if production_unit_printers:
                for printer in production_unit_printers:
                    pos_print_flag = False
                    if printer.custom_block_takeaway_kot == 1 :
                        if self.restaurant_table and self.table_takeaway == 0:
                            print_kot(printer.printer, printer.custom_kot_print_format)
                    else:
                        print_kot(printer.printer, printer.custom_kot_print_format)

                # Check if restaurant table is specified and it's not a takeaway order
                if self.restaurant_table and self.table_takeaway == 0:
                    room = frappe.db.get_value(
                        "URY Table", self.restaurant_table, "restaurant_room"
                    )

                    room_kot_printers = frappe.get_all(
                        "URY Printer Settings",
                        fields=["printer", "custom_kot_print_format","custom_kot_print"],
                        filters={"parent": room, "custom_kot_print": 1,"parenttype":"URY Room"},
                        order_by="idx"
                    )

                    # If room printer is specified, print KOT in room
                    if room_kot_printers:
                        for printer in room_kot_printers:
                            pos_print_flag = False
                            print_kot(printer.printer, printer.custom_kot_print_format)

                    if pos_print_flag == True:
                        if pos_kot_printers:
                            for printer in pos_kot_printers:
                                print_kot(printer.printer, printer.custom_kot_print_format)

                else:
                    if pos_kot_printers:
                        for printer in pos_kot_printers:
                            print_kot(printer.printer, printer.custom_kot_print_format)


    # Function for displaying KOT-related information in real-time On KDS(Kitchen Display System)
    def kotDisplayRealtime(self):
        """Publish this KOT to the KDS realtime channel(s).

        **Legacy — URY Production Unit mode.** The POS Profile's
        ``custom_kds_routing_mode`` is ``"URY Production Unit"``
        (or the profile is old and doesn't have the field yet). One
        KOT per production means one publish to
        ``kot_update_<branch>_<production>`` — the KDS for that
        production picks it up, every other station ignores it.
        Unchanged from pre-revamp behavior.

        **Menu Course mode.** The POS Profile is ``"Menu Course"``.
        One KOT per order holds items from multiple departments, so
        we fan out ONE publish per distinct department present in
        this KOT, targeting
        ``kot_update_<branch>_<Food|Drinks|Other>``. Each KDS filters
        out messages it shouldn't see via its own target-filtered
        poll + the same channel name. We ALSO publish to
        ``kot_update_<branch>_All`` unconditionally so a "show
        everything" KDS (``/URYMosaic/All``) receives a single ping
        per KOT.

        See CLAUDE.md "Fixes log" 2026-04-16 (print revamp Round 1 /
        Phase C KDS routing mode).
        """
        currentBranch = self.branch
        production = self.production
        kotjson = json.loads(frappe.as_json(self))
        audio_file = frappe.db.get_value(
            "POS Profile", self.pos_profile, "custom_kot_alert_sound"
        )

        kds_mode = (
            frappe.db.get_value(
                "POS Profile", self.pos_profile, "custom_kds_routing_mode"
            )
            or "Menu Course"
        )

        def _publish(target):
            cache_key = "{}_{}_last_kot_time".format(currentBranch, target)
            time = frappe.cache().get_value(cache_key)
            channel = "kot_update_{}_{}".format(currentBranch, target)
            frappe.publish_realtime(
                channel,
                {
                    "kot": kotjson,
                    "audio_file": audio_file,
                    "last_kot_time": time,
                },
            )
            frappe.cache().set_value(cache_key, self.time)

        if kds_mode == "URY Production Unit":
            # Legacy path: one publish to the production's channel.
            _publish(production)
            return

        # Menu Course mode: fan out per distinct department in the
        # KOT's items plus the "All" broadcast.
        from ury.ury.api.ury_print import (
            _classify_kot_item_department,
            _get_kot_items_list,
        )
        departments = {
            _classify_kot_item_department(row)
            for row in _get_kot_items_list(self)
        }
        for dept in departments:
            _publish(dept)
        _publish("All")

    def userSetting(self):
        userDoc = frappe.get_doc("User", self.owner)
        self.user = userDoc.full_name


def _try_print_kot(kot_doc, printer, kot_print_format):
    """Attempt to print a KOT doc on a specific URY Printer target.

    Routes through ``ury_print.ury_print_via_cups`` which reads the
    URY Printer record's server_ip/port/printer_name and talks to
    CUPS directly. The old ``frappe.utils.print_format.print_by_server``
    required a Network Printer Settings doc — we decoupled from that
    on 2026-04-16 to unblock cloud-hosted deployments where admins
    can't create Network Printer Settings records without CUPS.

    Returns (ok, err_msg). The caller handles fallback policy via
    ``apply_print_fallback``.
    """
    if not printer:
        return (False, "no printer configured")
    from ury.ury.api.ury_print import ury_print_via_cups
    return ury_print_via_cups(
        printer,
        "URY KOT",
        kot_doc.name,
        print_format=kot_print_format,
        doc=kot_doc,
    )


def _publish_print_failure(kot_doc, department, printer, err_msg):
    """Publish a realtime event to the React POS so a KOT print
    failure surfaces as a toast on the cashier's device. The channel
    matches the existing KOT update channel so clients already
    subscribed to it get the event without extra wiring.
    """
    try:
        channel = "{}_{}_kot_print_failed".format(
            kot_doc.branch or "", kot_doc.production or ""
        )
        frappe.publish_realtime(
            channel,
            {
                "kot": kot_doc.name,
                "department": department,
                "printer": printer,
                "error": err_msg,
            },
        )
    except Exception:
        # Publishing is best-effort; don't let a realtime hiccup
        # cascade into the save-KOT transaction.
        pass

    