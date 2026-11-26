frappe.ui.form.on("Transport Order", {
	setup(frm) {
		// Commodity must be a physical-cargo Item — filter picker to the
		// Cargo Items group and its descendants. Server-side validate() is
		// the actual enforcement; this is the UX hint.
		frm.set_query("commodity", () => ({
			query: "goods_transport.goods_transport.services.cargo.cargo_item_query",
		}));
	},
	refresh(frm) {
		if (frappe.boot.goods_transport_route_preview && frm.doc.docstatus !== 2) {
			frm.add_custom_button(__("Itinéraire et péages"), () => {
				const dialog = new frappe.ui.Dialog({
					title: __("Préparer l’itinéraire"),
					fields: [
						{ fieldname: "origin", label: __("Départ"), fieldtype: "Link",
							options: "Transport Location", default: frm.doc.origin, reqd: 1 },
						{ fieldname: "via", label: __("Étape"), fieldtype: "Link", options: "Transport Location", default: frm.doc.via },
						{ fieldname: "destination", label: __("Arrivée"), fieldtype: "Link",
							options: "Transport Location", default: frm.doc.destination, reqd: 1 },
					],
					primary_action_label: __("Calculer"),
					async primary_action(values) {
						const { message } = await frappe.call({
							method: "goods_transport.goods_transport.services.toll_routing.preview_route",
							args: values, freeze: true,
						});
						if (frm.doc.docstatus === 0 && values.origin === frm.doc.origin && values.destination === frm.doc.destination) {
							await frm.set_value({
								via: values.via || null,
								estimated_distance: message.distance_m / 1000,
							});
						}
						await frappe.require("/assets/goods_transport/js/toll_map.js");
						dialog.hide();
						await goods_transport.toll_map.show(message);
					},
				});
				dialog.show();
			});
		}
		if (frm.doc.docstatus === 1 && ["Confirmed", "Partially Dispatched", "Fully Dispatched"].includes(frm.doc.status)
			&& (!frm.doc.dispatched_quantity || frm.doc.remaining_quantity > 0)
			&& frappe.model.can_create("Transport Trip")) {
			frm.add_custom_button(
				__("Transport Trip"),
				() => {
					const d = new frappe.ui.Dialog({
						title: __("Create Trip for Order {0}", [frm.doc.name]),
						fields: [
							{
								label: __("Vehicle"),
								fieldname: "vehicle",
								fieldtype: "Link",
								options: "Vehicle",
								get_query: () => ({ filters: { company: frm.doc.company } }),
								reqd: 1,
							},
							{
								label: __("Quantity Allocated"),
								fieldname: "quantity",
								fieldtype: "Float",
								default: Math.max(0, frm.doc.quantity - (frm.doc.dispatched_quantity || 0)) || undefined,
								description: __("Leave blank to use the remaining dispatchable quantity."),
							},
						],
						primary_action_label: __("Create Trip"),
						primary_action(values) {
							frappe.call({
								method: "goods_transport.goods_transport.services.operations.create_trip_from_order",
								args: {
									transport_order: frm.doc.name,
									vehicle: values.vehicle,
									quantity: values.quantity || undefined,
								},
								freeze: true,
								callback: (r) => {
									if (r.message) {
										d.hide();
										frappe.set_route("Form", "Transport Trip", r.message);
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

		if (!frm.is_new() && frappe.model.can_read("Transport Trip")) {
			frm.add_custom_button(__("Transport Trip"), async () => {
				const names = await frappe.xcall(
					"goods_transport.goods_transport.services.operations.get_order_trips", { transport_order: frm.doc.name },
				);
				if (!names.length) {
					frappe.msgprint(__("No missions are linked to this order."));
					return;
				}
				if (names.length === 1) frappe.set_route("Form", "Transport Trip", names[0]);
				else frappe.set_route("List", "Transport Trip", { name: ["in", names] });
			}, __("Related Documents"));
		}
	},
});
