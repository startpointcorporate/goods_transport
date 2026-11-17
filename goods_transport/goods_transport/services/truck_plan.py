"""Planning estimates for the Congo truck routing service."""

from math import cos, hypot, isfinite, radians

import frappe
import requests
from frappe.utils import getdate

ENVELOPE = {"height": 4, "width": 2.55, "length": 18.75, "ptac": 50000}
# Annex 4.2.1 of the LCR operating regulation (decree 2023-1663).
CEMAC = {
	"P11": (26000, (13000, 13000)), "P12": (34000, (13000, 21000)),
	"P13": (40000, (13000, 27000)), "P22": (42000, (21000, 21000)),
	"P23": (48000, (21000, 27000)), "T1151": (39000, (13000, 13000, 13000)),
	"T1152": (47000, (13000, 13000, 21000)), "T1153": (50000, (13000, 13000, 27000)),
	"T1251": (47000, (13000, 21000, 13000)), "T1252": (50000, (13000, 21000, 21000)),
	"T1253": (50000, (13000, 21000, 21000)), "T1254": (50000, (13000, 21000, 27000)),
}


def boot_session(bootinfo):
	bootinfo.goods_transport_truck_plan = bool(frappe.conf.get("goods_transport_truck_osrm_url"))


def vehicle_limits(vehicle, cargo_kg, cargo_m3, axle_group_loads):
	gross = vehicle["tare"] + cargo_kg
	if not all(isfinite(vehicle[key]) and vehicle[key] > 0 for key in ("tare", "ptac", "height", "width", "length", "axles", "payload", "volume")):
		raise ValueError("Renseigner la tare, le PTAC/PTRA, les dimensions, les essieux et les capacités du camion.")
	if not all(isfinite(value) and value >= 0 for value in (cargo_kg, cargo_m3)):
		raise ValueError("Le poids et le volume déclarés doivent être positifs ou nuls.")
	if cargo_kg > vehicle["payload"] or cargo_m3 > vehicle["volume"]:
		raise ValueError("Le chargement dépasse la capacité du camion.")
	max_gross, group_limits = CEMAC.get(vehicle.get("cemac"), (None, ()))
	if max_gross is None or gross > min(vehicle["ptac"], max_gross):
		raise ValueError("La configuration CEMAC est manquante ou le poids en charge dépasse sa limite.")
	if any(vehicle[name] > value for name, value in ENVELOPE.items()):
		raise ValueError("Le camion dépasse le gabarit ou le poids pris en charge par le graphe.")
	if axle_group_loads:
		if len(axle_group_loads) != len(group_limits) or any(
			not isfinite(load) or not 0 < load <= limit for load, limit in zip(axle_group_loads, group_limits)
		):
			raise ValueError("Les charges déclarées ne correspondent pas aux limites par groupe d’essieux.")
		if abs(sum(axle_group_loads) - gross) > 100:
			raise ValueError("La somme des charges aux essieux doit correspondre au poids total en charge à 100 kg près.")
	if vehicle["ptac"] <= 3500 and vehicle["height"] < 3:
		raise ValueError("La catégorie poids lourd ne peut pas être établie pour ce véhicule.")
	expected_axles = sum(int(digit) for digit in (vehicle["cemac"][1:3] + vehicle["cemac"][4:]))
	if vehicle["axles"] != expected_axles:
		raise ValueError("Le nombre d’essieux doit correspondre à la configuration CEMAC renseignée.")
	return gross, "3b" if vehicle["axles"] == 2 else "4"


def number(value, default=0):
	return float(default if value is None else value)


def fetch_route(base, locations):
	query = ";".join(f"{lon:.7f},{lat:.7f}" for lon, lat in locations)
	try:
		response = requests.get(f"{base.rstrip('/')}/route/v1/driving/{query}", params={
			"overview": "full", "geometries": "geojson",
			"radiuses": ";".join(["1000"] * len(locations)),
		}, timeout=(3, 15))
		payload = response.json()
		if payload.get("code") == "Ok":
			return payload["routes"][0]
		if payload.get("code") in ("NoRoute", "NoSegment"):
			frappe.throw("Aucun itinéraire dans le graphe pour ces étapes.")
	except (requests.RequestException, ValueError, KeyError, IndexError):
		pass
	frappe.throw("Le service de routage est temporairement indisponible.")


