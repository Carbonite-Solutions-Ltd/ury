# Copyright (c) 2026, Tridz Technologies Pvt. Ltd and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class URYPrinter(Document):
    """URY-owned printer record.

    Decoupled from Frappe's built-in ``Network Printer Settings``
    doctype because:

      1. Network Printer Settings's ``printer_name`` is a Select
         populated by a "Get Printers List" button that calls a live
         CUPS server. On cloud-hosted Frappe (where the server can't
         reach the restaurant's local printer), CUPS is unreachable
         and admins can't create records at all.
      2. For URY's QZ Tray mode (the default, and the only option
         that actually works on cloud), the printer name is a PLAIN
         STRING that the cashier's browser passes to QZ — no CUPS
         lookup needed. A free-text ``printer_name`` field here
         avoids the CUPS dependency entirely.
      3. For URY's CUPS Direct mode (self-hosted deployments only),
         the ``server_ip`` + ``port`` fields on this doctype give
         URY's print helpers everything they need to call ``cups``
         directly — no dependency on Frappe's ``print_by_server``
         (which hard-requires a Network Printer Settings doc).

    See CLAUDE.md "Fixes log" 2026-04-16 (print revamp Round 1).
    """

    pass
