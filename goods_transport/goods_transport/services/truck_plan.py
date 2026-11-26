"""Planning estimates for the Congo truck routing service."""

from hashlib import sha256
from json import dumps, loads
from math import cos, hypot, isfinite, radians

import frappe
import requests
from frappe.utils import get_datetime, getdate, now_datetime

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
	bootinfo.goods_transport_trip_finance = bool(frappe.conf.get("goods_transport_trip_finance"))
	bootinfo.goods_transport_truck_plan = bool(frappe.conf.get("goods_transport_truck_osrm_url"))
	bootinfo.goods_transport_partner_fuel = bool(frappe.conf.get("goods_transport_partner_fuel"))


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


def osrm_response(url, params, timeout):
	# The Desk map may cache OSRM responses. Reserves and route-plan decisions
	# are always evaluated against current Frappe data.
	key = None
	if frappe.flags.get("goods_transport_cache_osrm"):
		identity = [url, params, frappe.conf.get("goods_transport_osrm_graph_revision")]
		key = "goods_transport:map:osrm:" + sha256(dumps(identity, sort_keys=True).encode()).hexdigest()
		cached = frappe.cache.get_value(key)
		if cached is not None:
			return cached
	response = requests.get(url, params=params, timeout=timeout).json()
	if key and response.get("code") == "Ok":
		frappe.cache.set_value(key, response, expires_in_sec=300)
	return response


def fetch_route(base, locations, *, fuel_stop=False):
	query = ";".join(f"{lon:.7f},{lat:.7f}" for lon, lat in locations)
	try:
		payload = osrm_response(f"{base.rstrip('/')}/route/v1/driving/{query}", {
			"overview": "full", "geometries": "geojson",
			"radiuses": ";".join(["1000"] * len(locations)),
			**({"continue_straight": "true"} if fuel_stop else {}),
		}, timeout=(3, 15))
		if payload.get("code") == "Ok":
			return payload["routes"][0]
		if payload.get("code") in ("NoRoute", "NoSegment"):
			if fuel_stop:
				return None
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


def fetch_distances(base, points):
	def query(service, locations, params):
		coords = ";".join(f"{lon:.7f},{lat:.7f}" for lon, lat in locations)
		return osrm_response(f"{base.rstrip('/')}/{service}/v1/driving/{coords}", params, timeout=(3, 12))

	try:
		radii = ";".join(["1000"] * len(points))
		data = query("table", points, {"annotations": "distance", "radiuses": radii})
		if data.get("code") == "Ok":
			return data["distances"]
		if data.get("code") == "NoSegment":
			reachable = [i for i, point in enumerate(points) if
				query("nearest", [point], {"radiuses": "1000"}).get("code") == "Ok"]
			matrix = [[None] * len(points) for _ in points]
			if len(reachable) >= 2:
				values = fetch_distances(base, [points[i] for i in reachable]) if len(reachable) < len(points) else None
				if values is None:
					frappe.throw("Le graphe poids lourd ne peut pas rattacher ces points.")
				for i, source in enumerate(reachable):
					for j, target in enumerate(reachable):
						matrix[source][target] = values[i][j]
			return matrix
	except (requests.RequestException, ValueError, KeyError):
		pass
	frappe.throw("La matrice de distances poids lourd est temporairement indisponible.")


def parse_reserves(value):
	try:
		names = loads(value) if isinstance(value, str) else value
	except ValueError:
		names = False
	if names is not None and (not isinstance(names, list) or len(names) > 48
			or any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names)):
		frappe.throw("Sélectionnez des réserves distinctes dans l’ordre du trajet.")
	return names


