"""Driver self-service projections. The role has no generic trip DocPerm."""

import json

import frappe
from frappe import _
from frappe.permissions import get_user_permissions
from frappe.utils import now_datetime

from goods_transport.setup.install_fleet_driver import ROLE

TRIP_FIELDS = (
	"name", "trip_date", "status", "vehicle", "vehicle_license_plate", "origin",
	"destination", "planned_departure_at", "planned_return_at", "departure_time",
	"arrival_time", "actual_distance", "departure_odometer", "arrival_odometer",
)
AUTHORIZATION_FIELDS = (
	"station", "fuel_type", "authorized_liters", "delivered_liters", "valid_from",
	"valid_until", "status",
)


def _assignment():
	user = frappe.session.user
	if user == "Guest" or ROLE not in frappe.get_roles(user):
		return None
	employees = frappe.get_all(
		"Employee", filters={"user_id": user, "status": "Active"},
		fields=["name", "company"], limit_page_length=2,
	)
	if len(employees) != 1 or not employees[0].company:
		return None
	employee = employees[0]
	drivers = frappe.get_all(
		"Driver", filters={"employee": employee.name, "status": "Active"},
		pluck="name", limit_page_length=2,
	)
	if len(drivers) != 1:
		return None
	company_permissions = get_user_permissions(user).get("Company", ())
	companies = {
		entry["doc"] for entry in company_permissions
		if entry.get("applicable_for") in (None, "", "Transport Trip")
	}
	if companies and employee.company not in companies:
		return None
	return {"driver": drivers[0], "company": employee.company, "docstatus": 1}


@frappe.whitelist(methods=["GET"])
def available():
	return bool(_assignment())


def _project_trip(trip, assignment):
	locations = []
	stored_plan = json.loads(trip.fuel_plan_inputs or "{}")
	for name in dict.fromkeys((trip.origin, stored_plan.get("via"), trip.destination)):
		if not name:
			continue
		location = frappe.db.get_value(
			"Transport Location", name,
			["name", "location_name", "address", "latitude", "longitude"], as_dict=True,
		)
		if location:
			locations.append(location)
	authorizations = frappe.get_all(
		"Fuel Authorization",
		filters={
			"trip": trip.name, "driver": assignment["driver"],
			"company": assignment["company"], "vehicle": trip.vehicle,
		},
		fields=AUTHORIZATION_FIELDS,
		order_by="valid_from asc, creation asc",
	)
	forecast = stored_plan.get("confirmed_forecast") or {}
	stop_fields = ("station", "latitude", "longitude", "refill_liters")
	stops = [{field: stop.get(field) for field in stop_fields} for stop in forecast.get("stops", [])]
	result = {field: trip.get(field) for field in TRIP_FIELDS}
	return {**result, "locations": locations, "fuel_stops": stops, "authorizations": authorizations}


@frappe.whitelist(methods=["GET"])
def missions():
	assignment = _assignment()
	if assignment is None:
		frappe.throw(_("Fleet Driver access is unavailable."), frappe.PermissionError)
	rows = frappe.get_all(
		"Transport Trip", filters=assignment, fields=(*TRIP_FIELDS, "fuel_plan_inputs"),
		order_by="trip_date desc, name desc",
	)
	return {
		"user": frappe.session.user,
		"trips": [_project_trip(row, assignment) for row in rows],
		"synced_at": now_datetime().isoformat(),
	}
