import frappe
from frappe import _
from frappe.model.document import Document


class TripVehicleInspection(Document):
	def validate(self):
		if not self.flags.inspection_service:
			frappe.throw(_("Use the inspection actions on the Transport Trip."))

	def before_update_after_submit(self):
		frappe.throw(_("A validated inspection can only be corrected through a new revision."))

	def before_cancel(self):
		frappe.throw(_("Validated inspections are retained for audit."))

	def on_trash(self):
		frappe.throw(_("Inspection history cannot be deleted."))
