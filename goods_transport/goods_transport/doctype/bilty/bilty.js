frappe.ui.form.on("Bilty", {
	setup(frm) {
		frm.set_query("transport_trip", () => ({ filters: { docstatus: ["!=", 2], company: frm.doc.company } }));
		frm.set_query("transport_order", () => {
			const filters = { docstatus: 1, company: frm.doc.company };
			if (frm.doc.customer) filters.customer = frm.doc.customer;
			return { filters };
		});
		// Cargo grid: only physical-cargo Items (Cargo Items group + descendants).
		// Applied via set_query on the child field so it fires on the row picker
		// every time the user adds or edits a row. Server-side validate() enforces.
		frm.set_query("item", "items", () => ({
			query: "goods_transport.goods_transport.services.cargo.cargo_item_query",
		}));
	},
	async transport_order(frm) {
		const order = frm.doc.transport_order;
		if (!order || frm.doc.docstatus !== 0) return;
		const { message } = await frappe.db.get_value("Transport Order", order, [
			"customer", "company", "origin", "destination", "loading_location", "delivery_location",
			"rate_basis", "rate", "currency", "pod_required",
		]);
		if (message && frm.doc.transport_order === order) await frm.set_value(message);
	},
	refresh(frm) {
		if (
			frappe.model.can_create("Proof of Delivery") && frappe.model.can_submit("Proof of Delivery") &&
			frm.doc.docstatus === 1 &&
			frm.doc.pod_required &&
			frm.doc.pod_status === "Pending"
		) {
			frm.add_custom_button(
				__("Record POD"),
				() => {
					frappe.prompt(
						[
							{
								fieldname: "delivered_quantity",
								label: __("Delivered Quantity"),
								fieldtype: "Float",
								default: frm.doc.total_quantity,
								reqd: 1,
							},
							{ fieldname: "receiver_name", label: __("Receiver Name"), fieldtype: "Data", reqd: 1 },
						],
						(v) => {
							frappe.call({
								method: "goods_transport.goods_transport.services.operations.create_pod_from_bilty",
								args: {
									bilty: frm.doc.name,
									delivered_quantity: v.delivered_quantity,
									receiver_name: v.receiver_name,
								},
								freeze: true,
								callback: (r) => {
									if (r.message) {
										frappe.msgprint(__("POD {0} created and submitted.", [r.message]));
										frm.reload_doc();
									}
								},
							});
						},
						__("Record Proof of Delivery"),
					);
				},
				__("Actions"),
			);
		}
		if (frm.doc.docstatus === 1 && !frm.doc.sales_invoice && frm.perm[0]?.write
			&& frappe.model.can_create("Sales Invoice") && (!frm.doc.pod_required || frm.doc.pod_status === "Received")) {
			frm.add_custom_button(
				__("Sales Invoice"),
				() => {
					frappe.call({
						method: "goods_transport.goods_transport.services.billing.create_sales_invoice_from_bilties",
						args: { bilties: [frm.doc.name] },
						freeze: true,
						freeze_message: __("Creating Sales Invoice..."),
						callback: (r) => {
							if (r.message) {
								frappe.set_route("Form", "Sales Invoice", r.message);
							}
						},
					});
				},
				__("Create"),
			);
		}
		if (frm.doc.sales_invoice && frappe.model.can_read("Sales Invoice")) {
			frm.add_custom_button(
				__("Sales Invoice"),
				() => frappe.set_route("Form", "Sales Invoice", frm.doc.sales_invoice),
				__("View"),
			);
		}
	},
});
