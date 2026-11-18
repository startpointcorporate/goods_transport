from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	fields = {
		doctype: [{
			"fieldname": "custom_vehicle_immobilisation",
			"fieldtype": "Link",
			"options": "Vehicle Immobilisation",
			"label": "Vehicle Immobilisation",
			"insert_after": insert_after,
			"no_copy": 1,
		}]
		for doctype, insert_after in (
			("Asset Repair", "asset"),
			("Purchase Invoice", "supplier"),
			("Stock Entry", "stock_entry_type"),
			("Payment Entry", "payment_type"),
			("Journal Entry", "voucher_type"),
		)
	}
	for doctype in ("Purchase Invoice", "Journal Entry"):
		fields[doctype].append({
			"fieldname": "custom_fleet_cost_category", "fieldtype": "Select",
			"label": "Fleet Cost Category", "options": "\nParts\nLabor\nExternal Service",
			"insert_after": "custom_vehicle_immobilisation", "no_copy": 1,
			"depends_on": "eval:doc.custom_vehicle_immobilisation",
		})
	fields["Vehicle"] = [{
		"fieldname": "custom_maintenance_asset", "fieldtype": "Link", "options": "Asset",
		"label": "Maintenance Asset", "insert_after": "last_odometer", "unique": 1, "no_copy": 1,
	}]
	create_custom_fields(fields)
