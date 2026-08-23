/**
 * POS Invoice → "Change Waiter / Cashier" (2026-08-19)
 *
 * Both `cashier` and `custom_waiter` are read-only with allow_on_submit = 0,
 * so once a bill is submitted there is no way to correct them from the form —
 * yet they are the two fields Sales by Staff is built on, and they do go wrong:
 *
 *   • A user holding an elevated role (System Manager / URY Manager /
 *     URY Captain) is NOT treated as a self-serve waiter, so they get the full
 *     cashier UI and are stamped as `cashier` when they settle a bill — while
 *     still being pickable in the waiter dropdown. The same person then shows
 *     up in BOTH fields on the printed bill.
 *   • A cashier can simply pick the wrong waiter at order time.
 *
 * Neither field carries GL, stock or tax, so this correction is safe at any
 * point in the bill's life — including after consolidation, which is usually
 * when someone notices the report is wrong. The server does the write with
 * db.set_value and records a comment on the invoice.
 *
 * NOTE: do NOT call frm.clear_custom_buttons() here. It takes no group
 * argument and wipes EVERY custom button on the form, including the standard
 * ERPNext ones. That mistake previously left the User form with a single
 * button and nothing else.
 */
frappe.ui.form.on("POS Invoice", {
	refresh(frm) {
		if (frm.is_new()) return;

		const allowed = ["Administrator", "System Manager", "URY Manager"];
		const can_edit =
			frappe.session.user === "Administrator" ||
			allowed.some((r) => frappe.user.has_role(r));
		if (!can_edit) return;

		frm.add_custom_button(__("Change Waiter / Cashier"), () =>
			ury_open_attribution_dialog(frm)
		);
	},
});

function ury_open_attribution_dialog(frm) {
	frappe.call({
		method: "ury.ury_pos.api.get_invoice_attribution",
		args: { invoice: frm.doc.name },
		freeze: true,
		freeze_message: __("Loading attribution…"),
		callback(r) {
			if (!r || !r.message) return;
			ury_render_attribution_dialog(frm, r.message);
		},
	});
}

function ury_render_attribution_dialog(frm, info) {
	const cancelled = info.docstatus === 2;
	const same =
		info.cashier &&
		info.waiter_name &&
		String(info.cashier_name || "").trim().toLowerCase() ===
			String(info.waiter_name || "").trim().toLowerCase();

	// Current state, stated plainly, plus a nudge when the same person is
	// sitting in both fields — that is the case this dialog exists for.
	let banner = `
		<div style="padding:10px 12px;border:1px solid #d1d8dd;border-radius:6px;
					background:#f9fafb;margin-bottom:12px;font-size:12px;line-height:1.7">
			<div><b>${__("Current waiter")}:</b> ${frappe.utils.escape_html(
		info.waiter_name || info.waiter || "—"
	)}</div>
			<div><b>${__("Current cashier")}:</b> ${frappe.utils.escape_html(
		info.cashier_name || info.cashier || "—"
	)}</div>
			<div><b>${__("Created by")}:</b> ${frappe.utils.escape_html(info.owner || "—")}</div>
		</div>`;

	if (same) {
		banner += `
		<div style="padding:10px 12px;border:1px solid #f0c36d;border-radius:6px;
					background:#fff9e6;margin-bottom:12px;font-size:12px;line-height:1.6">
			<b>${__("Same person in both fields.")}</b><br>
			${__(
				"This happens when a user who also holds an elevated role (System Manager, ExPOS Manager or ExPOS Captain) takes the payment: they are not treated as a waiter, so they get stamped as the cashier while still being pickable as the waiter."
			)}
		</div>`;
	}

	if (info.consolidated) {
		banner += `
		<div style="padding:10px 12px;border:1px solid #b3d4fc;border-radius:6px;
					background:#f0f7ff;margin-bottom:12px;font-size:12px;line-height:1.6">
			${__(
				"This bill has already been consolidated into the accounts. That is fine — the waiter and cashier fields carry no accounting, so correcting them only fixes the reports."
			)}
		</div>`;
	}

	const d = new frappe.ui.Dialog({
		title: __("Change Waiter / Cashier"),
		size: "small",
		fields: [
			{ fieldtype: "HTML", fieldname: "state", options: banner },
			{
				fieldtype: "Link",
				fieldname: "waiter",
				label: __("Waiter"),
				options: "URY Waiter",
				default: info.waiter || "",
				// Only offer waiters who are still active.
				get_query: () => ({ filters: { disabled: 0 } }),
				description: __("Clear this field to remove the waiter from the bill."),
			},
			{
				fieldtype: "Link",
				fieldname: "cashier",
				label: __("Cashier"),
				options: "User",
				default: info.cashier || "",
				get_query: () => ({ filters: { enabled: 1 } }),
				description: __("Who actually took the money. Clear to leave it unattributed."),
			},
			{
				fieldtype: "Small Text",
				fieldname: "reason",
				label: __("Reason"),
				description: __("Recorded in the invoice's comments alongside the change."),
			},
		],
		primary_action_label: __("Save Change"),
		primary_action(values) {
			// Send "" (clear) vs undefined (leave alone) deliberately — the
			// server treats those as different requests.
			const args = { invoice: frm.doc.name, reason: values.reason || null };
			const w = values.waiter || "";
			const c = values.cashier || "";
			if (w !== (info.waiter || "")) args.waiter = w;
			if (c !== (info.cashier || "")) args.cashier = c;

			if (args.waiter === undefined && args.cashier === undefined) {
				frappe.msgprint({
					title: __("Nothing Changed"),
					message: __("Pick a different waiter or cashier first."),
					indicator: "blue",
				});
				return;
			}

			frappe.call({
				method: "ury.ury_pos.api.update_invoice_attribution",
				args: args,
				freeze: true,
				freeze_message: __("Updating…"),
				callback(r) {
					if (!r || !r.message) return;
					d.hide();
					if (!r.message.changed) {
						frappe.show_alert({ message: r.message.message, indicator: "blue" });
						return;
					}
					frappe.show_alert({
						message: __("Attribution updated — {0}", [r.message.detail]),
						indicator: "green",
					});
					frm.reload_doc();
				},
			});
		},
	});

	if (cancelled) {
		d.set_primary_action(__("Save Change"), null);
		d.get_primary_btn().prop("disabled", true);
	}
	d.show();
}
