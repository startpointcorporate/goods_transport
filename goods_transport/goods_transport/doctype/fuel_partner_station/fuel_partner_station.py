import frappe
from frappe import _
from frappe.model.document import Document


class FuelPartnerStation(Document):
	def validate(self):
		if not (-90 <= self.latitude <= 90 and -180 <= self.longitude <= 180):
			frappe.throw(_("Coordonnées GPS invalides."))
		if not (self.diesel or self.essence):
			frappe.throw(_("Sélectionnez au moins un carburant."))
		if not self.is_new() and self.has_value_changed("company"):
			frappe.throw(_("La société de la station est fixe."))
