frappe.provide("goods_transport.toll_map");

Object.assign(goods_transport.toll_map, {
	async show({ geometry, waypoints = [], tolls, distance_m, duration_s }) {
		await frappe.require(["leaflet.bundle.js", "leaflet.bundle.css"]);
		const dialog = new frappe.ui.Dialog({
			title: geometry ? __("Itinéraire et péages") : __("Carte des péages"),
			size: "extra-large",
			fields: [{ fieldname: "content", fieldtype: "HTML" }],
		});
		const content = dialog.fields_dict.content.$wrapper;
		if (geometry) {
			$("<p>").text(__("{0} km · {1} min · Profil routier voiture", [
				(distance_m / 1000).toFixed(1), Math.round(duration_s / 60),
			])).appendTo(content);
		}
		const container = $("<div>").css({ height: "380px", background: "#edf2f6" }).appendTo(content);
		const summary = $("<ol>").addClass("mt-3").appendTo(content);
		if (geometry && !tolls.length) {
			$("<p>").text(__("Aucun péage du référentiel n’a été rapproché du tracé.")).appendTo(content);
		}
		dialog.show();

		const map = L.map(container[0], { maxZoom: 19 });
		L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
			maxZoom: 19,
			attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
		}).addTo(map);
		const layers = [];
		if (geometry) {
			layers.push(L.polyline(geometry.map(([lon, lat]) => [lat, lon]), {
				color: "#1a66b3", weight: 5,
			}).addTo(map));
		}
		for (const stop of waypoints) {
			const [lon, lat] = stop.coordinates;
			layers.push(L.circleMarker([lat, lon], { radius: 6, color: "#164f82" }).addTo(map)
				.bindTooltip($("<span>").text(stop.name)[0]));
		}
		for (const toll of tolls) {
			const qualification = toll.estimated ? __("Passage estimé") : toll.custom_toll_precision;
			const price = toll.cost == null ? __("Tarif indisponible") : toll.cost;
			const text = [toll.name, toll.custom_toll_road, qualification, toll.custom_toll_precision,
				toll.custom_toll_status, geometry && price].filter(Boolean).filter((value, index, items) =>
				items.indexOf(value) === index).join(" · ");
			const color = toll.custom_toll_precision === "Repère de recherche" ? "#704ba3" :
				toll.estimated || toll.custom_toll_precision !== "Passage cartographié" ? "#a9570c" : "#126440";
			const marker = L.circleMarker([toll.latitude, toll.longitude], {
				radius: 8, color, weight: 3, fillOpacity: 0.75,
			}).addTo(map).bindPopup($("<span>").text(text)[0]);
			layers.push(marker);
			const item = $("<li>").appendTo(summary);
			$("<button>", { type: "button", class: "btn btn-link text-left" }).text(text)
				.on("click", () => { map.setView(marker.getLatLng(), 13); marker.openPopup(); }).appendTo(item);
		}
		const frame = () => {
			map.invalidateSize();
			if (layers.length) map.fitBounds(L.featureGroup(layers).getBounds().pad(0.13), { maxZoom: 14 });
			else map.setView([-4.3, 13.5], 7);
		};
		dialog.$wrapper.one("shown.bs.modal", frame).one("hidden.bs.modal", () => map.remove());
		frame();
	},
});
