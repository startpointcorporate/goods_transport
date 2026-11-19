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
		if (frm.doc.docstatus === 1 && TRIP_STATUSES.indexOf(frm.doc.status) < TRIP_STATUSES.indexOf("Delivered")
			&& frappe.model.can_create("Vehicle Immobilisation")) {
			frm.add_custom_button(__("Report Breakdown"), () => frappe.new_doc("Vehicle Immobilisation", {
				vehicle: frm.doc.vehicle, company: frm.doc.company, transport_trip: frm.doc.name, reason: "Breakdown",
			}), __("Actions"));
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
		if (!frm.is_new() && frappe.boot.goods_transport_map_tiles) {
			frm.add_custom_button(__("View on map"), () => frappe.set_route("fleet-map", frm.doc.name));
		}
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

(() => {
	const service = "goods_transport.goods_transport.services.trip_inspection.";
	const call = (method, args) => frappe.xcall(service + method, args);
	const label = (row) => (frappe.boot.lang || "").startsWith("fr") ? row.label_fr : row.label_en;
	const statuses = ["Pass", "Fail", "Not Applicable", "Not Checked"];
	const severities = ["Minor", "Major", "Critical"];
	const generalViews = {front: __("Front"), rear: __("Rear"), left: __("Left"), right: __("Right"), cab: __("Cab"), tyres: __("Tyres")};
	const dialog = (title) => new frappe.ui.Dialog({title, size: "extra-large", fields: [{fieldtype: "HTML", fieldname: "panel"}]});
	const text = (parent, val, tag = "p") => $(document.createElement(tag)).text(val ?? "—").appendTo(parent);
	const button = (parent, title, handler) => $("<button>", {
		type: "button", class: "btn btn-default btn-sm mr-2 mb-2", text: title,
	}).on("click", handler).appendTo(parent);

	function showPhoto(container, photo) {
		if (!photo.file_url?.startsWith("/private/files/")) return;
		const layer = document.createElement("dialog");
		const image = $("<img>", {src: photo.file_url, alt: __("Inspection photograph"), loading: "lazy"})
			.css({width: "96px", height: "72px", objectFit: "cover"});
		const link = button(container, __("Enlarge photograph"), () => {
			$(layer).empty();
			button(layer, __("Close"), () => layer.close());
			image.clone().css({display: "block", width: "auto", height: "auto", maxWidth: "90vw", maxHeight: "80vh"}).appendTo(layer);
			layer.showModal();
		});
		link.empty().append(image).attr("aria-label", __("Enlarge photograph"));
		container.append(layer);
	}

	function photos(container, doc, control, editable) {
		const list = $("<div>").appendTo(container);
		function preview(photo) {
			const group = $("<span>", {class: "d-inline-flex align-items-center"}).appendTo(list);
			showPhoto(group, photo);
			if (editable && photo.inspection === doc.name) {
				button(group, __("Remove Photograph"), async () => {
					await call("remove_photo", {inspection: doc.name, photo: photo.name});
					doc.photos = doc.photos.filter((item) => item.name !== photo.name);
					group.remove();
				});
			}
		}
		for (const photo of doc.photos.filter((photo) => photo.attached_to_field === control)) preview(photo);
		if (!editable) return;
		for (const camera of [true, false]) {
			const input = $("<input>", {type: "file", accept: "image/jpeg,image/png,image/webp", hidden: true}).appendTo(container);
			if (camera) input.attr("capture", "environment");
			const select = button(container, camera ? __("Take Photograph") : __("Import Photograph"), () => input.trigger("click"));
			input.on("change", async () => {
				if (!input[0].files[0]) return;
				const form = new FormData();
				form.append("file", input[0].files[0]);
				form.append("inspection", doc.name);
				form.append("control", control);
				select.prop("disabled", true);
				try {
					const response = await fetch("/api/method/" + service + "upload_photo", {
						method: "POST", headers: {"X-Frappe-CSRF-Token": frappe.csrf_token}, body: form,
					});
					if (!response.ok) throw new Error("Upload failed");
					const {message} = await response.json();
					doc.photos.push(message);
					preview(message);
				} catch {
					frappe.msgprint(__("The photograph could not be uploaded."));
				} finally {
					select.prop("disabled", false);
					input.val("");
				}
			});
		}
	}

	function showInspection(doc, title) {
		const modal = dialog(title);
		const body = modal.fields_dict.panel.$wrapper;
		text(body, [doc.trip, doc.plate || doc.vehicle, doc.driver, doc.location].filter(Boolean).join(" · "), "h5");
		text(body, __("Inspected by {0} on {1}", [doc.inspector, frappe.datetime.str_to_user(doc.created)]));
		if (doc.validated_at) {
			text(body, __("Validated by {0} on {1}", [doc.validated_by, frappe.datetime.str_to_user(doc.validated_at)]));
		}
		if (doc.departure) text(body, __("Departure inspection {0} · {1} km", [doc.departure, doc.departure_odometer]));
		let position = doc.position;
		if (!doc.submitted) {
			button(body, __("Record GPS Position"), () => {
				if (!navigator.geolocation) return frappe.msgprint(__("GPS position is unavailable."));
				navigator.geolocation.getCurrentPosition(({coords}) => {
					const {latitude, longitude, accuracy} = coords;
					position = {latitude, longitude, accuracy};
					frappe.show_alert(__("GPS position recorded."));
				}, () => frappe.msgprint(__("GPS position is unavailable.")));
			});
		}
		const formField = (title, input, container = body) => {
			const wrapper = $("<label>", {class: "d-block mb-2"}).appendTo(container);
			text(wrapper, title, "span");
			return input.addClass("form-control").appendTo(wrapper);
		};
		const odometer = formField(__("Actual Odometer (km)"), $("<input>", {inputmode: "numeric", value: doc.odometer}));
		const observations = formField(__("General Observations"), $("<textarea>", {rows: 2}).css("min-height", "3rem").val(doc.observations || ""));
		const inputs = {};
		function select(options, value) {
			const field = $("<select>");
			for (const option of options) $("<option>", {value: option, text: __(option)}).appendTo(field);
			return field.val(value);
		}
		for (const row of doc.controls) {
			const section = $("<fieldset>", {class: "border rounded p-3 mb-3", "data-control": row.code}).appendTo(body);
			text(section, label(row), "h5");
			const available = statuses.filter((value) => value !== "Not Applicable" || row.allow_na);
			const result = formField(__("Result"), select(available, row.result || "Not Checked"), section);
			const issue = $("<div>").appendTo(section);
			const severity = formField(__("Severity"), select(["", ...severities], row.severity || ""), issue);
			const defect = formField(__("Defect Code"), $("<input>", {value: row.defect || ""}), issue);
			const observation = formField(__("Observation"), $("<textarea>", {rows: 2}).css("min-height", "3rem").val(row.observation || ""), section);
			result.on("change", () => issue.toggle(result.val() === "Fail")).trigger("change");
			if (row.min_photos) text(section, __("Required photographs: {0}", [row.min_photos]));
			photos(section, doc, row.code, !doc.submitted);
			inputs[row.code] = {result, severity, defect, observation};
		}
		text(body, __("Recommended General Views"), "h5");
		for (const [key, title] of Object.entries(generalViews)) {
			text(body, title, "h6");
			photos(body, doc, key, !doc.submitted);
		}
		if (doc.submitted) {
			body.find("input, textarea, select").prop("disabled", true);
			text(body, __("Validated"));
			if (doc.revisions.length) {
				text(body, __("Inspection History"), "h5");
				for (const revision of doc.revisions) {
					button(body, [revision.name, revision.correction_reason].filter(Boolean).join(" · "), async () => {
						const historical = await call("read_inspection", {inspection: revision.name});
						modal.hide();
						showInspection(historical, title);
					});
				}
			}
			if (doc.controls.some((row) => row.result === "Fail")) {
				button(body, doc.repair || doc.maintenance_task ? __("Open Repair") : __("Create Maintenance Repair"), async () => {
					const repair = await call("create_repair", {inspection: doc.name});
					modal.hide();
					frappe.set_route("Form", repair.doctype, repair.name);
				});
			}
			if (frappe.user.has_role("System Manager") && doc.revisions[0]?.name === doc.name) {
				button(body, __("Administrative Correction"), () => frappe.prompt(
					[{fieldname: "reason", label: __("Correction Reason"), fieldtype: "Small Text", reqd: 1}],
					async ({reason}) => {
						const next = await call("open_inspection", {trip: doc.trip, phase: doc.phase, correction_reason: reason});
						modal.hide();
						showInspection(next, title);
					}, __("Administrative Correction"), __("Continue")
				));
			}
		} else {
			modal.set_primary_action(__("Validate Inspection"), async () => {
				const results = Object.fromEntries(Object.entries(inputs).map(([code, fields]) => [
					code, Object.fromEntries(Object.entries(fields).map(([key, field]) => [key, field.val()])),
				]));
				const updated = await call("validate_inspection", {
					inspection: doc.name, odometer: odometer.val(), results: JSON.stringify(results),
					observations: observations.val(), position: JSON.stringify(position),
				});
				modal.hide();
				showInspection(updated, title);
			});
		}
		modal.show();
	}

	function showComparison(data) {
		const modal = dialog(__("Compare Vehicle Inspections"));
		const body = modal.fields_dict.panel.$wrapper;
		text(body, data.trip, "h4");
		for (const [title, value] of [
			[__("Departure Inspection"), data.before ? __("Validated") : __("Missing")],
			[__("Return Inspection"), data.after ? __("Validated") : __("Missing")],
			[__("Actual Distance (km)"), data.distance],
			[__("Controls Checked"), data.rows.filter((row) => row.evolution !== "Not Checked").length],
			[__("New Defects"), data.rows.filter((row) => row.evolution === "New Defect").length],
			[__("Existing Defects"), data.rows.filter((row) => row.evolution === "Existing Defect").length],
			[__("Vehicle Compliance"), __(data.vehicle)],
			[__("Operational Compliance"), __(data.operational)],
			[__("Overall Result"), __(data.overall)],
		]) {
			text(body, title + " · " + (value ?? "—"));
		}
		const general = $("<section>", {class: "border rounded p-3 mb-2"}).appendTo(body);
		text(general, __("Recommended General Views"), "h5");
		for (const [key, title] of Object.entries(generalViews)) {
			if (!data.before?.photos.some((photo) => photo.attached_to_field === key)
				&& !data.after?.photos.some((photo) => photo.attached_to_field === key)) continue;
			text(general, title, "h6");
			const columns = $("<div>", {class: "row mb-3"}).appendTo(general);
			for (const [phase, heading] of [["before", __("Departure")], ["after", __("Return")]]) {
				const column = $("<div>", {class: "col-6"}).appendTo(columns);
				text(column, heading);
				if (data[phase]) photos(column, data[phase], key, false);
			}
		}
		for (const row of data.rows) {
			const control = $("<section>", {class: "border rounded p-3 mb-2"}).appendTo(body);
			text(control, label(row) + " · " + __(row.evolution), "h5");
			const columns = $("<div>", {class: "row"}).appendTo(control);
			for (const [phase, title] of [["before", __("Departure")], ["after", __("Return")]]) {
				const column = $("<div>", {class: "col-6"}).appendTo(columns);
				text(column, title, "h6");
				text(column, row[phase] ? __(row[phase].result) : __("Not Checked"));
				if (row[phase]?.observation) text(column, row[phase].observation);
				if (data[phase]) photos(column, data[phase], row.code, false);
			}
		}
		modal.show();
	}

	frappe.ui.form.on("Transport Trip", {
		refresh(frm) {
			if (frm.doc.docstatus !== 1 || !frm.doc.inspection_policy) return;
			for (const [phase, title] of [["Departure", __("Departure Inspection")], ["Return", __("Return Inspection")]]) {
				frm.add_custom_button(title, async () => showInspection(
					await call("open_inspection", {trip: frm.doc.name, phase}), title
				));
			}
			frm.add_custom_button(__("Compare Vehicle Inspections"), async () => showComparison(
				await call("compare", {trip: frm.doc.name})
			));
		},
	});
})();
