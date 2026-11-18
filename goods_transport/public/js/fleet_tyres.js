frappe.ui.form.on("Vehicle", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Tyres"), () => show_tyres(frm));
		}
	},
});

async function show_tyres(frm) {
	const vehicle = frm.doc.name;
	const request = (operation, args = {}) => frappe.xcall(
		"goods_transport.goods_transport.services.fleet_tyres." + operation, { vehicle, ...args }
	);
	const overview = await request("overview");
	const dialog = new frappe.ui.Dialog({ title: __("Fleet Tyres"), size: "large" });
	const body = $("<div>").appendTo(dialog.body);
	const writable = frm.perm[0]?.write;

	function action(container, label, fn) {
		return $("<button>", { type: "button", class: "btn btn-default btn-sm mr-2 mb-2" })
			.text(__(label)).on("click", fn).appendTo(container);
	}
	function submit(title, fields, method, extra = {}) {
		const form = new frappe.ui.Dialog({
			title: __(title), fields, primary_action_label: __("Confirm"),
			async primary_action(values) {
				await request(method, { ...extra, ...values });
				form.hide();
				dialog.hide();
				await show_tyres(frm);
			},
		});
		form.show();
	}
	const input = (fieldname, label, fieldtype = "Data", options, reqd = 1, default_value) => ({
		fieldname, label: __(label), fieldtype, options, reqd, default: default_value,
	});

	async function fit(position, operation) {
		const fields = [
			input("odometer", "Actual odometer (km)", "Int", undefined, 1, overview.odometer),
			input("recorded_at", "Performed at", "Datetime", undefined, 1, overview.operation_time),
		];
		if (["Mount", "Replace"].includes(operation)) {
			const available = await request("available_tyres");
			fields.push(input("tyre", "Tyre", "Select", [
				{ value: "", label: "" },
				...available.map(tyre => ({ value: tyre.name, label: tyre.reference })),
			]));
		}
		if (["Mount", "Remove"].includes(operation)) {
			fields.push(input("warehouse", "Destination warehouse", "Link", "Warehouse"));
		}
		if (operation === "Replace") {
			fields.push(input("notes", "Replacement reason", "Small Text"));
			fields.push(input("warehouse", "Retired tyre holding warehouse", "Link", "Warehouse", 0));
		}
		if (operation === "Rotate") {
			const empty = overview.positions.filter(slot => !slot.active_tyre);
			fields.push(input("destination", "Destination position", "Select", [
				{ value: "", label: "" },
				...empty.map(slot => ({ value: slot.name, label: slot.axle + " · " + slot.label })),
			]));
		}
		submit(operation, fields, "fit", { position: position.name, operation });
	}

	if (writable) {
		action(body, "Add position", () => submit("Add position", [
			input("axle", "Axle", "Int"),
			input("label", "Position"),
		], "add_position"));
		action(body, "Register tyre", () => submit("Register tyre", [
			input("reference", "Individual reference"),
			input("serial_no", "ERPNext serial number", "Link", "Serial No"),
			input("manufacturer_serial", "Manufacturer serial number", "Data", undefined, 0),
			input("dimension", "Dimension"),
		], "register"));
	}

	if (["Accounts Manager", "Accounts User", "System Manager"].some(role => frappe.user.has_role(role))) {
		action(body, "Tyre costs", async () => {
			const costs = await request("costs");
			const report = new frappe.ui.Dialog({ title: __("Tyre costs") });
			const format_cost = value => value == null ? "—" :
				format_currency(value, costs.currency);
			$("<p>").text(__("Vehicle tyre cost {0}", [
				format_cost(costs.allocated_acquisition_cost + costs.vehicle_service_cost),
			])).appendTo(report.body);
			for (const row of costs.rows) {
				$("<p>").text([
					row.reference, row.vehicle_distance + " km",
					format_cost(row.allocated_acquisition_cost),
					format_cost(row.cost_per_km) + "/km",
				].join(" · ")).appendTo(report.body);
			}
			if (writable && costs.rows.length) {
				action(report.body, "Allocate service invoice line", () => {
					const fields = [
						input("tyre", "Tyre", "Select", costs.rows.map(row => ({
							value: row.tyre, label: row.reference,
						}))),
						input("invoice", "Purchase invoice", "Link", "Purchase Invoice"),
						input("invoice_item", "Service invoice line", "Select", [""]),
						input("category", "Cost category", "Select", ["Installation", "Repair", "Maintenance"]),
					];
					const form = new frappe.ui.Dialog({
						title: __("Allocate service invoice line"), fields,
						primary_action_label: __("Confirm"),
						async primary_action(values) {
							await request("allocate_expense", values);
							form.hide();
							report.hide();
							dialog.hide();
							await show_tyres(frm);
						},
					});
					form.fields_dict.invoice.df.onchange = async () => {
						const invoice = form.get_value("invoice");
						const lines = invoice ? await request("service_invoice_items", { invoice }) : [];
						form.set_df_property("invoice_item", "options", [
							{ value: "", label: "" },
							...lines.map(line => ({
								value: line.name, label: line.label + " · " + format_cost(line.amount),
							})),
						]);
					};
					form.show();
				});
			}
			report.show();
		});
	}

	let last_axle;
	let axle;
	for (const position of overview.positions) {
		if (position.axle !== last_axle) {
			axle = $("<section>", { class: "border rounded p-3 mb-3" }).appendTo(body);
			$("<h5>").text(__("Axle {0}", [position.axle])).appendTo(axle);
			last_axle = position.axle;
		}
		const row = $("<div>", { class: "mb-2" }).appendTo(axle);
		const tyre = position.tyre;
		const details = tyre
			? [tyre.reference, __(tyre.state), position.distance + " km", position.installed_at]
			: [__("Empty")];
		if (position.inspection_due) details.push(__("Inspection due"));
		$("<p>", { class: "mb-1" }).text([position.label, ...details].join(" · ")).appendTo(row);
		if (tyre) {
			$("<p>", { class: "text-muted small mb-1" }).text([
				tyre.item?.brand, tyre.item?.item_name, tyre.dimension, tyre.serial_no,
			].filter(Boolean).join(" · ")).appendTo(row);
		}
		if (tyre) {
			action(row, "History", () => show_history(position.active_tyre, tyre.reference));
		}
		if (writable && tyre) {
			for (const operation of ["Replace", "Remove", "Rotate"]) {
				action(row, operation, () => fit(position, operation));
			}
			action(row, "Inspection", () => submit("Inspection", [
				input("inspection_type", "Intervention type", "Select", [
					"Visual Inspection", "Pressure Check", "Tread Inspection", "Repair", "Puncture",
				]),
				input("notes", "Observations", "Small Text"),
				input("interval_days", "Inspection interval (days)", "Data", undefined, 0),
				input("interval_km", "Inspection interval (km)", "Data", undefined, 0),
			], "inspect", { position: position.name }));
		} else if (writable) {
			action(row, "Mount", () => fit(position, "Mount"));
		}
	}
	if (overview.historic.length) {
		$("<h5>").text(__("Tyre history")).appendTo(body);
		for (const tyre of overview.historic) {
			action(body, tyre.reference, () => show_history(tyre.name, tyre.reference));
			if (writable && tyre.state === "Removed") {
				action(body, __("Inspect {0} for return to service", [tyre.reference]), () =>
					submit("Return-to-service inspection", [
						input("notes", "Observations", "Small Text"),
					], "approve_removed", { tyre: tyre.name }));
			}
			if (writable && tyre.awaiting_disposal) {
				action(body, __("Scrap {0}", [tyre.reference]), () => submit("Scrap tyre", [
					input("notes", "Disposal reason", "Small Text"),
				], "scrap", { tyre: tyre.name }));
			}
		}
	}

	async function show_history(name, reference) {
		const events = await request("history", { tyre: name });
		const history = new frappe.ui.Dialog({ title: reference });
		for (const event of events) {
			$("<p>").text([
				__(event.operation), event.inspection_type, event.recorded_at, event.odometer + " km", event.notes,
			].filter(Boolean).join(" · ")).appendTo(history.body);
		}
		history.show();
	}

	dialog.show();
}
