(() => {
	const links = {
		"Bilty": {
			transport_order: "Transport Order", transport_trip: "Transport Trip", rate_contract: "Transport Rate Contract",
		},
		"Proof of Delivery": { bilty: "Bilty", trip: "Transport Trip" },
		"Trip Advance": { trip: "Transport Trip", journal_entry: "Journal Entry" },
		"Trip Expense": { trip: "Transport Trip", trip_advance: "Trip Advance", journal_entry: "Journal Entry",
			purchase_invoice: "Purchase Invoice" },
		"Trip Settlement": { trip: "Transport Trip" },
	};

	for (const [doctype, fields] of Object.entries(links)) {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				if (frm.is_new()) return;
				for (const [field, target] of Object.entries(fields)) {
					if (!frm.doc[field] || !frappe.model.can_read(target)) continue;
					frm.add_custom_button(__(target), () => {
						const name = frm.doc[field];
						if (!frappe.get_doc(target, name)?.__unsaved) frappe.model.remove_from_locals(target, name);
						return frappe.set_route("Form", target, name);
					}, __("Related Documents"));
				}
			},
		});
	}
})();
