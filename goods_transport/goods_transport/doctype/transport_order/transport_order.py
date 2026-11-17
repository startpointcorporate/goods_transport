import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from goods_transport.goods_transport.services.cargo import validate_cargo_item


class TransportOrder(Document):
	def validate(self):
		self._default_currency()
		self._validate_commodity_is_cargo()
		self._compute_estimated_totals()
		self._set_status_draft_time()

	def _validate_commodity_is_cargo(self):
		# Server-side gate: covers imports, APIs, background jobs — not just the
		# form. Client-side get_query is a UX hint; this is the enforcement.
		validate_cargo_item(self.commodity)

	def on_submit(self):
		if not self.status or self.status == "Draft":
			self.db_set("status", "Confirmed")

	def on_cancel(self):
		bilty_count = frappe.db.count("Bilty", {"transport_order": self.name, "docstatus": ["!=", 2]})
		if bilty_count:
			frappe.throw(
				_("Cannot cancel Transport Order {0}: {1} active Bilty record(s) reference it. Cancel them first.").format(
					self.name, bilty_count
				)
			)
		self.db_set("status", "Cancelled")

	# --- helpers ---------------------------------------------------------

	def _default_currency(self):
		if not self.currency and self.company:
			self.currency = frappe.get_cached_value("Company", self.company, "default_currency")

	def _compute_estimated_totals(self):
		self.estimated_freight = flt(self.rate) * flt(self.quantity)
		self.grand_total = flt(self.estimated_freight) + flt(self.additional_charges)

	def _set_status_draft_time(self):
		if self.docstatus == 0:
			self.status = "Draft"
		elif self.docstatus == 2:
			self.status = "Cancelled"

	# --- called by Bilty controller and POD controller -------------------

	def refresh_progress(self):
		"""Recompute dispatched/delivered/remaining/billed from linked Bilties."""
		rows = frappe.db.sql(
			"""
			SELECT b.total_quantity, b.grand_total, b.pod_required, b.sales_invoice,
			       b.status, p.delivered_quantity, t.status AS trip_status
			FROM `tabBilty` b
			LEFT JOIN `tabProof of Delivery` p ON p.bilty = b.name AND p.docstatus = 1
			LEFT JOIN `tabTransport Trip` t ON t.name = b.transport_trip AND t.docstatus = 1
			WHERE b.transport_order = %s AND b.docstatus = 1
			""",
			(self.name,),
			as_dict=1,
		)
		dispatched = sum(flt(r.total_quantity) for r in rows)
		delivered = sum(
			min(max(flt(r.delivered_quantity), 0), flt(r.total_quantity))
			if r.delivered_quantity is not None
			else flt(r.total_quantity)
			for r in rows
			if r.delivered_quantity is not None
			or (
				not r.pod_required
				and (r.status == "Delivered" or r.trip_status in ("Delivered", "Settled", "Closed"))
			)
		)
		billed = sum(flt(r.grand_total) for r in rows if r.sales_invoice)
		remaining = max(flt(self.quantity) - delivered, 0)

		new_status = self.status
		if self.docstatus == 1:
			if dispatched <= 0:
				new_status = "Confirmed"
			elif delivered >= flt(self.quantity) - 1e-9:
				new_status = "Delivered"
			elif dispatched < flt(self.quantity):
				new_status = "Partially Dispatched"
			else:
				new_status = "Fully Dispatched"

		frappe.db.set_value(
			"Transport Order",
			self.name,
			{
				"dispatched_quantity": dispatched,
				"delivered_quantity": delivered,
				"remaining_quantity": remaining,
				"billed_amount": billed,
				"status": new_status,
			},
			update_modified=False,
		)
