frappe.provide("goods_transport.truck_plan");

goods_transport.truck_plan.open = function (frm) {
	const saved = frappe.boot.goods_transport_partner_fuel ? JSON.parse(frm.doc.fuel_plan_inputs || "{}") : {};
	const dialog = new frappe.ui.Dialog({
		title: __("Préparer le trajet poids lourd"),
		fields: [
			{ fieldname: "vehicle", label: __("Camion"), fieldtype: "Data", read_only: 1, default: frm.doc.vehicle },
			{ fieldname: "via", label: __("Étape intermédiaire"), fieldtype: "Link", options: "Transport Location", default: saved.via },
			{ fieldname: "cargo_kg", label: __("Charge prévue (kg)"), fieldtype: "Float", reqd: 1,
				default: saved.cargo_kg ?? (frm.doc.loaded_weight || 0) },
			{ fieldname: "cargo_m3", label: __("Volume prévu (m³)"), fieldtype: "Float", reqd: 1, default: saved.cargo_m3 },
			{ fieldname: "axle_loads", label: __("Charges par groupe d’essieux (kg)"), fieldtype: "Data", default: saved.axle_loads,
				description: __("Dans l’ordre du véhicule, séparées par un point-virgule. Facultatif.") },
			...(frappe.boot.goods_transport_partner_fuel ? [{
				fieldname: "departure_liters", label: __("Niveau estimé au départ (L)"), fieldtype: "Float",
				default: saved.departure_liters,
				description: __("Renseigner ce niveau pour calculer l’autonomie et les arrêts carburant."),
			}] : []),
		],
		primary_action_label: __("Calculer le plan"),
		async primary_action(values) {
			const args = { trip_name: frm.doc.name, ...values };
			if (values.departure_liters == null || values.departure_liters === "") delete args.departure_liters;
			const inputsMatch = ["cargo_kg", "cargo_m3", "departure_liters", "via", "axle_loads"].every(
				(key) => String(saved[key] ?? "") === String(values[key] ?? ""));
			if ("departure_liters" in args && inputsMatch && frm.doc.fuel_stop_reserve && !saved.authorization_codes) {
				args.selected_reserves = saved.selected_reserves || [frm.doc.fuel_stop_reserve];
			}
			if (inputsMatch && saved.authorization_codes && "departure_liters" in args) args.confirmed = true;
			const { message } = await frappe.call({
				method: "goods_transport.goods_transport.services.truck_plan.preview",
				args,
				freeze: true,
			});
			await frappe.require(["leaflet.bundle.js", "leaflet.bundle.css"]);
			dialog.hide();
			goods_transport.truck_plan.show(message, frm, args);
		},
	});
	dialog.show();
};

