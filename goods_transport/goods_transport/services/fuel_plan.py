"""Evaluate contract-backed stops on the truck graph."""

from math import ceil, isfinite

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime

from .fuel import AUTHORIZATION, RESERVE, STATION

FUEL_TYPES = {"Diesel": "Diesel", "Petrol": "Essence"}


def fueling(distance_before, distance_after, departure, rate, capacity):
	arrival = departure - distance_before * rate
	refill = distance_after * rate - arrival
	if arrival < 0 or refill <= 0 or distance_after * rate > capacity:
		return None
	# Round up to the precision of the reserves and dispensing records.
	return ceil(refill * 1000) / 1000


def estimate(trip, vehicle, points, baseline, departure_liters, route, selected=None):
	fuel = FUEL_TYPES.get(vehicle.fuel_type)
	tank = vehicle.get("custom_fuel_tank_liters") or 0
	rate = (vehicle.get("custom_fuel_liters_100km") or 0) / 100000
	if not fuel or not all(isfinite(x) and x > 0 for x in (tank, rate)):
		frappe.throw(_("Renseignez le carburant, le réservoir et la consommation moyenne du camion."))
	if not isfinite(departure_liters) or not 0 <= departure_liters <= tank:
		frappe.throw(_("Le niveau au départ doit être compris entre zéro et la capacité du réservoir."))
	day = getdate(trip.trip_date)
	now = now_datetime()
	authorizations = frappe.get_list(AUTHORIZATION, filters={"trip": trip.name},
		fields=["reserve", "status", "authorized_liters", "valid_from", "valid_until", "delivered_liters"],
		limit_page_length=0)
	reserved = {}
	for row in authorizations:
		if row.status == "Reserved" and row.valid_until > now and row.valid_from.date() <= day <= row.valid_until.date():
			reserved[row.reserve] = reserved.get(row.reserve, 0) + row.authorized_liters
	result = {
		"fuel_type": fuel, "departure_liters": departure_liters, "capacity_liters": tank,
		"range_km": departure_liters / rate / 1000, "liters_100km": rate * 100000,
		"required_liters": baseline["distance"] * rate,
		"authorized_liters": sum(reserved.values()),
		"delivered_liters": sum(row.delivered_liters or 0 for row in authorizations if row.status == "Consumed"),
		"stops": [],
	}
	if not selected and result["required_liters"] <= departure_liters:
		return result, baseline, points
	reserves = frappe.get_list(RESERVE, filters={"company": trip.company, "fuel_type": fuel,
		"valid_from": ["<=", day]}, fields=["name", "station", "valid_until", "available_liters"],
		limit_page_length=0)
	cache = {}
	candidates = []
	for reserve in reserves:
		available = reserve.available_liters + reserved.get(reserve.name, 0)
		if available <= 0 or (reserve.valid_until and reserve.valid_until < day):
			continue
		station = frappe.get_doc(STATION, reserve.station)
		if not station.has_permission("read") or not station.get(fuel.lower()):
			continue
		if station.name not in cache:
			coords = station.longitude, station.latitude
			cache[station.name] = []
			for index in range(1, len(points)):
				waypoints = [*points[:index], coords, *points[index:]]
				option = route(waypoints)
				if option is None:
					continue
				legs = option["legs"]
				refill = fueling(sum(leg["distance"] for leg in legs[:index]),
					sum(leg["distance"] for leg in legs[index:]), departure_liters, rate, tank)
				if refill is not None:
					cache[station.name].append((option, waypoints, refill))
		for option, waypoints, refill in cache[station.name]:
			if available >= refill:
				candidates.append(({
					"reserve": reserve.name, "station": station.station_name, "latitude": station.latitude,
					"longitude": station.longitude, "available_liters": available, "refill_liters": refill,
					"detour_km": max(0, (option["distance"] - baseline["distance"]) / 1000),
				}, option, waypoints))
	candidates.sort(key=lambda entry: (entry[0]["detour_km"], entry[1]["duration"], entry[0]["reserve"]))
	seen = set()
	for stop, _, _ in candidates:
		if stop["reserve"] not in seen:
			result["stops"].append(stop)
			seen.add(stop["reserve"])
	if selected:
		for stop, option, waypoints in candidates:
			if stop["reserve"] == selected:
				result["selected"] = stop
				result["required_liters"] = option["distance"] * rate
				return result, option, waypoints
		frappe.throw(_("La réserve choisie ne permet plus un arrêt réalisable pour ce trajet."))
	return result, baseline, points
