"""Mission financial control. Ledger amounts are expressed in company currency."""

from collections import defaultdict
from decimal import Decimal
from json import dumps, loads

import frappe
from frappe import _
from frappe.utils import getdate, now

from . import truck_plan

BUCKETS = ("Péages", "Carburant", "Indemnités", "Autres frais")
INPUTS = ("cargo_kg", "cargo_m3", "via", "axle_loads", "departure_liters", "selected_reserves", "confirmed")


def trip_for_finance(name, write=False):
	if not frappe.conf.get("goods_transport_trip_finance"):
		frappe.throw(_("Le contrôle financier est indisponible sur ce site."))
	trip = frappe.get_doc("Transport Trip", name, for_update=write)
	trip.check_permission("write" if write else "read")
	frappe.get_doc("Company", trip.company).check_permission("read")
	return trip


def native_rows(doctype, filters, fields):
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("La lecture de {0} est requise.").format(doctype), frappe.PermissionError)
	return frappe.get_list(doctype, filters=filters, fields=fields, limit_page_length=0)


def converted(amount, source, target, date):
	if amount is None or not source:
		return None
	if source == target or not amount:
		return float(amount)
	from erpnext.setup.utils import get_exchange_rate

	rate = get_exchange_rate(source, target, getdate(date))
	return float(amount) * rate if rate else None


def complete_sum(values):
	values = list(values)
	return None if None in values else sum(values)


def bucket(expense):
	if expense.toll_location or expense.expense_type in ("Toll", "Péage", "Péages"):
		return BUCKETS[0]
	if expense.expense_type == "Fuel":
		return BUCKETS[1]
	if expense.expense_type == "Driver Allowance":
		return BUCKETS[2]
	return BUCKETS[3]


@frappe.whitelist(methods=["POST"])
def save_budget(trip_name: str, route_inputs: str | None = None, extra: str | None = None):
	trip = trip_for_finance(trip_name, write=True)
	if trip.docstatus == 2 or trip.status in ("Settled", "Closed", "Cancelled"):
		frappe.throw(_("Le budget d’une mission clôturée ou annulée est verrouillé."))
	budget = loads(trip.financial_budget or "{}")
	if route_inputs is not None:
		args = loads(route_inputs)
		plan = truck_plan.preview(trip.name, **{key: args[key] for key in INPUTS if key in args})
		fuel = plan["fuel"] or {}
		budget["route"] = {
			"category": plan["class"], "km": plan["truck"]["distance"] / 1000,
			"tolls": plan["tolls"], "currency": fuel.get("currency"),
			"required_liters": fuel.get("required_liters"), "rate": fuel.get("liters_100km"),
			"stops": [{key: stop[key] for key in ("station", "refill_liters", "unit_price")}
				for stop in fuel.get("stops", [])],
			"context": [trip.vehicle, trip.origin, trip.destination, str(trip.trip_date), trip.currency],
		}
	if extra is not None:
		lines = []
		for row in loads(extra):
			category = frappe.get_doc("Trip Expense Type", row["type"])
			category.check_permission("read")
			if category.name in ("Fuel", "Driver Allowance", "Toll", "Péage", "Péages"):
				frappe.throw(_("Ce poste est déjà couvert par la mission ou le plan routier."))
			value = row.get("amount")
			if value not in (None, ""):
				try:
					value = Decimal(str(value))
					if not value.is_finite() or not 0 <= value <= 1e12:
						raise ValueError
				except (ArithmeticError, ValueError):
					frappe.throw(_("Saisissez un montant positif ou laissez-le vide."))
			lines.append({"type": category.name, "amount": float(value) if value not in (None, "") else None})
		budget["extra"] = lines
		budget["extra_currency"] = trip.currency
	budget.update(saved_at=now(), saved_by=frappe.session.user)
	trip.db_set("financial_budget", dumps(budget, ensure_ascii=False))
	return budget


def compare(planned, actual):
	delta = actual - planned if planned is not None and actual is not None else None
	return {
		"planned": planned, "actual": actual, "delta": delta,
		"percent": 100 * delta / planned if delta is not None and planned else None,
		"status": ("Données incomplètes" if delta is None else
			"Imprévu" if not planned and actual else
			"Prévu sans coût enregistré" if planned and not actual else
			"Dépassement" if delta > 0 else ""),
	}


