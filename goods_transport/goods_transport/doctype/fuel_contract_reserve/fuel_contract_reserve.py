import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class FuelContractReserve(Document):
	def validate(self):
		station = frappe.get_doc("Fuel Partner Station", self.station)
		station.check_permission("read")
		if station.company != self.company or not station.get(self.fuel_type.lower()):
			frappe.throw(_("La station doit appartenir à la société et distribuer ce carburant."))
		if self.valid_until and getdate(self.valid_until) < getdate(self.valid_from):
			frappe.throw(_("La fin du contrat doit suivre son début."))
		if not self.is_new():
			frappe.throw(_("Les conditions et les soldes de la réserve sont verrouillés."))
		for field in ("remaining_liters", "reserved_liters", "available_liters", "consumed_liters"):
			self.set(field, 0)
