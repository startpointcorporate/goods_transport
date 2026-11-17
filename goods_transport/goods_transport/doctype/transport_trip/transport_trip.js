const TRIP_STATUSES = [
	"Vehicle Assigned",
	"At Loading Point",
	"Loaded",
	"In Transit",
	"Arrived",
	"Unloading",
	"Delivered",
	"Settled",
	"Closed",
];

const PENDING_ORDER_STATUSES = ["Confirmed", "Partially Dispatched"];

frappe.ui.form.on("Transport Trip", {
	setup(frm) {
		// Trip's freight_item is the SI freight line item for every Bilty on
		// this trip. Filter to the seeded Freight Services group.
		frm.set_query("freight_item", () => ({
			filters: { item_group: "Freight Items" },
		}));
	},
	refresh(frm) {
		if (frappe.boot.goods_transport_trip_finance && !frm.is_new()) {
			frm.add_custom_button(__("Contrôle financier"), async () => {
				await frappe.require("/assets/goods_transport/js/trip_finance.js");
				goods_transport.trip_finance.open(frm);
			});
		}
		if (frm.doc.docstatus === 1 && frm.doc.status !== "Cancelled" && frm.doc.status !== "Closed") {
			frm.add_custom_button(
				__("Bilty"),
				() => {
					let d;
					d = new frappe.ui.Dialog({
						title: __("Create Bilty under {0}", [frm.doc.name]),
						fields: [
							{
								fieldname: "customer",
								label: __("Customer"),
								fieldtype: "Link",
								options: "Customer",
								reqd: 1,
								onchange: () => {
									// Reset order — old value would belong to the previous customer.
									if (d.get_value("transport_order")) {
										d.set_value("transport_order", "");
									}
								},
							},
							{
								fieldname: "transport_order",
								label: __("Transport Order"),
								fieldtype: "Link",
								options: "Transport Order",
								description: __(
									"Only submitted, still-open orders (Confirmed / Partially Dispatched) for the selected customer are shown.",
								),
								get_query: () => {
									const customer = d.get_value("customer");
									const filters = {
										docstatus: 1,
										status: ["in", PENDING_ORDER_STATUSES],
										company: frm.doc.company,
									};
									if (customer) {
										filters.customer = customer;
									}
									return { filters };
								},
								onchange: async () => {
									const order = d.get_value("transport_order");
									if (!order) return;
									const r = await frappe.db.get_value(
										"Transport Order",
										order,
										["rate", "rate_basis"],
									);
									const vals = (r && r.message) || {};
									if (vals.rate_basis && !d.get_value("rate_basis")) {
										d.set_value("rate_basis", vals.rate_basis);
									}
									if (vals.rate && !d.get_value("rate")) {
										d.set_value("rate", vals.rate);
									}
								},
							},
							{
								fieldname: "freight_item",
								label: __("Freight Item"),
								fieldtype: "Link",
								options: "Item",
								reqd: 1,
								default: frm.doc.freight_item || "",
								get_query: () => ({ filters: { item_group: "Freight Items" } }),
							},
							{
								fieldname: "rate_basis",
								label: __("Rate Basis"),
								fieldtype: "Select",
								options: "Per Trip\nPer Vehicle\nPer Ton\nPer Kg\nPer Package\nPer KM\nFixed",
								reqd: 1,
							},
							{ fieldname: "rate", label: __("Rate"), fieldtype: "Currency", reqd: 1 },
							{ fieldname: "freight_quantity", label: __("Freight Quantity"), fieldtype: "Float", default: 1 },
						],
						primary_action_label: __("Create Bilty"),
						primary_action(v) {
							frappe.call({
								method: "goods_transport.goods_transport.services.operations.create_bilty_from_trip",
								args: {
									transport_trip: frm.doc.name,
									customer: v.customer,
									transport_order: v.transport_order,
									freight_item: v.freight_item,
									rate: v.rate,
									rate_basis: v.rate_basis,
									freight_quantity: v.freight_quantity,
								},
								freeze: true,
								callback: (r) => {
									if (r.message) {
										d.hide();
										frappe.set_route("Form", "Bilty", r.message);
									}
								},
							});
						},
					});
					d.show();
				},
				__("Create"),
			);

			frm.add_custom_button(
				__("Advance Status"),
				() => {
					const later = TRIP_STATUSES.filter(
						(s) => s !== "Settled" && (s !== "Closed" || frm.doc.status === "Settled") &&
							TRIP_STATUSES.indexOf(s) > TRIP_STATUSES.indexOf(frm.doc.status),
					);
					if (!later.length) {
						frappe.msgprint(__("Already at final status."));
						return;
					}
					frappe.prompt(
						[
							{
								fieldname: "to_status",
								label: __("To Status"),
								fieldtype: "Select",
								options: later.join("\n"),
								reqd: 1,
							},
						],
						(v) => {
							frappe.call({
								method: "goods_transport.goods_transport.doctype.transport_trip.transport_trip.advance_status",
								args: { trip: frm.doc.name, to_status: v.to_status },
								callback: () => frm.reload_doc(),
							});
						},
						__("Advance Trip Status"),
					);
				},
				__("Actions"),
			);
		}
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(
				__("Bilties on this Trip"),
				() => frappe.set_route("List", "Bilty", { transport_trip: frm.doc.name }),
				__("View"),
			);
		}
		if (
			frm.doc.docstatus === 1 &&
			frm.doc.transporter &&
			frm.doc.agreed_vehicle_hire > 0 &&
			!frm.doc.purchase_invoice &&
			frm.doc.status !== "Cancelled"
		) {
			frm.add_custom_button(
				__("Transporter Purchase Invoice"),
				() => {
					const d = new frappe.ui.Dialog({
						title: __("Create Vehicle Hire PI for {0}", [frm.doc.name]),
						fields: [
							{ fieldname: "hire_item", label: __("Hire Item"), fieldtype: "Link", options: "Item", reqd: 1 },
							{ fieldname: "expense_account", label: __("Expense Account"), fieldtype: "Link", options: "Account", reqd: 1, get_query: () => ({ filters: { root_type: "Expense", company: frm.doc.company, is_group: 0 } }) },
							{ fieldname: "amount", label: __("Amount"), fieldtype: "Currency", default: frm.doc.agreed_vehicle_hire },
						],
						primary_action_label: __("Create PI"),
						primary_action(v) {
							frappe.call({
								method: "goods_transport.goods_transport.services.operations.create_transporter_purchase_invoice",
								args: {
									transport_trip: frm.doc.name,
									hire_item: v.hire_item,
									expense_account: v.expense_account,
									amount: v.amount,
								},
								freeze: true,
								callback: (r) => {
									if (r.message) {
										d.hide();
										frappe.set_route("Form", "Purchase Invoice", r.message);
									}
								},
							});
						},
					});
					d.show();
				},
				__("Create"),
			);
		}
		if (
			frm.doc.docstatus === 1 &&
			(frm.doc.status === "Delivered" || frm.doc.status === "Arrived" || frm.doc.status === "Unloading") &&
			!frm.doc.trip_settlement
		) {
			frm.add_custom_button(
				__("Trip Settlement"),
				() => {
					frappe.call({
						method: "goods_transport.goods_transport.doctype.trip_settlement.trip_settlement.create_settlement_for_trip",
						args: { trip: frm.doc.name },
						freeze: true,
						callback: (r) => {
							if (r.message) frappe.set_route("Form", "Trip Settlement", r.message);
						},
					});
				},
				__("Create"),
			);
		}
		if (frm.doc.purchase_invoice) {
			frm.add_custom_button(
				__("Vehicle Hire PI"),
				() => frappe.set_route("Form", "Purchase Invoice", frm.doc.purchase_invoice),
				__("View"),
			);
		}
		if (frm.doc.trip_settlement) {
			frm.add_custom_button(
				__("Trip Settlement"),
				() => frappe.set_route("Form", "Trip Settlement", frm.doc.trip_settlement),
				__("View"),
			);
		}
	},
});