def planned_tolls(path, stops, date, category):
	estimates = []
	for station in stops:
		# Search-area pins are excluded. Near-route matches are budget estimates.
		if station.custom_toll_precision == "Repère de recherche":
			continue
		scale = 111195
		latitude = station.latitude
		longitude = station.longitude
		if latitude is None or longitude is None:
			continue
		x_scale = scale * cos(radians(latitude))
		points = [((lon - longitude) * x_scale, (lat - latitude) * scale) for lon, lat in path]
		along = 0
		closest = (float("inf"), 0)
		for (x, y), (x2, y2) in zip(points, points[1:]):
			dx, dy = x2 - x, y2 - y
			length = hypot(dx, dy)
			if length:
				t = max(0, min(1, -(x * dx + y * dy) / length**2))
				closest = min(closest, (hypot(x + t * dx, y + t * dy), along + t * length))
				along += length
		if closest[0] > min(650, max(45, station.custom_toll_accuracy_m or 45)):
			continue
		rates = [
			rate for rate in station.custom_toll_rates
			if rate.vehicle_class == category and rate.currency == "XAF"
			and getdate(rate.valid_from) <= date
			and (not rate.valid_until or date <= getdate(rate.valid_until))
		]
		rate = rates[0] if len(rates) == 1 else None
		estimates.append({
			"name": station.name, "latitude": latitude, "longitude": longitude,
			"precision": station.custom_toll_precision, "position_m": round(closest[1]),
			"amount": rate.amount if rate else None, "source": rate.source if rate else None,
		})
	return sorted(estimates, key=lambda stop: stop["position_m"])


@frappe.whitelist()
def preview(trip_name: str, cargo_kg: float, cargo_m3: float, via: str | None = None, axle_loads: str = ""):
	"""Use persisted trip, vehicle and station records, subject to their Desk permissions."""
	url = frappe.conf.get("goods_transport_truck_osrm_url")
	if not url or not frappe.conf.get("goods_transport_osrm_url"):
		frappe.throw("Le routage poids lourds est indisponible sur ce site.")
	trip = frappe.get_doc("Transport Trip", trip_name)
	trip.check_permission("read")
	if not trip.vehicle:
		frappe.throw("Sélectionner un camion dans la mission.")
	vehicle = frappe.get_doc("Vehicle", trip.vehicle)
	vehicle.check_permission("read")
	spec = {
		"height": number(vehicle.get("custom_truck_height")),
		"width": number(vehicle.get("custom_truck_width")),
		"length": number(vehicle.get("custom_truck_length")),
		"tare": number(vehicle.get("custom_truck_tare")),
		"ptac": number(vehicle.get("custom_truck_ptac")),
		"axles": number(vehicle.get("custom_truck_axles")),
		"payload": number(vehicle.payload_capacity),
		"volume": number(vehicle.volume_capacity),
	}
	try:
		axles = [float(load.strip()) for load in axle_loads.split(";")] if axle_loads.strip() else []
		if cargo_kg < (trip.loaded_weight or 0):
			raise ValueError("Le poids prévu est inférieur au chargement enregistré dans la mission.")
		gross, category = vehicle_limits(spec | {"cemac": vehicle.get("custom_truck_cemac")}, cargo_kg, cargo_m3, axles)
	except ValueError as error:
		frappe.throw(str(error))
	stops = [name for name in (trip.origin, via, trip.destination) if name]
	if not trip.origin or not trip.destination or len(stops) != len(set(stops)):
		frappe.throw("Renseigner les lieux distincts de départ et d’arrivée sur la mission.")
	points = []
	for name in stops:
		location = frappe.get_doc("Transport Location", name)
		location.check_permission("read")
		lat, lon = location.latitude, location.longitude
		if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat, lon) == (0, 0):
			frappe.throw("Coordonnées GPS manquantes ou invalides pour {0}.".format(name))
		points.append((lon, lat))
	truck = fetch_route(url, points)
	car = fetch_route(frappe.conf.goods_transport_osrm_url, points)
	path = truck["geometry"]["coordinates"]
	stations = [
		frappe.get_doc("Transport Location", item.name) for item in frappe.get_list(
			"Transport Location", filters={"location_type": "Péage", "is_active": 1}, limit_page_length=0,
		)
	]
	tolls = planned_tolls(path, stations, getdate(trip.trip_date), category)
	return {
		"truck": truck, "car": car, "tolls": tolls, "class": category, "gross_kg": gross,
		"known_subtotal": sum(toll["amount"] for toll in tolls if toll["amount"] is not None),
		"missing_tariffs": sum(toll["amount"] is None for toll in tolls),
		"axle_loads_entered": bool(axles),
	}
