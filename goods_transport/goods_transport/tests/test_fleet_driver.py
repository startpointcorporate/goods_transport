from unittest import TestCase
from unittest.mock import Mock, patch

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
			patch.object(frappe, "get_meta"),
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
		with (
			patch.object(frappe, "get_all", return_value=[]) as get_all,
			patch.object(frappe.db, "table_exists", return_value=False),
		):
			result = fleet_driver._project_trip(trip, {"driver": "D-1", "company": "Site"})
		self.assertNotIn("fuel_plan_inputs", result)
		self.assertEqual(result["fuel_stops"], [
			{"station": "Station", "latitude": None, "longitude": None, "refill_liters": 20},
		])
		self.assertEqual(get_all.call_args.kwargs["filters"], {
			"trip": "TRIP-1", "driver": "D-1", "company": "Site", "vehicle": "TRUCK-1",
		})

	def test_tolls_projection_never_reads_or_returns_rates(self):
		trip = frappe._dict(route="RN1", trip_date="2026-11-19", fuel_plan_inputs=None)
		locations = [frappe._dict(latitude=1, longitude=2), frappe._dict(latitude=1, longitude=3)]
		station = frappe._dict(
			name="STOP", location_name="Péage", address="Accès principal",
			latitude=1, longitude=2, custom_toll_accuracy_m=100, custom_toll_precision="Précis",
		)
		with (
			patch.object(frappe, "conf", frappe._dict(goods_transport_truck_osrm_url="http://routing")),
			patch.object(frappe, "get_all", return_value=[station]) as stations,
			patch("goods_transport.goods_transport.services.truck_plan.fetch_route",
				return_value={"geometry": {"coordinates": [(2, 1), (3, 1)]}}),
		):
			tolls = fleet_driver._route_tolls(trip, {"locations": locations})
		self.assertEqual(tolls, [{
			"name": "Péage", "axis": "RN1", "address": "Accès principal",
			"latitude": 1, "longitude": 2, "precision": "Précis",
		}])
		self.assertNotIn("custom_toll_rates", stations.call_args.kwargs["fields"])

	def test_driver_cannot_use_a_financial_or_out_of_order_transition(self):
		trip = frappe._dict(name="TRIP-1", driver="D-1", status="Vehicle Assigned")
		with (
			patch.object(fleet_driver, "_assigned_trip", return_value=trip),
			patch.object(fleet_driver, "_field_event_exists", return_value=False),
		):
			for event in ("Settled", "Closed", "departed"):
				with self.subTest(event=event), self.assertRaises(frappe.ValidationError):
					fleet_driver.record_field_event(trip.name, event)

	def test_driver_replay_returns_without_writing_a_second_event(self):
		trip = Mock(name="TRIP-1", driver="D-1", status="Loaded")
		with (
			patch.object(fleet_driver, "_assigned_trip", return_value=trip),
			patch.object(fleet_driver, "_field_event_exists", return_value=True),
		):
			self.assertEqual(fleet_driver.record_field_event("TRIP-1", "at_loading"), "Loaded")
		trip.add_comment.assert_not_called()
