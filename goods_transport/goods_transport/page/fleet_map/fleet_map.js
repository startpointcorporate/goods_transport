frappe.pages["fleet-map"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Fleet Map"), single_column: true });
	wrapper.fleet_map = new FleetMap(page);
};

frappe.pages["fleet-map"].on_page_show = function (wrapper) {
	wrapper.fleet_map.open(frappe.get_route()[1] || "");
};

class FleetMap {
	constructor(page) {
		this.page = page;
		this.request = 0;
		this.selector = page.add_field({
			fieldtype: "Link", fieldname: "mission", label: __("Transport Trip"), options: "Transport Trip",
			change: () => {
				const name = this.selector.get_value() || "";
				if (name !== (frappe.get_route()[1] || "")) frappe.set_route("fleet-map", ...(name ? [name] : []));
			},
		});
		page.set_primary_action(__("Refresh map"), () => this.open(frappe.get_route()[1] || ""));
		this.body = $("<section>").addClass("bg-white border rounded p-3").appendTo(page.main);
	}

	async open(name) {
		const request = ++this.request;
		this.selector.set_value(name);
		if (this.map) {
			this.map.remove();
			this.map = null;
		}
		this.page.clear_secondary_action();
		this.body.empty();
		if (!frappe.boot.goods_transport_map_tiles) {
			this.body.text(__("Route preview is unavailable on this site."));
			return;
		}
		const status = $("<p>").attr("role", "status").text(name ? __("Loading mission map…") :
			__("Select a transport trip to display its route and stops.")).appendTo(this.body);
		try {
			await frappe.require(["leaflet.bundle.js", "leaflet.bundle.css", "/assets/goods_transport/js/map_surface.js"]);
			if (request !== this.request) return;
			const data = name ? await frappe.xcall("goods_transport.goods_transport.services.fleet_map.mission",
				{ trip_name: name }, "GET") : null;
			if (request !== this.request) return;
			if (data) {
				status.text([data.name, data.plate || data.vehicle, data.driver_name || data.driver, __(data.status || "")].filter(Boolean).join(" · "));
				this.page.set_secondary_action(__("Open Transport Trip"),
					() => frappe.set_route("Form", "Transport Trip", data.name));
				this.details(data);
			}
			const canvas = $("<div>").attr({ "aria-label": __("Fleet Map"), "data-fleet-map": "" })
				.css({ height: "min(62vh, 680px)", minHeight: "320px", background: "#edf2f6" }).appendTo(this.body);
			const tiles = $("<p>").attr("role", "status").appendTo(this.body);
			this.map = goods_transport.map_surface.create(canvas[0],
				() => tiles.text(__("Some map tiles could not be loaded.")));
			this.map.setView([-4.3, 13.5], 7);
			if (data) this.draw(data);
		} catch {
			if (request === this.request) status.text(__("Could not load the mission map."));
		}
	}

	details(data) {
		const labels = [];
		if (data.routes.truck) labels.push(__("Truck route · {0} km", [(data.routes.truck.distance / 1000).toFixed(1)]));
		if (data.routes.car) labels.push(__("Car route · {0} km", [(data.routes.car.distance / 1000).toFixed(1)]));
		if (!labels.length && data.distance_km) labels.push(__("Planned distance · {0} km", [data.distance_km]));
		if (labels.length) $("<p>").text(labels.join(" | ")).appendTo(this.body);
		if (data.routes.truck) $("<p>").text(__("Indicative route. Check local truck restrictions and use weigh stations.")).appendTo(this.body);
		if (data.warning) $("<p>").addClass("text-warning").text(data.warning).appendTo(this.body);
		const gps = data.gps;
		$("<p>").attr("data-gps-status", gps.state).text(this.gpsLabel(gps)).appendTo(this.body);
	}

	gpsLabel(gps) {
		if (!gps.point) return __("Last known position unavailable");
		const freshness = gps.state === "recent" ? __("Recent position") : __("Old position");
		return [freshness, __("Last fix {0} · {1} min ago", [frappe.datetime.str_to_user(gps.recorded_at), gps.age_minutes]),
			gps.accuracy_m == null ? "" : __("Accuracy {0} m", [gps.accuracy_m])].filter(Boolean).join(" · ");
	}

