"""Seed master data for the operational journey on a disposable local Desk."""
import json
import os

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.utils import today

from goods_transport.goods_transport.services.fuel import credit
from goods_transport.goods_transport.tests.test_transport_recette import TestTransportRecette, make

os.chdir("/home/frappe/frappe-bench/sites")
site = os.environ["JOURNEY_QA_SITE"]
if not site.endswith(".localhost"):
	raise ValueError("Use a disposable local Frappe site")
frappe.init(site)
frappe.connect()
case = TestTransportRecette()
case.setUpClass()
for group in ("Cargo Items", "Freight Items"):
	if not frappe.db.exists("Item Group", group):
		make("Item Group", item_group_name=group, is_group=int(group == "Cargo Items"))
case.freight.item_group = "Freight Items"
case.freight.save()
cargo = make("Item", item_code=f"{case.label} Cargo", item_group="Cargo Items", stock_uom="Kg")
if not frappe.db.exists("DocType", "Journey QA Toll Rate"):
	frappe.get_doc(dict(doctype="DocType", name="Journey QA Toll Rate", module="Goods Transport",
		custom=1, istable=1, fields=[
			{"fieldname": field, "label": field.replace("_", " ").title(), "fieldtype": kind}
			for field, kind in (("vehicle_class", "Data"), ("amount", "Currency"), ("currency", "Data"),
				("valid_from", "Date"), ("valid_until", "Date"), ("source", "Small Text"))
		])).insert()
create_custom_fields({
	"Vehicle": [
		{"fieldname": name, "label": name.replace("_", " ").title(), "fieldtype": kind}
		for name, kind in (
			("custom_truck_height", "Float"), ("custom_truck_width", "Float"), ("custom_truck_length", "Float"),
			("custom_truck_tare", "Float"), ("custom_truck_ptac", "Float"), ("custom_truck_axles", "Int"),
			("custom_truck_cemac", "Data"), ("custom_fuel_tank_liters", "Float"),
			("custom_fuel_liters_100km", "Float"),
		)
	],
	"Transport Location": [
		{"fieldname": name, "label": name.replace("_", " ").title(), "fieldtype": kind,
			**({"options": "Journey QA Toll Rate"} if kind == "Table" else {})}
		for name, kind in (
			("custom_toll_id", "Data"), ("custom_toll_road", "Data"), ("custom_toll_status", "Data"),
			("custom_toll_precision", "Data"), ("custom_toll_accuracy_m", "Int"),
			("custom_toll_routing", "Data"), ("custom_toll_rates", "Table"),
		)
	],
})
frappe.db.set_value("Vehicle", case.vehicle.name, {
	"custom_truck_height": 3.5, "custom_truck_width": 2.5, "custom_truck_length": 9,
	"custom_truck_tare": 8000, "custom_truck_ptac": 18000, "custom_truck_axles": 2,
	"volume_capacity": 25, "custom_truck_cemac": "P11",
	"custom_fuel_tank_liters": 100, "custom_fuel_liters_100km": 40,
})
frappe.db.set_value("Transport Location", case.origin, {"latitude": -4.27, "longitude": 15.28})
frappe.db.set_value("Transport Location", case.destination, {"latitude": -4.35, "longitude": 15.10})
via = make("Transport Location", location_name=f"{case.label} Intermediate", location_type="Terminal",
	is_active=1, latitude=-4.30, longitude=15.20)
location_types = frappe.get_meta("Transport Location").get_field("location_type").options
if "Péage" not in location_types.splitlines():
	make_property_setter("Transport Location", "location_type", "options", location_types + "\nPéage", "Text")
toll = make("Transport Location", location_name=f"{case.label} Toll", location_type="Péage",
	is_active=1, latitude=-4.30, longitude=15.20, custom_toll_id=case.label,
	custom_toll_precision="Passage cartographié", custom_toll_accuracy_m=100,
	custom_toll_rates=[dict(vehicle_class="3b", currency="XAF", amount=15000, valid_from=today(),
		source="FICTITIOUS JOURNEY QA")])
supplier = make("Supplier", supplier_name=f"{case.label} Fuel Supplier",
	supplier_group=frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"))
user = make("User", email=f"journey-{frappe.generate_hash(length=8)}@example.invalid",
	first_name="Fictitious Journey Station", send_welcome_email=0)
station = make("Fuel Partner Station", company=case.company.name, station_name=f"{case.label} Fuel",
	street_address="FICTITIOUS JOURNEY QA", longitude=15.24, latitude=-4.285, diesel=1,
	supplier=supplier.name, station_user=user.name)
reserve = make("Fuel Contract Reserve", company=case.company.name, station=station.name, fuel_type="Diesel",
	valid_from=today(), contract_reference=case.label)
credit(reserve.name, "80", "FICTITIOUS JOURNEY QA")
make("Trip Inspection Template", __newname=f"{case.label} checklist", company=case.company.name,
	require_inspections=1, controls=[
		{"code": "body", "label_en": "Bodywork", "label_fr": "Carrosserie", "required_control": 1},
	])
expense_type = make("Trip Expense Type", expense_type_name=f"{case.label} Expense", is_active=1)
company = case.company
expense = frappe.db.get_value("Account", {"company": company.name, "root_type": "Expense", "is_group": 0})
advance = frappe.db.get_value("Account", {"company": company.name, "root_type": "Asset", "is_group": 0,
	"account_type": ["in", ["", "Current Asset"]]}, "name")
for app in frappe.get_all("Installed Application", pluck="name"):
	frappe.db.set_value("Installed Application", app, "is_setup_complete", 1)
frappe.clear_cache()
frappe.db.commit()
print(json.dumps(dict(
	company=company.name, customer=case.customer.name, vehicle=case.vehicle.name, origin=case.origin,
	destination=case.destination, via=via.name, freight=case.freight.name, cargo=cargo.name,
	cash=company.default_cash_account, expense_account=expense, advance_account=advance,
	expense_type=expense_type.name, driver=case.driver.name, toll=toll.name, reserve=reserve.name,
)))
