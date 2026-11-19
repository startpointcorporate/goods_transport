"""Seed fictional map data on an existing disposable Frappe QA site."""
import json
import os

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import add_days, now_datetime, today

site = os.environ["FLEET_QA_SITE"]
if not site.endswith(".localhost"):
	raise RuntimeError("Use a disposable local site")
os.chdir("sites")
frappe.init(site)
frappe.connect()
frappe.set_user("Administrator")

if not frappe.db.exists("DocType", "Fleet Toll Rate"):
	frappe.get_doc(dict(doctype="DocType", name="Fleet Toll Rate", module="Goods Transport",
		custom=1, istable=1, fields=[
			{"fieldname": field, "label": field.replace("_", " ").title(), "fieldtype": kind}
			for field, kind in (("vehicle_class", "Data"), ("amount", "Currency"), ("currency", "Data"),
				("valid_from", "Date"), ("valid_until", "Date"), ("source", "Small Text"))
		])).insert()
	create_custom_fields({"Transport Location": [
		{"fieldname": field, "label": field.replace("_", " ").title(), "fieldtype": kind,
			**({"options": "Fleet Toll Rate"} if kind == "Table" else {})}
		for field, kind in (
			("custom_toll_id", "Data"), ("custom_toll_road", "Data"), ("custom_toll_status", "Data"),
			("custom_toll_precision", "Data"), ("custom_toll_accuracy_m", "Int"),
			("custom_toll_routing", "Data"), ("custom_toll_rates", "Table"),
		)
	]})
	frappe.clear_cache()

create_custom_fields({"Vehicle": [
	{"fieldname": f"custom_truck_{name}", "label": f"Truck {name}", "fieldtype": kind}
	for name, kind in (("height", "Float"), ("width", "Float"), ("length", "Float"), ("tare", "Float"),
		("ptac", "Float"), ("axles", "Int"), ("cemac", "Data"))
]})

company, other = frappe.get_all("Company", order_by="name", pluck="name")[:2]
base = frappe.get_doc("Transport Trip", frappe.get_all(
	"Transport Trip", filters={"name": ["not like", "MAP-QA-%"]}, limit=1, pluck="name",
)[0])
vehicle = frappe.get_doc("Vehicle", base.vehicle)

def fixture(doctype, name, **fields):
	doc = frappe.get_doc({"doctype": doctype, "name": name, **fields})
	if frappe.db.exists(doctype, name):
		doc.db_update()
	else:
		doc.db_insert()
	return doc

def location(name, longitude, latitude, **fields):
	kind = "Péage" if "custom_toll_id" in fields else "City"
	return fixture("Transport Location", name, location_name=name, location_type=kind,
		longitude=longitude, latitude=latitude, is_active=1, **fields)

origin = location("Pointe-Noire (QA)", 11.86, -4.79)
destination = location("Brazzaville (QA)", 15.28, -4.27)
via = location("Étape RN1 (QA)", 12.471474, -4.260278)
changed = location("Nouvelle étape RN1 (QA)", 13.256121, -4.163477)
for index, (name, lon, lat) in enumerate([
	("Péage QA vérifié", 12.052949, -4.579437),
	("Péage QA sans tarif", 13.959666, -4.314413),
], 1):
	toll = location(name, lon, lat, custom_toll_id=f"MAP-QA-{index}",
		custom_toll_road="RN1", custom_toll_accuracy_m=100,
		custom_toll_precision="Passage cartographié")
	if index == 1:
		rate = toll.append("custom_toll_rates", dict(vehicle_class="3b", currency="XAF",
			valid_from=add_days(today(), -2), amount=15000, source="QA"))
		rate.name = "MAP-QA-RATE"
		if not frappe.db.exists(rate.doctype, rate.name):
			rate.db_insert()
for index, (name, lon, lat, owner) in enumerate([
	("Station QA sélectionnée", 12.362961, -4.327394, company),
	("Station QA disponible", 12.593755, -4.185465, company),
	("Station QA indisponible", 14.922954, -3.939201, company),
	("Station QA étrangère", 13.256121, -4.163477, other),
], 1):
	station = fixture("Fuel Partner Station", f"MAP-QA-STATION-{index}", company=owner,
		station_name=name, street_address="RN1", longitude=lon, latitude=lat, diesel=1)
	if index != 3:
		fixture("Fuel Contract Reserve", f"MAP-QA-RESERVE-{index}", company=owner,
			station=station.name, fuel_type="Diesel", valid_from=add_days(today(), -2),
			contract_reference=f"MAP-QA-{index}", available_liters=350, remaining_liters=350)

frappe.db.set_value("Vehicle", vehicle.name, {
	"custom_truck_height": 3.5, "custom_truck_width": 2.45, "custom_truck_length": 9,
	"custom_truck_tare": 8000, "custom_truck_ptac": 18000, "custom_truck_axles": 2,
	"payload_capacity": 10000, "volume_capacity": 42, "custom_truck_cemac": "P11",
	"fuel_type": "Diesel", "custom_fuel_tank_liters": 400, "custom_fuel_liters_100km": 35,
})
plan = dict(cargo_kg=7500, cargo_m3=20, departure_liters=90,
	via=via.name, axle_loads="", selected_reserves=["MAP-QA-RESERVE-1"])
for index, name in enumerate(("MAP-QA-RECENT", "MAP-QA-STALE", "MAP-QA-MISSING")):
	trip = frappe.copy_doc(base)
	trip.name, trip.company, trip.docstatus = name, company, 0
	trip.status, trip.trip_date, trip.currency = "Planned", today(), "XAF"
	trip.origin, trip.destination, trip.planned_distance = origin.name, destination.name, 576
	trip.loaded_weight, trip.fuel_plan_inputs = 0, json.dumps(plan)
	trip.route = None
	if index:
		trip.fuel_plan_inputs = json.dumps({**plan, "via": changed.name, "departure_liters": None, "selected_reserves": []})
	if frappe.db.exists(trip.doctype, name):
		trip.set("__islocal", 0)
		trip.db_update()
	else:
		trip.db_insert()

fixture("Fuel Authorization", "MAP-QA-AUTH", trip="MAP-QA-RECENT", company=company,
	vehicle=base.vehicle, driver=base.driver, station="MAP-QA-STATION-1", reserve="MAP-QA-RESERVE-1",
	fuel_type="Diesel", status="Reserved", authorized_liters=100,
	valid_from=add_days(now_datetime(), -1), valid_until=add_days(now_datetime(), 1))
user = "fleet-map-no-access@example.test"
if not frappe.db.exists("User", user):
	frappe.get_doc(dict(doctype="User", email=user, first_name="Map QA restricted", user_type="System User",
		send_welcome_email=0, roles=[{"role": "Desk User"}])).insert(ignore_permissions=True)
frappe.db.commit()
print(json.dumps({"trip": "MAP-QA-RECENT", "stale": "MAP-QA-STALE", "missing": "MAP-QA-MISSING",
	"via": via.name, "changedVia": changed.name}))
