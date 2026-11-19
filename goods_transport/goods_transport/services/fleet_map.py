"""Permission-checked projection of Goods Transport data for Desk maps."""

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, now_datetime

from . import fuel_plan, toll_routing, truck_plan
from .fuel import AUTHORIZATION, RESERVE, STATION, active


def boot_session(bootinfo):
	if frappe.conf.get("goods_transport_osrm_url"):
		bootinfo.goods_transport_map_tiles = {
			"url": frappe.conf.get("goods_transport_map_tile_url") or "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
			"attribution": frappe.conf.get("goods_transport_map_tile_attribution") or "",
		}


def coordinates(lon, lat):
	if isinstance(lon, (float, int)) and isinstance(lat, (float, int)) and (lon or lat):
		if -180 <= lon <= 180 and -90 <= lat <= 90:
			return [lon, lat]
	return None


def waypoint(name, kind):
	if not name:
		return None
	doc = frappe.get_doc("Transport Location", name)
	doc.check_permission("read")
	return {"name": name, "kind": kind, "point": coordinates(doc.longitude, doc.latitude)}


def fuel_layers(trip, plan, geometry, selected=()):
	if not frappe.conf.get("goods_transport_partner_fuel") or not frappe.has_permission(STATION, "read"):
		return []
	stations = frappe.get_list(STATION, filters={"company": trip.company}, fields=[
		"name", "station_name", "street_address", "latitude", "longitude", "diesel", "essence",
	], order_by="station_name asc", limit_page_length=0)
	by_station = {station.name: station for station in stations}
	reserves = {}
	vehicle = frappe.get_doc("Vehicle", trip.vehicle) if trip.vehicle else None
	if vehicle and vehicle.has_permission("read") and frappe.has_permission(RESERVE, "read"):
		fuel = fuel_plan.FUEL_TYPES.get(vehicle.fuel_type)
		if fuel:
			for candidate in fuel_plan.candidates(trip, fuel, getdate(trip.trip_date), geometry):
				station = by_station.get(candidate["station_id"])
				if station:
					reserves.setdefault(station.name, []).append({
						"name": candidate["reserve"], "liters": candidate["supply"] / 1000, "fuel": fuel,
					})
	stops = {}
	if frappe.has_permission(RESERVE, "read"):
		planned = {row["reserve"]: row["refill_liters"] for row in (plan or {}).get("stops", [])}
		for order, name in enumerate(dict.fromkeys([*selected, *planned]), 1):
			reserve = frappe.get_doc(RESERVE, name)
			if reserve.company == trip.company and reserve.station in by_station and reserve.has_permission("read"):
				stop = stops.setdefault(reserve.station, {"stop_order": order})
				if name in planned:
					stop["planned_liters"] = planned[name]
	if frappe.has_permission(AUTHORIZATION, "read"):
		authorizations = frappe.get_list(AUTHORIZATION, filters={
			"trip": trip.name, "company": trip.company, "status": "Reserved",
		}, fields=["station", "vehicle", "driver", "authorized_liters", "status", "valid_from", "valid_until"],
			limit_page_length=0)
		for item in authorizations:
			if item.station not in by_station:
				continue
			try:
				active(item, trip)
			except frappe.ValidationError:
				frappe.clear_messages()
				continue
			stop = stops.setdefault(item.station, {})
			stop["authorized_liters"] = stop.get("authorized_liters", 0) + item.authorized_liters
	return [{
		"name": station.station_name, "address": station.street_address,
		"point": coordinates(station.longitude, station.latitude),
		"fuels": [label for field, label in (("diesel", "Diesel"), ("essence", "Petrol")) if station[field]],
		"kind": "station",
		"state": "selected" if station.name in stops else "available" if station.name in reserves else "unavailable",
		"reserves": reserves.get(station.name, []), **stops.get(station.name, {}),
	} for station in stations]


def garages(trip):
	if not trip.vehicle or not all(frappe.has_permission(dt, "read") for dt in (
		"Vehicle Immobilisation", "Supplier", "Address",
	)):
		return []
	jobs = frappe.get_list("Vehicle Immobilisation", filters={"company": trip.company, "vehicle": trip.vehicle,
		"docstatus": ["!=", 2]}, pluck="supplier", limit_page_length=0)
	meta = frappe.get_meta("Address")
	lon, lat = next(((x, y) for x, y in (("longitude", "latitude"),
		("custom_longitude", "custom_latitude")) if meta.has_field(x) and meta.has_field(y)), (None, None))
	if not lon:
		return []
	result = []
	for name in sorted(set(filter(None, jobs))):
		supplier = frappe.get_doc("Supplier", name)
		if not supplier.has_permission("read") or not supplier.supplier_primary_address:
			continue
		address = frappe.get_doc("Address", supplier.supplier_primary_address)
		if address.has_permission("read") and (point := coordinates(address.get(lon), address.get(lat))):
			result.append({"name": supplier.supplier_name, "kind": "garage", "point": point,
				"address": ", ".join(filter(None, [address.address_line1, address.city]))})
	return result


