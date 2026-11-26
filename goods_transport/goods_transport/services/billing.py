"""Bilty → Sales Invoice consolidation service.

One customer's delivered / unbilled Bilties are consolidated into a single draft
Sales Invoice with one row per Bilty freight line plus one row per billable
Bilty Charge. Each source Bilty is back-linked via the `bilty_references` child
table on Sales Invoice and marked `Billed`.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import flt, today


@frappe.whitelist(methods=["POST"])
def create_sales_invoice_from_bilties(bilties: str | list[str]) -> str:
	"""Create a draft Sales Invoice consolidating the given Bilties.

	Args:
	    bilties: List (or JSON-encoded list) of Bilty names.

	Returns:
	    Name of the newly created Sales Invoice.
	"""
	names = _parse_names(bilties)
	if not names:
		frappe.throw(_("No Bilties supplied."))

	locked = {name: frappe.get_doc("Bilty", name, for_update=True) for name in sorted(names)}
	docs = [locked[name] for name in names]
	for bilty in docs:
		bilty.check_permission("write")
	_validate_billable(docs)

	head = docs[0]
	si = frappe.new_doc("Sales Invoice")
	si.customer = head.billing_customer or head.customer
	si.company = head.company
	si.currency = head.currency
	si.posting_date = today()
	si.due_date = today()
	si.set("bilty_references", [])
	si.set("items", [])

	# If every consolidated Bilty belongs to the same Trip, propagate the
	# Trip to the SI header so the accounting dimension is set and every
	# resulting GL Entry is tagged.
	trips = {d.transport_trip for d in docs}
	if len(trips) == 1:
		trip = next(iter(trips))
		if trip and si.meta.has_field("transport_trip"):
			si.transport_trip = trip

	for bilty in docs:
		_append_freight_row(si, bilty)
		for charge in bilty.charges or []:
			if not charge.billable_to_customer:
				continue
			_append_charge_row(si, bilty, charge)
		si.append(
			"bilty_references",
			{
				"bilty": bilty.name,
				"bilty_date": bilty.bilty_date,
				"customer": bilty.customer,
				"origin": bilty.origin,
				"destination": bilty.destination,
				"amount": bilty.grand_total,
			},
		)

	si.flags.ignore_permissions = False
	si.insert()

	for bilty in docs:
		frappe.db.set_value("Bilty", bilty.name, {"sales_invoice": si.name, "status": "Billed"})

	for order in {bilty.transport_order for bilty in docs if bilty.transport_order}:
		frappe.get_doc("Transport Order", order).refresh_progress()
	return si.name


# ---------------------------------------------------------------------------


def _parse_names(bilties: str | list[str]) -> list[str]:
	if isinstance(bilties, str):
		try:
			parsed = json.loads(bilties)
		except json.JSONDecodeError:
			parsed = [bilties]
	else:
		parsed = list(bilties)
	# Deduplicate while preserving order.
	seen: set[str] = set()
	out: list[str] = []
	for n in parsed:
		if n and n not in seen:
			seen.add(n)
			out.append(n)
	return out


def _validate_billable(docs: list) -> None:
	billing_customers = {(d.billing_customer or d.customer) for d in docs}
	if len(billing_customers) > 1:
		frappe.throw(
			_("Selected Bilties belong to different billing customers: {0}").format(
				", ".join(sorted(billing_customers))
			)
		)
	companies = {d.company for d in docs}
	if len(companies) > 1:
		frappe.throw(_("Selected Bilties belong to different companies: {0}").format(", ".join(sorted(companies))))
	currencies = {d.currency for d in docs}
	if len(currencies) > 1:
		frappe.throw(_("Selected Bilties have different currencies: {0}").format(", ".join(sorted(currencies))))

	for d in docs:
		if d.docstatus != 1:
			frappe.throw(_("Bilty {0} is not submitted.").format(d.name))
		if d.sales_invoice:
			frappe.throw(
				_("Bilty {0} is already linked to Sales Invoice {1}.").format(d.name, d.sales_invoice)
			)
		validate_bilty_delivery(d)
		if not d.freight_item:
			frappe.throw(_("Bilty {0} has no Freight Item set.").format(d.name))


def validate_bilty_delivery(bilty, *, trip_delivered=False):
	"""Use submitted POD quantities, never the cached Bilty POD status."""
	pod = frappe.db.get_value(
		"Proof of Delivery",
		{"bilty": bilty.name, "docstatus": 1},
		["name", "delivered_quantity"],
		as_dict=True,
	)
	if pod:
		if abs(flt(pod.delivered_quantity) - flt(bilty.total_quantity)) > 1e-9:
			frappe.throw(_("Bilty {0} does not have a full, valid delivery quantity.").format(bilty.name))
		return

	if bilty.pod_required:
		frappe.throw(_("Bilty {0} requires a submitted Proof of Delivery.").format(bilty.name))
	if not trip_delivered and bilty.status != "Delivered":
		trip_status = None
		if bilty.transport_trip:
			trip_status = frappe.db.get_value(
				"Transport Trip", {"name": bilty.transport_trip, "docstatus": 1}, "status"
			)
		if trip_status not in ("Delivered", "Settled", "Closed"):
			frappe.throw(_("Delivery has not been recorded for Bilty {0}.").format(bilty.name))


def validate_invoice_bilty_delivery(invoice, method=None):
	"""Also recheck existing drafts and invoices created through native Desk/API."""
	if invoice.is_return or not invoice.meta.has_field("bilty_references"):
		return
	for reference in invoice.bilty_references or []:
		bilty = frappe.get_doc("Bilty", reference.bilty, for_update=True)
		if bilty.docstatus != 1:
			frappe.throw(_("Bilty {0} is not submitted.").format(bilty.name))
		if (invoice.customer, invoice.company, invoice.currency) != (
			bilty.billing_customer or bilty.customer, bilty.company, bilty.currency,
		):
			frappe.throw(_("Invoice customer, company and currency must match Bilty {0}.").format(bilty.name))
		validate_bilty_delivery(bilty)


def _append_freight_row(si, bilty) -> None:
	description = _("Freight for Bilty {0}: {1} → {2}").format(
		bilty.name, bilty.origin or "", bilty.destination or ""
	)
	row = si.append(
		"items",
		{
			"item_code": bilty.freight_item,
			"description": description,
			"qty": 1,
			"rate": flt(bilty.freight_amount),
		},
	)
	_set_row_trip_dimension(row, bilty.transport_trip)


def _append_charge_row(si, bilty, charge) -> None:
	description = charge.description or charge.item
	if bilty.name:
		description = f"{description} (Bilty {bilty.name})"
	row = si.append(
		"items",
		{
			"item_code": charge.item,
			"description": description,
			"qty": flt(charge.quantity) or 1,
			"rate": flt(charge.rate),
		},
	)
	_set_row_trip_dimension(row, bilty.transport_trip)


def _set_row_trip_dimension(row, trip: str | None) -> None:
	"""Per-row Trip dimension: needed when one SI consolidates Bilties from
	different Trips so each GL line ends up tagged with the right Trip."""
	if trip and row.meta.has_field("transport_trip"):
		row.transport_trip = trip


@frappe.whitelist()
def get_billable_bilties(customer: str | None = None, company: str | None = None) -> list[dict]:
	"""Convenience wrapper used by the Bilty list-view action."""
	from goods_transport.goods_transport.doctype.bilty.bilty import get_unbilled_bilties

	return get_unbilled_bilties(customer=customer, company=company)
