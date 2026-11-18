"""Evaluate contract-backed stops on the truck graph."""

from decimal import Decimal
from math import ceil, cos, hypot, isfinite, radians

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime

from .fuel import AUTHORIZATION, RESERVE, STATION

from .fuel_optimizer import allocate, demand, find_paths

FUEL_TYPES = {"Diesel": "Diesel", "Petrol": "Essence"}


def fueling(distance_before, distance_after, departure, rate, capacity):
	arrival = departure - distance_before * rate
	refill = distance_after * rate - arrival
	if arrival < 0 or refill <= 0 or distance_after * rate > capacity:
		return None
	# Round up to the precision of the reserves and dispensing records.
	return ceil(refill * 1000) / 1000


def position(point, geometry):
	scale = cos(radians(point[1]))
	closest = (float("inf"), 0)
	for index, (a, b) in enumerate(zip(geometry, geometry[1:])):
		x, y = (a[0] - point[0]) * scale, a[1] - point[1]
		dx, dy = (b[0] - a[0]) * scale, b[1] - a[1]
		length = dx * dx + dy * dy
		fraction = max(0, min(1, -(x * dx + y * dy) / length)) if length else 0
		closest = min(closest, (hypot(x + fraction * dx, y + fraction * dy), index + fraction))
	return closest


def candidates(trip, fuel, day, geometry):
	reserves = frappe.get_list(RESERVE, filters={"company": trip.company, "fuel_type": fuel,
		"valid_from": ["<=", day], "available_liters": [">", 0]},
		fields=["name", "station", "valid_until", "available_liters", "price_currency", "price_per_liter"],
		limit_page_length=0)
	nodes = []
	stations = {}
	for reserve in reserves:
		if reserve.valid_until and reserve.valid_until < day:
			continue
		if reserve.station not in stations:
			stations[reserve.station] = frappe.get_doc(STATION, reserve.station)
		station = stations[reserve.station]
		if not station.has_permission("read") or not station.get(fuel.lower()):
			continue
		point = (station.longitude, station.latitude)
		offset, progress = position(point, geometry)
		nodes.append({"reserve": reserve.name, "station": station.station_name, "station_id": station.name,
			"point": point, "offset": offset, "progress": progress,
			"supply": int(Decimal(str(reserve.available_liters)) * 1000),
			"price": reserve.price_per_liter if reserve.price_currency == trip.currency else None})
	return nodes


def evaluate(nodes, calculated, initial, capacity, rate):
	legs = calculated["legs"]
	if len(legs) != len(nodes) - 1:
		return None
	distances = [leg["distance"] for leg in legs]
	required = [demand(distance, rate) for distance in distances]
	intermediate = nodes[1:-1]
	priced = all(node["price"] is not None for node in intermediate if node.get("reserve"))
	supplies = [node.get("supply", 0) for node in intermediate]
	prices = [Decimal(str(node.get("price") or 0)) if priced else 1 for node in intermediate]
	amounts = allocate(required, supplies, prices, initial, capacity)
	if amounts is None:
		return None
	fuel = initial
	stops = []
	total_cost = 0
	since_stop = 0
	for index, amount in enumerate(amounts):
		node = intermediate[index]
		fuel -= required[index]
		since_stop += distances[index]
		if node.get("reserve"):
			price = node.get("price")
			if price is not None:
				total_cost += float(price) * amount / 1000
			stops.append({"reserve": node["reserve"], "station": node["station"],
				"longitude": node["point"][0], "latitude": node["point"][1],
				"arrival_liters": fuel / 1000, "refill_liters": amount / 1000,
				"departure_liters": (fuel + amount) / 1000,
				"range_km": float(Decimal(fuel + amount) / rate / 1000),
				"leg_km": since_stop / 1000, "available_liters": node["supply"] / 1000,
				"unit_price": price})
			since_stop = 0
		fuel += amount
	return {"stops": stops, "cost": total_cost if priced else None,
		"destination_liters": (fuel - required[-1]) / 1000,
		"last_leg_km": (since_stop + distances[-1]) / 1000}


