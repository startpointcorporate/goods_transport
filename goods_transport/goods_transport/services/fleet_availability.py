import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from goods_transport.goods_transport.doctype.vehicle_maintenance_schedule.vehicle_maintenance_schedule import due_state
from goods_transport.goods_transport.services.fleet_odometer import lock_vehicle


ACTIVE_TRIP_STATUSES = ("Vehicle Assigned", "At Loading Point", "Loaded", "In Transit", "Arrived", "Unloading")


def reservation_window(trip):
	if not trip.planned_departure_at and not trip.planned_return_at:
		return None
	if not trip.planned_departure_at or not trip.planned_return_at:
		frappe.throw(_("Enter both planned departure and planned return."))
	start, end = get_datetime(trip.planned_departure_at), get_datetime(trip.planned_return_at)
	if start >= end:
		frappe.throw(_("The planned return must be later than the planned departure."))
	return start, end


def validate_assignment(trip, departing=False):
	vehicle = lock_vehicle(trip.vehicle)
	if vehicle.current_status in ("Under Maintenance", "Out of Service"):
		frappe.throw(_("Vehicle {0} is out of service.").format(trip.vehicle))
	immobilisation = frappe.db.get_value(
		"Vehicle Immobilisation",
		{"vehicle": trip.vehicle, "released_at": ["is", "not set"], "start_at": ["<=", now_datetime()]},
		"name", for_update=True,
	)
	if immobilisation:
		frappe.throw(_("Vehicle {0} is immobilised ({1}).").format(trip.vehicle, immobilisation))
	window = reservation_window(trip)
	reservations = frappe.db.get_values(
		"Transport Trip",
		{"vehicle": trip.vehicle, "docstatus": 1, "status": ["in", ACTIVE_TRIP_STATUSES],
		 "name": ["!=", trip.name]},
		["name", "status", "planned_departure_at", "planned_return_at"], as_dict=True, for_update=True,
	)
	for reservation in reservations:
		reserved = reservation_window(reservation)
		overlap = not (window and reserved) or window[0] < reserved[1] and reserved[0] < window[1]
		in_use = departing and reservation.status != "Vehicle Assigned"
		if overlap or in_use:
			frappe.throw(_("Vehicle {0} is already assigned to an active trip ({1}).").format(trip.vehicle, reservation.name))

	schedules = frappe.db.get_values("Vehicle Maintenance Schedule", {
		"vehicle": trip.vehicle, "enabled": 1, "blocking": 1,
	}, ["name", "due_date", "due_odometer", "advance_days", "advance_km"], as_dict=True, for_update=True)
	for schedule in schedules:
		if due_state(schedule, vehicle.last_odometer) in ("Due", "Overdue"):
			frappe.throw(_("Vehicle {0} has blocking maintenance due ({1}).").format(trip.vehicle, schedule.name))
