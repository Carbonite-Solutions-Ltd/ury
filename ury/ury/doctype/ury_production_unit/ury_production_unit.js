// Copyright (c) 2023, Tridz Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('URY Production Unit', {
	refresh: function (frm) {
		if (frm.is_new() || !frm.doc.production) return;
		frm.add_custom_button(__('Open Kitchen Display'), () => {
			const url = `/Mosaic/${encodeURIComponent(frm.doc.production)}`;
			window.open(url, '_blank', 'noopener');
		});
	},
});
