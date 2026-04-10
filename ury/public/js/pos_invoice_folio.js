// Shared folio-charge handlers — registered for both POS Invoice and Sales Invoice
// (Sales Invoice mode is activated via POS Profile → "Create Sales Invoice").
const _folio_events = {
	refresh(frm) {
		toggle_room_charge_fields(frm);
		set_ihotel_room_query(frm);
	},
	customer(frm) {
		if (frm.doc.custom_charge_to_room) {
			frm.set_value("custom_ihotel_room", null);
			frm.set_value("custom_ihotel_profile", null);
			frm.set_value("custom_guest", null);
		}
		set_ihotel_room_query(frm);
	},
	custom_charge_to_room(frm) {
		toggle_room_charge_fields(frm);
		if (!frm.doc.custom_charge_to_room) {
			frm.set_value("custom_ihotel_room", null);
			frm.set_value("custom_ihotel_profile", null);
			frm.set_value("custom_guest", null);
		}
		set_ihotel_room_query(frm);
	},
	custom_ihotel_room(frm) {
		if (!frm.doc.custom_ihotel_room) {
			frm.set_value("custom_ihotel_profile", null);
			frm.set_value("custom_guest", null);
			return;
		}

		frappe.call({
			method: "ury.ury.hooks.ury_pos_invoice.get_ihotel_folio_from_room",
			args: {
				customer: frm.doc.customer,
				room: frm.doc.custom_ihotel_room,
			},
			callback(r) {
				const row = r.message || {};
				frm.set_value("custom_ihotel_profile", row.profile || null);
				frm.set_value("custom_guest", row.guest || null);
			},
		});
	},
};

frappe.ui.form.on("POS Invoice", _folio_events);
// Sales Invoice mode: same fields, same server-side logic
frappe.ui.form.on("Sales Invoice", _folio_events);

function toggle_room_charge_fields(frm) {
	const enabled = !!frm.doc.custom_charge_to_room;
	frm.toggle_display("custom_ihotel_room", enabled);
	frm.toggle_display("custom_guest", enabled);
}

function set_ihotel_room_query(frm) {
	// Use filter key `guest` (not `customer`) so the link dropdown says "Guest is one of …" with guest names.
	frm.set_query("custom_ihotel_room", () => {
		if (!frm.doc.customer) {
			return { filters: { name: ["in", []] } };
		}
		let guest_ids = [];
		frappe.call({
			method: "ury.ury.hooks.ury_pos_invoice.get_pos_guest_names_for_charge_to_room",
			args: { customer: frm.doc.customer },
			async: false,
			callback(r) {
				guest_ids = r.message || [];
			},
		});
		return {
			query: "ury.ury.hooks.ury_pos_invoice.get_ihotel_rooms_for_customer_query",
			filters: { guest: ["in", guest_ids] },
		};
	});
}
