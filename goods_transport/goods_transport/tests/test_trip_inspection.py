import io
from unittest import TestCase
from unittest.mock import patch

import frappe
from PIL import Image
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from goods_transport.goods_transport.doctype.transport_trip.transport_trip import advance_status
from goods_transport.goods_transport.services.trip_inspection import (
	INSPECTION, compare, create_repair, open_inspection, upload_photo, validate_inspection,
)
from goods_transport.goods_transport.tests import test_transport_recette as fixtures


def setup_template(case):
	return fixtures.make(
		"Trip Inspection Template", __newname=f"{case.label} checklist",
		company=case.company.name, require_inspections=1, controls=[
			{"code": "body", "label_en": "Bodywork", "label_fr": "Carrosserie", "required_control": 1, "min_photos": 1},
			{"code": "brakes", "label_en": "Brakes", "label_fr": "Freins", "safety": 1},
			{"code": "papers", "label_en": "Vehicle Papers", "label_fr": "Documents du véhicule", "documents": 1},
		],
	)


def add_asset(case):
	company = case.company.name
	category = fixtures.make("Asset Category", asset_category_name=f"{case.label} Trucks", accounts=[{
		"company_name": company,
		"fixed_asset_account": frappe.db.get_value("Account", {
			"company": company, "account_type": "Fixed Asset", "is_group": 0,
		}, "name"),
	}])
	item = fixtures.make("Item", item_code=f"{case.label} Truck Asset", item_group=case.freight.item_group,
		stock_uom="Kg", is_stock_item=0, is_fixed_asset=1, asset_category=category.name)
	location = fixtures.make("Location", location_name=f"{case.label} Garage")
	asset = fixtures.make("Asset", True, item_code=item.name, asset_name=case.label, location=location.name,
		company=company, purchase_date=frappe.utils.today(), available_for_use_date=frappe.utils.today(),
		asset_type="Existing Asset", net_purchase_amount=200000)
	vehicle = frappe.get_doc("Vehicle", case.vehicle.name)
	vehicle.custom_maintenance_asset = asset.name
	vehicle.save()


def results(body=None, brakes=None):
	return {
		"body": body or {"result": "Pass"},
		"brakes": brakes or {"result": "Pass"},
		"papers": {"result": "Pass"},
	}


def defect(code, severity="Minor"):
	return {"result": "Fail", "defect": code, "severity": severity, "observation": "Manually observed defect"}


