import click
import frappe

from ury.setup import after_install as setup, get_custom_fields
from ury.permissions import ensure_role_permissions


def after_install():
    try:
        print("Setting up URY...")
        setup()

        click.secho("Thank you for installing URY App!", fg="green")

    except Exception:
        pass

    # Run these OUTSIDE the blanket try/except above — if any of these
    # fail we want it loud, not silent. Each function is idempotent.
    _fix_sales_invoice_order_type_fetch()
    ensure_pos_settings_configured()
    _ensure_pos_warehouse_optional()
    _safe_ensure_role_permissions()
    _check_cups_dependency()


def after_migrate():
    """Runs on every `bench migrate`. Idempotent setup that keeps existing
    installs in a URY-compatible state as the app evolves. See CLAUDE.md
    "Fixes log" 2026-04-08 / 2026-04-09 for context.

    Calls `_safe_refresh_custom_fields` so Custom Fields added in
    newer URY releases land on pre-existing sites. Without this,
    dual-source-of-truth fields listed in ury/setup.py never reach
    older installs — fixtures only run on `bench install-app`, not
    on `bench migrate`. See the 2026-04-09 fixes log entry about
    `custom_terminal` silently missing after a feature upgrade.
    """
    _safe_refresh_custom_fields()
    _fix_sales_invoice_order_type_fetch()
    ensure_pos_settings_configured()
    _ensure_pos_warehouse_optional()
    _safe_ensure_role_permissions()
    _check_cups_dependency()


def _fix_sales_invoice_order_type_fetch():
    """Clear a misconfigured `fetch_from` on the Sales Invoice order_type
    Custom Field.

    An old URY release shipped `Sales Invoice-order_type` with
    `fetch_from = "customer.mobile_number"` (copy-pasted from the
    mobile_number field). With that fetch_from, every Sales Invoice save
    pulls the customer's PHONE NUMBER into order_type — a Select field —
    failing validation. The blast radius is brutal: ERPNext's POS Closing
    Entry consolidation creates a Sales Invoice per customer, so a single
    customer with a phone number rolls the WHOLE shift close back with a
    masked "Could not find Reference Name: POS-CLO-…" error.

    setup.py now ships `fetch_from=""`, but `create_custom_fields` doesn't
    reliably CLEAR an existing value (it only sets keys present in the
    spec, and an existing site already has the bad value), so we correct
    it explicitly here. Runs on after_install + after_migrate. Idempotent
    — a no-op once the field is clean. See CLAUDE.md "Fixes log"
    2026-06-05.
    """
    try:
        name = "Sales Invoice-order_type"
        if not frappe.db.exists("Custom Field", name):
            return
        current = frappe.db.get_value("Custom Field", name, "fetch_from")
        if current:
            frappe.db.set_value("Custom Field", name, "fetch_from", "")
            # Invalidate the Sales Invoice meta cache so subsequent saves
            # stop applying the (now-removed) fetch_from.
            frappe.clear_cache(doctype="Sales Invoice")
            frappe.db.commit()
            click.secho(
                f"[URY] Cleared bad fetch_from ('{current}') on "
                f"Sales Invoice.order_type. Phone numbers will no longer "
                f"leak into order_type and block shift close.",
                fg="yellow",
            )
    except Exception as e:
        click.secho(
            f"[URY] Failed to fix Sales Invoice.order_type fetch_from: {e}. "
            f"Open the Custom Field 'Sales Invoice-order_type' in the desk "
            f"and clear its 'Fetch From' value manually.",
            fg="red",
        )


def _safe_refresh_custom_fields():
    """Per-field defensive wrapper around the ury/setup.py
    get_custom_fields() spec. Frappe's `create_custom_fields` processes
    fields in a loop and aborts on the first raise — which means a
    single legacy field with an incompatible fieldtype (e.g. an
    old `Data` field the new spec wants as `Time`) blocks every
    subsequent field from getting created on an existing site. We
    iterate per-field here so one bad apple doesn't spoil the batch.

    Failed fields are logged as a yellow warning with their doctype
    + fieldname + error — admin can investigate those individually
    without losing the fields that did apply.
    """
    from frappe.custom.doctype.custom_field.custom_field import (
        create_custom_fields,
    )

    try:
        all_fields = get_custom_fields()
    except Exception as e:
        click.secho(
            f"[URY] Failed to load custom field spec: {e}", fg="red"
        )
        return

    successes = 0
    failures = []
    for doctype, fields in all_fields.items():
        if isinstance(fields, dict):
            fields = [fields]
        for field_spec in fields:
            fieldname = field_spec.get("fieldname", "<no fieldname>")
            try:
                create_custom_fields({doctype: [field_spec]})
                successes += 1
            except Exception as e:
                failures.append((doctype, fieldname, str(e)))

    if failures:
        click.secho(
            f"[URY] Custom field refresh: {successes} fields OK, "
            f"{len(failures)} failed:",
            fg="yellow",
        )
        for dt, fn, err in failures:
            click.secho(f"    {dt}.{fn} — {err}", fg="yellow")
        click.secho(
            "  These failures usually mean a legacy field on this site "
            "has an incompatible fieldtype vs the current spec. Inspect "
            "the field in the desk (Customize Form) and either align "
            "it with setup.py or delete + recreate.",
            fg="yellow",
        )
    else:
        click.secho(
            f"[URY] Custom field refresh: {successes} fields OK.",
            fg="green",
        )