@frappe.whitelist()
def preview(trip_name: str, cargo_kg: float, cargo_m3: float, via: str | None = None, axle_loads: str = "",
		departure_liters: float | None = None, selected_reserve: str | None = None,
		selected_reserves: str | list[str] | None = None, confirmed: bool = False):
	"""Use persisted trip, vehicle and station records, subject to their Desk permissions."""
	selected_reserves = parse_reserves(selected_reserves)
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
	from .toll_routing import location_coordinates

	stops = [name for name in (trip.origin, via, trip.destination) if name]
	if not trip.origin or not trip.destination or len(stops) != len(set(stops)):
		frappe.throw("Renseigner les lieux distincts de départ et d’arrivée sur la mission.")
	points = [location_coordinates(name) for name in stops]
	truck = fetch_route(url, points)
	car_points = points
	stations = [
		frappe.get_doc("Transport Location", item.name) for item in frappe.get_list(
			"Transport Location", filters={"location_type": "Péage", "is_active": 1}, limit_page_length=0,
		)
	]
	def tolls_on(route):
		return planned_tolls(route["geometry"]["coordinates"], stations, getdate(trip.trip_date), category)

	fuel = None
	if departure_liters is not None and frappe.conf.get("goods_transport_partner_fuel"):
		from .fuel_plan import estimate, project_withdrawals

		stored = loads(trip.fuel_plan_inputs or "{}") if confirmed else {}
		args = dict(cargo_kg=cargo_kg, cargo_m3=cargo_m3, departure_liters=departure_liters,
			via=via, axle_loads=axle_loads)
		snapshot = stored.get("confirmed_forecast")
		original_args = {key: stored.get(key) for key in args}
		# Frappe may coerce a request integer to float. Keep the stored representation
		# for signature verification once the input values have been matched.
		if snapshot and args == original_args and stored["signature"] == plan_signature(trip, original_args, snapshot):
			fuel = snapshot
			current = fetch_route(url, fuel["waypoints"], fuel_stop=True)
			if not current or abs(current["distance"] - fuel["distance"]) > 1:
				frappe.throw("Le graphe routier a changé depuis la confirmation. Consultez les retraits déjà autorisés.")
			truck = current
			fuel["confirmed"] = True
			from .fuel import AUTHORIZATION
			history = frappe.get_list(AUTHORIZATION, filters={"trip": trip.name}, fields=[
				"name", "status", "authorized_liters", "delivered_liters", "valid_until"], limit_page_length=0)
			by_code = {row.name: row for row in history}
			fuel["actual_projection"] = project_withdrawals(fuel,
				[by_code.get(code) for code in stored["authorization_codes"]], now_datetime())
			fuel["authorized_liters"] = sum(row.authorized_liters for row in history
				if row.status == "Reserved" and row.valid_until > now_datetime())
			fuel["delivered_liters"] = sum(row.delivered_liters or 0 for row in history if row.status == "Consumed")
		else:
			fuel, truck, points = estimate(trip, vehicle, points, truck, departure_liters,
				lambda waypoints: fetch_route(url, waypoints, fuel_stop=True),
				lambda waypoints: fetch_distances(url, waypoints),
				selected_reserves or ([selected_reserve] if selected_reserve else None), tolls_on)
	car = fetch_route(frappe.conf.goods_transport_osrm_url, car_points)
	tolls = tolls_on(truck)
	return {
		"truck": truck, "car": car, "tolls": tolls, "class": category, "gross_kg": gross,
		"known_subtotal": sum(toll["amount"] for toll in tolls if toll["amount"] is not None),
		"missing_tariffs": sum(toll["amount"] is None for toll in tolls),
		"axle_loads_entered": bool(axles), "fuel": fuel,
	}


def plan_signature(trip, args, forecast):
	content = [trip.name, trip.company, trip.vehicle, trip.driver, trip.origin, trip.destination,
		str(trip.trip_date), args, [(s["reserve"], s["refill_liters"], s["leg_km"],
			s["latitude"], s["longitude"]) for s in forecast["stops"]], forecast.get("last_leg_km")]
	return sha256(dumps(content, sort_keys=True).encode()).hexdigest()


