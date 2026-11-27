"""Seed disposable missions and real Frappe users for the Fleet Driver PWA."""
import json
import os

import frappe
from frappe.utils import add_days, now_datetime, today
from frappe.utils.password import update_password

from goods_transport.goods_transport.services import fuel
from goods_transport.goods_transport.tests.test_transport_recette import TestTransportRecette, make
from goods_transport.goods_transport.tests.test_trip_inspection import setup_template
from goods_transport.setup.install_fleet_driver import execute as install_role

site = os.environ["FLEET_QA_SITE"]
if not site.endswith(".localhost"):
	raise ValueError("Use a disposable localhost site")
password = os.environ["FLEET_QA_PASSWORD"]
os.chdir("sites")
frappe.init(site)
frappe.connect()
install_role()
fixture = {}
for scenario in ("driver", "other", "employee"):
	TestTransportRecette.setUpClass()
	case = TestTransportRecette()
	email = f"fleet-{scenario}-{frappe.generate_hash(length=8)}@example.test"
	roles = [{"role": "Employee"}]
	if scenario != "employee":
		roles.append({"role": "Fleet Driver"})
	make("User", email=email, first_name="Fleet QA", language="fr", send_welcome_email=0,
		user_type="System User", roles=roles)
	update_password(email, password)
	frappe.db.set_value("Employee", case.driver.employee, "user_id", email)
	record = {"user": email}
	if scenario != "employee":
		setup_template(case)
		_, trip, bilty = case.route(quantity=10)
		record.update(trip=trip.name, bilty=bilty.name, vehicle=trip.vehicle)
		if scenario == "driver":
			supplier = make("Supplier", supplier_name=case.label, supplier_type="Company")
			station = make(fuel.STATION, company=case.company.name, station_name=case.label + " Station",
				supplier=supplier.name, street_address="RN1", latitude=-4.26, longitude=15.28,
				diesel=1, station_user="Administrator")
			reserve = make(fuel.RESERVE, company=case.company.name, station=station.name,
				contract_reference=case.label, fuel_type="Diesel", valid_from=today())
			fuel.credit(reserve.name, "100", case.label)
			end = add_days(now_datetime(), 1)
			record["fuel_code"] = fuel.authorize(trip.name, reserve.name, "20", end)
			_, _, second = case.route(quantity=10, vehicle=case.second_vehicle())
			record["other_mission"] = second.transport_trip
	fixture[scenario] = record
frappe.db.commit()
print(json.dumps(fixture))
