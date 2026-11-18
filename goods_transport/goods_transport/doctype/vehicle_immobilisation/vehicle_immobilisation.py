import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

from goods_transport.goods_transport.services.fleet_odometer import lock_vehicle, reading


class VehicleImmobilisation(Document):
	def validate(self):
		vehicle = lock_vehicle(self.vehicle)
		before = self.get_doc_before_save()
		if self.company != vehicle.company:
			frappe.throw(_("The immobilisation and vehicle must belong to the same company."))
		if self.transport_trip and frappe.db.get_value("Transport Trip", self.transport_trip, "vehicle") != self.vehicle:
			frappe.throw(_("The trip must use the immobilised vehicle."))
		if self.asset_repair and frappe.db.get_value(
			"Asset Repair", self.asset_repair, "custom_vehicle_immobilisation",
		) != self.name:
			frappe.throw(_("Select an Asset Repair linked to this immobilisation."))
		reading(self.odometer)
		if self.is_new():
			if self.released_at or self.released_by:
				frappe.throw(_("Use the release operation to return this vehicle to service."))
			return
		if before.released_at:
			frappe.throw(_("Released immobilisations are retained as history."))
		if (get_datetime(self.start_at) != get_datetime(before.start_at)
			or any(self.get(field) != before.get(field) for field in ("vehicle", "company", "reason"))):
			frappe.throw(_("The vehicle, reason and start time cannot be changed after declaration."))
		if not self.flags.releasing and (self.released_at or self.released_by):
			frappe.throw(_("Use the release operation to return this vehicle to service."))


@frappe.whitelist(methods=["POST"])
def release_vehicle(name: str):
	if "System Manager" not in frappe.get_roles() and "Stock Manager" not in frappe.get_roles():
		frappe.throw(_("Only a fleet supervisor may release an immobilisation."), frappe.PermissionError)
	doc = frappe.get_doc("Vehicle Immobilisation", name, for_update=True)
	doc.check_permission("write")
	if doc.released_at:
		return doc.released_at
	if not (doc.resolution or "").strip():
		frappe.throw(_("Record the resolution before releasing the vehicle."))
	if doc.asset_repair:
		status = frappe.db.get_value("Asset Repair", doc.asset_repair, ["docstatus", "repair_status"])
		if status != (1, "Completed"):
			frappe.throw(_("Complete and submit the linked repair before releasing the vehicle."))
	now = now_datetime()
	if get_datetime(doc.start_at) > now:
		frappe.throw(_("The release time must follow the immobilisation start."))
	doc.flags.releasing = True
	doc.released_at = now
	doc.released_by = frappe.session.user
	doc.save()
	return doc.released_at
