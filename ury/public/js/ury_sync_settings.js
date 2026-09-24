/**
 * "Test Connection" on ExPOS Sync Settings.
 *
 * Runs ury.ury.sync.diagnostics.test_connection and renders the per-check
 * report, so an operator finds out whether the cloud site is reachable,
 * authenticated, running ExPOS and migrated BEFORE enabling sync on a live
 * branch — instead of discovering it as a queue row stuck in Retrying.
 *
 * Two deliberate behaviours:
 *
 *  1. It SAVES FIRST when the form is dirty. The API Secret is a Password
 *     field, and the server reads it with get_password() — an unsaved value
 *     is not readable, so testing a dirty form would test the previous
 *     credentials and report a confusing failure.
 *
 *  2. Every value from the remote is escaped before it reaches the dialog.
 *     Some detail strings include the remote's own response body, and that
 *     is not our HTML to trust.
 *
 * ⚠ Do NOT add frm.clear_custom_buttons() here. It takes no group argument
 * and wipes EVERY custom button on the form, including the standard Frappe
 * ones — see the 2026-06-10 User-form entry in CLAUDE.md.
 */

frappe.ui.form.on("URY Sync Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Test Connection"), () => runSyncConnectionTest(frm));
	},
});

function runSyncConnectionTest(frm) {
	// The secret has to be on the server before it can be read back.
	const ready = frm.is_dirty() ? frm.save() : Promise.resolve();

	Promise.resolve(ready)
		.then(() => {
			frappe.dom.freeze(__("Testing connection to the remote site..."));
			return frappe.call({
				method: "ury.ury.sync.diagnostics.test_connection",
			});
		})
		.then((r) => {
			frappe.dom.unfreeze();
			if (r && r.message) {
				showSyncTestResult(r.message);
			}
		})
		.catch(() => {
			// A thrown server error (e.g. the permission gate) is already
			// shown by Frappe's own error dialog; just clear the freeze.
			frappe.dom.unfreeze();
		});
}

function showSyncTestResult(result) {
	const esc = frappe.utils.escape_html;

	const tone = {
		pass: { color: "#059669", bg: "#ecfdf5", mark: "&#10003;" },
		fail: { color: "#b91c1c", bg: "#fef2f2", mark: "&#10007;" },
		warn: { color: "#b45309", bg: "#fffbeb", mark: "&#9888;" },
		skip: { color: "#6b7280", bg: "#f9fafb", mark: "&#8211;" },
	};

	const rows = (result.checks || [])
		.map((check) => {
			const t = tone[check.status] || tone.skip;
			const remedy = check.remedy
				? `<div style="margin-top:4px;font-size:12px;color:#374151;">
						&rarr; ${esc(check.remedy)}
				   </div>`
				: "";
			return `
				<div style="display:flex;gap:10px;padding:10px 12px;margin-bottom:6px;
							border-radius:6px;background:${t.bg};
							border:1px solid ${t.color}33;">
					<div style="color:${t.color};font-weight:700;line-height:1.3;">${t.mark}</div>
					<div style="flex:1;min-width:0;">
						<div style="font-weight:600;color:${t.color};">${esc(check.label)}</div>
						<div style="font-size:12px;color:#4b5563;margin-top:2px;
									word-break:break-word;">${esc(check.detail || "")}</div>
						${remedy}
					</div>
				</div>`;
		})
		.join("");

	const ok = !!result.ok;
	const banner = `
		<div style="padding:12px;margin-bottom:14px;border-radius:6px;
					background:${ok ? "#ecfdf5" : "#fef2f2"};
					border:1px solid ${ok ? "#05966933" : "#b91c1c33"};">
			<div style="font-weight:700;color:${ok ? "#059669" : "#b91c1c"};">
				${ok ? __("Ready to sync") : __("Not ready")}
			</div>
			<div style="font-size:12px;color:#4b5563;margin-top:3px;">
				${
					ok
						? __("Every check passed. Warnings, if any, are listed below.")
						: __("Fix the failed checks below, then test again.")
				}
				${
					result.remote_site
						? " " + __("Remote site:") + " <b>" + esc(result.remote_site) + "</b>"
					: ""
				}
			</div>
		</div>`;

	new frappe.ui.Dialog({
		title: __("Sync Connection Test"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				options: `<div style="max-height:60vh;overflow-y:auto;">${banner}${rows}</div>`,
			},
		],
		primary_action_label: __("Close"),
		primary_action(_values) {
			this.hide();
		},
	}).show();
}
