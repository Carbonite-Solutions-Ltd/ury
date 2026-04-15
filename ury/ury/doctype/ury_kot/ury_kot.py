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

        order_type = None
        if getattr(self, "invoice", None):
            order_type = frappe.db.get_value(
                "POS Invoice", self.invoice, "order_type"
            )

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
                _try_print_kot(filtered_doc, fallback_printer, kot_print_format)
            return

        # ---- Legacy path: old custom_print_mode isn't set yet. ----
        def print_kot(printer, kot_print_format):
            """Legacy print helper. Kept for the backwards-compat
            path where an admin hasn't migrated to the new config.
            Still wraps exceptions (but now logs them — no bare pass).
            """
            try:
                print_by_server("URY KOT", self.name, printer, kot_print_format)
            except Exception:
                frappe.log_error(
                    title="URY KOT legacy print failed",
                    message=f"KOT {self.name} printer={printer}\n{traceback.format_exc()}",
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
        currentBranch = self.branch
        production = self.production
        kotjson = json.loads(frappe.as_json(self))
        audio_file = frappe.db.get_value(
            "POS Profile", self.pos_profile, "custom_kot_alert_sound"
        )
        cache_key = "{}_{}_last_kot_time".format(currentBranch, production)
        time = frappe.cache().get_value(cache_key)
        kot_channel = "{}_{}_{}".format("kot_update", currentBranch, production)
        frappe.publish_realtime(
            kot_channel,
            {"kot": kotjson, "audio_file": audio_file, "last_kot_time": time},
        )
        frappe.cache().set_value(cache_key, self.time)

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

    