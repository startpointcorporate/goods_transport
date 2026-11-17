"""Goods Transport acceptance cases on a disposable ERPNext/HRMS site."""

from unittest import TestCase

import frappe
from frappe.utils import getdate, today

from goods_transport.goods_transport.doctype.bilty.bilty import get_unbilled_bilties
from goods_transport.goods_transport.doctype.transport_trip.transport_trip import advance_status
from goods_transport.goods_transport.doctype.trip_settlement.trip_settlement import create_settlement_for_trip
from goods_transport.goods_transport.report.trip_profitability.trip_profitability import execute
from goods_transport.goods_transport.services.billing import create_sales_invoice_from_bilties


def make(doctype, submit=False, **fields):
	doc = frappe.get_doc({"doctype": doctype, **fields}).insert()
	if submit:
		doc.submit()
	return doc


class TestTransportRecette(TestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(frappe.db.rollback)
		cls.addClassCleanup(frappe.set_user, frappe.session.user)
		frappe.set_user("Administrator")
		frappe.local.lang = "en"
		cls.addClassCleanup(setattr, frappe.flags, "mute_emails", frappe.flags.get("mute_emails"))
		frappe.flags.mute_emails = True
		token = frappe.generate_hash(length=4)
		cls.label = f"Transport Regression {token}"
		for doctype, field, name in (
			("Warehouse Type", "name", "Transit"),
			("Gender", "gender", "Male"),
			("UOM", "uom_name", "Kg"),
			("UOM", "uom_name", "Litre"),
			("Party Type", "party_type", "Customer"),
		):
			if not frappe.db.exists(doctype, name):
				extra = {"account_type": "Receivable"} if doctype == "Party Type" else {}
				make(doctype, **{field: name}, **extra)

		cls.company = make(
			"Company", company_name=cls.label, abbr=token.upper(), country="France",
			default_currency="EUR", chart_of_accounts="Standard",
			create_chart_of_accounts_based_on="Standard Template",
		)
		year = getdate(today()).year
		if not frappe.db.exists("Fiscal Year", {
			"year_start_date": ["<=", today()], "year_end_date": [">=", today()], "disabled": 0,
		}):
			make("Fiscal Year", year=cls.label, year_start_date=f"{year}-01-01",
				year_end_date=f"{year}-12-31")
		group = make("Customer Group", customer_group_name=f"{cls.label} Customers")
		territory = make("Territory", territory_name=f"{cls.label} Territory")
		price_list = make("Price List", price_list_name=cls.label, currency="EUR", selling=1, enabled=1)
		cls.customer = make(
			"Customer", customer_name=cls.label, customer_type="Company", customer_group=group.name,
			territory=territory.name, default_currency="EUR", default_price_list=price_list.name,
		)
		frappe.db.set_single_value("Selling Settings", "selling_price_list", price_list.name)
		employee = make("Employee", first_name=cls.label, gender="Male", date_of_birth="1990-01-01",
			date_of_joining=today(), company=cls.company.name, status="Active")
		cls.driver = make("Driver", full_name=cls.label, employee=employee.name, status="Active",
			license_number=token)
		cls.vehicle = make(
			"Vehicle", license_plate=cls.label, make="Test", model="Test", last_odometer=0,
			fuel_type="Diesel", uom="Litre", company=cls.company.name, ownership_type="Company Owned",
			payload_capacity=10000, default_driver=cls.driver.name,
		)
		cls.origin, cls.destination = (
			make("Transport Location", location_name=f"{cls.label} {end}", location_type="Terminal",
				is_active=1, country="France").name
			for end in ("Origin", "Destination")
		)
		item_group = make("Item Group", item_group_name=f"{cls.label} Services")
		cls.freight = make("Item", item_code=cls.label, item_group=item_group.name, stock_uom="Kg",
			is_stock_item=0, is_sales_item=1)

	def route(self, quantity=1000, order=None, order_quantity=1000):
		common = dict(company=self.company.name, origin=self.origin, destination=self.destination, currency="EUR")
		order = order or make(
			"Transport Order", True, **common, customer=self.customer.name,
			quantity=order_quantity, uom="Kg", rate_basis="Per Kg", rate=1, pod_required=1,
		)
		trip = make("Transport Trip", True, **common, vehicle=self.vehicle.name,
			driver=self.driver.name, freight_item=self.freight.name)
		bilty = make(
			"Bilty", True, **common, customer=self.customer.name, transport_order=order.name,
			transport_trip=trip.name, freight_item=self.freight.name, rate_basis="Per Kg",
			rate=1, freight_quantity=quantity, items=[
				dict(description="Fictitious cargo", quantity=quantity, uom="Kg", gross_weight=quantity),
			],
		)
		return order, trip, bilty

	def pod(self, bilty, quantity):
		return make("Proof of Delivery", True, bilty=bilty.name, delivered_quantity=quantity,
			receiver_name="Fictitious receiver")

	def deliver(self, trip, bilty, quantity=1000):
		for status in ("At Loading Point", "Loaded", "In Transit", "Arrived", "Unloading"):
			advance_status(trip.name, status)
		pod = self.pod(bilty, quantity)
		advance_status(trip.name, "Delivered")
		return pod

	def invoice(self, *bilties):
		name = create_sales_invoice_from_bilties([bilty.name for bilty in bilties])
		return frappe.get_doc("Sales Invoice", name).submit()

	def test_gt01_required_pod_missing(self):
		_, trip, bilty = self.route()
		with self.assertRaises(frappe.ValidationError):
			create_sales_invoice_from_bilties([bilty.name])
		self.assertFalse(bilty.reload().sales_invoice)
		self.assertEqual(trip.reload().status, "Vehicle Assigned")

	def test_gt02_consolidated_invoice(self):
		self.check_consolidated_invoice(shared_order=False)

	def test_gt02_consolidated_invoice_for_one_order(self):
		self.check_consolidated_invoice(shared_order=True)

	def check_consolidated_invoice(self, shared_order):
		order, first_trip, first_bilty = self.route(order_quantity=2000 if shared_order else 1000)
		_, second_trip, second_bilty = self.route(order=order if shared_order else None)
		self.deliver(first_trip, first_bilty)
		self.deliver(second_trip, second_bilty)
		invoice = self.invoice(first_bilty, second_bilty)
		self.assertFalse(invoice.transport_trip)
		self.assertEqual(invoice.grand_total, 2000)
		self.assertEqual({item.transport_trip: item.net_amount for item in invoice.items},
			{first_trip.name: 1000, second_trip.name: 1000})
		for trip in (first_trip, second_trip):
			settlement = frappe.get_doc("Trip Settlement", create_settlement_for_trip(trip.name))
			settlement.refresh_from_source()
			self.assertEqual(settlement.total_revenue, 1000)
			self.assertEqual(settlement.pending_revenue, 0)
			self.assertEqual(settlement.invoice_count, 1)
			_, rows = execute({"trip": trip.name})
			self.assertEqual(rows[0].revenue, settlement.total_revenue)

	def test_gt03_partial_and_remainder(self):
		order, trip, bilty = self.route()
		pod = self.pod(bilty, 900)
		self.assertEqual(pod.short_quantity, 100)
		order.reload()
		self.assertEqual((order.dispatched_quantity, order.delivered_quantity, order.remaining_quantity),
			(1000, 900, 100))
		self.assertEqual(order.status, "Fully Dispatched")
		with self.assertRaises(frappe.ValidationError):
			create_sales_invoice_from_bilties([bilty.name])
		with self.assertRaises(frappe.ValidationError):
			advance_status(trip.name, "Delivered")
		_, retry_trip, retry_bilty = self.route(quantity=100, order=order)
		self.deliver(retry_trip, retry_bilty, 100)
		order.reload()
		self.assertEqual((order.delivered_quantity, order.remaining_quantity, order.status),
			(1000, 0, "Delivered"))

	def test_gt03_surplus_is_invalid(self):
		_, _, bilty = self.route()
		with self.assertRaises(frappe.ValidationError):
			self.pod(bilty, 1200)
		self.assertFalse(frappe.db.exists("Proof of Delivery", {"bilty": bilty.name}))

	def test_gt04_cannot_close_or_settle_early(self):
		_, trip, _ = self.route()
		with self.assertRaises(frappe.ValidationError):
			advance_status(trip.name, "Closed")
		with self.assertRaises(frappe.ValidationError):
			advance_status(trip.name, "Settled")
		settlement = frappe.get_doc("Trip Settlement", create_settlement_for_trip(trip.name))
		with self.assertRaises(frappe.ValidationError):
			settlement.submit()
		self.assertEqual(trip.reload().status, "Vehicle Assigned")

	def test_gt05_restricted_user(self):
		_, trip, _ = self.route()
		user = make("User", email=f"gt-{frappe.generate_hash(length=8)}@example.invalid",
			first_name="Transport Regression Employee", send_welcome_email=0, roles=[{"role": "Employee"}])
		frappe.set_user(user.name)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_unbilled_bilties(self.customer.name, self.company.name)
			for status in ("At Loading Point", "Closed"):
				with self.assertRaises(frappe.PermissionError):
					advance_status(trip.name, status)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(trip.reload().status, "Vehicle Assigned")

	def test_nominal_delivery_invoice_payment_and_closure(self):
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		order, trip, bilty = self.route()
		pod = self.deliver(trip, bilty)
		self.assertEqual(order.reload().delivered_quantity, 1000)
		self.assertEqual(order.status, "Delivered")
		invoice = self.invoice(bilty)
		self.assertEqual(invoice.grand_total, 1000)
		self.assertEqual(invoice.transport_trip, trip.name)
		with self.assertRaises(frappe.ValidationError):
			pod.cancel()
		payment = get_payment_entry("Sales Invoice", invoice.name, bank_account=self.company.default_cash_account)
		payment.reference_no = "FICTITIOUS-GT-REGRESSION"
		payment.reference_date = today()
		payment.insert().submit()
		self.assertEqual(invoice.reload().outstanding_amount, 0)
		for voucher in (invoice, payment):
			entries = frappe.get_all("GL Entry", filters={"voucher_no": voucher.name, "is_cancelled": 0},
				fields=["debit", "credit"])
			self.assertTrue(entries)
			self.assertAlmostEqual(sum(row.debit - row.credit for row in entries), 0)
		frappe.get_doc("Trip Settlement", create_settlement_for_trip(trip.name)).submit()
		self.assertEqual(advance_status(trip.name, "Closed"), "Closed")