def estimate(trip, vehicle, points, baseline, departure_liters, route, table, selected=None, tolls_on=None):
	fuel = FUEL_TYPES.get(vehicle.fuel_type)
	tank = vehicle.get("custom_fuel_tank_liters") or 0
	consumption = vehicle.get("custom_fuel_liters_100km") or 0
	if not fuel or not all(isfinite(x) and x > 0 for x in (tank, consumption)):
		frappe.throw(_("Renseignez le carburant, le réservoir et la consommation moyenne du camion."))
	if not isfinite(departure_liters) or not 0 <= departure_liters <= tank:
		frappe.throw(_("Le niveau au départ doit être compris entre zéro et la capacité du réservoir."))
	rate = Decimal(str(consumption)) / 100
	initial = int(Decimal(str(departure_liters)) * 1000)
	capacity = int(Decimal(str(tank)) * 1000)
	day = getdate(trip.trip_date)
	now = now_datetime()
	history = frappe.get_list(AUTHORIZATION, filters={"trip": trip.name},
		fields=["status", "authorized_liters", "valid_until", "delivered_liters"], limit_page_length=0)
	result = {"fuel_type": fuel, "departure_liters": departure_liters, "capacity_liters": tank,
		"range_km": float(Decimal(initial) / rate / 1000), "liters_100km": consumption,
		"required_liters": baseline["distance"] * consumption / 100000, "currency": trip.currency,
		"authorized_liters": sum(row.authorized_liters for row in history
			if row.status == "Reserved" and row.valid_until > now),
		"delivered_liters": sum(row.delivered_liters or 0 for row in history if row.status == "Consumed"),
		"stops": [], "alternatives": [], "feasible": False}
	skeleton = [{"point": point, "mandatory": True} for point in points]
	direct = evaluate(skeleton, baseline, initial, capacity, rate)
	if direct and not selected:
		result.update(direct, feasible=True, detour_km=0)
		return result, baseline, points
	geometry = baseline["geometry"]["coordinates"]
	options = candidates(trip, fuel, day, geometry)
	result["limited"] = len(options) > 48
	# Keep explicit choices even when the corridor shortlist is full.
	options.sort(key=lambda node: (node["reserve"] not in (selected or []), node["offset"], node["reserve"]))
	options = options[:48]
	by_reserve = {node["reserve"]: node for node in options}
	for node in skeleton[1:-1]:
		node["progress"] = position(node["point"], geometry)[1]
	middle = sorted([*skeleton[1:-1], *options], key=lambda node: (node["progress"], node.get("reserve", "")))
	nodes = [skeleton[0], *middle, skeleton[-1]]
	coords = [node["point"] for node in nodes]
	matrix = table(coords) if options else []
	for i, node in enumerate(nodes):
		if not matrix:
			break
		for j in range(i + 1, len(nodes)):
			if node.get("station_id") and node["station_id"] == nodes[j].get("station_id"):
				matrix[i][j] = None
	paths = find_paths(nodes, matrix, initial, capacity, rate) if matrix else []
	if selected and all(reserve in by_reserve for reserve in selected):
		indices = {node["reserve"]: i for i, node in enumerate(nodes) if node.get("reserve")}
		selected_path = (0, *sorted([*(indices[r] for r in selected),
			*(i for i, node in enumerate(nodes[1:-1], 1) if node.get("mandatory"))]), len(nodes) - 1)
		if [nodes[i].get("reserve") for i in selected_path if nodes[i].get("reserve")] == selected:
			paths = list(dict.fromkeys([selected_path, *paths]))
	plans = []
	for path in paths:
		sequence = [nodes[i] for i in path]
		station_ids = [node["station_id"] for node in sequence if node.get("reserve")]
		if len(set(station_ids)) != len(station_ids):
			continue
		waypoints = [node["point"] for node in sequence]
		calculated = route(waypoints)
		if not calculated:
			continue
		forecast = evaluate(sequence, calculated, initial, capacity, rate)
		if not forecast or any(not stop["refill_liters"] for stop in forecast["stops"]):
			continue
		forecast.update(detour_km=max(0, (calculated["distance"] - baseline["distance"]) / 1000),
			reserves=[stop["reserve"] for stop in forecast["stops"]],
			waypoints=waypoints, distance=calculated["distance"],
			required_liters=calculated["distance"] * consumption / 100000)
		tolls = tolls_on(calculated) if tolls_on else []
		if trip.currency == "XAF" and forecast["cost"] is not None and all(toll["amount"] is not None for toll in tolls):
			forecast["total_cost"] = forecast["cost"] + sum(toll["amount"] for toll in tolls)
		plans.append((forecast, calculated, waypoints))
	compare_total = bool(plans) and all(plan[0].get("total_cost") is not None for plan in plans)
	compare_cost = bool(plans) and all(plan[0]["cost"] is not None for plan in plans)
	cost_key = "total_cost" if compare_total else "cost"
	plans.sort(key=lambda plan: (round(plan[0]["detour_km"] * 1000),
		plan[0][cost_key] if compare_cost else 0, len(plan[0]["stops"]), plan[1]["duration"], plan[0]["reserves"]))
	result["alternatives"] = [{"reserves": forecast["reserves"], "stations": [s["station"] for s in forecast["stops"]],
		"detour_km": forecast["detour_km"], "cost": forecast["cost"]} for forecast, _, _ in plans[:6]]
	result["cost_ranked"] = compare_cost
	for forecast, calculated, waypoints in plans:
		if selected is None or forecast["reserves"] == selected:
			result.update(forecast, feasible=True)
			return result, calculated, waypoints
	return result, baseline, points


def project_withdrawals(forecast, authorizations, now):
	"""Apply evidenced deliveries and outstanding authorizations to the confirmed forecast."""
	variance = Decimal(0)
	first_shortfall = None
	update = []
	for stop, auth in zip(forecast["stops"], authorizations, strict=True):
		projected_arrival = Decimal(str(stop["arrival_liters"])) + variance
		if projected_arrival < 0 and first_shortfall is None:
			first_shortfall = {"location": stop["station"], "liters": float(-projected_arrival)}
		if auth and auth.status == "Consumed":
			quantity = auth.delivered_liters or 0
		elif auth and auth.status == "Reserved" and auth.valid_until > now:
			quantity = auth.authorized_liters
		else:
			quantity = 0
		variance += Decimal(str(quantity)) - Decimal(str(stop["refill_liters"]))
		projected_departure = Decimal(str(stop["departure_liters"])) + variance
		update.append({"arrival_liters": float(projected_arrival), "withdrawal_liters": quantity,
			"departure_liters": float(projected_departure), "status": auth.status if auth else None,
			"range_km": float(max(Decimal(0), projected_departure) * 100
				/ Decimal(str(forecast["liters_100km"])))})
	destination = Decimal(str(forecast["destination_liters"])) + variance
	if first_shortfall is None and destination < 0:
		first_shortfall = {"liters": float(-destination)}
	return {"stops": update, "destination_liters": float(destination), "first_shortfall": first_shortfall}
