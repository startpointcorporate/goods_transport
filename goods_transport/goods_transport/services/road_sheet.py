"""Printable projection of a Transport Trip and its current routing plan."""

from json import loads
from urllib.parse import urlencode, urlsplit

import frappe
from frappe.utils import get_datetime, now_datetime
from frappe.utils.pdf import get_pdf
from werkzeug.wrappers import Response

from .fuel import AUTHORIZATION, RESERVE, STATION
from .truck_plan import plan_signature, preview

ENDPOINT = "/api/method/goods_transport.goods_transport.services.road_sheet.render"
INPUTS = ("cargo_kg", "cargo_m3", "via", "axle_loads", "departure_liters")


def gps(latitude, longitude):
	return "https://www.google.com/maps/dir/?" + urlencode({
		"api": 1, "destination": f"{latitude:.6f},{longitude:.6f}",
	})


def itinerary(trip, via, truck, fuel):
	locations = [frappe.get_doc("Transport Location", name) for name in (trip.origin, via, trip.destination) if name]
	locations_by_point = {(row.longitude, row.latitude): row for row in locations}
	points = fuel.get("waypoints") or [(row.longitude, row.latitude) for row in locations]
	stations = {(stop["longitude"], stop["latitude"]): stop for stop in fuel.get("stops", [])}
	rows = []
	for index, point in enumerate(points):
		longitude, latitude = point
		location = locations_by_point.get(tuple(point))
		station = stations.get(tuple(point))
		kind = "start" if index == 0 else "end" if index == len(points) - 1 else "via"
		if station and kind == "via":
			kind = "station"
		if kind == "start":
			name = trip.origin
		elif kind == "end":
			name = trip.destination
		elif kind == "station":
			name = station["station"]
		else:
			name = location.name
		rows.append({
			"name": name,
			"kind": kind, "latitude": latitude, "longitude": longitude, "gps": gps(latitude, longitude),
			"km": truck["legs"][index - 1]["distance"] / 1000 if index else None,
		})
	return rows


def fuel_rows(trip, stored, fuel):
	now = now_datetime()
	codes = stored.get("authorization_codes", []) if fuel.get("confirmed") else []
	authorizations = {}
	if codes:
		authorizations = {row.name: row for row in frappe.get_list(AUTHORIZATION,
			filters={"name": ["in", codes], "trip": trip.name, "company": trip.company,
				"vehicle": trip.vehicle, "driver": trip.driver},
			fields=["name", "reserve", "status", "valid_from", "valid_until", "authorized_liters",
				"delivered_liters"], limit_page_length=0)}
	rows = []
	for index, stop in enumerate(fuel.get("stops", [])):
		auth = authorizations.get(codes[index]) if index < len(codes) else None
		station = frappe.db.get_value(RESERVE, stop["reserve"], "station")
		address = None
		if station:
			station_doc = frappe.get_doc(STATION, station)
			if station_doc.has_permission("read"):
				address = station_doc.street_address
		status, authorized, delivered = "pending", None, None
		if auth and auth.reserve == stop["reserve"]:
			if auth.status == "Consumed":
				status, authorized, delivered = "consumed", auth.authorized_liters, auth.delivered_liters
			elif auth.status == "Reserved" and get_datetime(auth.valid_until) > now:
				status = "scheduled" if get_datetime(auth.valid_from) > now else "authorized"
				authorized = auth.authorized_liters
			else:
				status = "inactive"
		rows.append({
			"station": stop["station"], "address": address, "type": fuel["fuel_type"],
			"planned": stop["refill_liters"], "authorized": authorized, "delivered": delivered,
			"status": status, "gps": gps(stop["latitude"], stop["longitude"]),
			"latitude": stop["latitude"], "longitude": stop["longitude"],
		})
	return rows


def costs(trip, plan, fuel):
	toll_total = plan["known_subtotal"] if not plan["missing_tariffs"] else None
	fuel_total = fuel.get("cost")
	other = [
		(key, trip.get(field)) for key, field in (("hire", "agreed_vehicle_hire"), ("allowance", "driver_allowance"))
		if trip.get(field)
	]
	total = None
	if (toll_total is not None and fuel_total is not None and trip.currency
		and (not toll_total or trip.currency == "XAF") and (not fuel_total or fuel.get("currency") == trip.currency)):
		total = toll_total + fuel_total + sum(amount for _, amount in other)
	return other, toll_total, fuel_total, total


def company_details(company_name):
	company = frappe.get_doc("Company", company_name)
	company.check_permission("read")
	logo = company.company_logo
	# Restrict image sources to the current site's public files.
	if logo and (urlsplit(logo).netloc or not logo.startswith("/files/")):
		logo = None
	addresses = frappe.get_list("Address", filters=[
		["Dynamic Link", "link_doctype", "=", "Company"],
		["Dynamic Link", "link_name", "=", company_name],
		["Address", "disabled", "=", 0],
	], fields=["address_line1", "address_line2", "city", "country", "phone", "email_id"],
		order_by="is_primary_address desc, name asc", limit_page_length=1)
	return company, logo, addresses[0] if addresses else {}


