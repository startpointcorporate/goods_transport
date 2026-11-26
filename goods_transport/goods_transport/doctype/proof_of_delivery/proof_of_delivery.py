import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class ProofofDelivery(Document):
	def validate(self):
		self.shipped_quantity = self._get_shipped_quantity()
		self._compute_short_quantity()

	def before_submit(self):
		if frappe.db.get_value("Proof of Delivery", {
			"bilty": self.bilty, "docstatus": 1, "name": ["!=", self.name],
		}, "name", for_update=True):
			frappe.throw(_("A submitted Proof of Delivery already exists for Bilty {0}.").format(self.bilty))

	def on_submit(self):
		# Advance Bilty state.
		bilty = frappe.get_doc("Bilty", self.bilty)
		updates = {"pod_status": "Received"}
		# Preserve Billed / Closed if already reached.
		if bilty.status not in ("Billed", "Closed", "Cancelled"):
			updates["status"] = "POD Received"
		frappe.db.set_value("Bilty", self.bilty, updates, update_modified=False)

		# Nudge the parent Order to recompute delivered qty.
		order = frappe.db.get_value("Bilty", self.bilty, "transport_order")
		if order:
			frappe.get_doc("Transport Order", order).refresh_progress()

	def before_cancel(self):
		bilty = frappe.get_doc("Bilty", self.bilty, for_update=True)
		if bilty.sales_invoice and frappe.db.get_value("Sales Invoice", bilty.sales_invoice, "docstatus") == 1:
			frappe.throw(_("Cancel the submitted Sales Invoice before cancelling this Proof of Delivery."))

	def on_cancel(self):
		bilty = frappe.get_doc("Bilty", self.bilty)
		new_pod_status = "Pending" if bilty.pod_required else "Not Required"
		# Reset Bilty status if it was moved to POD Received solely by this doc.
		updates = {"pod_status": new_pod_status}
		if bilty.status == "POD Received":
			updates["status"] = "Issued"
		frappe.db.set_value("Bilty", self.bilty, updates, update_modified=False)

		order = bilty.transport_order
		if order:
			frappe.get_doc("Transport Order", order).refresh_progress()

	# --- helpers ---------------------------------------------------------

	def _get_shipped_quantity(self):
		source = frappe.db.get_value(
			"Bilty", self.bilty, ["docstatus", "total_quantity", "transport_trip", "customer", "destination"],
			as_dict=True, for_update=True,
		)
		if source is None:
			frappe.throw(_("Bilty {0} does not exist.").format(self.bilty))
		if source.docstatus != 1:
			frappe.throw(_("Bilty {0} is not submitted.").format(self.bilty))

		self.trip = source.transport_trip
		self.customer = source.customer
		self.destination = source.destination
		return source.total_quantity

	def _compute_short_quantity(self):
		shipped = flt(self.shipped_quantity)
		delivered = flt(self.delivered_quantity)
		if delivered < 0 or delivered > shipped:
			frappe.throw(_("Delivered quantity must be between zero and the shipped quantity ({0}).").format(shipped))
		self.short_quantity = shipped - delivered
