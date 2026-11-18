"""Apply actual trip readings to the shared HRMS vehicle counter."""

import re

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime


READING_FIELDS = ("departure_odometer", "arrival_odometer")
AUDIT_FIELDS = ("odometer_recorded_at", "odometer_recorded_by", "odometer_vehicle_log")
ARRIVAL_STATUSES = ("Arrived", "Unloading", "Delivered", "Settled", "Closed")


def reading(value):
	if value in (None, ""):
		return None
	if not re.fullmatch(r"[0-9]{1,10}", str(value)) or int(value) > 2147483647:
		frappe.throw(_("Enter an odometer reading as a non-negative whole number of kilometres."))
	return int(value)


def lock_vehicle(vehicle):
	current = frappe.db.get_value(
		"Vehicle", vehicle, ["name", "company", "last_odometer", "current_status", "custom_maintenance_asset"],
		as_dict=True, for_update=True,
	)
	if not current:
		frappe.throw(_("Vehicle {0} does not exist.").format(vehicle))
	return current


def validate_trip_readings(trip):
	before = trip.get_doc_before_save()
	if any(str(trip.get(field) or "") != str((before.get(field) or "") if before else "")
		for field in AUDIT_FIELDS):
		frappe.throw(_("Odometer audit fields are maintained by the system."))

	start, end = (reading(trip.get(field)) for field in READING_FIELDS)
	if before and before.odometer_recorded_at:
		if any(trip.get(field) != before.get(field) for field in (*READING_FIELDS, "vehicle", "actual_distance")):
			frappe.throw(_("Verified readings require an authorised correction."))
	if end is not None and (start is None or end < start):
		frappe.throw(_("The arrival odometer must be greater than or equal to the departure odometer."))


def record_trip_readings(trip):
	if trip.odometer_recorded_at or trip.status not in ARRIVAL_STATUSES:
		return
	start, end = (reading(trip.get(field)) for field in READING_FIELDS)
	if end is None:
		return
	if start is None or end < start:
		frappe.throw(_("The arrival odometer must be greater than or equal to the departure odometer."))

	vehicle = lock_vehicle(trip.vehicle)
	if vehicle.last_odometer is not None and start < vehicle.last_odometer:
		frappe.throw(_("The departure odometer is below the last recorded vehicle reading."))

	employee = frappe.db.get_value("Driver", trip.driver, "employee") if trip.driver else None
	log_name = None
	if employee:
		log = frappe.get_doc({
			"doctype": "Vehicle Log",
			"license_plate": trip.vehicle,
			"employee": employee,
			"date": getdate(trip.arrival_time or now_datetime()),
			"last_odometer": start,
			"odometer": end,
		})
		log.insert(ignore_permissions=True)
		log.submit()
		log_name = log.name
	else:
		frappe.db.set_value("Vehicle", trip.vehicle, "last_odometer", end)
	trip.db_set({
		"odometer_vehicle_log": log_name,
		"actual_distance": end - start,
		"odometer_recorded_at": now_datetime(),
		"odometer_recorded_by": frappe.session.user,
	})

	from goods_transport.goods_transport.doctype.vehicle_maintenance_schedule.vehicle_maintenance_schedule import refresh_vehicle_alerts

	refresh_vehicle_alerts(trip.vehicle, end)


def validate_vehicle_log_on_submit(log, method=None):
	vehicle = lock_vehicle(log.license_plate)
	if vehicle.last_odometer is not None and log.last_odometer < vehicle.last_odometer:
		frappe.throw(_("The starting odometer is below the last recorded vehicle reading."))


def validate_vehicle_log_on_cancel(log, method=None):
	vehicle = lock_vehicle(log.license_plate)
	if frappe.db.exists("Transport Trip", {"odometer_vehicle_log": log.name}):
		frappe.throw(_("Correct the odometer reading through its Transport Trip."))
	if vehicle.last_odometer != log.odometer:
		frappe.throw(_("A newer odometer reading exists for this vehicle."))


def validate_vehicle(doc, method=None):
	asset = doc.get("custom_maintenance_asset")
	if asset and frappe.db.get_value("Asset", asset, ["company", "docstatus"]) != (doc.company, 1):
		frappe.throw(_("Link a submitted maintenance asset from the same company."))
	if doc.is_new():
		return
	before = doc.get_doc_before_save()
	if before and doc.has_value_changed("last_odometer"):
		lock_vehicle(doc.name)
		if frappe.db.exists("Transport Trip", {"vehicle": doc.name, "odometer_recorded_at": ["is", "set"]}):
			frappe.throw(_("Use a recorded reading to update this vehicle's verified odometer."))
