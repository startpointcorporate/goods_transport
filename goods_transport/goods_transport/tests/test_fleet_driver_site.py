"""Run on an isolated ERPNext site with Goods Transport installed."""

import io
from unittest import TestCase
from unittest.mock import patch

from PIL import Image
from werkzeug.datastructures import MultiDict
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import frappe

from goods_transport.goods_transport.doctype.transport_trip.transport_trip import advance_status
from goods_transport.goods_transport.services import fleet_driver
from goods_transport.goods_transport.tests import test_trip_inspection as inspections
from goods_transport.goods_transport.tests import test_transport_recette as fixtures
from goods_transport.setup.install_fleet_driver import execute


class TestFleetDriverSite(TestCase):
	def test_two_driver_accounts_and_employee_without_role(self):
		case = fixtures.TestTransportRecette()
		self.addCleanup(case.doClassCleanups)
		case.setUpClass()
		execute()
		inspections.setup_template(case)
		_, trip_a, bilty_a = case.route()
		driver_a = case.driver
		employee_b = fixtures.make("Employee", first_name=case.label + " B", gender="Male",
			date_of_birth="1990-01-01", date_of_joining=frappe.utils.today(),
			company=case.company.name, status="Active")
		driver_b = fixtures.make("Driver", full_name=case.label + " B", employee=employee_b.name,
			status="Active", license_number=case.label + " B")
		case.driver = driver_b
		_, trip_b, _ = case.route(vehicle=case.second_vehicle())
		users = []
		for label, driver in (("a", driver_a), ("b", driver_b), ("staff", None)):
			user = fixtures.make(
				"User", email=f"{label}-{frappe.generate_hash(length=8)}@example.test",
				first_name=label, send_welcome_email=0, user_type="Website User",
				roles=[{"role": fleet_driver.ROLE}] if driver else [],
			)
			if driver:
				frappe.db.set_value("Employee", driver.employee, "user_id", user.name)
			users.append(user.name)
		self.addCleanup(frappe.set_user, "Administrator")

		for user, expected, other in ((users[0], trip_a, trip_b), (users[1], trip_b, trip_a)):
			frappe.set_user(user)
			self.assertTrue(fleet_driver.available())
			self.assertEqual([trip["name"] for trip in fleet_driver.missions()["trips"]], [expected.name])
			self.assertFalse(frappe.has_permission("Transport Trip", "read", doc=other))
			with self.assertRaises(frappe.PermissionError):
				fleet_driver.delivery_documents(other.name)
			self.assertFalse(frappe.has_permission("Trip Settlement", "read"))
			self.assertFalse(frappe.has_permission("Fuel Contract Reserve", "read"))
		frappe.set_user(users[2])
		self.assertFalse(fleet_driver.available())
		with self.assertRaises(frappe.PermissionError):
			fleet_driver.missions()

		frappe.set_user(users[0])
		departure = self._inspect(trip_a.name, "Departure", "150")
		self.assertTrue(departure["submitted"])
		self.assertEqual(fleet_driver.inspection_photo(departure["name"], departure["photos"][0]["name"]).mimetype, "image/png")

		frappe.set_user(users[1])
		with self.assertRaises(frappe.PermissionError):
			fleet_driver.inspection_photo(departure["name"], departure["photos"][0]["name"])

		with self.assertRaises(frappe.PermissionError):
			fleet_driver.report_incident(trip_a.name, "mechanical", "Wrong assignment")

		frappe.set_user(users[0])
		with self.assertRaises(frappe.ValidationError):
			fleet_driver.report_incident(trip_a.name, "Brk", "Unsupported category")
		with self._request("photo", "photo") as request, patch.object(frappe.local, "request", request, create=True):
			note = fleet_driver.report_incident(trip_a.name, "mechanical", "Loose cover <check>")
		comment = frappe.get_doc("Comment", note)
		self.assertEqual((comment.reference_doctype, comment.reference_name), ("Transport Trip", trip_a.name))
		self.assertEqual(comment.comment_email, users[0])
		self.assertIsNotNone(comment.creation)
		self.assertIn(trip_a.driver, comment.content)
		self.assertIn(trip_a.vehicle, comment.content)
		self.assertIn("&lt;check&gt;", comment.content)
		self.assertEqual(frappe.db.count("File", {"attached_to_doctype": "Transport Trip",
			"attached_to_name": trip_a.name, "is_private": 1}), 2)
		self.assertFalse(frappe.db.exists("Vehicle Immobilisation", {"transport_trip": trip_a.name}))

		frappe.set_user("Administrator")
		advance_status(trip_a.name, "Arrived")
		frappe.set_user(users[0])
		self.assertEqual([row.name for row in fleet_driver.delivery_documents(trip_a.name)], [bilty_a.name])
		with self._request("photo", "signature") as request, patch.object(frappe.local, "request", request, create=True):
			pod = fleet_driver.confirm_delivery(trip_a.name, bilty_a.name, 1000, 0, "Fixture receiver")
		self.assertEqual(frappe.db.get_value("Proof of Delivery", pod, "docstatus"), 1)
		self.assertTrue(frappe.db.get_value("Proof of Delivery", pod, "pod_image"))

		frappe.set_user("Administrator")
		advance_status(trip_a.name, "Delivered")
		frappe.set_user(users[0])
		self.assertTrue(self._inspect(trip_a.name, "Return", "200")["submitted"])
		self.assertEqual(float(frappe.db.get_value("Transport Trip", trip_a.name, "actual_distance")), 50)

		frappe.set_user(users[1])
		with self._request("photo") as request, patch.object(frappe.local, "request", request, create=True):
			incident = fleet_driver.report_critical_incident(trip_b.name, "Breakdown", "Fixture problem")
		self.assertEqual(frappe.db.get_value("Vehicle Immobilisation", incident, "vehicle"), trip_b.vehicle)
		frappe.set_user("Administrator")
		with self.assertRaisesRegex(frappe.ValidationError, "immobilised"):
			advance_status(trip_b.name, "In Transit")

	def _request(self, *file_fields):
		data = MultiDict()
		for index, field in enumerate(file_fields):
			image = io.BytesIO()
			Image.new("RGB", (32, 32), (32, 64 + index, len(field))).save(image, "PNG")
			image.seek(0)
			data.add(field, (image, f"{field}-{index}.png"))
		builder = EnvironBuilder(method="POST", data=data)
		self.addCleanup(builder.close)
		return Request(builder.get_environ())

	def _inspect(self, trip, phase, odometer):
		draft = fleet_driver.open_inspection(trip, phase)
		with self._request("file") as request, patch.object(frappe.local, "request", request, create=True):
			fleet_driver.upload_photo(draft["name"], "body")
		return fleet_driver.validate_inspection(draft["name"], odometer, inspections.results())
