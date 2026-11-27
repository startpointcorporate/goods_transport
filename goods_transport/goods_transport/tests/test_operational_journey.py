"""Operational journey regression cases for a disposable ERPNext site."""

from unittest import TestCase

import frappe

from goods_transport.goods_transport.services.cargo_measurements import cargo_weight
from goods_transport.goods_transport.services.truck_plan import vehicle_limits
from goods_transport.goods_transport.services.operations import (
	create_bilty_from_trip,
	create_pod_from_bilty,
	create_trip_from_order,
	get_order_trips,
	get_trip_orders,
)
from goods_transport.goods_transport.tests import test_transport_recette as fixture
from goods_transport.goods_transport.tests.test_transport_recette import make


class TestOperationalJourney(TestCase):
	@classmethod
	def setUpClass(cls):
		cls.case = fixture.TestTransportRecette()
		cls.case.setUpClass()
		cls.addClassCleanup(cls.case.doClassCleanups)

	def setUp(self):
		frappe.db.savepoint("operational_journey")
		self.addCleanup(frappe.db.rollback, save_point="operational_journey")

	def test_estimate_covers_all_bases(self):
		order = frappe.new_doc("Transport Order")
		order.update(dict(quantity=8, weight=2500, package_count=13, vehicle_count=2,
			estimated_distance=30, rate=450000, additional_charges=250))
		for basis, units in {
			"Per Trip": 1, "Fixed": 1, "Per Vehicle": 2, "Per Ton": 2.5,
			"Per Kg": 2500, "Per Package": 13, "Per KM": 30,
		}.items():
			with self.subTest(basis=basis):
				order.rate_basis = basis
				order._compute_estimated_totals()
				self.assertEqual(order.billable_quantity, units)
				self.assertEqual(order.estimated_freight, 450000 * units)
				self.assertEqual(order.grand_total, 450000 * units + 250)

	def test_prefills_groupage_split_and_partial_delivery(self):
		if not frappe.db.exists("Item Group", "Cargo Items"):
			make("Item Group", item_group_name="Cargo Items", is_group=1)
		commodity = make("Item", item_code=f"{self.case.label} Cargo", item_group="Cargo Items",
			stock_uom="Nos", is_stock_item=1)
		other_customer = make(
			"Customer", customer_name=f"{self.case.label} Other", customer_type="Company",
			customer_group=self.case.customer.customer_group, territory=self.case.customer.territory,
		)
		common = dict(company=self.case.company.name, origin=self.case.origin, destination=self.case.destination,
			customer=self.case.customer.name, commodity=commodity.name, currency="EUR", uom="Nos",
			quantity=8, weight=2400, cargo_volume=16, rate_basis="Per Ton", rate=450000, pod_required=1)
		order = make("Transport Order", True, **common, estimated_distance=30)
		intermediate = make("Transport Order", True, **dict(common, customer=other_customer.name,
			destination=self.case.origin, origin=self.case.destination))
		trip = frappe.get_doc("Transport Trip", create_trip_from_order(order.name, self.case.vehicle.name, 5))
		self.assertEqual(trip.planned_distance, 30)
		self.assertEqual((trip.planned_cargo_weight, trip.planned_cargo_volume), (1500, 10))
		prefilled = frappe.get_doc("Bilty", create_bilty_from_trip(trip.name, freight_item=self.case.freight.name))
		self.assertEqual((prefilled.transport_order, prefilled.customer, prefilled.total_quantity,
			prefilled.total_gross_weight, prefilled.total_cargo_volume), (order.name, order.customer, 5, 1500, 10))
		prefilled.delete()
		frappe.db.set_value("Vehicle", self.case.vehicle.name, "volume_capacity", 50)
		trip.freight_item = self.case.freight.name
		trip.append("order_allocations", {"transport_order": intermediate.name, "quantity": 8, "allocated_volume": 14})
		trip.submit()
		self.assertEqual((trip.planned_cargo_weight, trip.planned_cargo_volume), (3900, 24))

		with self.assertRaises(frappe.ValidationError):
			create_bilty_from_trip(trip.name, other_customer.name, order.name)
		with self.assertRaises(frappe.ValidationError):
			create_bilty_from_trip(trip.name, self.case.customer.name, order.name, rate=1)
		bilty = frappe.get_doc("Bilty", create_bilty_from_trip(trip.name, self.case.customer.name, order.name))
		self.assertEqual(bilty.driver, self.case.driver.name)
		self.assertEqual((bilty.items[0].item, bilty.total_quantity, bilty.freight_quantity, bilty.freight_amount),
			(commodity.name, 5, 1.5, 675000))
		self.assertEqual(bilty.total_cargo_volume, 10)
		self.assertEqual(trip.reload().loaded_weight, 0)
		bilty.items[0].cargo_volume = 9
		bilty.items[0].gross_weight = 1200
		bilty.submit()
		self.assertEqual((bilty.freight_quantity, bilty.freight_amount), (1.2, 540000))
		grouped = frappe.get_doc("Bilty", create_bilty_from_trip(trip.name, other_customer.name, intermediate.name))
		self.assertEqual(grouped.destination, intermediate.destination)
		self.assertNotEqual(grouped.destination, trip.destination)
		grouped.submit()
		trip.reload()
		self.assertEqual((trip.loaded_weight, trip.loaded_cargo_volume), (3600, 23))
		self.assertAlmostEqual(trip.volume_utilization, 46)
		self.assertCountEqual(get_trip_orders(trip.name), [order.name, intermediate.name])
		pod = frappe.get_doc("Proof of Delivery", create_pod_from_bilty(bilty.name, 4, "FICTITIOUS RECEIVER"))
		self.assertEqual((pod.trip, pod.customer, pod.short_quantity), (trip.name, self.case.customer.name, 1))
		remainder = frappe.get_doc("Transport Trip", create_trip_from_order(order.name, self.case.second_vehicle()))
		self.assertEqual(remainder.order_allocations[0].quantity, 4)
		self.assertEqual((remainder.planned_cargo_weight, remainder.planned_cargo_volume), (1200, 8))
		self.assertCountEqual(get_order_trips(order.name), [trip.name, remainder.name])

	def test_erpnext_weight_and_pricing_validation(self):
		if not frappe.db.exists("UOM Category", "Mass"):
			make("UOM Category", category_name="Mass")
		uom = make("UOM", uom_name=f"{self.case.label} mass")
		make("UOM Conversion Factor", category="Mass", from_uom="Kg", to_uom=uom.name, value=4)
		self.assertEqual(cargo_weight(8, uom.name, None), 2)
		self.assertEqual(cargo_weight(8, "Tonne", None), 8000)
		with self.assertRaises(frappe.ValidationError):
			cargo_weight(8, "Kg", 8000, validate=True)

		order = frappe.new_doc("Transport Order")
		order.update(dict(company=self.case.company.name, origin=self.case.origin, destination=self.case.destination,
			customer=self.case.customer.name, quantity=8, uom="Nos", rate_basis="Per Ton", rate=50))
		order.insert()
		with self.assertRaises(frappe.ValidationError):
			order.submit()

	def test_unknown_volume_keeps_vehicle_safety_checks(self):
		spec = dict(tare=12000, ptac=32000, height=3.8, width=2.55, length=11.5, axles=3,
			payload=20000, volume=45, cemac="P12")
		self.assertEqual(vehicle_limits(spec, 8000, None, []), (20000, "4"))
		for weight, volume in [(8000, 46), (20001, None)]:
			with self.subTest(weight=weight, volume=volume), self.assertRaises(ValueError):
				vehicle_limits(spec, weight, volume, [])
