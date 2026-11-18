"""Create tyre acceptance fixtures on the isolated tyres.localhost site."""

import frappe

from goods_transport.goods_transport.services import fleet_tyres
from goods_transport.goods_transport.tests.test_fleet_tyres import TestFleetTyres


def seed():
	if frappe.local.site != "tyres.localhost":
		raise RuntimeError("Use the isolated tyres.localhost site")
	case = TestFleetTyres()
	case.setUpClass()
	first, second = case.stock_tyre("001"), case.stock_tyre("002")
	left = fleet_tyres.add_position(case.vehicle, 1, "Left")
	right = fleet_tyres.add_position(case.vehicle, 1, "Right")
	other = fleet_tyres.add_position(case.other_vehicle, 1, "Left")
	frappe.db.commit()
	return {
		"vehicle": case.vehicle, "otherVehicle": case.other_vehicle,
		"oldTyre": first, "newTyre": second, "left": left, "right": right, "other": other,
		"mountedWarehouse": case.warehouses[1],
	}