def budget_amounts(trip, budget, currency):
	route = budget.get("route", {})
	if route.get("context") != [trip.vehicle, trip.origin, trip.destination, str(trip.trip_date), trip.currency]:
		route = {}
	stops = route.get("stops", [])
	liters = route.get("required_liters")
	refill = sum(row["refill_liters"] for row in stops)
	prices = {row["unit_price"] for row in stops}
	fuel = complete_sum(row["refill_liters"] * row["unit_price"] if row["unit_price"] is not None else None
		for row in stops)
	# A consistent contract rate can value the part of planned consumption supplied by the tank.
	if not liters or fuel is None or not refill or (abs(liters - refill) > 0.001 and len(prices) != 1):
		fuel = None
	elif len(prices) == 1:
		fuel = liters * next(iter(prices))
	return route, dict(zip(BUCKETS, (
		complete_sum(converted(row["amount"], "XAF", currency, trip.trip_date)
			for row in route["tolls"]) if route else None,
		converted(fuel, route.get("currency"), currency, trip.trip_date),
		converted(trip.driver_allowance or None, trip.currency, currency, trip.trip_date),
		complete_sum([converted(trip.agreed_vehicle_hire or 0, trip.currency, currency, trip.trip_date),
			*(converted(row["amount"], budget.get("extra_currency"), currency, trip.trip_date)
				for row in budget["extra"])]) if "extra" in budget else None,
	), strict=True))


def payments(trip, related_keys, source_keys, direct):
	"""Read bank movements only when every reference belongs to this trip."""
	if not related_keys or not frappe.has_permission("Payment Entry", "read"):
		return [], 0, 0
	from frappe.query_builder import DocType

	ref = DocType("Payment Entry Reference")
	entry = DocType("Payment Entry")
	candidates = (frappe.qb.from_(ref).join(entry).on(ref.parent == entry.name)
		.select(ref.parent).distinct().where(
			(entry.company == trip.company) & (entry.docstatus == 1)
			& ref.reference_doctype.isin(sorted({kind for kind, _ in related_keys}))
			& ref.reference_name.isin(sorted({name for _, name in related_keys}))
		).run(pluck=True))
	if not candidates:
		return [], 0, 0
	documents = native_rows("Payment Entry", {"company": trip.company, "docstatus": 1,
		"name": ["in", candidates]}, ["name", "payment_type", "unallocated_amount"])
	cash_in = cash_out = 0
	for row in documents:
		doc = frappe.get_doc("Payment Entry", row.name)
		doc.check_permission("read")
		references = {(ref.reference_doctype, ref.reference_name) for ref in doc.references}
		if not references & related_keys:
			continue
		row.attributed = row.name in direct
		if row.attributed or row.unallocated_amount or not references <= source_keys:
			continue
		amount, = frappe.db.sql("""
			SELECT COALESCE(SUM(g.debit - g.credit), 0)
			FROM `tabGL Entry` g
			JOIN `tabAccount` a ON a.name = g.account AND a.company = g.company
			WHERE g.company = %s AND g.voucher_type = 'Payment Entry' AND g.voucher_no = %s
				AND g.is_cancelled = 0 AND a.account_type IN ('Cash', 'Bank')
				AND COALESCE(g.transport_trip, '') = ''
		""", (trip.company, row.name))[0]
		if frappe.db.exists("GL Entry", {"company": trip.company, "voucher_type": "Payment Entry",
			"voucher_no": row.name, "is_cancelled": 0, "transport_trip": ["not in", ["", trip.name]]}):
			continue
		row.attributed = bool(amount)
		cash_in += max(float(amount), 0)
		cash_out += max(-float(amount), 0)
	return [row for row in documents if row.attributed is not None], cash_in, cash_out


def ledger(trip):
	return frappe.db.sql("""
		SELECT g.voucher_type, g.voucher_no, a.root_type, a.account_type,
			SUM(g.debit - g.credit) AS debit
		FROM `tabGL Entry` g
		JOIN `tabAccount` a ON a.name = g.account AND a.company = g.company
		WHERE g.company = %(company)s AND g.transport_trip = %(trip)s AND g.is_cancelled = 0
		GROUP BY g.voucher_type, g.voucher_no, a.root_type, a.account_type
	""", {"company": trip.company, "trip": trip.name}, as_dict=True)