def _ensure_pos_warehouse_optional():
    """Make POS Profile.warehouse conditional on the
    `custom_use_pos_warehouse` checkbox via Property Setters.

    ERPNext ships POS Profile.warehouse as `reqd: 1`. URY's "Use Single POS
    Warehouse" toggle (2026-06-11) needs the field to be required + visible
    only when the box is ON; when OFF (item-warehouse mode) the admin saves
    the profile without a warehouse and each item posts to its own Default
    Warehouse at shift close. We override the field with three Property
    Setters: reqd→0, plus mandatory_depends_on / depends_on bound to the
    checkbox. Runs on after_install + after_migrate, idempotent.
    """
    from frappe.custom.doctype.property_setter.property_setter import (
        make_property_setter,
    )

    specs = [
        ("reqd", "0", "Check"),
        ("mandatory_depends_on", "eval:doc.custom_use_pos_warehouse", "Data"),
        ("depends_on", "eval:doc.custom_use_pos_warehouse", "Data"),
    ]
    try:
        for prop, value, prop_type in specs:
            existing = frappe.db.exists(
                "Property Setter",
                {
                    "doc_type": "POS Profile",
                    "field_name": "warehouse",
                    "property": prop,
                },
            )
            if existing:
                frappe.db.set_value("Property Setter", existing, "value", value)
            else:
                make_property_setter(
                    "POS Profile",
                    "warehouse",
                    prop,
                    value,
                    prop_type,
                    for_doctype=False,
                    validate_fields_for_doctype=False,
                )
        frappe.clear_cache(doctype="POS Profile")
        frappe.db.commit()
        click.secho(
            "[URY] POS Profile.warehouse is now optional (bound to the "
            "'Use Single POS Warehouse' toggle).",
            fg="green",
        )
    except Exception as e:
        click.secho(
            f"[URY] Failed to make POS Profile.warehouse optional: {e}. The "
            f"'Use Single POS Warehouse' toggle still works, but the "
            f"Warehouse field may stay mandatory — fix via Customize Form "
            f"on POS Profile (set Warehouse reqd off).",
            fg="red",
        )


def _safe_ensure_role_permissions():
    """Wrap ensure_role_permissions in a defensive try/except so a single
    permission failure (e.g. a doctype that doesn't exist on this site)
    doesn't crash the whole migrate. Logs a red warning instead."""
    try:
        ensure_role_permissions()
    except Exception as e:
        click.secho(
            f"[URY] Failed to ensure role permissions: {e}. "
            f"URY Cashier / URY Captain users may hit 403s on POS doctypes. "
            f"Run `bench --site <site> execute "
            f"ury.permissions.ensure_role_permissions` manually to retry.",
            fg="red",
        )


def ensure_pos_settings_configured():
    """Force `POS Settings.invoice_type = "POS Invoice"`.

    URY creates `POS Invoice` docs directly (never Sales Invoices via POS).
    If the site's POS Settings has `invoice_type = "Sales Invoice"` — the
    alternative mode shipped by ERPNext — every POS order submission hits
    `POSInvoice.validate_is_pos_using_sales_invoice()` and throws:

        "Sales Invoice mode is activated in POS. Please create Sales
         Invoice instead."

    We auto-correct this on every install and migrate so the setting
    can't drift into a broken state. If the setting is already
    "POS Invoice", `frappe.db.set_single_value` is a no-op.
    """
    try:
        current = frappe.db.get_single_value("POS Settings", "invoice_type")
        if current != "POS Invoice":
            frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
            frappe.db.commit()
            click.secho(
                f"[URY] POS Settings.invoice_type auto-set to 'POS Invoice' "
                f"(was '{current}'). URY requires POS Invoice mode.",
                fg="yellow",
            )
    except Exception as e:
        # Don't crash install/migrate — but make the failure visible so
        # the operator can fix it manually.
        click.secho(
            f"[URY] Failed to auto-configure POS Settings.invoice_type: {e}. "
            f"Open 'POS Settings' in the desk and set 'Create POS Invoice in' "
            f"to 'POS Invoice' manually.",
            fg="red",
        )


