frappe.ui.form.on("Fuel Contract Reserve", {
	refresh(frm) {
		if (frm.is_new() || !frappe.model.can_create("Fuel Contract Reserve")) return;
		frm.add_custom_button(__("Créditer la réserve"), () => frappe.prompt([
			{ fieldname: "liters", label: __("Litres"), fieldtype: "Float", precision: 3, reqd: 1 },
			{ fieldname: "reference", label: __("Référence du crédit"), fieldtype: "Data", reqd: 1 },
		], async (values) => {
			await frappe.call({
				method: "goods_transport.goods_transport.services.fuel.credit",
				args: { reserve_name: frm.doc.name, ...values },
			});
			frm.reload_doc();
		}, __("Crédit de carburant")));
		frm.add_custom_button(__("Historique des crédits"), () => frappe.set_route("List", "Fuel Reserve Credit", {
			reserve: frm.doc.name,
		}));
		frm.add_custom_button(__("Historique des autorisations"), () => frappe.set_route("List", "Fuel Authorization", {
			reserve: frm.doc.name,
		}));
	},
});
