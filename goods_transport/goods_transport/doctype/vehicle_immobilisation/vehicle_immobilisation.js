frappe.ui.form.on("Vehicle Immobilisation", {
	refresh(frm) {
		const canRelease = ["System Manager", "Stock Manager"].some(role => frappe.user.has_role(role));
		if (!frm.is_new() && !frm.doc.released_at && canRelease) {
			frm.add_custom_button(__("Return to Service"), async () => {
				if (frm.is_dirty()) await frm.save();
				await frappe.call({
					method: "goods_transport.goods_transport.doctype.vehicle_immobilisation.vehicle_immobilisation.release_vehicle",
					args: { name: frm.doc.name },
					freeze: true,
				});
				await frm.reload_doc();
			});
		}
	},
});
