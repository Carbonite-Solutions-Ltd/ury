// "Add to ExPOS Menu" button on the Item form.
//
// Lets a user drop the current Item onto a URY Menu ("ExPOS Menu" via the
// translation layer) by picking the menu, an optional course, and a rate. The
// rate goes into the menu's own price list. If the item is already on the menu,
// the backend reports the rate/course changes and the user must confirm before
// they're applied.

frappe.ui.form.on("Item", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Add to ExPOS Menu"), () => {
			open_add_to_menu_dialog(frm);
		});
	},
});

function open_add_to_menu_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Add to ExPOS Menu"),
		fields: [
			{
				fieldname: "menu",
				fieldtype: "Link",
				options: "URY Menu",
				label: __("ExPOS Menu"),
				reqd: 1,
			},
			{
				fieldname: "course",
				fieldtype: "Link",
				options: "URY Menu Course",
				label: __("Course"),
			},
			{
				fieldname: "rate",
				fieldtype: "Currency",
				label: __("Rate"),
				description: __("Goes into the selected menu's price list."),
			},
			{ fieldname: "status_html", fieldtype: "HTML" },
		],
		primary_action_label: __("Create"),
		primary_action(values) {
			submit_add(frm, d, values, 0);
		},
	});

	// When a menu is picked, tell the user whether the item is already on it and
	// pre-fill its current rate/course so any edit is a deliberate change.
	d.fields_dict.menu.df.onchange = () => {
		const menu = d.get_value("menu");
		d.fields_dict.status_html.$wrapper.empty();
		if (!menu) return;

		frappe.call({
			method: "ury.ury.doctype.ury_menu.ury_menu.get_menu_item_details",
			args: { menu, item: frm.doc.name },
			callback(r) {
				const m = r.message || {};
				if (!m.exists) return;
				d.set_value("rate", m.rate);
				d.set_value("course", m.course);
				d.fields_dict.status_html.$wrapper.html(
					`<div class="text-muted" style="margin-top:4px">${__(
						"{0} is already on this menu — edit the rate or course to update it.",
						[frm.doc.item_name || frm.doc.name]
					)}</div>`
				);
			},
		});
	};

	d.show();
}

function submit_add(frm, d, values, confirm_update) {
	frappe.call({
		method: "ury.ury.doctype.ury_menu.ury_menu.add_item_to_menu",
		args: {
			item: frm.doc.name,
			menu: values.menu,
			course: values.course,
			rate: values.rate,
			confirm_update,
		},
		freeze: true,
		freeze_message: confirm_update ? __("Updating menu...") : __("Adding to menu..."),
		callback(r) {
			const res = r.message;
			if (r.exc || !res) return;
			const label = frm.doc.item_name || frm.doc.name;

			if (res.action === "added") {
				frappe.show_alert(
					{ message: __("{0} added to {1}", [label, values.menu]), indicator: "green" },
					5
				);
				d.hide();
			} else if (res.action === "updated") {
				frappe.show_alert(
					{ message: __("{0} updated on {1}", [label, values.menu]), indicator: "green" },
					5
				);
				d.hide();
			} else if (res.action === "unchanged") {
				frappe.show_alert(
					{
						message: __("{0} is already on {1} — no changes.", [label, values.menu]),
						indicator: "blue",
					},
					5
				);
				d.hide();
			} else if (res.action === "needs_confirmation") {
				const rows = (res.changes || [])
					.map(
						(c) =>
							`<tr><td><b>${__(c.field)}</b></td>` +
							`<td>${frappe.utils.escape_html(String(c.old))}</td>` +
							`<td>&rarr; ${frappe.utils.escape_html(String(c.new))}</td></tr>`
					)
					.join("");
				const msg =
					`<p>${__("{0} is already on {1}. Apply these changes?", [
						label,
						values.menu,
					])}</p>` +
					`<table class="table table-bordered" style="margin-top:8px">` +
					`<thead><tr><th>${__("Field")}</th><th>${__("Current")}</th><th>${__(
						"New"
					)}</th></tr></thead><tbody>${rows}</tbody></table>`;
				frappe.confirm(msg, () => submit_add(frm, d, values, 1));
			}
		},
	});
}