frappe.ui.form.on("Transport Trip", {
	refresh(frm) {
		if (frappe.boot.goods_transport_truck_plan && !frm.is_new() && frm.doc.docstatus !== 2 && frm.doc.vehicle) {
			frm.add_custom_button(__("Plan de route poids lourd"), async () => {
				await frappe.require("/assets/goods_transport/js/truck_plan.js");
				goods_transport.truck_plan.open(frm);
			});
		}
	},
});

frappe.ui.form.on("Transport Trip", {
	refresh(frm) {
		if (!frappe.boot.goods_transport_partner_fuel || frm.is_new()) return;
		frm.add_custom_button(__("Autorisations"), () => frappe.set_route("List", "Fuel Authorization", {
			trip: frm.doc.name,
		}), __("Carburant"));
		if (frm.doc.docstatus === 2 || !frm.doc.vehicle || !frm.doc.driver || !frm.perm[0]?.write) return;
		frm.add_custom_button(__("Autoriser un retrait"), () => frappe.prompt([
			{ fieldname: "reserve_name", label: __("Réserve contractuelle"), fieldtype: "Link",
				options: "Fuel Contract Reserve", reqd: 1, default: frm.doc.fuel_stop_reserve,
				get_query: () => ({ filters: { company: frm.doc.company } }) },
			{ fieldname: "liters", label: __("Maximum en litres"), fieldtype: "Float", precision: 3, reqd: 1 },
			{ fieldname: "valid_from", label: __("Valide à partir de"), fieldtype: "Datetime",
				description: __("Laisser vide pour une validité immédiate.") },
			{ fieldname: "valid_until", label: __("Valide jusqu’au"), fieldtype: "Datetime", reqd: 1 },
		], async (values) => {
			const { message } = await frappe.call("goods_transport.goods_transport.services.fuel.authorize", {
				trip_name: frm.doc.name, ...values,
			});
			frappe.set_route("Form", "Fuel Authorization", message);
		}, __("Autoriser un ravitaillement")), __("Carburant"));
	},
});


frappe.ui.form.on("Transport Trip", {
	refresh(frm) {
		if (!frappe.boot.goods_transport_partner_fuel || frm.is_new() || !frm.perm[0]?.write
			|| frm.doc.docstatus === 2) return;
		const plan = JSON.parse(frm.doc.fuel_plan_inputs || "{}");
		if (!plan.signature || !plan.selected_reserves?.length || plan.authorization_codes) return;
		frm.add_custom_button(__("Autoriser les arrêts du plan"), () => frappe.prompt([
			{ fieldname: "valid_from", label: __("Valide à partir de"), fieldtype: "Datetime",
				description: __("Laisser vide pour une validité immédiate.") },
			{ fieldname: "valid_until", label: __("Valide jusqu’au"), fieldtype: "Datetime", reqd: 1 },
		], async (values) => {
			await frappe.call({
				method: "goods_transport.goods_transport.services.truck_plan.confirm_fuel_plan",
				args: { trip_name: frm.doc.name, signature: plan.signature, ...values }, freeze: true,
			});
			await frm.reload_doc();
			frappe.set_route("List", "Fuel Authorization", { trip: frm.doc.name });
		}, __("Autoriser les ravitaillements")), __("Carburant"));
	},
});
