"""Contract fuel balances and single-use dispensing authorizations."""

from decimal import Decimal, InvalidOperation
from secrets import token_urlsafe

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, now_datetime

RESERVE = "Fuel Contract Reserve"
AUTHORIZATION = "Fuel Authorization"
STATION = "Fuel Partner Station"


def quantity(value):
	try:
		liters = Decimal(str(value))
		if liters.is_finite() and 0 < liters <= 999999999 and liters == liters.quantize(Decimal(".001")):
			return liters
	except InvalidOperation:
		pass
	frappe.throw(_("Saisissez un volume positif avec au plus trois décimales."))


def locked_reserve(name):
	return frappe.get_doc(RESERVE, name, for_update=True)


def balances(reserve, *, remaining=0, reserved=0, consumed=0):
	remaining += Decimal(str(reserve.remaining_liters or 0))
	reserved += Decimal(str(reserve.reserved_liters or 0))
	consumed += Decimal(str(reserve.consumed_liters or 0))
	if not 0 <= reserved <= remaining:
		frappe.throw(_("Solde carburant insuffisant."))
	frappe.db.set_value(RESERVE, reserve.name, {
		"remaining_liters": remaining, "reserved_liters": reserved,
		"available_liters": remaining - reserved, "consumed_liters": consumed,
	})


@frappe.whitelist(methods=["POST"])
def credit(reserve_name: str, liters: str, reference: str):
	reserve = locked_reserve(reserve_name)
	reserve.check_permission("create")
	reserve.check_permission("read")
	reference = reference.strip()
	if not reference:
		frappe.throw(_("Renseignez la référence du crédit."))
	amount = quantity(liters)
	if frappe.db.get_value("Fuel Reserve Credit", {"reserve": reserve.name, "reference": reference},
			"name", for_update=True):
		frappe.throw(_("Ce crédit a déjà été enregistré."))
	frappe.get_doc({
		"doctype": "Fuel Reserve Credit", "reserve": reserve.name,
		"company": reserve.company, "liters": amount, "reference": reference,
	}).insert(ignore_permissions=True)
	balances(reserve, remaining=amount)


@frappe.whitelist(methods=["POST"])
def authorize(trip_name: str, reserve_name: str, liters: str, valid_until: str, valid_from: str | None = None):
	trip = frappe.get_doc("Transport Trip", trip_name, for_update=True)
	trip.check_permission("write")
	return issue(trip, locked_reserve(reserve_name), liters, valid_until, valid_from)


def issue(trip, reserve, liters, valid_until, valid_from=None):
	reserve.check_permission("read")
	if trip.company != reserve.company or trip.docstatus == 2 or not trip.vehicle or not trip.driver:
		frappe.throw(_("La mission doit être active et avoir un camion et un chauffeur de la société."))
	station = frappe.get_doc(STATION, reserve.station)
	station.check_permission("read")
	from .fuel_plan import FUEL_TYPES

	if FUEL_TYPES.get(frappe.db.get_value("Vehicle", trip.vehicle, "fuel_type")) != reserve.fuel_type:
		frappe.throw(_("Le carburant doit correspondre au camion."))
	if not station.get(reserve.fuel_type.lower()):
		frappe.throw(_("Ce carburant est indisponible à la station."))
	amount = quantity(liters)
	start = get_datetime(valid_from) if valid_from else now_datetime()
	if not valid_until:
		frappe.throw(_("Renseignez la fin de validité."))
	end = get_datetime(valid_until)
	if end <= max(start, now_datetime()) or start.date() < getdate(reserve.valid_from) or (
		reserve.valid_until and end.date() > getdate(reserve.valid_until)
	):
		frappe.throw(_("La période doit être valide et couverte par le contrat."))
	balances(reserve, reserved=amount)
	authorization = frappe.get_doc({
		"doctype": AUTHORIZATION, "reserve": reserve.name, "company": trip.company,
		"trip": trip.name, "vehicle": trip.vehicle, "driver": trip.driver,
		"station": reserve.station, "fuel_type": reserve.fuel_type,
		"authorized_liters": amount, "valid_from": start, "valid_until": end, "status": "Reserved",
	})
	authorization.insert(ignore_permissions=True, set_name=token_urlsafe(18))
	return authorization.name


def station_permission(authorization):
	if frappe.db.get_value(STATION, authorization.station, "station_user") != frappe.session.user:
		frappe.throw(_("Autorisation de ravitaillement inaccessible."), frappe.PermissionError)


