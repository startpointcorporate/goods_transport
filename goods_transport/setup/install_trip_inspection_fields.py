from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields({"Asset Repair": [{
		"fieldname": "custom_trip_vehicle_inspection", "fieldtype": "Link",
		"options": "Trip Vehicle Inspection", "label": "Trip Vehicle Inspection",
		"insert_after": "custom_vehicle_immobilisation", "read_only": 1, "no_copy": 1,
	}]})