def _check_cups_dependency():
    """Verify that the `pycups` Python package can be imported, and if
    not, print a multi-line yellow warning with platform-aware install
    commands.

    Why this exists:
      - URY's print system uses CUPS (via `pycups`) for the CUPS Direct
        print mode AND for Frappe's built-in `Network Printer Settings.
        get_printers_list` whitelisted method (the "Get Printers List"
        button on the Network Printer Settings form).
      - `pycups` is a C extension that links against `libcups2`. The
        OS-level package (`libcups2-dev` on Debian/Ubuntu, `cups-devel`
        on RHEL/Fedora, `libcups` on Arch) MUST be installed BEFORE
        `pip install pycups` can build the binding.
      - If the OS package is missing, `bench install-app ury` fails on
        the pip step with a confusing "fatal error: cups/cups.h: No
        such file or directory". Even if pip succeeds at install time,
        a later container rebuild can leave pycups installed but
        unable to load (libcups2 missing at runtime).
      - This check runs after every install + migrate so a missing
        dep is loud + actionable, with the EXACT commands the admin
        needs to run, instead of waiting for the cashier to hit the
        "Get Printers List" error months later.

    Behavior:
      - Import succeeds: print one green line confirming.
      - Import fails: print a multi-line yellow warning with the apt /
        dnf / pacman commands AND the bench command to retry the
        Python install. Does NOT crash install/migrate — the rest of
        URY works fine without CUPS, the only impact is the printer
        list lookup button. Admins who don't use CUPS Direct mode
        (i.e. they use QZ Tray) can ignore this warning.

    See CLAUDE.md "Fixes log" 2026-04-16 (print revamp Round 1).
    """
    import platform

    try:
        import cups  # noqa: F401
        click.secho(
            "[URY] CUPS Python bindings (pycups) detected — Network Printer "
            "Settings 'Get Printers List' will work.",
            fg="green",
        )
        return
    except ImportError:
        pass
    except Exception as e:
        # pycups is installed but can't load (usually libcups2 missing
        # at runtime). Same fix as the missing-import case.
        click.secho(
            f"[URY] pycups installed but can't load: {e}. "
            f"This usually means libcups2 is missing at runtime.",
            fg="yellow",
        )

    # Build a platform-aware install hint. We can't just call apt-get
    # ourselves — the install hook runs as the bench user, not root.
    system = platform.system().lower()
    distro = ""
    try:
        # /etc/os-release is the standard way to detect Linux distro.
        with open("/etc/os-release", "r") as f:
            for line in f:
                if line.startswith("ID="):
                    distro = line.split("=", 1)[1].strip().strip('"').lower()
                    break
    except Exception:
        pass

    if distro in ("ubuntu", "debian", "raspbian", "linuxmint"):
        os_install = "sudo apt-get install -y libcups2-dev"
    elif distro in ("rhel", "centos", "fedora", "rocky", "almalinux"):
        os_install = "sudo dnf install -y cups-devel"
    elif distro in ("arch", "manjaro"):
        os_install = "sudo pacman -S libcups"
    elif system == "darwin":
        os_install = "brew install cups   # then `pip install pycups`"
    else:
        os_install = (
            "<your distro's libcups2-dev / cups-devel / libcups package>"
        )

    bench_root_hint = (
        "From your bench root (the directory containing the `apps/`, "
        "`sites/` and `env/` directories):"
    )

    click.secho(
        "\n" + "=" * 72 + "\n"
        "[URY] INFO: pycups is not installed — CUPS Direct mode is\n"
        "      unavailable. QZ Tray mode (the default, cloud-friendly\n"
        "      print path) works fine without it. IGNORE this message\n"
        "      if you're using QZ Tray.\n"
        + "=" * 72 + "\n\n"
        "To enable CUPS Direct printing only:\n\n"
        f"  1. Install the OS-level CUPS development headers:\n"
        f"     {os_install}\n\n"
        f"  2. {bench_root_hint}\n"
        f"     ./env/bin/pip install 'pycups>=2.0.1'\n\n"
        f"  3. Restart bench so the new module is picked up:\n"
        f"     bench restart\n\n"
        + "=" * 72 + "\n",
        fg="cyan",
    )
