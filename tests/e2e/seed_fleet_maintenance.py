"""Seed the Desk acceptance fixtures on fleet-maint.localhost."""

import json
import os

import frappe

from goods_transport.goods_transport.doctype.transport_trip.transport_trip import advance_status
from goods_transport.goods_transport.tests.test_transport_recette import TestTransportRecette, make


os.chdir("/home/frappe/frappe-bench/sites")
frappe.init("fleet-maint.localhost")
frappe.connect()

case = TestTransportRecette()
case.setUpClass()
frappe.db.set_value("Vehicle", case.vehicle.name, "last_odometer", 85000)
_, trip, _ = case.route()
advance_status(trip.name, "In Transit")
second_vehicle = case.second_vehicle()
pending_trip = make(
	"Transport Trip", company=case.company.name, vehicle=second_vehicle,
	driver=case.driver.name, origin=case.origin, destination=case.destination,
	freight_item=case.freight.name,
)
maintenance_vehicle = frappe.copy_doc(case.vehicle)
maintenance_vehicle.license_plate = f"{case.label} A"
maintenance_vehicle.insert()
frappe.db.set_value("Vehicle", maintenance_vehicle.name, "last_odometer", 85000)
schedule = make("Vehicle Maintenance Schedule", company=case.company.name, vehicle=maintenance_vehicle.name,
	operation="Oil change", responsible="Administrator", initial_odometer="80000", interval_km=10000,
	advance_km=5000, blocking=1)
_, maintenance_trip, _ = case.route(vehicle=maintenance_vehicle.name)
issue, invoice = case.repair_vouchers()
frappe.db.commit()
print(json.dumps({"trip": trip.name, "pendingTrip": pending_trip.name,
	"vehicle": second_vehicle, "company": case.company.name,
	"costVehicle": case.vehicle.name, "maintenanceTrip": maintenance_trip.name,
	"schedule": schedule.name, "issue": issue.name, "invoice": invoice.name}))
