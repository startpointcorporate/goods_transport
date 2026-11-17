from decimal import Decimal

from frappe.tests import UnitTestCase

from goods_transport.goods_transport.services.fuel_optimizer import allocate, demand, find_paths


class TestFuelOptimizer(UnitTestCase):
	def test_three_stops_with_smaller_than_full_withdrawals(self):
		self.assertEqual(allocate([40, 48, 51, 51], [55, 70, 60], [7, 5, 9], 45, 60), [43, 60, 42])

	def test_unreachable_leg_and_insufficient_supply(self):
		self.assertIsNone(allocate([30, 61], [100], [1], 40, 60))
		self.assertIsNone(allocate([30, 50], [19], [1], 40, 60))
		self.assertIsNone(allocate([30, 10], [100], [1], 29, 60))

	def test_uses_fuel_already_in_tank(self):
		self.assertEqual(allocate([30, 40], [40], [0], 50, 60), [20])
		self.assertEqual(allocate([40], [], [], 50, 60), [])

	def test_waypoint_cannot_be_skipped(self):
		nodes = [{}, {"supply": 40}, {"mandatory": True}, {"supply": 50}, {}]
		matrix = [[None, 30, None, None, 5], [None, None, 15, 5, None],
			[None, None, None, 20, None], [None, None, None, None, 35], [None] * 5]
		self.assertEqual(find_paths(nodes, matrix, 31, 52, Decimal(1)), [(0, 1, 2, 3, 4)])

	def test_rounds_up_leg_demand(self):
		self.assertEqual(demand(1010.15, Decimal("0.35")), 354)
