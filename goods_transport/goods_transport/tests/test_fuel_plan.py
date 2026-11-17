from frappe.tests import UnitTestCase

from goods_transport.goods_transport.services.fuel_plan import fueling


class TestFuelPlan(UnitTestCase):
	def test_minimum_fill_preserves_fuel_remaining_on_arrival(self):
		self.assertAlmostEqual(fueling(120000, 460000, 75, 0.00035, 400), 128, places=3)

	def test_rejects_station_beyond_departure_range(self):
		self.assertIsNone(fueling(300000, 280000, 75, 0.00035, 400))

	def test_rejects_remaining_leg_beyond_tank_capacity(self):
		self.assertIsNone(fueling(120000, 460000, 75, 0.00035, 150))

	def test_skips_fill_when_departure_fuel_is_sufficient(self):
		self.assertIsNone(fueling(120000, 460000, 300, 0.00035, 400))
