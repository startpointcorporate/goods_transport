from frappe import _


def get_data():
	return {
		"fieldname": "trip",
		"non_standard_fieldnames": {
			"Bilty": "transport_trip",
			"Vehicle Immobilisation": "transport_trip",
		},
		"transactions": [
			{"label": _("Operations"), "items": ["Bilty", "Trip Vehicle Inspection", "Vehicle Immobilisation"]},
			{"label": _("Fuel"), "items": ["Fuel Authorization"]},
			{"label": _("Finances"), "items": ["Trip Advance", "Trip Expense", "Trip Settlement", "Driver Trip Earning"]},
		],
	}
