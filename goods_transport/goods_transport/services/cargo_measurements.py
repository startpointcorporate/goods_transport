"""Cargo quantities, weights in kilograms and volumes in cubic metres."""

from math import isclose

import frappe
from frappe import _
from frappe.utils import flt

WEIGHT_BASES = ("Per Kg", "Per Ton")
KG_UNITS = {"kg", "kilogram", "kilogramme"}


def quantity_in_kg(quantity, uom, item=None):
	uom = uom or (frappe.get_cached_value("Item", item, "stock_uom") if item else None)
	if not uom or flt(quantity) <= 0:
		return None
	if uom.casefold() in KG_UNITS:
		return flt(quantity)
	conversions = frappe.get_all("UOM Conversion Factor", filters={"category": ["in", ["Mass", "Weight"]]},
		fields=["from_uom", "to_uom", "value"])
	# ERPNext stores direct factors as destination quantity per source unit.
	factors = {unit: 1 for unit in KG_UNITS}
	while True:
		size = len(factors)
		for row in conversions:
			if row.value <= 0:
				continue
			source, target = row.from_uom.casefold(), row.to_uom.casefold()
			if target in factors:
				factors.setdefault(source, row.value * factors[target])
			if source in factors:
				factors.setdefault(target, factors[source] / row.value)
		if len(factors) == size:
			break
	factor = factors.get(uom.casefold())
	if factor is None:
		factor = {"tonne": 1000, "t": 1000, "gram": 0.001, "gramme": 0.001, "g": 0.001}.get(uom.casefold())
	return flt(quantity) * factor if factor is not None else None


def cargo_weight(quantity, uom, weight, item=None, *, validate=False):
	declared = flt(weight)
	if declared > 0 and not validate:
		return declared
	expected = quantity_in_kg(quantity, uom, item)
	if validate and declared > 0 and expected is not None and not isclose(declared, expected, rel_tol=0.001, abs_tol=0.001):
		frappe.throw(_("Declared weight {0} kg conflicts with the quantity converted to {1} kg.").format(
			declared, round(expected, 3)))
	return declared or expected or 0


def require_billable_weight(basis, weight):
	if basis in WEIGHT_BASES and weight <= 0:
		frappe.throw(_("A positive cargo weight in kilograms is required for weight-based pricing."))


def assigned_measurements(order, quantity, allocation=None):
	ratio = flt(quantity) / flt(order.quantity) if order.quantity else 0
	weight = cargo_weight(order.quantity, order.uom, order.weight, order.commodity)
	allocation_ratio = flt(quantity) / flt(allocation.quantity) if allocation and allocation.quantity else 0
	return (
		flt(allocation.allocated_weight if allocation else None) * allocation_ratio or weight * ratio,
		flt(allocation.allocated_volume if allocation else None) * allocation_ratio or flt(order.cargo_volume) * ratio,
	)
