import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from goods_transport.goods_transport.services.cargo import validate_cargo_item
from goods_transport.goods_transport.services.freight import CARGO_BASES, billable_quantity


class Bilty(Document):
	def validate(self):
		self._inherit_from_trip()
		self._inherit_from_order()
		self._default_billing_customer()
		self._default_currency()
		self._validate_cargo_items()
		self._compute_item_totals()
		self._compute_charges()
		self._compute_freight_amount()
		self._compute_grand_total()
		self._resolve_rate_contract()
		self._set_pod_status()
		self._set_status()

	def _validate_cargo_items(self):
		# Server-side enforcement for every cargo row. Freight and additional
		# service Items live elsewhere on this doc; they must not leak in here
		# via imports, APIs, or scripts.
		for row in self.items or []:
			validate_cargo_item(row.item, row_idx=row.idx)

	def before_submit(self):
		self._snapshot_vehicle_plate()
		if self.transport_order:
			order = frappe.get_doc("Transport Order", self.transport_order, for_update=True)
			if flt(self.total_quantity) > order.available_to_dispatch(self.name, for_update=True) + 1e-9:
				frappe.throw(_("Bilty cargo quantity exceeds the dispatchable quantity on order {0}.").format(order.name))

	def on_submit(self):
		if self.status == "Draft":
			self.db_set("status", "Issued")
		self._notify_parents()

	def on_update_after_submit(self):
		self._notify_parents()

	def on_cancel(self):
		if self.sales_invoice:
			frappe.throw(
				_("Cannot cancel Bilty {0}: it is linked to Sales Invoice {1}. Cancel the invoice first.").format(
					self.name, self.sales_invoice
				)
			)
		self.db_set("status", "Cancelled")
		self._notify_parents()

	def _notify_parents(self):
		if self.transport_trip:
			try:
				frappe.get_doc("Transport Trip", self.transport_trip).refresh_load()
			except Exception:
				frappe.log_error(frappe.get_traceback(), "Bilty parent Trip refresh failed")
		if self.transport_order:
			try:
				frappe.get_doc("Transport Order", self.transport_order).refresh_progress()
			except Exception:
				frappe.log_error(frappe.get_traceback(), "Bilty parent Order refresh failed")

	def _inherit_from_trip(self):
		if not self.transport_trip:
			return
		trip = frappe.db.get_value(
			"Transport Trip",
			self.transport_trip,
			["vehicle", "vehicle_license_plate", "driver", "transporter", "company", "origin", "destination", "freight_item"],
			as_dict=True,
		)
		if not trip:
			return
		if trip.company and self.company and trip.company != self.company:
			frappe.throw(
				_("Bilty company {0} does not match Trip company {1}.").format(self.company, trip.company)
			)
		for field in ("vehicle", "driver"):
			value = trip.get(field)
			if value and self.get(field) and value != self.get(field):
				frappe.throw(_("Bilty {0} must match the assigned trip.").format(_(self.meta.get_label(field))))
			self.set(field, self.get(field) or value)
		self.vehicle_license_plate = self.vehicle_license_plate or trip.vehicle_license_plate
		if not self.transport_order:
			self.origin = self.origin or trip.origin
			self.destination = self.destination or trip.destination
		self.company = self.company or trip.company
		self.transporter = self.transporter or trip.transporter
		# Freight service Item: Trip carries the default for its whole journey;
		# every Bilty billed off this Trip goes through the same SI line item
		# unless the user overrides on the Bilty itself.
		self.freight_item = self.freight_item or trip.freight_item

	def _inherit_from_order(self):
		if not self.transport_order:
			return
		order = frappe.db.get_value(
			"Transport Order",
			self.transport_order,
			[
				"customer", "company", "origin", "destination", "loading_location",
				"delivery_location", "pod_required", "commodity", "currency",
				"rate_basis", "rate", "docstatus",
			],
			as_dict=True,
		)
		if not order:
			return
		if order.company and self.company and order.company != self.company:
			frappe.throw(
				_("Bilty company {0} does not match Order company {1}.").format(self.company, order.company)
			)
		if order.docstatus != 1:
			frappe.throw(_("Select a submitted Transport Order."))
		for field in ("customer", "origin", "destination", "currency"):
			value = order.get(field)
			if self.get(field) and value and self.get(field) != value:
				frappe.throw(_("Bilty {0} must match the linked order.").format(_(self.meta.get_label(field))))
		if order.commodity and any(row.item != order.commodity for row in self.items or []):
			frappe.throw(_("Bilty cargo must match the commodity on the linked order."))
		if order.rate_basis and (self.rate_basis != order.rate_basis or flt(self.rate) != flt(order.rate)):
			frappe.throw(_("Bilty rate and basis must match the linked order."))
		self.company = self.company or order.company
		if not self.customer:
			self.customer = order.customer
		self.origin = self.origin or order.origin
		self.destination = self.destination or order.destination
		self.loading_location = self.loading_location or order.loading_location
		self.delivery_location = self.delivery_location or order.delivery_location
		if not self.currency and order.currency:
			self.currency = order.currency
		if order.pod_required and not self.pod_required:
			self.pod_required = 1

	# --- helpers ---------------------------------------------------------

	def _default_billing_customer(self):
		if not self.billing_customer:
			self.billing_customer = self.customer

	def _default_currency(self):
		if not self.currency and self.company:
			self.currency = frappe.get_cached_value("Company", self.company, "default_currency")

	def _compute_item_totals(self):
		self.total_quantity = sum(flt(r.quantity) for r in (self.items or []))
		self.total_packages = sum(int(r.packages or 0) for r in (self.items or []))
		self.total_gross_weight = sum(flt(r.gross_weight) for r in (self.items or []))
		self.total_net_weight = sum(flt(r.net_weight) for r in (self.items or []))

	def _compute_charges(self):
		total_billable = 0.0
		for row in self.charges or []:
			row.amount = flt(row.quantity) * flt(row.rate)
			if row.billable_to_customer:
				total_billable += row.amount
		self.additional_charges_total = total_billable

	def _compute_freight_amount(self):
		if self.bill_from_cargo and self.rate_basis in CARGO_BASES:
			self.freight_quantity = billable_quantity(
				self.rate_basis, weight_kg=self.total_gross_weight, packages=self.total_packages,
			)
		self.freight_amount = flt(self.rate) * flt(self.freight_quantity if self.freight_quantity is not None else 1)

	def _compute_grand_total(self):
		self.grand_total = flt(self.freight_amount) + flt(self.additional_charges_total)

	def _resolve_rate_contract(self):
		# Best-effort lookup; user is free to override rate manually.
		if self.rate_contract:
			return
		if not (self.customer and self.company and self.origin and self.destination and self.bilty_date):
			return
		try:
			from goods_transport.goods_transport.services.rates import find_matching_contract

			contract = find_matching_contract(
				customer=self.customer,
				company=self.company,
				origin=self.origin,
				destination=self.destination,
				commodity=(self.items[0].item if self.items else None),
				on_date=self.bilty_date,
			)
		except Exception:
			contract = None
		if contract:
			self.rate_contract = contract

	def _snapshot_vehicle_plate(self):
		if self.vehicle and not self.vehicle_license_plate:
			plate = frappe.db.get_value("Vehicle", self.vehicle, "license_plate")
			if plate:
				self.vehicle_license_plate = plate

	def _set_pod_status(self):
		if not self.pod_required:
			self.pod_status = "Not Required"
		elif self.pod_status in (None, "", "Not Required"):
			self.pod_status = "Pending"

	def _set_status(self):
		# Draft-time status only; post-submit transitions handled elsewhere.
		if self.docstatus == 0:
			self.status = "Draft"
		elif self.docstatus == 2:
			self.status = "Cancelled"
		# Post-submit intermediate states (Issued/In Transit/Delivered/POD Received/Billed/Closed)
		# are advanced by their respective actions (submit, POD, billing). Preserve current value.


@frappe.whitelist()
def get_unbilled_bilties(customer: str | None = None, company: str | None = None):
	"""Return submitted Bilties for the customer that are not yet linked to a Sales Invoice."""
	filters = {"docstatus": 1, "sales_invoice": ["is", "not set"]}
	if customer:
		filters["billing_customer"] = customer
	if company:
		filters["company"] = company
	return frappe.get_list(
		"Bilty",
		limit_page_length=0,
		filters=filters,
		fields=[
			"name",
			"bilty_date",
			"customer",
			"billing_customer",
			"origin",
			"destination",
			"grand_total",
			"currency",
			"status",
		],
		order_by="bilty_date asc, name asc",
	)
