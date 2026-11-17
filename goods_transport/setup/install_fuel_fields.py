from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields({"Vehicle": [
		{"fieldname": "custom_fuel_tank_liters", "label": "Capacité du réservoir (L)", "fieldtype": "Float",
			"insert_after": "fuel_type", "non_negative": 1},
		{"fieldname": "custom_fuel_liters_100km", "label": "Consommation moyenne (L/100 km)", "fieldtype": "Float",
			"insert_after": "custom_fuel_tank_liters", "non_negative": 1},
	]})
	from goods_transport.setup.install_transport_user import _ensure_perm, _ensure_role

	_ensure_role()
	for doctype in ("Fuel Partner Station", "Fuel Contract Reserve", "Fuel Authorization", "Fuel Reserve Credit"):
		_ensure_perm(doctype, ("read",))