class TestTripInspection(TestCase):
	@classmethod
	def setUpClass(cls):
		cls.case = fixtures.TestTransportRecette()
		cls.case.setUpClass()
		cls.addClassCleanup(cls.case.doClassCleanups)
		setup_template(cls.case)

	def setUp(self):
		frappe.db.savepoint("inspection_case")
		self.addCleanup(frappe.db.rollback, save_point="inspection_case")
		self.addCleanup(frappe.set_user, "Administrator")
		_, self.trip, self.bilty = self.case.route()

	def photo(self, name, control="body"):
		content = io.BytesIO()
		Image.new("RGB", (32, 32), (32, 64, 92)).save(content, "PNG")
		builder = EnvironBuilder(method="POST", data={"file": (io.BytesIO(content.getvalue()), "test.png")})
		self.addCleanup(builder.close)
		request = Request(builder.get_environ())
		self.addCleanup(request.close)
		with patch.object(frappe.local, "request", request, create=True):
			return upload_photo(name, control)

	def inspect(self, phase, odometer, values=None):
		doc = open_inspection(self.trip.name, phase)
		self.photo(doc["name"])
		return validate_inspection(doc["name"], str(odometer), values or results())

	def return_trip(self):
		self.case.deliver(self.trip, self.bilty)

	def test_hyphen_in_checklist_code_keeps_photo_association(self):
		template = frappe.get_doc("Trip Inspection Template", self.trip.inspection_template)
		template.controls[0].code = "body-work"
		template.save()
		_, trip, _ = self.case.route(vehicle=self.case.second_vehicle())
		doc = open_inspection(trip.name, "Departure")
		photo = self.photo(doc["name"], "body-work")
		values = results()
		values["body-work"] = values.pop("body")
		validated = validate_inspection(doc["name"], "100", values)
		self.assertEqual(validated["photos"][0]["name"], photo["name"])
		self.assertEqual(validated["photos"][0]["attached_to_field"], "body-work")

	def test_a_conformity_and_single_vehicle_log(self):
		with self.assertRaises(frappe.ValidationError):
			advance_status(self.trip.name, "In Transit")
		self.inspect("Departure", 100)
		self.return_trip()
		with self.assertRaisesRegex(frappe.ValidationError, "return inspection"):
			advance_status(self.trip.name, "Closed")
		returned = self.inspect("Return", 680)
		self.assertEqual(compare(self.trip.name)["overall"], "Compliant")
		self.assertEqual(compare(self.trip.name)["distance"], 580)
		validate_inspection(returned["name"], "680", results())
		self.assertEqual(frappe.db.count("Vehicle Log", {"license_plate": self.trip.vehicle, "docstatus": 1}), 1)
		self.case.invoice(self.bilty)
		frappe.get_doc("Trip Settlement", fixtures.create_settlement_for_trip(self.trip.name)).submit()
		self.assertEqual(advance_status(self.trip.name, "Closed"), "Closed")
		self.assertEqual(compare(self.trip.name)["overall"], "Compliant")

	def test_site_activation_is_snapshotted_for_new_trips(self):
		frappe.db.set_value("Trip Inspection Template", {"company": self.case.company.name}, "require_inspections", 0)
		vehicle = self.case.second_vehicle()
		_, optional, _ = self.case.route(vehicle=vehicle)
		self.assertFalse(frappe.parse_json(optional.inspection_policy)["required"])
		vehicle = frappe.copy_doc(self.case.vehicle)
		vehicle.license_plate += " C"
		vehicle.insert()
		with patch.dict(frappe.conf, trip_inspection_required_from="2000-01-01 00:00:00"):
			_, mandatory, _ = self.case.route(vehicle=vehicle.name)
			self.assertTrue(frappe.parse_json(mandatory.inspection_policy)["required"])
			with self.assertRaisesRegex(frappe.ValidationError, "departure inspection"):
				advance_status(mandatory.name, "In Transit")
			self.assertEqual(advance_status(optional.name, "In Transit"), "In Transit")

	def test_b_new_defect_creates_native_repair(self):
		add_asset(self.case)
		self.inspect("Departure", 100)
		self.return_trip()
		returned = self.inspect("Return", 680, results(body=defect("impact")))
		report = compare(self.trip.name)
		self.assertEqual((report["vehicle"], report["operational"]), ("Non-compliant", "Compliant"))
		self.assertEqual(report["rows"][0]["evolution"], "New Defect")
		repair = create_repair(returned["name"])
		self.assertEqual(create_repair(returned["name"]), repair)
		self.assertEqual(frappe.db.get_value("Asset Repair", repair["name"], "custom_trip_vehicle_inspection"), returned["name"])

	def test_c_preexisting_anomaly(self):
		scratch = results(body=defect("scratch"))
		self.inspect("Departure", 100, scratch)
		self.return_trip()
		self.inspect("Return", 680, scratch)
		report = compare(self.trip.name)
		self.assertEqual(report["rows"][0]["evolution"], "Existing Defect")
		self.assertEqual(report["overall"], "Compliant")

	def test_d_missing_evidence(self):
		doc = open_inspection(self.trip.name, "Departure")
		for values in ({}, results()):
			with self.assertRaises(frappe.ValidationError):
				validate_inspection(doc["name"], "100", values)
		self.assertEqual(compare(self.trip.name)["overall"], "Review Required")

	def test_e_lower_odometer_does_not_change_counter(self):
		self.inspect("Departure", 100)
		self.return_trip()
		with self.assertRaises(frappe.ValidationError):
			self.inspect("Return", 99)
		self.assertEqual(frappe.db.get_value("Vehicle", self.trip.vehicle, "last_odometer"), 0)
		self.assertIsNone(self.trip.reload().odometer_recorded_at)

	def test_f_critical_safety_immobilises(self):
		inspection = self.inspect("Departure", 100, results(brakes=defect("brake-failure", "Critical")))
		self.assertTrue(inspection["immobilisation"])
		request = create_repair(inspection["name"])
		self.assertEqual(request["doctype"], "ToDo")
		self.assertEqual(frappe.db.get_value("ToDo", request["name"], "reference_name"), inspection["name"])
		with self.assertRaisesRegex(frappe.ValidationError, "immobilised"):
			advance_status(self.trip.name, "In Transit")
		with self.assertRaisesRegex(frappe.ValidationError, "immobilised"):
			self.case.route()

	def test_g_evidence_and_trip_permissions(self):
		doc = self.inspect("Departure", 100)
		inspection = frappe.get_doc(INSPECTION, doc["name"])
		inspection.observations = "Silent edit"
		with self.assertRaises(frappe.ValidationError):
			inspection.save()
		file = frappe.get_doc("File", doc["photos"][0]["name"])
		self.assertEqual(file.is_private, 1)
		file.attached_to_field = "rear"
		with self.assertRaises(frappe.ValidationError):
			file.save()
		with self.assertRaises(frappe.ValidationError):
			file.delete()
		revised = open_inspection(self.trip.name, "Departure", "Add a witnessed clarification")
		validate_inspection(revised["name"], "100", results(), "Administrative clarification")
		original = frappe.get_doc(INSPECTION, doc["name"])
		self.assertFalse(original.observations)
		self.assertEqual(compare(self.trip.name)["before"]["revision"], 2)
		_, other_trip, _ = self.case.route(vehicle=self.case.second_vehicle())
		other_inspection = open_inspection(other_trip.name, "Departure")
		user = fixtures.make("User", email=f"{frappe.generate_hash(length=8)}@example.com",
			first_name="Inspection reader", send_welcome_email=0, roles=[{"role": "Stock User"}])
		frappe.set_user(user.name)
		self.assertTrue(frappe.has_permission(INSPECTION, "read", doc=inspection))
		self.assertEqual(set(frappe.get_list(INSPECTION, filters={"trip": self.trip.name}, pluck="name")),
			{inspection.name, revised["name"]})
		self.assertIn(other_inspection["name"], frappe.get_list(INSPECTION, pluck="name"))
		frappe.set_user("Administrator")
		fixtures.make("User Permission", user=user.name, allow="Transport Trip", for_value=self.trip.name,
			apply_to_all_doctypes=0, applicable_for="Transport Trip")
		frappe.set_user(user.name)
		self.assertEqual(set(frappe.get_list(INSPECTION, pluck="name")), {inspection.name, revised["name"]})
		self.assertTrue(frappe.has_permission("File", "read", doc=file))
		self.assertFalse(frappe.has_permission("File", "write", doc=file))
		self.assertEqual(compare(self.trip.name)["before"]["name"], revised["name"])
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			compare(self.trip.name)
		self.assertFalse(frappe.has_permission(INSPECTION, "read", doc=inspection))
		self.assertFalse(frappe.has_permission("File", "read", doc=file))
