"""Create fictitious inspection missions on the isolated Desk site."""
import json
import os

import frappe

from goods_transport.goods_transport.tests.test_trip_inspection import add_asset, setup_template
from goods_transport.goods_transport.tests.test_transport_recette import TestTransportRecette

os.chdir("/home/frappe/frappe-bench/sites")
site = os.environ.get("INSPECTION_QA_SITE", "inspection-qa.localhost")
if not site.endswith(".localhost"):
	raise ValueError("Use a disposable local Frappe site")
frappe.init(site)
frappe.connect()
case = TestTransportRecette()
case.setUpClass()
setup_template(case)
add_asset(case)
missions = {}
for scenario in "ABCDEF":
	vehicle = case.vehicle
	if scenario != "B":
		vehicle = frappe.copy_doc(case.vehicle)
		vehicle.license_plate = f"Test Inspection {scenario} {frappe.generate_hash(length=5)}"
		vehicle.custom_maintenance_asset = None
		vehicle.insert()
	_, trip, bilty = case.route(vehicle=vehicle.name)
	missions[scenario] = {"trip": trip.name, "bilty": bilty.name, "vehicle": vehicle.name}
frappe.db.commit()
print(json.dumps(missions))