def latest_position(trip):
	"""Site applications may supply a last fix for the already authorised mission."""
	for provider in frappe.get_hooks("goods_transport_last_position"):
		fix = frappe.get_attr(provider)(trip)
		if not fix or fix.get("trip") != trip.name or fix.get("vehicle") != trip.vehicle:
			continue
		point = coordinates(fix.get("longitude"), fix.get("latitude"))
		if point and fix.get("recorded_at") and trip.vehicle:
			recorded = get_datetime(fix["recorded_at"])
			age = int((now_datetime() - recorded).total_seconds())
			if age < 0:
				continue
			return {"kind": "truck", "name": trip.vehicle, "trip": trip.name, "point": point,
				"recorded_at": str(recorded), "age_minutes": age // 60,
				"accuracy_m": fix.get("accuracy_m"), "state": "recent" if age < 900 else "stale"}
	return {"state": "unavailable"}


@frappe.whitelist(methods=["GET"])
def mission(trip_name: str):
	trip = frappe.get_doc("Transport Trip", trip_name)
	trip.check_permission("read")
	toll_routing.check_enabled()
	args = frappe.parse_json(trip.fuel_plan_inputs or "{}")
	can_read_fuel = frappe.has_permission(RESERVE, "read") and frappe.has_permission(STATION, "read")
	if not can_read_fuel or not all(
		frappe.db.exists(RESERVE, {"name": name, "company": trip.company})
		and frappe.get_doc(RESERVE, name).has_permission("read")
		for name in args.get("selected_reserves") or []
	):
		args = {key: value for key, value in args.items() if key in ("via", "cargo_kg", "cargo_m3", "axle_loads")}
	points = [point for point in (
		waypoint(trip.origin, "origin"), waypoint(args.get("via"), "via"), waypoint(trip.destination, "destination"),
	) if point]
	routes, tolls, plan, warning = {}, [], None, None
	if trip.origin and trip.destination and all(point["point"] for point in points):
		frappe.flags.goods_transport_cache_osrm = True
		waypoints = [point["point"] for point in points]
		try:
			if frappe.conf.get("goods_transport_truck_osrm_url") and trip.vehicle and "cargo_kg" in args:
				result = truck_plan.preview(trip.name, **{key: args[key] for key in (
					"cargo_kg", "cargo_m3", "via", "axle_loads", "departure_liters", "selected_reserves",
				) if key in args}, confirmed=bool(args.get("authorization_codes")))
				routes = {key: result[key] for key in ("truck", "car")}
				plan = result["fuel"]
				reference = {row.name: row for row in toll_routing.get_tolls()}
				tolls = [{**reference[row["name"]], **row, "category": result["class"], "currency": "XAF",
					"estimated": True} for row in result["tolls"] if row["name"] in reference]
			else:
				routes["car"] = truck_plan.fetch_route(frappe.conf.goods_transport_osrm_url, waypoints)
				tolls = toll_routing.match_tolls(routes["car"]["geometry"]["coordinates"], toll_routing.get_tolls())
		except frappe.ValidationError:
			frappe.clear_messages()
			warning = _("Route unavailable. Review the mission coordinates and road plan.")
		finally:
			frappe.flags.pop("goods_transport_cache_osrm", None)
	routes = {key: {field: route[field] for field in ("distance", "geometry")} for key, route in routes.items()}
	route = routes.get("truck") or routes.get("car")
	stations = fuel_layers(trip, plan, route["geometry"]["coordinates"] if route else [],
		args.get("selected_reserves") or [])
	return {"name": trip.name, "vehicle": trip.vehicle, "driver": trip.driver, "driver_name": trip.driver_name,
		"plate": trip.vehicle_license_plate, "status": trip.status,
		"distance_km": trip.planned_distance, "points": points, "routes": routes, "tolls": tolls, "stations": stations,
		"garages": garages(trip), "gps": latest_position(trip), "warning": warning}