	draw(data) {
		const types = {
			origin: ["▶", __("Departure")], destination: ["⚑", __("Destination")],
			via: ["◆", __("Waypoint")], toll: ["₣", __("Toll")],
			available: ["⛽", __("Partner station available")], selected: ["✓", __("Planned fuel stop")],
			unavailable: ["×", __("Partner station unavailable")], garage: ["⚒", __("Workshop")],
			truck: ["▣", __("Truck position")],
		};
		const legend = $("<p>").addClass("mb-2").appendTo(this.body);
		legend.text(Object.values(types).map(([symbol, label]) => symbol + " " + label).join("  ·  "));
		if (data.routes.truck && data.routes.car) $("<p>").text(__("Truck route (solid) · Car route (dashed)")).appendTo(this.body);
		const list = $("<div>").addClass("row").appendTo(this.body);
		const layers = [];
		const bounds = L.latLngBounds([]);
		// Draw the comparison route above the truck route so both remain visible on shared segments.
		for (const [key, style] of [
			["truck", { color: "#1765ab", weight: 6 }], ["car", { color: "#727984", weight: 3, dashArray: "5 7" }],
		]) {
			if (!data.routes[key]) continue;
			const route = goods_transport.map_surface.path(this.map, data.routes[key].geometry.coordinates, style);
			bounds.extend(route.getBounds());
		}
		const tolls = data.tolls.map((row, index) => ({
			...row, kind: "toll", name: (index + 1) + ". " + row.name, point: [row.longitude, row.latitude],
		}));
		const stations = [...data.stations].sort((a, b) => (a.stop_order || Infinity) - (b.stop_order || Infinity));
		for (const row of [...data.points, ...tolls, ...stations, ...data.garages, ...(data.gps.point ? [data.gps] : [])]) {
			const [symbol, category] = types[row.kind === "station" ? row.state : row.kind];
			const details = [row.stop_order ? row.stop_order + ". " + category : category, row.name, row.address, row.custom_toll_road, row.category,
				row.fuels?.map((fuel) => __(fuel)).join(", ")];
			if (row.kind === "toll") details.push(__("Estimated crossing"), row.amount == null ?
				__("Unverified or unavailable tariff") : row.amount + " " + row.currency, row.custom_toll_status);
			if (row.planned_liters != null) details.push(__("Planned {0} L", [row.planned_liters]));
			if (row.authorized_liters != null) details.push(__("Authorized {0} L", [row.authorized_liters]));
			for (const reserve of row.reserves || []) details.push(__("Reserve {0} · {1} L available", [reserve.name, reserve.liters]));
			if (row.kind === "truck") details.push(row.trip, this.gpsLabel(row));
			if (row.point) details.push(row.point.slice().reverse().join(", "));
			else details.push(__("GPS coordinates unavailable"));
			const label = details.filter(Boolean).join(" · ");
			const item = $("<div>").addClass("col-md-6 col-xl-4").appendTo(list);
			const button = $("<button>", { type: "button", disabled: !row.point })
				.addClass("btn btn-link text-left text-wrap").text(symbol + " " + label).appendTo(item);
			if (!row.point) continue;
			const [lon, lat] = row.point;
			const marker = L.marker([lat, lon], { title: category + " · " + row.name, riseOnHover: true,
				icon: L.divIcon({ className: "", iconSize: [28, 28], iconAnchor: [14, 14], html:
					'<span class="d-flex align-items-center justify-content-center bg-white border border-secondary rounded-circle shadow-sm" style="width:28px;height:28px;color:#172b42;font-weight:bold">' +
					symbol + '</span>' }),
			}).bindPopup($("<span>").text(label)[0]);
			layers.push(marker);
			if (row.kind !== "station" || row.state === "selected") bounds.extend(marker.getLatLng());
			button.on("click", () => this.map.setView(marker.getLatLng(), 14));
			button.on("click", () => marker.openPopup());
		}
		if (bounds.isValid()) this.map.fitBounds(bounds.pad(0.12), { maxZoom: 14 });
		this.addMarkers(layers);
	}

	addMarkers(markers) {
		// Group dense pins in screen-space at low zoom. Detail buttons always focus one point.
		const layer = L.layerGroup().addTo(this.map);
		const render = () => {
			layer.clearLayers();
			if (markers.length < 35 || this.map.getZoom() >= 13) {
				markers.forEach((marker) => layer.addLayer(marker));
				return;
			}
			const cells = new Map();
			for (const marker of markers) {
				const point = this.map.project(marker.getLatLng());
				const key = [Math.floor(point.x / 48), Math.floor(point.y / 48)].join(":");
				if (!cells.has(key)) cells.set(key, []);
				cells.get(key).push(marker);
			}
			for (const cell of cells.values()) {
				if (cell.length === 1) layer.addLayer(cell[0]);
				else layer.addLayer(L.marker(cell[0].getLatLng(), {
					title: __("Show {0} map points", [cell.length]),
					icon: L.divIcon({ className: "bg-white border border-secondary rounded-circle text-center font-weight-bold",
						iconSize: [30, 25], html: String(cell.length) }),
				}).on("click", () => this.map.setView(cell[0].getLatLng(), Math.max(this.map.getZoom() + 2, 13))));
			}
		};
		this.map.on("zoomend", render);
		render();
	}
}