@frappe.whitelist(methods=["GET"])
def render(trip_name: str, language: str, inputs: str, modified: str, pdf: int = 0):
	if language not in ("fr", "en"):
		frappe.throw("Language must be fr or en.")
	trip = frappe.get_doc("Transport Trip", trip_name)
	trip.check_permission("read")
	trip.check_permission("print")
	if trip.docstatus == 2:
		frappe.throw("Cancelled trip / Mission annulée")
	if get_datetime(modified) != get_datetime(trip.modified):
		frappe.throw("Reload the trip and recalculate its route. / Rechargez la mission et recalculez son itinéraire.")
	settings = loads(inputs)
	args = {key: settings.get(key) for key in INPUTS}
	args["cargo_kg"] = float(args.get("cargo_kg") or 0)
	if args["cargo_m3"] is not None:
		args["cargo_m3"] = float(args["cargo_m3"])
	args["via"] = args.get("via") or None
	args["axle_loads"] = args.get("axle_loads") or ""
	if args.get("departure_liters") is not None:
		args["departure_liters"] = float(args["departure_liters"])
	stored = loads(trip.fuel_plan_inputs or "{}")
	stale = False
	if stored.get("authorization_codes"):
		# Preserve the original numeric representation used by the signature.
		snapshot = stored.get("confirmed_forecast")
		original = {key: stored.get(key) for key in INPUTS}
		stale = (not snapshot or args != original
			or stored.get("signature") != plan_signature(trip, original, snapshot))
		if not stale:
			args = {**original, "confirmed": True}
	if not args.get("confirmed"):
		args["selected_reserves"] = settings.get("selected_reserves")
	plan = preview(trip_name, **args)
	fuel = plan["fuel"] or {}
	rows = fuel_rows(trip, stored, fuel)
	company, logo, address = company_details(trip.company)
	other, toll_total, fuel_total, total = costs(trip, plan, fuel)

	def number(value, places=1):
		if value is None:
			return "—"
		formatted = f"{value:,.{places}f}"
		return formatted.translate(str.maketrans({",": " ", ".": ","})) if language == "fr" else formatted

	def date(value, time=False):
		if not value:
			return "—"
		pattern = "%d/%m/%Y" if language == "fr" else "%Y-%m-%d"
		return get_datetime(value).strftime(pattern + (" %H:%M" if time else ""))

	html = frappe.render_template("goods_transport/templates/road_sheet.html", {
		"language": language, "trip": trip, "company": company, "logo": logo, "address": address,
		"route": plan["truck"], "tolls": plan["tolls"], "known_tolls": plan["known_subtotal"],
		"missing_tariffs": plan["missing_tariffs"], "rows": rows,
		"steps": itinerary(trip, args["via"], plan["truck"], fuel),
		"other": other, "toll_total": toll_total, "fuel_total": fuel_total, "fuel_currency": fuel.get("currency"),
		"total": total,
		"planned_liters": sum(row["planned"] for row in rows) if fuel.get("feasible") else None,
		"stale": stale, "fuel_checked": bool(fuel), "fuel_feasible": fuel.get("feasible"),
		"shortfall": (fuel.get("actual_projection") or {}).get("first_shortfall"),
		"volume_checked": plan["volume_checked"],
		"axles_checked": plan["axle_loads_entered"], "number": number, "date": date,
		"generated": now_datetime(), "gps": gps, "pdf": pdf,
		"download": ENDPOINT + "?" + urlencode({
			"trip_name": trip.name, "language": language, "inputs": inputs, "modified": modified, "pdf": 1,
		}),
	})
	if pdf:
		return Response(get_pdf(html, {"page-size": "A4"}), mimetype="application/pdf", headers={
			"Content-Disposition": f'attachment; filename="road-sheet-{language}.pdf"',
			"Cache-Control": "private, no-store",
		})
	return Response(html, mimetype="text/html", headers={"Cache-Control": "private, no-store"})


def fleet_pdf(trip, tolls, language):
	"""Render the chauffeur projection with the same PDF engine as the Desk."""
	html = frappe.render_template("goods_transport/templates/fleet_road_sheet.html", {
		"trip": trip, "tolls": tolls, "fr": language == "fr",
	})
	return Response(get_pdf(html, {"page-size": "A4"}), mimetype="application/pdf", headers={
		"Content-Disposition": f'inline; filename="road-sheet-{language}.pdf"',
		"Cache-Control": "private, no-store",
		"X-Content-Type-Options": "nosniff",
	})
