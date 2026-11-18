from unittest import TestCase

import frappe

from goods_transport.goods_transport.doctype.transport_trip.transport_trip import advance_status
from goods_transport.goods_transport.services import fleet_tyres as tyres
from goods_transport.goods_transport.services.fleet_odometer import record_trip_readings


class TestFleetTyres(TestCase):
	@classmethod
	def setUpClass(cls):
		from goods_transport.goods_transport.tests.test_transport_recette import TestTransportRecette, make

		cls.fixtures = TestTransportRecette()
		TestTransportRecette.setUpClass()
		cls.addClassCleanup(TestTransportRecette.doClassCleanups)
		company = cls.fixtures.company.name
		if not frappe.db.exists("Party Type", "Supplier"):
			make("Party Type", party_type="Supplier", account_type="Payable")
		frappe.db.set_single_value("Stock Settings", "enable_serial_and_batch_no_for_item", 1)
		for purpose in ("Material Receipt", "Material Transfer", "Material Issue"):
			if not frappe.db.exists("Stock Entry Type", purpose):
				make("Stock Entry Type", name=purpose, purpose=purpose)
		group = frappe.db.get_value("Item Group", {"is_group": 0})
		cls.item = make(
			"Item", item_code=f"{cls.fixtures.label} Tyre", item_group=group,
			stock_uom="Kg", is_stock_item=1, has_serial_no=1,
		).name
		cls.warehouses = [
			make("Warehouse", warehouse_name=name, company=company).name
			for name in ("Tyre Inventory", "Tyres on Vehicles", "Tyres under Inspection")
		]
		cls.vehicle = cls.fixtures.vehicle.name
		cls.other_vehicle = cls.fixtures.second_vehicle()

	def setUp(self):
		frappe.db.savepoint("tyre_case")
		self.addCleanup(frappe.db.rollback, save_point="tyre_case")

	def stock_tyre(self, suffix):
		serial = f"{self.fixtures.label}-{suffix}"
		entry = frappe.get_doc({
			"doctype": "Stock Entry", "stock_entry_type": "Material Receipt",
			"company": self.fixtures.company.name, "items": [{
				"item_code": self.item, "qty": 1, "basic_rate": 300,
				"t_warehouse": self.warehouses[0], "use_serial_batch_fields": 1, "serial_no": serial,
			}],
		}).insert()
		entry.submit()
		return tyres.register(self.vehicle, f"PNEU-{suffix}", serial, "315/80 R22.5")

	def test_mount_readings_rotation_replacement_and_terminal_state(self):
		first, second, third = (self.stock_tyre(suffix) for suffix in ("001", "002", "003"))
		left = tyres.add_position(self.vehicle, 1, "Left")
		right = tyres.add_position(self.vehicle, 1, "Right")
		other = tyres.add_position(self.other_vehicle, 1, "Left")
		rear = tyres.add_position(self.vehicle, 2, "Outside")
		with self.assertRaises(frappe.DuplicateEntryError):
			tyres.add_position(self.vehicle, 1, "left")
		tyres.fit(self.vehicle, left, 0, "Mount", tyre=first, warehouse=self.warehouses[1])
		tyres.fit(self.vehicle, rear, 0, "Mount", tyre=third, warehouse=self.warehouses[1])
		with self.assertRaises(frappe.ValidationError):
			tyres.fit(self.vehicle, left, 0, "Mount", tyre=second, warehouse=self.warehouses[1])
		with self.assertRaises(frappe.ValidationError):
			tyres.fit(self.other_vehicle, other, 0, "Mount", tyre=first, warehouse=self.warehouses[1])
		tyres.inspect(self.vehicle, left, "Initial check", inspection_type="Pressure Check", interval_km=120)
		tyres.fit(self.vehicle, left, 50, "Rotate", destination=right)
		_, trip, _ = self.fixtures.route()
		trip.update({"departure_odometer": "0", "arrival_odometer": "100", "status": "Arrived"})
		record_trip_readings(trip)
		record_trip_readings(trip)
		trip.db_set("status", "Delivered")
		_, second_trip, _ = self.fixtures.route()
		second_trip.reload()
		second_trip.update({"departure_odometer": "100", "arrival_odometer": "150"})
		second_trip.save()
		advance_status(second_trip.name, "Arrived")
		positions = tyres.overview(self.vehicle)["positions"]
		self.assertEqual(positions[1].distance, 150)
		self.assertTrue(positions[1].inspection_due)
		tyres.inspect(self.vehicle, right, "Pressure checked", inspection_type="Pressure Check")
		self.assertFalse(tyres.overview(self.vehicle)["positions"][1].inspection_due)
		self.assertEqual(positions[2].distance, 150)
		tyres.fit(self.vehicle, right, 150, "Replace", tyre=second, notes="Worn")
		self.assertEqual(tyres.overview(self.vehicle)["positions"][2].active_tyre, third)
		events = tyres.history(self.vehicle, first)
		self.assertEqual(sum(event.distance or 0 for event in events), 150)
		self.assertEqual(events[-1].operation, "Retire")
		for vehicle, position, reading in ((self.vehicle, left, 150), (self.other_vehicle, other, 0)):
			with self.assertRaises(frappe.ValidationError):
				tyres.fit(vehicle, position, reading, "Mount", tyre=first, warehouse=self.warehouses[1])
		retired = frappe.get_doc("Fleet Tyre", first)
		retired.state = "Available"
		with self.assertRaises(frappe.PermissionError):
			retired.save(ignore_permissions=True)
		self.assertFalse(frappe.db.get_value("Serial No", retired.serial_no, "warehouse"))


	def test_purchase_receipt_stock_and_costs(self):
		from goods_transport.goods_transport.tests.test_transport_recette import make

		company = self.fixtures.company.name
		group = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
		if not group:
			group = make("Supplier Group", supplier_group_name="Tyre Suppliers").name
		supplier = make("Supplier", supplier_name=f"{self.fixtures.label} Supplier", supplier_group=group)
		serial = self.fixtures.label + "-purchased"
		receipt = make("Purchase Receipt", True, company=company, supplier=supplier.name, currency="EUR",
			items=[dict(item_code=self.item, qty=1, rate=300, warehouse=self.warehouses[0],
				use_serial_batch_fields=1, serial_no=serial)])
		tyre = tyres.register(self.vehicle, "PNEU-PURCHASED", serial, "315/80 R22.5")
		position = tyres.add_position(self.vehicle, 1, "Left")
		tyres.fit(self.vehicle, position, 0, "Mount", tyre=tyre, warehouse=self.warehouses[1])
		self.assertEqual(frappe.db.get_value("Serial No", serial, "warehouse"), self.warehouses[1])

		service = make("Item", item_code=f"{self.fixtures.label} Service",
			item_group=self.fixtures.freight.item_group, stock_uom="Kg", is_stock_item=0, is_purchase_item=1)
		invoice = make("Purchase Invoice", True, company=company, supplier=supplier.name, currency="EUR",
			items=[dict(item_code=service.name, qty=1, rate=45,
				expense_account=self.fixtures.company.stock_adjustment_account,
				cost_center=self.fixtures.company.cost_center)])
		line = invoice.items[0].name
		tyres.allocate_expense(self.vehicle, tyre, invoice.name, line, "Installation")
		with self.assertRaises(frappe.ValidationError):
			tyres.allocate_expense(self.vehicle, tyre, invoice.name, line, "Repair")
		tyres.fit(self.vehicle, position, 100, "Remove", warehouse=self.warehouses[2])
		self.assertEqual(frappe.db.get_value("Serial No", serial, "warehouse"), self.warehouses[2])
		report = tyres.costs(self.vehicle)
		self.assertEqual(report["rows"][0]["acquisition"]["voucher_no"], receipt.name)
		self.assertAlmostEqual(report["rows"][0]["cost_per_km"], 3.45)
		self.assertEqual(report["vehicle_service_cost"], 45)

		with self.assertRaises(frappe.ValidationError):
			tyres.fit(self.vehicle, position, 100, "Mount", tyre=tyre, warehouse=self.warehouses[1])
		tyres.approve_removed(self.vehicle, tyre, "Pressure and tread checked")
		tyres.fit(self.vehicle, position, 100, "Mount", tyre=tyre, warehouse=self.warehouses[1])
		self.assertEqual(tyres.overview(self.vehicle)["positions"][0].distance, 100)
