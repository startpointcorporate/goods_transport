from collections import Counter, defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, add_months, get_datetime, now_datetime, today

from goods_transport.goods_transport.doctype.vehicle_maintenance_schedule.vehicle_maintenance_schedule import due_state
from goods_transport.goods_transport.services.fleet_availability import ACTIVE_TRIP_STATUSES
from goods_transport.goods_transport.services.fleet_costs import vehicle_costs


ACCOUNTING_ROLES = {"Accounts Manager", "Accounts User", "System Manager"}


def stopped_hours(incidents, start, end, now):
	start, end = get_datetime(start), min(get_datetime(add_days(end, 1)), now)
	windows = sorted((max(row.start_at, start), min(row.released_at or now, end)) for row in incidents)
	seconds = 0
	covered_until = start
	for begin, finish in windows:
		begin = max(begin, covered_until)
		if finish > begin:
			seconds += (finish - begin).total_seconds()
			covered_until = finish
	return round(seconds / 3600, 2)


def execute(filters=None):
	filters = filters or {}
	vehicles = frappe.get_list("Vehicle", filters={
		target: filters[source] for source, target in (("company", "company"), ("vehicle", "name"))
		if filters.get(source)
	}, fields=["name", "last_odometer", "current_status"], limit=0)
	vehicle_names = [vehicle.name for vehicle in vehicles]
	financial = filters.get("company") and ACCOUNTING_ROLES.intersection(frappe.get_roles())
	start = filters.get("from_date") or add_months(today(), -3)
	end = filters.get("to_date") or today()
	costs = vehicle_costs(filters["company"], vehicle_names, start, end) if financial else {}
	distance = defaultdict(float)
	if financial and vehicle_names:
		for trip in frappe.get_list("Transport Trip", filters={
			"vehicle": ["in", vehicle_names], "company": filters["company"], "docstatus": 1,
			"odometer_recorded_at": ["is", "set"], "trip_date": ["between", [start, end]],
		}, fields=["vehicle", "actual_distance"], limit=0):
			distance[trip.vehicle] += trip.actual_distance
	rows = []
	summary = []
	if vehicle_names:
		trips = set(frappe.get_list("Transport Trip", filters={
			"vehicle": ["in", vehicle_names], "status": ["in", ACTIVE_TRIP_STATUSES], "docstatus": 1,
		}, pluck="vehicle", limit=0))
		incidents = defaultdict(list)
		for row in frappe.get_list("Vehicle Immobilisation", filters={"vehicle": ["in", vehicle_names]},
			fields=["name", "vehicle", "reason", "start_at", "released_at"], limit=0):
			incidents[row.vehicle].append(row)
		schedules = defaultdict(list)
		for row in frappe.get_list("Vehicle Maintenance Schedule", filters={
			"vehicle": ["in", vehicle_names], "enabled": 1,
		}, fields=["name", "vehicle", "due_date", "due_odometer", "advance_days", "advance_km", "blocking"], limit=0):
			schedules[row.vehicle].append(row)
		now = now_datetime()
		for vehicle in vehicles:
			current = [row for row in incidents[vehicle.name] if not row.released_at and row.start_at <= now]
			due = Counter(due_state(schedule, vehicle.last_odometer) for schedule in schedules[vehicle.name])
			if any(row.reason == "Breakdown" for row in current):
				status = "Breakdown"
			elif vehicle.current_status == "Under Maintenance" or any(row.reason == "Maintenance" for row in current):
				status = "Under Maintenance"
			elif current or vehicle.current_status == "Out of Service":
				status = "Out of Service"
			elif any(schedule.blocking and due_state(schedule, vehicle.last_odometer) in ("Due", "Overdue")
				for schedule in schedules[vehicle.name]):
				status = "Blocked by Maintenance"
			elif vehicle.name in trips:
				status = "In Trip"
			else:
				status = "Available"
			price = costs.get(vehicle.name, {})
			km = distance[vehicle.name]
			charges = price.get("charges", 0)
			rows.append({
				"parts": price.get("Parts", 0), "labor": price.get("Labor", 0),
				"external": price.get("External Service", 0), "charges": charges,
				"investment": price.get("investment", 0), "cash_out": price.get("cash_out", 0),
				"verified_km": km, "cost_per_km": charges / km if km else None,
				"vehicle": vehicle.name, "last_odometer": vehicle.last_odometer, "status": _(status),
				"upcoming": due["Upcoming"], "due": due["Due"], "overdue": due["Overdue"],
				"open_breakdowns": sum(row.reason == "Breakdown" for row in current),
				"stops": len(incidents[vehicle.name]),
				"stopped_hours": stopped_hours(incidents[vehicle.name], start, end, now),
			})
		counts = Counter(row["status"] for row in rows)
		summary = [
			{"label": _("Vehicles"), "value": len(rows), "indicator": "Blue"},
			{"label": _("Available"), "value": counts[_("Available")], "indicator": "Green"},
			{"label": _("In Trip"), "value": counts[_("In Trip")], "indicator": "Blue"},
			{"label": _("Unavailable"), "value": len(rows) - counts[_("Available")] - counts[_("In Trip")], "indicator": "Red"},
			{"label": _("Upcoming"), "value": sum(row["upcoming"] for row in rows), "indicator": "Orange"},
			{"label": _("Overdue"), "value": sum(row["overdue"] for row in rows), "indicator": "Red"},
		]
	columns = [
		{"fieldname": "vehicle", "label": _("Vehicle"), "fieldtype": "Link", "options": "Vehicle", "width": 170},
		{"fieldname": "status", "label": _("Availability"), "fieldtype": "Data", "width": 170},
		*({"fieldname": name, "label": _(label), "fieldtype": "Int", "width": 120} for name, label in (
			("last_odometer", "Odometer (km)"), ("upcoming", "Upcoming"), ("due", "Due"),
			("overdue", "Overdue"), ("open_breakdowns", "Open Breakdowns"), ("stops", "Immobilisations"),
		)),
	]
	columns.append({"fieldname": "stopped_hours", "label": _("Immobilised hours"), "fieldtype": "Float", "width": 130})
	if financial:
		currency = frappe.db.get_value("Company", filters["company"], "default_currency")
		for name, label in (("parts", "Parts"), ("labor", "Labor"), ("external", "External Service"),
			("charges", "Maintenance Charges"), ("investment", "Capitalised"), ("cash_out", "Cash Paid"),
			("verified_km", "Verified km"), ("cost_per_km", "Maintenance Cost per km")):
			columns.append({"fieldname": name, "label": _(label), "width": 145,
				"fieldtype": "Float" if name == "verified_km" else "Currency", "options": currency})
		summary.append({"label": _("Maintenance Charges"), "value": sum(row["charges"] for row in rows),
			"datatype": "Currency", "currency": currency, "indicator": "Blue"})
	return columns, rows, None, None, summary
