from unittest import TestCase
from unittest.mock import patch

import frappe

from goods_transport.goods_transport.services import fleet_driver


class TestFleetDriver(TestCase):
	def setUp(self):
		session = patch.object(fleet_driver.frappe, "session", frappe._dict(user="driver@example.com"))
		roles = patch.object(fleet_driver.frappe, "get_roles", return_value=["Fleet Driver"])
		permissions = patch.object(fleet_driver, "get_user_permissions", return_value={})
		self.addCleanup(session.stop)
		self.addCleanup(roles.stop)
		self.addCleanup(permissions.stop)
		session.start()
		self.roles = roles.start()
		self.permissions = permissions.start()

	def test_user_without_role_cannot_resolve_assignment(self):
		self.roles.return_value = ["Employee"]
		with patch.object(frappe, "get_all") as get_all:
			self.assertFalse(fleet_driver.available())
		get_all.assert_not_called()

	def test_unambiguous_assignment_requires_company_access(self):
		self.permissions.return_value = {"Company": [{"doc": "Other", "applicable_for": ""}]}
		with patch.object(frappe, "get_all", side_effect=[[frappe._dict(name="EMP-1", company="Site")], ["D-1"]]):
			self.assertFalse(fleet_driver.available())

	def test_missions_queries_only_assigned_company_and_driver(self):
		employee = frappe._dict(name="EMP-1", company="Site")
		with (
			patch.object(frappe, "get_all", side_effect=[[employee], ["D-1"], []]) as get_all,
			patch.object(fleet_driver, "now_datetime"),
		):
			self.assertEqual(fleet_driver.missions()["trips"], [])
		self.assertEqual(get_all.call_args.args, ("Transport Trip",))
		self.assertEqual(get_all.call_args.kwargs["filters"], {"driver": "D-1", "company": "Site", "docstatus": 1})
		self.assertNotIn("financial_budget", get_all.call_args.kwargs["fields"])
		self.assertNotIn("name", fleet_driver.AUTHORIZATION_FIELDS)

	def test_multiple_driver_links_fail_closed(self):
		employee = frappe._dict(name="EMP-1", company="Site")
		with patch.object(frappe, "get_all", side_effect=[[employee], ["D-1", "D-2"]]):
			self.assertFalse(fleet_driver.available())

	def test_projection_omits_prices_reserves_and_retrieval_codes(self):
		trip = frappe._dict(
			name="TRIP-1", vehicle="TRUCK-1",
			fuel_plan_inputs=(
				'{"authorization_codes":["SECRET"],"confirmed_forecast":{"stops":'
				'[{"station":"Station","reserve":"RESERVE-1","cost":100,"refill_liters":20}]}}'
			),
		)
		with patch.object(frappe, "get_all", return_value=[]) as get_all:
			result = fleet_driver._project_trip(trip, {"driver": "D-1", "company": "Site"})
		self.assertNotIn("fuel_plan_inputs", result)
		self.assertEqual(result["fuel_stops"], [
			{"station": "Station", "latitude": None, "longitude": None, "refill_liters": 20},
		])
		self.assertEqual(get_all.call_args.kwargs["filters"], {
			"trip": "TRIP-1", "driver": "D-1", "company": "Site", "vehicle": "TRUCK-1",
		})
