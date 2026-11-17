frappe.provide("goods_transport.truck_plan");

goods_transport.truck_plan.open = function (frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Préparer le trajet poids lourd"),
		fields: [
			{ fieldname: "vehicle", label: __("Camion"), fieldtype: "Data", read_only: 1, default: frm.doc.vehicle },
			{ fieldname: "via", label: __("Étape intermédiaire"), fieldtype: "Link", options: "Transport Location" },
			{ fieldname: "cargo_kg", label: __("Charge prévue (kg)"), fieldtype: "Float", reqd: 1,
				default: frm.doc.loaded_weight || 0 },
			{ fieldname: "cargo_m3", label: __("Volume prévu (m³)"), fieldtype: "Float", reqd: 1 },
			{ fieldname: "axle_loads", label: __("Charges par groupe d’essieux (kg)"), fieldtype: "Data",
				description: __("Dans l’ordre du véhicule, séparées par un point-virgule. Facultatif.") },
		],
		primary_action_label: __("Calculer le plan"),
		async primary_action({ via, cargo_kg, cargo_m3, axle_loads }) {
			const { message } = await frappe.call({
				method: "goods_transport.goods_transport.services.truck_plan.preview",
				args: { trip_name: frm.doc.name, via, cargo_kg, cargo_m3, axle_loads },
				freeze: true,
			});
			await frappe.require(["leaflet.bundle.js", "leaflet.bundle.css"]);
			dialog.hide();
			goods_transport.truck_plan.show(message);
		},
	});
	dialog.show();
};

goods_transport.truck_plan.show = function (plan) {
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
	const frame = () => { map.invalidateSize(); map.fitBounds(truck.getBounds().pad(0.10)); };
	dialog.$wrapper.one("shown.bs.modal", frame).one("hidden.bs.modal", () => map.remove());
	frame();
};