@frappe.whitelist()
def overview(trip_name: str):
	trip = trip_for_finance(trip_name)
	# Ledger detail requires full accounting access. No source with row-level
	# restrictions is substituted by an unrestricted lookup for document details.
	if not frappe.has_permission("GL Entry", "report"):
		frappe.throw(_("L’accès au rapport Grand livre est requis."), frappe.PermissionError)
	currency = frappe.get_cached_value("Company", trip.company, "default_currency")
	scope = {"trip": trip.name, "company": trip.company, "docstatus": ["<", 2]}
	expenses = native_rows("Trip Expense", scope, [
		"name", "docstatus", "expense_type", "toll_location", "amount", "currency", "payment_mode",
		"receipt", "journal_entry", "purchase_invoice", "expense_date",
	])
	advances = native_rows("Trip Advance", scope, ["name", "amount", "currency", "status", "docstatus", "receipt"])
	settlements = native_rows("Trip Settlement", scope, ["name", "docstatus", "outstanding_from_driver", "currency"])
	withdrawals = native_rows("Fuel Authorization", {
		"trip": trip.name, "company": trip.company, "status": "Consumed",
	}, ["station", "vehicle", "driver", "delivered_liters", "closed_at", "trip_expense",
		"reserve"])
	reserve_names = sorted({row.reserve for row in withdrawals})
	reserves = {row.name: row for row in native_rows("Fuel Contract Reserve", {
		"name": ["in", reserve_names], "company": trip.company,
	}, ["name", "price_currency", "price_per_liter"])} if reserve_names else {}
	budget = loads(trip.financial_budget or "{}")
	route, planned = budget_amounts(trip, budget, currency)
	postings = ledger(trip)
	expense_by_voucher = {(kind, row[field]): row for row in expenses if row.docstatus == 1
		for kind, field in (("Journal Entry", "journal_entry"), ("Purchase Invoice", "purchase_invoice")) if row[field]}
	actual = dict.fromkeys(BUCKETS, 0.0)
	posted_costs = defaultdict(float)
	posted_cash = defaultdict(float)
	revenue = income_rows = cash_in = cash_out = 0
	for row in postings:
		key = (row.voucher_type, row.voucher_no)
		amount = float(row.debit)
		if row.root_type == "Income":
			revenue -= amount
			income_rows += 1
		if row.root_type == "Expense":
			posted_costs[key] += amount
			expense = expense_by_voucher.get(key)
			actual[bucket(expense) if expense else BUCKETS[3]] += amount
		if row.account_type in ("Cash", "Bank"):
			cash_in += max(amount, 0)
			cash_out += max(-amount, 0)
			posted_cash[key] += max(-amount, 0)

	missing = set()
	pending = []
	by_name = {row.name: row for row in expenses}
	for row in expenses:
		posted = ("Journal Entry", row.journal_entry) in posted_costs or (
			"Purchase Invoice", row.purchase_invoice) in posted_costs
		if row.docstatus == 0 or not posted:
			missing.add(bucket(row))
		if row.docstatus == 0 or not row.receipt:
			pending.append(row.name)
		row.posted = posted
		row.receipt = bool(row.receipt)
		row.cost = posted_costs.get(("Journal Entry", row.journal_entry),
			posted_costs.get(("Purchase Invoice", row.purchase_invoice))) if posted else None
	linked = {row.trip_expense for row in withdrawals if row.trip_expense}
	ambiguous_fuel = bool(posted_costs.keys() - expense_by_voucher.keys()) or any(
		row.posted and bucket(row) == BUCKETS[1] and row.name not in linked for row in expenses
	)
	for row in withdrawals:
		# Contract terms are immutable once the reserve is inserted.
		reserve = reserves.get(row.reserve)
		row.unit_price = reserve.price_per_liter if reserve and reserve.price_currency else None
		row.price_currency = reserve.price_currency if reserve else None
		row.value = converted(row.unit_price * row.delivered_liters if row.unit_price is not None else None,
			row.price_currency, currency, row.closed_at)
		expense = by_name.get(row.trip_expense)
		if expense and expense.docstatus == 1 and expense.posted:
			row.basis = _("Déjà imputé via Trip Expense")
			if bucket(expense) != BUCKETS[1]:
				key = ("Purchase Invoice", expense.purchase_invoice)
				value = posted_costs.get(key, 0)
				actual[bucket(expense)] -= value
				actual[BUCKETS[1]] += value
		elif row.value is not None and not row.trip_expense and not ambiguous_fuel:
			row.basis = _("Valorisation opérationnelle du retrait")
			actual[BUCKETS[1]] += row.value
		else:
			missing.add(BUCKETS[1])
			row.basis = _("Valorisation ou rapprochement incomplet")
	known_actual = sum(actual.values())
	ledger_cost = sum(posted_costs.values())
	for name in missing:
		actual[name] = None
	total_actual = complete_sum(actual.values())
	revenue = revenue if income_rows else None
	margin = revenue - known_actual if revenue is not None else None
	invoice_names = {row.voucher_no for row in postings if row.voucher_type == "Sales Invoice"}
	purchase_names = {row.voucher_no for row in postings if row.voucher_type == "Purchase Invoice"}
	invoices = native_rows("Sales Invoice", {"name": ["in", sorted(invoice_names)], "company": trip.company,
		"docstatus": 1}, ["name", "base_grand_total", "currency", "outstanding_amount"]) if invoice_names else []
	related_keys = {("Sales Invoice", row.name) for row in invoices} | {
		("Purchase Invoice", name) for name in purchase_names}
	source_keys = set()
	for kind, name in sorted(related_keys):
		trips = {row[0] for row in frappe.db.sql("""
			SELECT DISTINCT g.transport_trip FROM `tabGL Entry` g
			JOIN `tabAccount` a ON a.name = g.account AND a.company = g.company
			WHERE g.company = %s AND g.voucher_type = %s AND g.voucher_no = %s
				AND g.is_cancelled = 0 AND a.root_type IN ('Income', 'Expense')
		""", (trip.company, kind, name))}
		if trips == {trip.name}:
			source_keys.add((kind, name))
	for invoice in invoices:
		if ("Sales Invoice", invoice.name) not in source_keys:
			invoice.base_grand_total = None
	direct = {row.voucher_no for row in postings if row.voucher_type == "Payment Entry"
		and row.account_type in ("Cash", "Bank")}
	payment_docs, extra_in, extra_out = payments(trip, related_keys, source_keys, direct)
	toll_names = {row["name"] for row in route.get("tolls", [])}
	tolls = []
	for name in sorted(toll_names | {row.toll_location for row in expenses if row.toll_location}):
		estimate = next((row for row in route.get("tolls", []) if row["name"] == name), None)
		recorded = [row for row in expenses if row.toll_location == name]
		tolls.append({"name": name, "amount": estimate["amount"] if estimate else None,
			"actual": complete_sum(row.cost for row in recorded) if recorded else None,
			"paid": complete_sum(
				posted_cash.get(("Journal Entry", row.journal_entry))
				if row.payment_mode == "Company Cash/Bank" else None for row in recorded
			) if recorded else None,
			"status": _("Imprévu") if not estimate else _("Tarif indisponible") if estimate["amount"] is None
				else _("À rapprocher") if not recorded else _("Coût enregistré")})
	return {
		"currency": currency, "budget": budget, "route": route,
		"rows": [{"category": name, **compare(planned[name], actual[name])} for name in BUCKETS],
		"total": compare(complete_sum(planned.values()), total_actual),
		"billed": complete_sum(row.base_grand_total for row in invoices) if invoices and len(invoices) == len(invoice_names) else None,
		"recognized": revenue, "cash_in": cash_in + extra_in, "cash_out": cash_out + extra_out,
		"payments": payment_docs,
		"known_cost": known_actual, "ledger_cost": ledger_cost,
		"operational_fuel_cost": known_actual - ledger_cost, "margin": margin, "margin_rate": 100 * margin / revenue if margin is not None and revenue else None,
		"provisional": trip.status != "Closed" or bool(missing or pending) or revenue is None,
		"operational_status": trip.status,
		"tolls": tolls, "expenses": expenses, "withdrawals": withdrawals, "advances": advances,
		"settlements": settlements, "invoices": invoices, "pending": pending,
	}
