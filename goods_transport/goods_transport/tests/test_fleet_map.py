from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import frappe
from frappe.tests import UnitTestCase

from goods_transport.goods_transport.services import fleet_map, truck_plan


class TestFleetMap(UnitTestCase):
	def test_trip_permission_is_checked_before_linked_records(self):
		trip = Mock()
		trip.check_permission.side_effect = frappe.PermissionError
		with patch.object(frappe, "get_doc", return_value=trip) as get_doc:
			with self.assertRaises(frappe.PermissionError):
				fleet_map.mission("FICTITIOUS-TRIP")
		trip.check_permission.assert_called_once_with("read")
		get_doc.assert_called_once_with("Transport Trip", "FICTITIOUS-TRIP")

	def test_fuel_isolation_and_live_availability(self):
		trip = frappe._dict(name="TRIP", company="OWN", vehicle="TRUCK", trip_date="2026-11-19")
		station = frappe._dict(name="OWN-STATION", station_name="Station", street_address="RN1",
			latitude=-4.3, longitude=13.5, diesel=1, essence=0)
		vehicle = Mock(fuel_type="Diesel")
		reserve = Mock(company="FOREIGN", station="OWN-STATION")
		plan = {"stops": [{"reserve": "FOREIGN-RESERVE", "refill_liters": 73}]}

		def get_list(doctype, *, filters, **kwargs):
			self.assertEqual(filters["company"], "OWN")
			return [station] if doctype == fleet_map.STATION else []

		with patch.object(frappe, "conf", {"goods_transport_partner_fuel": True}), \
			patch.object(fleet_map, "now_datetime", return_value=datetime(2026, 11, 19, 12)), \
			patch.object(frappe, "has_permission", return_value=True), \
			patch.object(frappe, "get_list", side_effect=get_list), \
			patch.object(frappe, "get_doc", side_effect=lambda doctype, name: vehicle if doctype == "Vehicle" else reserve), \
			patch.object(fleet_map.fuel_plan, "candidates", side_effect=[
				[{"station_id": "OWN-STATION", "reserve": "OWN-RESERVE", "supply": 32000},
				 {"station_id": "FOREIGN-STATION", "reserve": "FOREIGN-RESERVE", "supply": 73000}],
				[],
			]):
			first = fleet_map.fuel_layers(trip, plan, [])[0]
			second = fleet_map.fuel_layers(trip, plan, [])[0]
		self.assertEqual(first["reserves"], [{"name": "OWN-RESERVE", "liters": 32, "fuel": "Diesel"}])
		self.assertEqual(first["state"], "available")
		self.assertNotIn("planned_liters", first)
		self.assertEqual(second["state"], "unavailable")
		self.assertEqual(second["reserves"], [])

	def test_gps_age_and_scope(self):
		now = datetime(2026, 11, 19, 12)
		trip = frappe._dict(name="TRIP", vehicle="TRUCK")
		fix = {"trip": trip.name, "vehicle": trip.vehicle,
			"latitude": -4.3, "longitude": 13.5, "accuracy_m": 12, "recorded_at": now}
		with patch.object(frappe, "get_hooks", return_value=["provider"]), \
			patch.object(frappe, "get_attr", return_value=lambda trip: fix), \
			patch.object(fleet_map, "now_datetime", return_value=now):
			self.assertEqual(fleet_map.latest_position(trip)["state"], "recent")
			fix["recorded_at"] -= timedelta(minutes=20)
			stale = fleet_map.latest_position(trip)
			self.assertEqual((stale["state"], stale["age_minutes"], stale["accuracy_m"]), ("stale", 20, 12))
			fix["trip"] = "OTHER"
			self.assertEqual(fleet_map.latest_position(trip), {"state": "unavailable"})
			fix.update(trip=trip.name, longitude=None)
			self.assertEqual(fleet_map.latest_position(trip), {"state": "unavailable"})

	def test_osrm_cache_keys_include_route_and_graph(self):
		data = {"code": "Ok", "routes": [{"distance": 1200}]}
		cache = {}
		with patch.object(frappe, "flags", frappe._dict(goods_transport_cache_osrm=True)), \
			patch.object(frappe, "conf", {}) as conf, \
			patch.object(frappe.cache, "get_value", side_effect=cache.get), \
			patch.object(frappe.cache, "set_value", side_effect=lambda field, value, **kw: cache.update({field: value})), \
			patch.object(truck_plan.requests, "get", return_value=Mock(**{"json.return_value": data})) as get:
			first = [(13.5, -4.3), (11.9, -4.8)]
			changed = [(13.5, -4.3), (12.5, -4.6), (11.9, -4.8)]
			self.assertEqual(truck_plan.fetch_route("http://osrm", first)["distance"], 1200)
			truck_plan.fetch_route("http://osrm", first)
			self.assertEqual(get.call_count, 1)
			truck_plan.fetch_route("http://osrm", changed)
			conf["goods_transport_osrm_graph_revision"] = "next"
			truck_plan.fetch_route("http://osrm", changed)
			self.assertEqual(get.call_count, 3)
