frappe.ui.form.on("Proof of Delivery", {
	bilty(frm) {
		const bilty = frm.doc.bilty;
		if (bilty) {
			frappe.db.get_value("Bilty", frm.doc.bilty, "total_quantity").then((r) => {
				if (frm.doc.bilty === bilty && r?.message) {
					frm.set_value("delivered_quantity", r.message.total_quantity);
				}
			});
		}
	},
});
