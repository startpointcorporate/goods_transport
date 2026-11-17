frappe.pages["fuel-dispensing"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Ravitaillement partenaire"), single_column: true });
	const input = page.add_field({ fieldname: "code", label: __("Code d’autorisation"), fieldtype: "Data" });
	const details = $("<p>").addClass("p-3").appendTo(page.main);

	page.set_primary_action(__("Vérifier"), async () => {
		details.empty();
		const code = input.get_value().trim();
		if (!code) return;
		const { message } = await frappe.call("goods_transport.goods_transport.services.fuel.verify", { code });
		details.text(__("Camion {0} · Chauffeur {1} · {2} · Maximum {3} L · Valable jusqu’au {4}", [
			message.vehicle, message.driver, message.fuel_type, message.authorized_liters, message.valid_until,
		]));
		frappe.prompt([
			{ fieldname: "liters", label: __("Litres réellement délivrés"), fieldtype: "Float", precision: 3, reqd: 1 },
		], async ({ liters }) => {
			await frappe.call("goods_transport.goods_transport.services.fuel.dispense", { code, liters });
			input.set_value("");
			details.text(__("Retrait confirmé · {0} L", [liters]));
		}, __("Confirmer le retrait"), __("Enregistrer"));
	});
};