def active(authorization, trip=None):
	trip = trip or frappe.get_doc("Transport Trip", authorization.trip)
	if trip.docstatus == 2 or (trip.driver, trip.vehicle) != (authorization.driver, authorization.vehicle):
		frappe.throw(_("Le chauffeur ou le camion de la mission a changé, ou la mission est annulée."))
	if authorization.status != "Reserved" or not (
		get_datetime(authorization.valid_from) <= now_datetime() < get_datetime(authorization.valid_until)
	):
		frappe.throw(_("Cette autorisation n’est plus utilisable ou n’est pas encore valide."))


@frappe.whitelist()
def verify(code: str):
	code = code.strip()
	if not frappe.db.exists(AUTHORIZATION, code):
		frappe.throw(_("Autorisation de ravitaillement inaccessible."), frappe.PermissionError)
	authorization = frappe.get_doc(AUTHORIZATION, code)
	station_permission(authorization)
	active(authorization)
	return {field: authorization.get(field) for field in (
		"vehicle", "driver", "fuel_type", "authorized_liters", "valid_until",
	)}


def lock_authorization(code):
	reserve_name = frappe.db.get_value(AUTHORIZATION, code, "reserve")
	if not reserve_name:
		frappe.throw(_("Autorisation de ravitaillement inaccessible."), frappe.PermissionError)
	reserve = locked_reserve(reserve_name)
	return reserve, frappe.get_doc(AUTHORIZATION, code, for_update=True)


def close(reserve, authorization, status, delivered=0):
	balances(reserve, remaining=-delivered, reserved=-quantity(authorization.authorized_liters),
		consumed=delivered)
	frappe.db.set_value(AUTHORIZATION, authorization.name, {
		"status": status, "delivered_liters": delivered, "closed_at": now_datetime(),
		"closed_by": frappe.session.user,
	})


@frappe.whitelist(methods=["POST"])
def dispense(code: str, liters: str):
	code = code.strip()
	trip_name = frappe.db.get_value(AUTHORIZATION, code, "trip")
	if not trip_name:
		frappe.throw(_("Autorisation de ravitaillement inaccessible."), frappe.PermissionError)
	trip = frappe.get_doc("Transport Trip", trip_name, for_update=True)
	reserve, authorization = lock_authorization(code)
	station_permission(authorization)
	active(authorization, trip)
	delivered = quantity(liters)
	if delivered > quantity(authorization.authorized_liters):
		frappe.throw(_("Le retrait dépasse le volume autorisé."))
	close(reserve, authorization, "Consumed", delivered)


@frappe.whitelist(methods=["POST"])
def cancel(code: str):
	reserve, authorization = lock_authorization(code)
	frappe.get_doc("Transport Trip", authorization.trip).check_permission("write")
	if authorization.status != "Reserved":
		frappe.throw(_("Cette autorisation est déjà clôturée."))
	close(reserve, authorization, "Cancelled")


def expire():
	for name in frappe.get_all(AUTHORIZATION, filters={
		"status": "Reserved", "valid_until": ["<=", now_datetime()],
	}, pluck="name", order_by="reserve asc, name asc"):
		reserve, authorization = lock_authorization(name)
		if authorization.status == "Reserved" and get_datetime(authorization.valid_until) <= now_datetime():
			close(reserve, authorization, "Expired")


@frappe.whitelist(methods=["POST"])
def attach_expense(code: str, expense_name: str):
	expense = frappe.get_doc("Trip Expense", expense_name, for_update=True)
	expense.check_permission("write")
	_, authorization = lock_authorization(code)
	frappe.get_doc("Transport Trip", authorization.trip).check_permission("write")
	authorization.check_permission("read")
	supplier = frappe.db.get_value(STATION, authorization.station, "supplier")
	existing = frappe.db.get_value(AUTHORIZATION, {"trip_expense": expense.name}, "name", for_update=True)
	if (
		authorization.status != "Consumed" or authorization.trip_expense or existing
		or expense.trip != authorization.trip or expense.supplier != supplier
		or expense.payment_mode != "Third-Party Bill" or expense.docstatus != 1
	):
		frappe.throw(_("Sélectionnez une dépense fournisseur soumise, du même trajet et de la même station."))
	frappe.db.set_value(AUTHORIZATION, authorization.name, "trip_expense", expense.name)
