"""Route previews for the Transport Demo site."""

from math import cos, hypot, radians

import frappe
import requests
from frappe import _

TOLL_FIELDS = [
	"name", "latitude", "longitude", "custom_toll_road", "custom_toll_precision",
	"custom_toll_accuracy_m", "custom_toll_status", "custom_toll_routing",
]


def extend_bootinfo(bootinfo):
	bootinfo.goods_transport_route_preview = bool(frappe.conf.get("goods_transport_osrm_url"))


def check_enabled():
	if not frappe.conf.get("goods_transport_osrm_url"):
		frappe.throw(_("Route preview is unavailable on this site."))


def get_tolls():
	return frappe.get_list(
		"Transport Location",
		filters={"location_type": "Péage", "custom_toll_id": ["is", "set"], "is_active": 1},
		fields=TOLL_FIELDS,
		order_by="custom_toll_id asc",
		limit_page_length=0,
	)


@frappe.whitelist()
def list_tolls():
	check_enabled()
	return get_tolls()


def location_coordinates(name):
	location = frappe.get_doc("Transport Location", name)
	location.check_permission("read")
	lon, lat = location.longitude, location.latitude
	if lon is None or lat is None or (lon == 0 and lat == 0) or not (
		-180 <= lon <= 180 and -90 <= lat <= 90
	):
		frappe.throw(_("Set valid GPS coordinates for {0}.").format(location.name))
	return lon, lat


@frappe.whitelist()
def preview_route(origin: str, destination: str, via: str | None = None):
	check_enabled()
	if not (frappe.has_permission("Transport Order", "create") or
		frappe.has_permission("Transport Order", "read")):
		frappe.throw(_("You do not have permission to preview an itinerary."), frappe.PermissionError)
	stops = [origin, via, destination] if via else [origin, destination]
	if len(set(stops)) != len(stops):
		frappe.throw(_("Choose distinct itinerary stops."))
	coordinates = ";".join(f"{lon:.7f},{lat:.7f}" for lon, lat in map(location_coordinates, stops))
	try:
		response = requests.get(
			f"{frappe.conf.goods_transport_osrm_url.rstrip('/')}/route/v1/driving/{coordinates}",
			params={"overview": "full", "geometries": "geojson", "radiuses": ";".join(["1000"] * len(stops))},
			timeout=(3, 12),
		)
		payload = response.json()
		if payload.get("code") in {"NoRoute", "NoSegment"}:
			frappe.throw(_("OSRM found no route between these stops. Check their coordinates."))
		response.raise_for_status()
	except (requests.RequestException, ValueError):
		frappe.throw(_("OSRM is temporarily unavailable. Try again later."))
	route = payload["routes"][0]
	geometry = route["geometry"]["coordinates"]
	return {
		"geometry": geometry,
		"waypoints": [{"name": name, "coordinates": point["location"]} for name, point in zip(stops, payload["waypoints"])],
		"distance_m": route["distance"],
		"duration_s": route["duration"],
		"tolls": match_tolls(geometry, get_tolls()),
	}


def match_tolls(geometry, tolls):
	# Measure proximity to the travelled polyline and record the position along it.
	# The reference dataset has no verified directed crossings, so every match
	# remains an estimate and contributes no automatic charge.
	matches = []
	for toll in tolls:
		if toll["latitude"] is None or toll["longitude"] is None:
			continue
		# Search-area pins have unknown error and may refer to a nearby town.
		# A close result is still reported as estimated for the demonstration.
		tolerance = min(650, max(45, toll["custom_toll_accuracy_m"] or 100))
		scale_y = 111_195
		scale_x = scale_y * cos(radians(toll["latitude"]))
		points = [
			((lon - toll["longitude"]) * scale_x, (lat - toll["latitude"]) * scale_y)
			for lon, lat in geometry
		]
		closest = (float("inf"), 0.0)
		travelled = 0.0
		for (x, y), (end_x, end_y) in zip(points, points[1:]):
			dx, dy = end_x - x, end_y - y
			length = hypot(dx, dy)
			if not length:
				continue
			fraction = max(0, min(1, -(x * dx + y * dy) / length**2))
			closest = min(closest, (hypot(x + fraction * dx, y + fraction * dy), travelled + fraction * length))
			travelled += length
		offset, position = closest
		if offset <= tolerance:
			matches.append({
				**toll,
				"offset_m": round(offset),
				"position_m": round(position),
				"estimated": True,
				"cost": None,
			})
	return sorted(matches, key=lambda toll: toll["position_m"])
