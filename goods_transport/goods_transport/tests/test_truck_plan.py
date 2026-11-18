from frappe import _dict
from frappe.tests import UnitTestCase
from frappe.utils import getdate

from goods_transport.goods_transport.services.truck_plan import planned_tolls, vehicle_limits


class TestTruckPlan(UnitTestCase):
	def setUp(self):
		self.vehicle = {
			"height": 3.5, "width": 2.45, "length": 9, "tare": 8000, "ptac": 18000,
			"axles": 2, "payload": 10000, "volume": 42, "cemac": "P11",
		}

	def test_planned_two_axle_truck(self):
		self.assertEqual(vehicle_limits(self.vehicle, 7500, 20, [7000, 8500]), (15500, "3b"))

	def test_planned_three_axle_truck(self):
		self.assertEqual(vehicle_limits(self.vehicle | {"axles": 3, "cemac": "P12"}, 7500, 20, []), (15500, "4"))

	def test_rejects_incompatible_loads_or_vehicle(self):
		for vehicle, weight, volume, axle_loads in (
			(self.vehicle, 11000, 20, []), (self.vehicle, 7500, 43, []),
			(self.vehicle | {"ptac": 15000}, 7500, 20, []),
			(self.vehicle | {"height": 4.1}, 7500, 20, []),
			(self.vehicle | {"axles": 3}, 7500, 20, []),
			(self.vehicle, 7500, 20, [14000, 1500]),
			(self.vehicle, float("nan"), 20, []),
		):
			with self.subTest(vehicle=vehicle, weight=weight, volume=volume, axle_loads=axle_loads):
				with self.assertRaises(ValueError):
					vehicle_limits(vehicle, weight, volume, axle_loads)

	def test_effective_rates_missing_rates_and_order(self):
		rate = _dict(vehicle_class="3b", currency="XAF", valid_from="2019-09-09",
			valid_until="2026-11-30", amount=15000, source="source")
		def station(name, lon, precision="Passage cartographié", rates=()):
			return _dict(name=name, latitude=0, longitude=lon, custom_toll_precision=precision,
				custom_toll_accuracy_m=20, custom_toll_rates=rates)
		stations = [station("second", 0.04, rates=[rate]), station("first", 0.02),
			station("repère", 0.03, precision="Repère de recherche")]
		result = planned_tolls([[0, 0], [0.06, 0]], stations, getdate("2026-11-17"), "3b")
		self.assertEqual([(row["name"], row["amount"]) for row in result], [("first", None), ("second", 15000)])
		self.assertIsNone(planned_tolls([[0, 0], [0.06, 0]], stations, getdate("2026-12-01"), "3b")[1]["amount"])
