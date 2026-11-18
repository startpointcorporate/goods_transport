frappe.ui.form.on("Fuel Authorization", {
	refresh(frm) {
		if (frm.doc.status === "Reserved") {
			frm.add_custom_button(__("Annuler l’autorisation"), () => frappe.confirm(
				__("Libérer le carburant réservé ?"),
				async () => {
					await frappe.call("goods_transport.goods_transport.services.fuel.cancel", { code: frm.doc.name });
					frm.reload_doc();
				},
			));
		}
		if (frm.doc.status === "Consumed" && !frm.doc.trip_expense) {
			frm.add_custom_button(__("Rapprocher une dépense"), () => frappe.prompt([
				{ fieldname: "expense_name", label: __("Dépense"), fieldtype: "Link",
					options: "Trip Expense", reqd: 1, get_query: () => ({ filters: { trip: frm.doc.trip, docstatus: 1 } }) },
			], async (values) => {
				await frappe.call("goods_transport.goods_transport.services.fuel.attach_expense", {
					code: frm.doc.name, ...values,
				});
				frm.reload_doc();
			}, __("Rapprocher une dépense")));
		}
	},
});
