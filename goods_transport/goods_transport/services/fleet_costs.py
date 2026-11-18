from collections import defaultdict

import frappe
from frappe import _


def validate_repair_voucher(doc, method=None):
	link = doc.get("custom_vehicle_immobilisation")
	if not link:
		return
	incident = frappe.db.get_value(
		"Vehicle Immobilisation", link, ["company", "transport_trip", "vehicle"], as_dict=True,
	)
	if not incident or incident.company != doc.company:
		frappe.throw(_("The maintenance voucher and immobilisation must belong to the same company."))
	if doc.get("transport_trip") and doc.transport_trip != incident.transport_trip:
		frappe.throw(_("The maintenance voucher must reference the immobilisation's trip."))
	if doc.doctype == "Asset Repair":
		if doc.asset != frappe.db.get_value("Vehicle", incident.vehicle, "custom_maintenance_asset"):
			frappe.throw(_("The repair must use the asset linked to the vehicle."))
		for row in doc.invoices:
			linked = frappe.db.get_value("Purchase Invoice", row.purchase_invoice, "custom_vehicle_immobilisation")
			if linked != link:
				frappe.throw(_("Tag this repair's purchase invoice with the same immobilisation."))
	elif doc.doctype == "Stock Entry":
		if doc.purpose != "Material Issue":
			frappe.throw(_("Only material issues can be attributed to maintenance consumption."))
	elif doc.doctype == "Payment Entry":
		if doc.payment_type != "Pay" or not doc.references:
			frappe.throw(_("Link the maintenance payment to its maintenance purchase invoices."))
		for row in doc.references:
			if row.reference_doctype != "Purchase Invoice" or frappe.db.get_value(
				"Purchase Invoice", row.reference_name, "custom_vehicle_immobilisation",
			) != link:
				frappe.throw(_("All allocations on a maintenance payment must belong to the same immobilisation."))
	elif not doc.get("custom_fleet_cost_category"):
		frappe.throw(_("Select a maintenance cost category."))


def vehicle_costs(company, authorised_vehicles, from_date, to_date):
	"""Aggregate each submitted accounting voucher once using its actual GL entries."""
	if not authorised_vehicles:
		return {}
	if not {"Accounts Manager", "Accounts User", "System Manager"}.intersection(frappe.get_roles()):
		frappe.throw(_("Accounting access is required to view fleet maintenance costs."), frappe.PermissionError)
	params = {"company": company, "vehicles": tuple(authorised_vehicles), "start": from_date, "end": to_date}
	totals = defaultdict(lambda: defaultdict(float))
	sources = {
		"Purchase Invoice": ("voucher.custom_vehicle_immobilisation",
			"voucher.custom_fleet_cost_category", ""),
		"Journal Entry": ("voucher.custom_vehicle_immobilisation",
			"voucher.custom_fleet_cost_category", ""),
		"Stock Entry": ("COALESCE(NULLIF(voucher.custom_vehicle_immobilisation, ''), repair.custom_vehicle_immobilisation)",
			"'Parts'", "LEFT JOIN `tabAsset Repair` repair ON repair.name = voucher.asset_repair AND repair.docstatus = 1"),
		"Asset Repair": ("voucher.custom_vehicle_immobilisation", "'External Service'", ""),
		"Payment Entry": ("voucher.custom_vehicle_immobilisation", "''", ""),
	}
	for doctype, (incident, category, additional_join) in sources.items():
		entries = frappe.db.sql(
			f"""
			SELECT stop.vehicle, {category} AS category,
			       SUM(IF(account.root_type = 'Expense', gl.debit - gl.credit, 0)) AS charges,
			       SUM(IF(account.account_type = 'Fixed Asset', gl.debit - gl.credit, 0)) AS investment,
			       SUM(IF(account.account_type IN ('Cash', 'Bank'), gl.credit - gl.debit, 0)) AS cash_out
			FROM `tabGL Entry` gl
			INNER JOIN `tabAccount` account ON account.name = gl.account
			INNER JOIN `tab{doctype}` voucher ON voucher.name = gl.voucher_no AND voucher.docstatus = 1
			{additional_join}
			INNER JOIN `tabVehicle Immobilisation` stop ON stop.name = {incident}
			WHERE gl.voucher_type = %(doctype)s AND gl.is_cancelled = 0 AND gl.company = %(company)s
			  AND stop.vehicle IN %(vehicles)s AND stop.company = %(company)s
			  AND gl.posting_date BETWEEN %(start)s AND %(end)s
			GROUP BY stop.vehicle, category
			""",
			{**params, "doctype": doctype}, as_dict=True,
		)
		for row in entries:
			totals[row.vehicle][row.category] += float(row.charges)
			totals[row.vehicle]["charges"] += float(row.charges)
			totals[row.vehicle]["investment"] += float(row.investment)
			totals[row.vehicle]["cash_out"] += float(row.cash_out)
	return totals