@frappe.whitelist(methods=["POST"])
def save_fuel_plan(trip_name: str, cargo_kg: float, cargo_m3: float, departure_liters: float,
		selected_reserves: str | list[str] | None = None, via: str | None = None, axle_loads: str = ""):
	trip = frappe.get_doc("Transport Trip", trip_name, for_update=True)
	trip.check_permission("write")
	if trip.docstatus == 2 or not frappe.conf.get("goods_transport_partner_fuel"):
		frappe.throw("La sélection des arrêts carburant est indisponible.")
	selected_reserves = parse_reserves(selected_reserves)
	args = dict(cargo_kg=cargo_kg, cargo_m3=cargo_m3, departure_liters=departure_liters,
		via=via, axle_loads=axle_loads)
	plan = preview(trip_name, **args, selected_reserves=selected_reserves)
	forecast = plan["fuel"]
	if not forecast["feasible"]:
		frappe.throw("Cette combinaison de réserves ne permet plus de terminer la mission.")
	reserves = [stop["reserve"] for stop in forecast["stops"]]
	prior = loads(trip.fuel_plan_inputs or "{}")
	if prior.get("authorization_codes"):
		from .fuel import AUTHORIZATION

		if frappe.db.exists(AUTHORIZATION, {"name": ["in", prior["authorization_codes"]],
				"status": ["in", ["Reserved", "Consumed"]]}):
			frappe.throw("Ce plan a des retraits réservés ou consommés. Consultez ses autorisations.")
	signature = plan_signature(trip, args, forecast)
	frappe.db.set_value("Transport Trip", trip_name, {
		"fuel_stop_reserve": reserves[0] if reserves else None,
		"fuel_plan_inputs": dumps({**args, "selected_reserves": reserves, "signature": signature}),
	})
	return plan


@frappe.whitelist(methods=["POST"])
def select_fuel_stop(trip_name: str, cargo_kg: float, cargo_m3: float, departure_liters: float,
		selected_reserve: str, via: str | None = None, axle_loads: str = ""):
	return save_fuel_plan(trip_name, cargo_kg, cargo_m3, departure_liters, [selected_reserve], via, axle_loads)


@frappe.whitelist(methods=["POST"])
def confirm_fuel_plan(trip_name: str, signature: str, valid_until: str, valid_from: str | None = None):
	from .fuel import AUTHORIZATION, issue, locked_reserve

	trip = frappe.get_doc("Transport Trip", trip_name, for_update=True)
	trip.check_permission("write")
	stored = loads(trip.fuel_plan_inputs or "{}")
	if trip.docstatus == 2 or not frappe.conf.get("goods_transport_partner_fuel") or not stored.get("signature"):
		frappe.throw("Enregistrez un plan carburant valide avant de l’autoriser.")
	if signature != stored["signature"]:
		frappe.throw("Le plan a changé. Rechargez la mission.")
	if stored.get("authorization_codes"):
		return stored["authorization_codes"]
	start = get_datetime(valid_from) if valid_from else now_datetime()
	if not valid_until or not start.date() <= getdate(trip.trip_date) <= getdate(valid_until):
		frappe.throw("La période de validité doit couvrir la date de la mission.")
	reserves = stored.get("selected_reserves")
	if not reserves:
		frappe.throw("Le plan ne nécessite aucun ravitaillement.")
	args = {key: stored[key] for key in ("cargo_kg", "cargo_m3", "departure_liters", "via", "axle_loads")}
	plan = preview(trip_name, **args, selected_reserves=reserves)
	forecast = plan["fuel"]
	if not forecast["feasible"] or plan_signature(trip, args, forecast) != signature:
		frappe.throw("La mission, l’itinéraire ou les réserves ont changé. Recalculez et enregistrez le plan.")
	if frappe.db.get_value(AUTHORIZATION, {"trip": trip_name, "status": "Reserved"}, "name"):
		frappe.throw("Cette mission a déjà des autorisations en cours. Consultez-les avant de confirmer le plan.")
	locked = {name: locked_reserve(name) for name in sorted(reserves)}
	codes = [issue(trip, locked[stop["reserve"]], str(stop["refill_liters"]), valid_until, valid_from)
		for stop in forecast["stops"]]
	stored["authorization_codes"] = codes
	stored["confirmed_forecast"] = forecast
	frappe.db.set_value("Transport Trip", trip_name, "fuel_plan_inputs", dumps(stored))
	return codes