goods_transport.truck_plan.show = function (plan, frm, args) {
	const dialog = new frappe.ui.Dialog({
		title: __("Plan de route poids lourd"),
		size: "extra-large",
		fields: [{ fieldname: "content", fieldtype: "HTML" }],
	});
	const body = dialog.fields_dict.content.$wrapper;
	const km = (route) => (route.distance / 1000).toFixed(1);
	const minutes = (route) => Math.round(route.duration / 60);
	$("<p>").text(__("Poids lourd {0} km · {1} min | Voiture {2} km · {3} min", [
		km(plan.truck), minutes(plan.truck), km(plan.car), minutes(plan.car),
	])).appendTo(body);
	$("<p>").text(__("Classe LCR {0} · Poids total en charge {1} kg", [plan.class, plan.gross_kg])).appendTo(body);
	$("<p>").text(__("Itinéraire indicatif. Confirmer les restrictions locales et passer par les postes de pesage.")).appendTo(body);
	if (!plan.axle_loads_entered) $("<p>").text(__("Charges aux essieux à vérifier.")).appendTo(body);
	const canvas = $("<div>").css({ height: "340px", background: "#edf2f6" }).appendTo(body);
	$("<p>").addClass("mt-2").text(__("Bleu · poids lourd / Gris pointillé · voiture")).appendTo(body);
	const list = $("<ol>").appendTo(body);
	const format = (value) => new Intl.NumberFormat("fr-CG").format(value) + " XAF";
	$("<p>").addClass("font-weight-bold").text(__("Sous-total estimé des tarifs connus {0} · {1} tarif(s) indisponible(s)", [
		format(plan.known_subtotal), plan.missing_tariffs,
	])).appendTo(body);
	$("<p>").text(__("Passages estimés à partir du tracé. Le coût final dépend du franchissement et du tarif en gare.")).appendTo(body);

	dialog.show();
	const map = L.map(canvas[0]);
	L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
		maxZoom: 19,
		attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
	}).addTo(map);
	const path = (route, style) => L.polyline(
		route.geometry.coordinates.map(([lon, lat]) => [lat, lon]), style,
	).addTo(map);
	const truck = path(plan.truck, { color: "#1765ab", weight: 6 });
	path(plan.car, { color: "#737d8a", dashArray: "3, 6", weight: 3 });
	for (const toll of plan.tolls) {
		const label = [toll.name, __("Passage estimé"), toll.amount == null ?
			__("Tarif indisponible") : format(toll.amount)].join(" · ");
		$("<li>").text(label).appendTo(list);
		L.circleMarker([toll.latitude, toll.longitude], { radius: 7, color: "#9b4e13" }).addTo(map)
			.bindTooltip($("<span>").text(label)[0]);
	}
	if (plan.fuel) {
		const fuel = plan.fuel;
		$("<p>").text(__("{0} · Autonomie au départ {1} km · Consommation prévue {2} L · Autorisés {3} L · Retirés {4} L", [
			fuel.fuel_type, fuel.range_km.toFixed(1), fuel.required_liters.toFixed(1),
			fuel.authorized_liters, fuel.delivered_liters,
		])).appendTo(body);
		if (!fuel.feasible) {
			$("<p>").text(__("Aucune combinaison d’arrêts exploitable avec les réserves et le parcours évalués.")).appendTo(body);
		} else if (!fuel.stops.length) {
			$("<p>").text(__("Aucun ravitaillement nécessaire.")).appendTo(body);
		} else {
			$("<p>").text(__("Détour total {0} km · Dernier tronçon {1} km · Carburant à destination {2} L", [
				fuel.detour_km.toFixed(1), fuel.last_leg_km.toFixed(1), fuel.destination_liters.toFixed(3),
			])).appendTo(body);
			$("<p>").text(fuel.cost == null ? __("Coût carburant incomplet. Certains prix sont indisponibles.")
				: __("Coût estimé du carburant {0} {1}", [fuel.cost.toFixed(2), fuel.currency])).appendTo(body);
			if (fuel.total_cost != null) $("<p>").text(__("Total carburant et péages {0} {1}", [
				fuel.total_cost.toFixed(2), fuel.currency,
			])).appendTo(body);
			$("<p>").text(fuel.cost_ranked
				? __("Classement par détour, puis coût lorsque les prix sont comparables.")
				: __("Classement par détour, puis nombre d’arrêts.")).appendTo(body);
		}
		const projection = fuel.actual_projection;
		if (projection?.first_shortfall) {
			const gap = projection.first_shortfall;
			$("<p>").addClass("text-danger").text(gap.location
				? __("Autonomie insuffisante avant {0} · manque {1} L", [gap.location, gap.liters.toFixed(3)])
				: __("Autonomie insuffisante avant la destination · manque {0} L", [gap.liters.toFixed(3)]))
				.appendTo(body);
		}
		const rows = $("<ol>").attr("data-fuel-stops", "").appendTo(body);
		for (const [index, stop] of fuel.stops.entries()) {
			const label = __("{0} · {1} km · arrivée {2} L · retrait {3} L · départ {4} L · autonomie {5} km", [
				stop.station, stop.leg_km.toFixed(1), stop.arrival_liters.toFixed(3), stop.refill_liters.toFixed(3),
				stop.departure_liters.toFixed(3), stop.range_km.toFixed(1),
			]);
			const row = $("<li>").addClass("mb-2").text(label + " ").appendTo(rows);
			const actual = projection?.stops[index];
			if (actual) $("<div>").addClass("small text-muted").text(
				__("Projection actualisée · arrivée {0} L · retrait {1} L · départ {2} L · autonomie {3} km", [
					actual.arrival_liters.toFixed(3), actual.withdrawal_liters.toFixed(3),
					actual.departure_liters.toFixed(3), actual.range_km.toFixed(1),
				])
			).appendTo(row);
			L.marker([stop.latitude, stop.longitude], {
				icon: L.divIcon({ className: "badge badge-success", html: String(index + 1), iconSize: [22, 22] }),
			}).addTo(map).bindTooltip($("<span>").text(label)[0]);
			const gps = new URL("https://www.google.com/maps/dir/");
			gps.search = new URLSearchParams({ api: "1", destination: `${stop.latitude},${stop.longitude}` });
			$("<a>").attr({ href: gps.href, target: "_blank", rel: "noopener" }).text(__("Guidage GPS")).appendTo(row);
		}
		if (fuel.limited) $("<p>").text(__("Recherche limitée aux réserves les plus proches du trajet.")).appendTo(body);
		if (!fuel.confirmed && (fuel.alternatives.length > 1 || (!fuel.feasible && args.selected_reserves))) {
			const selector = $("<select>").attr("aria-label", __("Ajuster les arrêts"))
				.addClass("form-control mb-2").appendTo(body);
			$("<option>").val("").text(__("Choisir une autre combinaison")).appendTo(selector);
			for (const option of fuel.alternatives) {
				$("<option>").val(JSON.stringify(option.reserves)).text(
					`${option.stations.join(" → ")} · ${option.detour_km.toFixed(1)} km`
				).appendTo(selector);
			}
			selector.on("change", async () => {
				if (!selector.val()) return;
				const adjusted = { ...args, selected_reserves: JSON.parse(selector.val()) };
				const { message } = await frappe.call({
					method: "goods_transport.goods_transport.services.truck_plan.preview", args: adjusted, freeze: true,
				});
				dialog.hide();
				goods_transport.truck_plan.show(message, frm, adjusted);
			});
		}
		if (fuel.confirmed) {
			$("<p>").text(__("Prévision du plan déjà autorisé.")).appendTo(body);
		} else if (fuel.feasible && fuel.stops.length && frm.perm[0]?.write && frm.doc.docstatus !== 2) {
			const { selected_reserve, confirmed, ...inputs } = args;
			const reserves = fuel.stops.map((stop) => stop.reserve);
			$("<button>").attr("type", "button").addClass("btn btn-default mr-2").text(__("Enregistrer le plan"))
				.appendTo(body).on("click", async () => {
					await frappe.call({
						method: "goods_transport.goods_transport.services.truck_plan.save_fuel_plan",
						args: { ...inputs, selected_reserves: reserves }, freeze: true,
					});
					await frm.reload_doc();
					frappe.show_alert(__("Plan enregistré. Les réserves sont disponibles jusqu’à l’autorisation."));
					dialog.hide();
				});
		}
	}
	const frame = () => { map.invalidateSize(); map.fitBounds(truck.getBounds().pad(0.10)); };
	dialog.$wrapper.one("shown.bs.modal", frame).one("hidden.bs.modal", () => map.remove());
	frame();
};
