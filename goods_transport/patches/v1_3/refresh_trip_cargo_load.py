"""Recalculate pre-existing trip loads from issued consignment notes."""

import frappe


def execute():
	for name in frappe.get_all("Bilty", filters={"transport_trip": ["is", "set"], "docstatus": ["<", 2]},
			pluck="transport_trip", distinct=True):
		if frappe.db.exists("Transport Trip", {"name": name, "docstatus": ["<", 2]}):
			frappe.get_doc("Transport Trip", name).refresh_load()
