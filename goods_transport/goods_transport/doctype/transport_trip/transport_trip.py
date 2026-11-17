import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


TRIP_STATUS_ORDER = [
	"Planned",
	"Vehicle Assigned",
	"At Loading Point",
	"Loaded",
	"In Transit",
	"Arrived",
	"Unloading",
	"Delivered",
	"Settled",
	"Closed",
]


class TransportTrip(Document):
	def validate(self):
		self._default_currency()
		self._compute_estimated_cost()
		self._compute_load_from_bilties()
		self._validate_capacity()
		self._set_status_draft_time()

	def before_submit(self):
		if not self.vehicle_license_plate and self.vehicle:
			plate = frappe.db.get_value("Vehicle", self.vehicle, "license_plate")
			if plate:
				self.vehicle_license_plate = plate

	def on_submit(self):
		self.db_set("status", "Vehicle Assigned")

	def on_cancel(self):
		bilty_count = frappe.db.count("Bilty", {"transport_trip": self.name, "docstatus": ["!=", 2]})
		if bilty_count:
			frappe.throw(
				_("Cannot cancel Transport Trip {0}: {1} active Bilty record(s) reference it. Cancel them first.").format(
					self.name, bilty_count
				)
			)
		self.db_set("status", "Cancelled")

	# --- helpers ---------------------------------------------------------

	def _default_currency(self):
		if not self.currency and self.company:
			self.currency = frappe.get_cached_value("Company", self.company, "default_currency")

	def _compute_estimated_cost(self):
		self.estimated_cost = flt(self.agreed_vehicle_hire) + flt(self.driver_allowance)

	def _compute_load_from_bilties(self):
		if not self.name:
			return
		rows = frappe.db.sql(
			"""
			SELECT COALESCE(SUM(total_gross_weight), 0) AS wt, COUNT(*) AS n
			FROM `tabBilty`
			WHERE transport_trip = %s AND docstatus < 2
			""",
			(self.name,),
			as_dict=1,
		)
		wt = flt(rows[0].wt) if rows else 0
		n = int(rows[0].n) if rows else 0
		self.loaded_weight = wt
		self.bilty_count = n
		if self.vehicle_capacity:
			self.capacity_utilization = min(wt / flt(self.vehicle_capacity) * 100, 999.99)
		else:
			self.capacity_utilization = 0

	def _validate_capacity(self):
		if not (self.vehicle_capacity and self.loaded_weight):
			return
		if flt(self.loaded_weight) > flt(self.vehicle_capacity) * 1.001:  # 0.1% tolerance
			frappe.msgprint(
				_("Loaded weight {0} kg exceeds vehicle capacity {1} kg.").format(
					self.loaded_weight, self.vehicle_capacity
				),
				alert=True,
				indicator="orange",
			)

	def _set_status_draft_time(self):
		if self.docstatus == 0 and (self.status or "") in ("", "Draft"):
			self.status = "Planned"
		elif self.docstatus == 2:
			self.status = "Cancelled"

	def validate_delivery(self):
		from goods_transport.goods_transport.services.billing import validate_bilty_delivery

		bilties = frappe.get_all("Bilty", filters={"transport_trip": self.name, "docstatus": ["<", 2]},
			fields=["name", "docstatus", "pod_required", "total_quantity", "sales_invoice"])
		for bilty in bilties:
			if bilty.docstatus != 1:
				frappe.throw(_("Submit Bilty {0} before marking the Trip delivered.").format(bilty.name))
			validate_bilty_delivery(bilty, trip_delivered=True)
		return bilties

	def refresh_orders(self):
		orders = frappe.get_all("Bilty", filters={"transport_trip": self.name, "docstatus": 1},
			pluck="transport_order", distinct=True)
		for order in filter(None, orders):
			frappe.get_doc("Transport Order", order).refresh_progress()

	def validate_closure(self):
		if self.status != "Settled" or not frappe.db.exists("Trip Settlement", {
			"name": self.trip_settlement, "trip": self.name, "docstatus": 1,
		}):
			frappe.throw(_("Submit the Trip Settlement before closing the Trip."))
		for bilty in self.validate_delivery():
			if not bilty.sales_invoice or frappe.db.get_value("Sales Invoice", bilty.sales_invoice, "docstatus") != 1:
				frappe.throw(_("Submit the Sales Invoice for Bilty {0} before closing the Trip.").format(bilty.name))

	# --- called by Bilty controller --------------------------------------

	def refresh_load(self):
		self._compute_load_from_bilties()
		frappe.db.set_value(
			"Transport Trip",
			self.name,
			{
				"loaded_weight": self.loaded_weight,
				"bilty_count": self.bilty_count,
				"capacity_utilization": self.capacity_utilization,
			},
			update_modified=False,
		)


@frappe.whitelist(methods=["POST"])
def advance_status(trip: str, to_status: str) -> str:
	"""Advance a submitted Trip through the operational milestones."""
	doc = frappe.get_doc("Transport Trip", trip, for_update=True)
	doc.check_permission("write")
	if doc.docstatus != 1:
		frappe.throw(_("Trip must be submitted before advancing status."))
	if to_status not in TRIP_STATUS_ORDER:
		frappe.throw(_("Unknown status {0}.").format(to_status))
	current_idx = TRIP_STATUS_ORDER.index(doc.status) if doc.status in TRIP_STATUS_ORDER else -1
	target_idx = TRIP_STATUS_ORDER.index(to_status)
	if target_idx <= current_idx:
		frappe.throw(_("Cannot move Trip status from {0} back to {1}.").format(doc.status, to_status))
	if to_status == "Settled":
		frappe.throw(_("Submit a Trip Settlement to settle the Trip."))
	if to_status == "Closed":
		doc.validate_closure()
	if to_status == "Delivered":
		doc.validate_delivery()
	doc.db_set("status", to_status)
	if to_status == "Delivered":
		doc.refresh_orders()
	return to_status
