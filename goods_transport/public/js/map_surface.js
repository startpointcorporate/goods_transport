frappe.provide("goods_transport.map_surface");

goods_transport.map_surface.create = function (container, onTileError) {
	const map = L.map(container, { maxZoom: 19 });
	const tiles = frappe.boot.goods_transport_map_tiles || {};
	const attribution = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
	const layer = L.tileLayer(tiles.url || "https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
		maxZoom: 19,
		attribution: attribution + (tiles.attribution ? " · " + frappe.utils.escape_html(tiles.attribution) : ""),
		referrerPolicy: "strict-origin-when-cross-origin",
		updateWhenIdle: true,
	});
	if (onTileError) layer.on("tileerror", onTileError);
	layer.addTo(map);
	return map;
};

goods_transport.map_surface.path = function (map, coordinates, style) {
	return L.polyline(coordinates.map(([lon, lat]) => [lat, lon]), style).addTo(map);
};
