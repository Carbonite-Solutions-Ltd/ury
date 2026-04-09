import click
import frappe

from ury.setup import after_install as setup
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
    ensure_pos_settings_configured()
    _safe_ensure_role_permissions()


def after_migrate():
    """Runs on every `bench migrate`. Idempotent setup that keeps existing
    installs in a URY-compatible state as the app evolves. See CLAUDE.md
    "Fixes log" 2026-04-08 / 2026-04-09 for context."""
    ensure_pos_settings_configured()
    _safe_ensure_role_permissions()


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
