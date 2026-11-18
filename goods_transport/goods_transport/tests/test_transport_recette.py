"""Goods Transport acceptance cases on a disposable ERPNext/HRMS site."""

from unittest import TestCase

import frappe
from frappe.utils import getdate, now_datetime, today

from goods_transport.goods_transport.doctype.bilty.bilty import get_unbilled_bilties
from goods_transport.goods_transport.doctype.transport_trip.transport_trip import advance_status
from goods_transport.goods_transport.doctype.vehicle_immobilisation.vehicle_immobilisation import release_vehicle
from goods_transport.goods_transport.doctype.vehicle_maintenance_schedule.vehicle_maintenance_schedule import (
	complete_schedule,
	due_state,
	refresh_vehicle_alerts,
)
from goods_transport.goods_transport.doctype.trip_settlement.trip_settlement import create_settlement_for_trip
from goods_transport.goods_transport.report.fleet_maintenance.fleet_maintenance import execute as fleet_report
from goods_transport.goods_transport.report.trip_profitability.trip_profitability import execute
from goods_transport.goods_transport.services.billing import create_sales_invoice_from_bilties
from goods_transport.goods_transport.services.fleet_costs import vehicle_costs


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

	def setUp(self):
		frappe.db.savepoint("transport_acceptance_case")
		self.addCleanup(frappe.db.rollback, save_point="transport_acceptance_case")

	def route(self, quantity=1000, order=None, order_quantity=1000, vehicle=None):
		common = dict(company=self.company.name, origin=self.origin, destination=self.destination, currency="EUR")
		order = order or make(
			"Transport Order", True, **common, customer=self.customer.name,
			quantity=order_quantity, uom="Kg", rate_basis="Per Kg", rate=1, pod_required=1,
		)
		trip = make("Transport Trip", True, **common, vehicle=vehicle or self.vehicle.name,
			driver=self.driver.name, freight_item=self.freight.name)
		bilty = make(
			"Bilty", True, **common, customer=self.customer.name, transport_order=order.name,
			transport_trip=trip.name, freight_item=self.freight.name, rate_basis="Per Kg",
			rate=1, freight_quantity=quantity, items=[
				dict(description="Fictitious cargo", quantity=quantity, uom="Kg", gross_weight=quantity),
			],
		)
		return order, trip, bilty

	def second_vehicle(self):
		vehicle = frappe.copy_doc(self.vehicle)
		vehicle.license_plate = f"{self.label} B"
		return vehicle.insert().name

	def test_fleet_a_preventive_maintenance_without_asset(self):
		frappe.db.set_value("Vehicle", self.vehicle.name, "last_odometer", 85000)
		schedule = make("Vehicle Maintenance Schedule", company=self.company.name,
			vehicle=self.vehicle.name, operation="Oil change", responsible="Administrator",
			initial_odometer="80000", interval_km=10000, advance_km=5000, blocking=1)
		self.assertEqual(schedule.due_odometer, "90000")
		self.assertEqual(due_state(schedule, 85000), "Upcoming")
		self.assertEqual(due_state(schedule, 90000), "Due")
		self.assertEqual(due_state(schedule, 90001), "Overdue")
		refresh_vehicle_alerts(self.vehicle.name, 85000)
		self.assertEqual(frappe.db.count("ToDo", {"reference_type": schedule.doctype,
			"reference_name": schedule.name, "status": "Open"}), 1)
		frappe.db.set_value("Vehicle", self.vehicle.name, "last_odometer", 90000)
		with self.assertRaises(frappe.ValidationError):
			complete_schedule(schedule.name, today(), "Oil and filter replaced", "90001")
		complete_schedule(schedule.name, today(), "Oil and filter replaced", "90000")
		schedule.reload()
		self.assertEqual(schedule.due_odometer, "100000")
		self.assertEqual(len(schedule.completions), 1)

	def test_fleet_native_asset_lifecycle(self):
		company = self.company.name
		category = make("Asset Category", asset_category_name=f"{self.label} Trucks", accounts=[{
			"company_name": company,
			"fixed_asset_account": frappe.db.get_value("Account", {
				"company": company, "account_type": "Fixed Asset", "is_group": 0,
			}, "name"),
		}])
		item = make("Item", item_code=f"{self.label} Truck Asset", item_group=self.freight.item_group,
			stock_uom="Kg", is_stock_item=0, is_fixed_asset=1, asset_category=category.name)
		location = make("Location", location_name=f"{self.label} Garage")
		asset = make("Asset", True, item_code=item.name, asset_name=self.label, location=location.name,
			company=company, purchase_date=today(), available_for_use_date=today(),
			asset_type="Existing Asset", net_purchase_amount=200000, maintenance_required=1)
		vehicle = frappe.get_doc("Vehicle", self.vehicle.name)
		vehicle.custom_maintenance_asset = asset.name
		vehicle.save()
		frappe.db.set_value("Vehicle", vehicle.name, "last_odometer", 90000)
		team = make("Asset Maintenance Team", maintenance_team_name=f"{self.label} Mechanics", company=company,
			maintenance_team_members=[{"team_member": "Administrator", "maintenance_role": "System Manager"}])
		native = make("Asset Maintenance", asset_name=asset.name, company=company, maintenance_team=team.name,
			asset_maintenance_tasks=[{"maintenance_task": "Oil change", "assign_to": "Administrator",
				"maintenance_type": "Preventive Maintenance", "maintenance_status": "Planned",
				"start_date": today(), "periodicity": "Monthly"}])
		task = native.asset_maintenance_tasks[0].name
		schedule = make("Vehicle Maintenance Schedule", company=company, vehicle=vehicle.name,
			operation="Oil change", responsible="Administrator", asset_maintenance=native.name, asset_task=task,
			initial_odometer="80000", interval_km=10000)
		log = frappe.get_doc("Asset Maintenance Log", {"asset_maintenance": native.name, "task": task})
		log.maintenance_status, log.completion_date = "Completed", today()
		log.submit()
		self.assertEqual(schedule.reload().due_odometer, "100000")
		self.assertEqual(schedule.completions[0].asset_log, log.name)

		incident = make("Vehicle Immobilisation", company=company, vehicle=vehicle.name,
			reason="Breakdown", description="Fictitious fault")
		repair = make("Asset Repair", company=company, asset=asset.name, failure_date=now_datetime(),
			custom_vehicle_immobilisation=incident.name, repair_status="Pending")
		incident.asset_repair, incident.resolution = repair.name, "Fictitious repair completed"
		incident.save()
		with self.assertRaises(frappe.ValidationError):
			release_vehicle(incident.name)
		repair.completion_date, repair.repair_status = now_datetime(), "Completed"
		repair.submit()
		self.assertTrue(release_vehicle(incident.name))

	def test_fleet_b_actual_odometer_without_asset(self):
		frappe.db.set_value("Vehicle", self.vehicle.name, "last_odometer", 85000)
		_, trip, _ = self.route()
		trip.departure_odometer = "85000"
		trip.arrival_odometer = "84999"
		with self.assertRaises(frappe.ValidationError):
			trip.save()
		trip.reload()
		trip.departure_odometer = "85000"
		trip.arrival_odometer = "85600"
		trip.save()
		advance_status(trip.name, "Arrived")
		trip.reload()
		self.assertEqual(trip.actual_distance, 600)
		self.assertEqual(trip.odometer_recorded_by, "Administrator")
		self.assertEqual(frappe.db.get_value("Vehicle Log", trip.odometer_vehicle_log, "odometer"), 85600)
		self.assertEqual(frappe.db.get_value("Vehicle", trip.vehicle, "last_odometer"), 85600)
		trip.arrival_odometer = "86000"
		with self.assertRaises(frappe.ValidationError):
			trip.save()

	def test_fleet_c_server_rejects_immobilised_vehicle_until_release(self):
		incident = make("Vehicle Immobilisation", company=self.company.name, vehicle=self.vehicle.name,
			reason="Breakdown", description="Fictitious brake fault")
		trip = make("Transport Trip", company=self.company.name, origin=self.origin,
			destination=self.destination, vehicle=self.vehicle.name, freight_item=self.freight.name,
			driver=self.driver.name)
		with self.assertRaises(frappe.ValidationError):
			trip.submit()
		with self.assertRaises(frappe.ValidationError):
			release_vehicle(incident.name)
		incident.resolution = "Fictitious brake inspection completed"
		incident.save()
		release_vehicle(incident.name)
		trip.reload().submit()
		self.assertEqual(trip.status, "Vehicle Assigned")

	def test_fleet_c_reservations_reject_overlap(self):
		common = dict(company=self.company.name, vehicle=self.vehicle.name,
			origin=self.origin, destination=self.destination, freight_item=self.freight.name,
			driver=self.driver.name, planned_departure_at=f"{today()} 08:00:00",
			planned_return_at=f"{today()} 10:00:00")
		first = make("Transport Trip", True, **common)
		overlap = make("Transport Trip", **dict(common, planned_departure_at=f"{today()} 09:00:00"))
		with self.assertRaises(frappe.ValidationError):
			overlap.submit()
		next_trip = make("Transport Trip", True, **dict(common,
			planned_departure_at=f"{today()} 10:00:00", planned_return_at=f"{today()} 12:00:00"))
		advance_status(first.name, "In Transit")
		with self.assertRaises(frappe.ValidationError):
			advance_status(next_trip.name, "In Transit")

	def repair_vouchers(self, submit=False):
		company = self.company.name
		vehicle = self.vehicle.name
		incident = make("Vehicle Immobilisation", company=company, vehicle=vehicle,
			reason="Breakdown", description="Fictitious repair requiring parts")
		item = make("Item", item_code=f"{self.label} Brake Parts", item_group=self.freight.item_group,
			stock_uom="Kg", is_stock_item=1)
		warehouse = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")
		center = frappe.db.get_value("Company", company, "cost_center")
		expense = frappe.db.get_value("Company", company, "stock_adjustment_account")
		line = dict(item_code=item.name, qty=2, basic_rate=30000, cost_center=center, expense_account=expense)
		make("Stock Entry", True, company=company, stock_entry_type="Material Receipt",
			items=[dict(line, t_warehouse=warehouse)])
		issue = make("Stock Entry", submit, company=company, stock_entry_type="Material Issue",
			custom_vehicle_immobilisation=incident.name, items=[dict(line, s_warehouse=warehouse)])

		group = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
		supplier = make("Supplier", supplier_name=f"{self.label} Garage", supplier_group=group)
		service = make("Item", item_code=f"{self.label} Repair Service", item_group=self.freight.item_group,
			stock_uom="Kg", is_stock_item=0, is_purchase_item=1)
		invoice = make("Purchase Invoice", submit, company=company, supplier=supplier.name, currency="EUR",
			posting_date=today(), set_posting_time=1, custom_vehicle_immobilisation=incident.name, custom_fleet_cost_category="External Service",
			items=[dict(item_code=service.name, qty=1, rate=120000, expense_account=expense, cost_center=center)])
		return issue, invoice

	def test_fleet_d_e_submitted_stock_and_purchase_vouchers(self):
		frappe.db.set_value("Vehicle", self.vehicle.name, "last_odometer", 85000)
		_, trip, _ = self.route()
		trip.reload()
		trip.departure_odometer, trip.arrival_odometer = "85000", "85600"
		trip.save()
		advance_status(trip.name, "Arrived")

		issue, invoice = self.repair_vouchers(submit=True)
		self.assertEqual(issue.total_outgoing_value, 60000)
		self.assertTrue(frappe.db.exists("GL Entry", {"voucher_type": "Stock Entry", "voucher_no": issue.name}))
		costs = vehicle_costs(self.company.name, [self.vehicle.name], today(), today())[self.vehicle.name]
		self.assertEqual(costs["Parts"], 60000)
		self.assertEqual(costs["External Service"], 120000)
		self.assertEqual(costs["charges"], 180000)
		self.assertEqual(costs["investment"], 0)
		self.assertEqual(costs["cash_out"], 0)
		_, rows, *_ = fleet_report({"company": self.company.name, "vehicle": self.vehicle.name})
		self.assertEqual(rows[0]["cost_per_km"], 300)

		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		payment = get_payment_entry("Purchase Invoice", invoice.name, bank_account=self.company.default_cash_account)
		payment.custom_vehicle_immobilisation = invoice.custom_vehicle_immobilisation
		payment.reference_no, payment.reference_date = "FICTITIOUS-FLEET-REPAIR", today()
		payment.insert().submit()
		paid_costs = vehicle_costs(self.company.name, [self.vehicle.name], today(), today())[self.vehicle.name]
		self.assertEqual(paid_costs["cash_out"], 120000)
		self.assertEqual(paid_costs["charges"], 180000)

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
		_, second_trip, second_bilty = self.route(order=order if shared_order else None, vehicle=self.second_vehicle())
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
		_, retry_trip, retry_bilty = self.route(quantity=100, order=order, vehicle=self.second_vehicle())
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
