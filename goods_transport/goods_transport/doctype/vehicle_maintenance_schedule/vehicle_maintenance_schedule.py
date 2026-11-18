import frappe
from frappe import _
from frappe.model.document import Document
from frappe.translate import get_user_lang
from frappe.utils import add_days, getdate, today

from goods_transport.goods_transport.services.fleet_odometer import lock_vehicle, reading


class VehicleMaintenanceSchedule(Document):
	def validate(self):
		vehicle = lock_vehicle(self.vehicle)
		before = self.get_doc_before_save()
		if vehicle.company != self.company:
			frappe.throw(_("The maintenance schedule and vehicle must belong to the same company."))
		if before and before.vehicle != self.vehicle:
			frappe.throw(_("The vehicle on a maintenance schedule cannot be changed."))
		if not self.flags.recording_completion:
			before_names = [row.get_valid_dict() for row in before.completions] if before else []
			new_names = [row.get_valid_dict() for row in self.completions]
			if before_names != new_names:
				frappe.throw(_("Use the completion operation to record preventive work."))
		if not (self.interval_days or self.interval_km):
			frappe.throw(_("Enter a maintenance interval in days or kilometres."))
		if bool(self.asset_maintenance) != bool(self.asset_task):
			frappe.throw(_("Provide both the Asset Maintenance document and its task row."))
		if self.asset_maintenance:
			task = frappe.db.get_value("Asset Maintenance Task", self.asset_task, ["parent", "parenttype"])
			if task != (self.asset_maintenance, "Asset Maintenance"):
				frappe.throw(_("The task must belong to the linked Asset Maintenance document."))
			if frappe.db.get_value("Asset Maintenance", self.asset_maintenance, ["company", "asset_name"]) != (
				self.company, vehicle.custom_maintenance_asset,
			):
				frappe.throw(_("Asset Maintenance must belong to the asset linked to the vehicle."))
			if frappe.db.exists("Vehicle Maintenance Schedule", {
				"asset_task": self.asset_task, "name": ["!=", self.name or ""], "enabled": 1,
			}):
				frappe.throw(_("A fleet maintenance schedule already uses this asset task."))

		last = self.completions[-1] if self.completions else None
		start_date = last.completion_date if last else self.initial_date
		start_km = reading(last.odometer if last else self.initial_odometer)
		if self.interval_days and not start_date:
			frappe.throw(_("Enter an initial date for calendar maintenance."))
		if self.interval_km and start_km is None:
			frappe.throw(_("Enter an initial odometer reading for mileage maintenance."))
		self.due_date = add_days(start_date, self.interval_days) if self.interval_days else None
		self.due_odometer = str(start_km + self.interval_km) if self.interval_km else None

	def on_update(self):
		refresh_schedule_alert(self)


def due_state(schedule, odometer, date=None):
	date = getdate(date or today())
	due_date = getdate(schedule.due_date) if schedule.due_date else None
	due_km = reading(schedule.due_odometer)
	remaining = []
	if due_date:
		remaining.append(((due_date - date).days, schedule.advance_days or 0))
	if due_km is not None and odometer is not None:
		remaining.append((due_km - odometer, schedule.advance_km or 0))
	if any(distance < 0 for distance, _ in remaining):
		return "Overdue"
	if any(distance == 0 for distance, _ in remaining):
		return "Due"
	if any(distance <= advance for distance, advance in remaining):
		return "Upcoming"
	return None


def refresh_schedule_alert(schedule, odometer=None):
	if odometer is None:
		odometer = frappe.db.get_value("Vehicle", schedule.vehicle, "last_odometer")
	state = due_state(schedule, odometer) if schedule.enabled else None
	todos = frappe.get_all("ToDo", filters={
		"reference_type": schedule.doctype, "reference_name": schedule.name, "status": "Open",
	}, fields=["name", "allocated_to", "description"])
	description = None
	if state:
		language = get_user_lang(schedule.responsible)
		description = _("Vehicle {0}: {1} ({2})", lang=language).format(
			schedule.vehicle, schedule.operation, _(state, lang=language, context="Fleet Maintenance"),
		)
	for todo in todos:
		if todo.allocated_to == schedule.responsible and todo.description == description:
			return
		frappe.db.set_value("ToDo", todo.name, "status", "Closed")
	if description:
		frappe.get_doc({
			"doctype": "ToDo", "reference_type": schedule.doctype, "reference_name": schedule.name,
			"allocated_to": schedule.responsible, "description": description,
			"date": schedule.due_date, "priority": "High" if state != "Upcoming" else "Medium",
		}).insert(ignore_permissions=True)


def refresh_vehicle_alerts(vehicle, odometer=None):
	for name in frappe.get_all("Vehicle Maintenance Schedule", filters={"vehicle": vehicle}, pluck="name"):
		refresh_schedule_alert(frappe.get_doc("Vehicle Maintenance Schedule", name), odometer)


def refresh_daily_alerts():
	vehicles = frappe.get_all("Vehicle Maintenance Schedule", filters={"enabled": 1}, distinct=True, pluck="vehicle")
	for vehicle in sorted(vehicles):
		current = lock_vehicle(vehicle)
		refresh_vehicle_alerts(vehicle, current.last_odometer)


@frappe.whitelist(methods=["POST"])
def complete_schedule(name, completion_date=None, details=None, odometer=None):
	schedule = frappe.get_doc("Vehicle Maintenance Schedule", name, for_update=True)
	schedule.check_permission("write")
	if schedule.asset_maintenance:
		frappe.throw(_("Submit the associated ERPNext Asset Maintenance Log to complete this task."))
	record_completion(schedule, completion_date or today(), details, odometer)


def record_completion(schedule, completion_date, details, odometer=None, asset_log=None):
	vehicle = lock_vehicle(schedule.vehicle)
	date = getdate(completion_date)
	current = reading(odometer)
	last = schedule.completions[-1] if schedule.completions else None
	if not schedule.enabled or not (details or "").strip() or date > getdate(today()):
		frappe.throw(_("Complete an active schedule with the date and work performed."))
	if last and date < getdate(last.completion_date):
		frappe.throw(_("The completion date is before the previous completion."))
	if schedule.interval_km and (current is None or current > (vehicle.last_odometer or 0)):
		frappe.throw(_("Enter a completion reading supported by the vehicle odometer."))
	minimum = reading(last.odometer if last else schedule.initial_odometer)
	if current is not None and minimum is not None and current < minimum:
		frappe.throw(_("The completion reading is below the previous maintenance baseline."))
	schedule.flags.recording_completion = True
	schedule.append("completions", {
		"completion_date": date, "odometer": str(current) if current is not None else None,
		"details": details, "completed_by": frappe.session.user, "asset_log": asset_log,
	})
	schedule.save()


def complete_asset_task(log, method=None):
	if log.maintenance_status != "Completed":
		return
	name = frappe.db.get_value("Vehicle Maintenance Schedule", {
		"asset_maintenance": log.asset_maintenance, "asset_task": log.task, "enabled": 1,
	})
	if name:
		schedule = frappe.get_doc("Vehicle Maintenance Schedule", name, for_update=True)
		vehicle = lock_vehicle(schedule.vehicle)
		record_completion(schedule, log.completion_date, _("ERPNext maintenance log {0}").format(log.name),
			vehicle.last_odometer, log.name)


def prevent_asset_completion_cancel(log, method=None):
	if frappe.db.exists("Vehicle Maintenance Completion", {"asset_log": log.name}):
		frappe.throw(_("Correct the linked fleet maintenance completion before cancelling this log."))
