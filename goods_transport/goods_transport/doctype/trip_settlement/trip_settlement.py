import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class TripSettlement(Document):
	def validate(self):
		self._validate_unique_open_settlement()
		self._refresh_from_source()
		self._compute_final()

	def before_submit(self):
		trip = frappe.get_doc("Transport Trip", self.trip, for_update=True)
		trip.check_permission("read")
		if trip.docstatus != 1 or trip.status != "Delivered":
			frappe.throw(_("Trip {0} must be delivered before settlement.").format(self.trip))
		trip.validate_delivery()

	def on_submit(self):
		frappe.db.set_value(
			"Transport Trip",
			self.trip,
			{"status": "Settled", "trip_settlement": self.name},
			update_modified=False,
		)

	def on_cancel(self):
		frappe.db.set_value(
			"Transport Trip",
			self.trip,
			{"status": "Delivered", "trip_settlement": None},
			update_modified=False,
		)

	# --- computation -----------------------------------------------------

	def _validate_unique_open_settlement(self):
		other = frappe.db.get_value(
			"Trip Settlement",
			{"trip": self.trip, "docstatus": ["!=", 2], "name": ["!=", self.name or "__new__"]},
			"name",
		)
		if other:
			frappe.throw(_("Trip Settlement {0} already exists for Trip {1}.").format(other, self.trip))

	@frappe.whitelist(methods=["POST"])
	def refresh_from_source(self):
		self.check_permission("create" if self.is_new() else "write")
		self._refresh_from_source()

	def _refresh_from_source(self):
		"""Recompute all figures from the underlying Bilty / Sales Invoice /
		Trip Expense / Trip Advance records. Called from validate() and via
		the client-side Refresh button."""
		trip = frappe.get_doc("Transport Trip", self.trip)

		trip.check_permission("read")
		# Match Trip Profitability: posted income in company currency, including
		# credit notes and excluding cancelled ledger rows. Convert for this form.
		revenue = frappe.db.sql(
			"""
			SELECT SUM(gle.credit - gle.debit) AS total, si.currency, si.conversion_rate, si.posting_date
			FROM `tabGL Entry` gle
			JOIN `tabAccount` acc ON acc.name = gle.account
			JOIN `tabSales Invoice` si ON si.name = gle.voucher_no AND si.docstatus = 1
			WHERE gle.transport_trip = %s AND gle.is_cancelled = 0
			  AND gle.voucher_type = 'Sales Invoice' AND acc.root_type = 'Income'
			GROUP BY si.name, si.currency, si.conversion_rate, si.posting_date
			""",
			(self.trip,),
			as_dict=True,
		)
		company_currency = frappe.get_cached_value("Company", trip.company, "default_currency")
		self.total_revenue = sum(self._revenue_in_trip_currency(row, company_currency, trip.currency) for row in revenue)
		self.invoice_count = len(revenue)

		bilties = frappe.get_all(
			"Bilty",
			filters={"transport_trip": self.trip, "docstatus": 1},
			fields=["name", "grand_total", "sales_invoice"],
		)
		self.bilty_count = len(bilties)
		self.pending_revenue = sum(flt(b.grand_total) for b in bilties if not b.sales_invoice)

		# Cost — planned from Trip + actuals from Trip Expense
		self.vehicle_hire = flt(trip.agreed_vehicle_hire)
		self.driver_allowance = flt(trip.driver_allowance)
		expense_total = (
			frappe.db.sql(
				"SELECT COALESCE(SUM(amount), 0) FROM `tabTrip Expense` WHERE trip=%s AND docstatus=1",
				(self.trip,),
			)[0][0]
			or 0
		)
		self.total_expenses = flt(expense_total)

		# Advances
		self.total_advances = (
			frappe.db.sql(
				"SELECT COALESCE(SUM(amount), 0) FROM `tabTrip Advance` WHERE trip=%s AND docstatus=1",
				(self.trip,),
			)[0][0]
			or 0
		)
		self.consumed_from_advance = (
			frappe.db.sql(
				"""SELECT COALESCE(SUM(te.amount), 0)
				FROM `tabTrip Expense` te
				WHERE te.trip=%s AND te.docstatus=1 AND te.payment_mode='Trip Advance'""",
				(self.trip,),
			)[0][0]
			or 0
		)

	@staticmethod
	def _revenue_in_trip_currency(row, company_currency, trip_currency):
		if trip_currency == company_currency:
			return flt(row.total)
		if trip_currency == row.currency:
			return flt(row.total) / (flt(row.conversion_rate) or 1)

		from erpnext.setup.utils import get_exchange_rate

		rate = get_exchange_rate(company_currency, trip_currency, row.posting_date)
		if not rate:
			frappe.throw(_("An exchange rate is required to calculate Trip Settlement revenue."))
		return flt(row.total) * rate

	def _compute_final(self):
		# Cost model — planned Driver Allowance is intentionally NOT part of
		# total_cost. Actual driver allowance is recorded as a submitted Trip
		# Expense with expense_type='Driver Allowance' and rolls up through
		# `total_expenses`. driver_allowance on the header is a planning /
		# budgeting reference and is shown separately in the settlement print
		# for comparison; it must not be added here or the actual + planned
		# allowance would be double-counted.
		self.total_cost = flt(self.vehicle_hire) + flt(self.total_expenses)
		self.gross_profit = flt(self.total_revenue) - flt(self.total_cost)
		self.margin_percent = (self.gross_profit / self.total_revenue * 100) if self.total_revenue else 0
		self.advance_balance = flt(self.total_advances) - flt(self.consumed_from_advance)
		self.outstanding_from_driver = max(flt(self.advance_balance) - flt(self.cash_returned), 0)


@frappe.whitelist(methods=["POST"])
def create_settlement_for_trip(trip: str) -> str:
	"""Create a draft Trip Settlement prefilled from the given Trip."""
	frappe.get_doc("Transport Trip", trip).check_permission("read")
	if frappe.db.exists("Trip Settlement", {"trip": trip, "docstatus": ["!=", 2]}):
		frappe.throw(_("An open Trip Settlement already exists for Trip {0}.").format(trip))
	ts = frappe.new_doc("Trip Settlement")
	ts.trip = trip
	ts.insert()
	return ts.name
