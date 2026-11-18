"""Manage tyre fitment and preserve every completed mounting interval."""

from contextlib import contextmanager
from hashlib import sha256

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, get_datetime, now_datetime

from goods_transport.goods_transport.services.fleet_odometer import lock_vehicle, reading


@contextmanager
def managed_write():
	previous = frappe.flags.fleet_tyres_write
	frappe.flags.fleet_tyres_write = True
	try:
		yield
	finally:
		frappe.flags.fleet_tyres_write = previous


class ManagedTyreDocument(Document):
	def validate(self):
		self.require_managed_write()

	def db_set(self, *args, **kwargs):
		self.require_managed_write()
		return super().db_set(*args, **kwargs)

	@staticmethod
	def require_managed_write():
		if not frappe.flags.fleet_tyres_write:
			frappe.throw(_("Use the Fleet Tyres operations to change this record."), frappe.PermissionError)

	def on_trash(self):
		frappe.throw(_("Fleet Tyres records are retained for audit."), frappe.PermissionError)


def identity(*parts):
	return sha256(frappe.as_json(parts).encode()).hexdigest()


def authorised_vehicle(vehicle, permission):
	frappe.get_doc("Vehicle", vehicle).check_permission(permission)
	if permission == "write":
		return lock_vehicle(vehicle)
	return frappe.db.get_value("Vehicle", vehicle, ["company", "last_odometer"], as_dict=True)


def latest_event(filters, operations, lock=True):
	return frappe.db.get_value(
		"Fleet Tyre Event", {**filters, "operation": ["in", operations]},
		["recorded_at", "odometer", "vehicle", "position", "operation", "creation"], order_by="recorded_at desc, creation desc",
		as_dict=True, for_update=lock,
	)


@frappe.whitelist(methods=["POST"])
def add_position(vehicle, axle, label):
	authorised_vehicle(vehicle, "write")
	axle = reading(axle)
	label = label.strip()
	if not axle or not label:
		frappe.throw(_("Enter a positive axle number and a position label."))
	with managed_write():
		position = frappe.new_doc("Fleet Tyre Position")
		position.update({"vehicle": vehicle, "axle": axle, "label": label})
		position.insert(ignore_permissions=True, set_name=identity(vehicle, axle, label.casefold()))
	return position.name


@frappe.whitelist(methods=["POST"])
def register(vehicle, reference, serial_no, dimension, manufacturer_serial=None):
	current = authorised_vehicle(vehicle, "write")
	serial = frappe.get_doc("Serial No", serial_no)
	serial.check_permission("read")
	if serial.company != current.company or not serial.warehouse:
		frappe.throw(_("Choose an ERPNext serial number held in stock by this company."))
	reference = reference.strip()
	dimension = dimension.strip()
	if not reference or not dimension:
		frappe.throw(_("Enter a reference and a dimension."))
	with managed_write():
		tyre = frappe.new_doc("Fleet Tyre")
		tyre.update({
			"company": current.company, "reference": reference, "serial_no": serial_no,
			"dimension": dimension, "manufacturer_serial": manufacturer_serial, "state": "Available",
		})
		tyre.insert(ignore_permissions=True, set_name=identity(current.company, reference.casefold()))
	return tyre.name


def position_for(vehicle, name):
	position = frappe.get_doc("Fleet Tyre Position", name, for_update=True)
	if position.vehicle != vehicle:
		frappe.throw(_("The position belongs to another vehicle."))
	return position


def mileage_at_operation(vehicle, current, odometer, recorded_at):
	odometer = reading(odometer)
	recorded_at = (get_datetime(recorded_at) if recorded_at else now_datetime()).replace(microsecond=0)
	previous = latest_event({"vehicle": vehicle}, ("Mount", "Remove", "Retire"))
	if odometer is None or odometer < (current.last_odometer or 0):
		frappe.throw(_("Enter an actual odometer at least as high as the last verified reading."))
	if recorded_at > now_datetime():
		frappe.throw(_("The operation date cannot be in the future."))
	if previous and (odometer < previous.odometer or recorded_at < previous.recorded_at.replace(microsecond=0)):
		frappe.throw(_("The operation cannot precede an existing tyre operation."))
	return odometer, recorded_at


def append_event(tyre, position, operation, odometer, recorded_at, **details):
	frappe.get_doc({
		"doctype": "Fleet Tyre Event", "tyre": tyre.name, "vehicle": position.vehicle,
		"position": position.name, "operation": operation, "odometer": odometer,
		"recorded_at": recorded_at.replace(microsecond=0), **details,
	}).insert(ignore_permissions=True)


def get_tyres_for_update(*names):
	return {name: frappe.get_doc("Fleet Tyre", name, for_update=True) for name in sorted(set(names))}


def move_stock(tyre, warehouse, issue=False):
	serial = frappe.get_doc("Serial No", tyre.serial_no, for_update=True)
	if not serial.warehouse or serial.company != tyre.company:
		frappe.throw(_("The serial number is no longer in company stock."))
	if not issue and (not warehouse or warehouse == serial.warehouse):
		frappe.throw(_("Choose a different destination warehouse."))
	entry = frappe.get_doc({
		"doctype": "Stock Entry", "company": tyre.company,
		"stock_entry_type": "Material Issue" if issue else "Material Transfer",
		"items": [{
			"item_code": serial.item_code, "qty": 1, "s_warehouse": serial.warehouse,
			"t_warehouse": warehouse if not issue else None,
			"use_serial_batch_fields": 1, "serial_no": serial.name,
		}],
	})
	entry.insert()
	entry.submit()
	return entry.name


def mount(tyre, position, current, odometer, recorded_at, stock_entry=None):
	if tyre.company != current.company or tyre.state not in ("Available", "Removed"):
		frappe.throw(_("The tyre is unavailable for mounting."))
	if position.active_tyre:
		frappe.throw(_("The position already has a mounted tyre."))
	previous = latest_event({"tyre": tyre.name}, ("Mount", "Remove", "Retire"))
	if previous and recorded_at < previous.recorded_at.replace(microsecond=0):
		frappe.throw(_("Mounting cannot precede the previous tyre operation."))
	append_event(tyre, position, "Mount", odometer, recorded_at, stock_entry=stock_entry)
	tyre.state = "Mounted"
	tyre.save(ignore_permissions=True)
	position.active_tyre = tyre.name
	position.save(ignore_permissions=True)


def remove(tyre, position, current, odometer, recorded_at, retired, notes, stock_entry=None):
	if tyre.state != "Mounted" or tyre.company != current.company:
		frappe.throw(_("The position has no mounted tyre in this company."))
	start = latest_event({"tyre": tyre.name}, ("Mount",))
	if not start or start.position != position.name or odometer < start.odometer:
		frappe.throw(_("The removal reading precedes mounting."))
	append_event(
		tyre, position, "Retire" if retired else "Remove", odometer, recorded_at,
		distance=odometer - start.odometer, notes=notes, stock_entry=stock_entry,
	)
	tyre.state = "Retired" if retired else "Removed"
	tyre.save(ignore_permissions=True)
	position.active_tyre = None
	position.save(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def fit(vehicle, position, odometer, operation, tyre=None, destination=None, notes=None, recorded_at=None, warehouse=None):
	current = authorised_vehicle(vehicle, "write")
	odometer, recorded_at = mileage_at_operation(vehicle, current, odometer, recorded_at)
	position = position_for(vehicle, position)
	if operation not in ("Mount", "Remove", "Replace", "Rotate"):
		frappe.throw(_("Choose a tyre operation."))
	if operation == "Replace" and not (notes or "").strip():
		frappe.throw(_("Enter the replacement reason."))
	if operation in ("Mount", "Replace") and not tyre:
		frappe.throw(_("Choose a tyre."))
	if operation != "Mount" and not position.active_tyre:
		frappe.throw(_("Choose a position with a mounted tyre."))
	if operation == "Rotate":
		destination = position_for(vehicle, destination)
		if destination.active_tyre or destination.name == position.name:
			frappe.throw(_("Choose another, empty position."))
	if operation == "Replace" and tyre == position.active_tyre:
		frappe.throw(_("Choose a different replacement tyre."))
	tyres = get_tyres_for_update(*(name for name in (tyre, position.active_tyre) if name))
	with managed_write():
		if operation == "Mount":
			mount_candidate(tyres[tyre], position, current, odometer, recorded_at, warehouse)
			return
		active = tyres[position.active_tyre]
		active_warehouse = frappe.db.get_value("Serial No", active.serial_no, "warehouse")
		stock_entry = None
		if operation != "Rotate":
			stock_entry = move_stock(active, warehouse, issue=operation == "Replace" and not warehouse)
		remove(active, position, current, odometer, recorded_at, operation == "Replace", notes, stock_entry)
		if operation == "Replace":
			mount_candidate(tyres[tyre], position, current, odometer, recorded_at, active_warehouse)
		elif operation == "Rotate":
			mount(active, destination, current, odometer, recorded_at)


def mount_candidate(tyre, position, current, odometer, recorded_at, warehouse):
	if tyre.company != current.company or tyre.state not in ("Available", "Removed") or position.active_tyre:
		frappe.throw(_("Choose an available tyre and an empty position."))
	if tyre.state == "Removed":
		removed = latest_event({"tyre": tyre.name}, ("Remove",))
		control = latest_event({"tyre": tyre.name, "inspection_type": "Return to Service"}, ("Inspection",))
		if not control or control.creation <= removed.creation or control.recorded_at > recorded_at:
			frappe.throw(_("A removed tyre requires a recorded return-to-service inspection."))
	stock_entry = move_stock(tyre, warehouse)
	mount(tyre, position, current, odometer, recorded_at, stock_entry)


def validate_completed_reading(vehicle, odometer):
	operation = latest_event({"vehicle": vehicle}, ("Mount", "Remove", "Retire"))
	if operation and operation.odometer > odometer:
		frappe.throw(_("The closing odometer is below a recorded tyre operation."))


def tyre_history(name):
	return frappe.get_all(
		"Fleet Tyre Event", filters={"tyre": name}, order_by="recorded_at asc, creation asc",
		fields=["operation", "vehicle", "position", "recorded_at", "odometer", "distance", "notes",
				"next_date", "next_odometer", "stock_entry", "inspection_type", "interval_days", "interval_km"],
	)


def known_odometer(vehicle, verified):
	operation = latest_event({"vehicle": vehicle}, ("Mount", "Remove", "Retire"), lock=False)
	return max(verified or 0, operation.odometer if operation else 0)


@frappe.whitelist()
def overview(vehicle):
	current = authorised_vehicle(vehicle, "read")
	odometer = known_odometer(vehicle, current.last_odometer)
	positions = frappe.get_all(
		"Fleet Tyre Position", filters={"vehicle": vehicle},
		fields=["name", "axle", "label", "active_tyre"], order_by="axle asc, label asc",
	)
	for position in positions:
		if not position.active_tyre:
			continue
		position.tyre = frappe.db.get_value("Fleet Tyre", position.active_tyre, ["reference", "state"], as_dict=True)
		events = tyre_history(position.active_tyre)
		mounts = [event for event in events if event.operation == "Mount"]
		position.installed_at = mounts[-1].recorded_at
		position.first_installed_at = mounts[0].recorded_at
		serial_no, dimension = frappe.db.get_value("Fleet Tyre", position.active_tyre, ["serial_no", "dimension"])
		position.tyre.serial_no = serial_no
		position.tyre.dimension = dimension
		item = frappe.db.get_value("Serial No", serial_no, "item_code")
		position.tyre.item = frappe.db.get_value("Item", item, ["item_name", "brand"], as_dict=True)
		position.distance = mounted_mileage(events, mounts[-1], odometer)
		inspections = latest_inspections(events)
		position.inspection_due = any(
			(inspection.next_date and inspection.next_date <= now_datetime().date())
			or (inspection.next_odometer and inspection.next_odometer <= position.distance)
			for inspection in inspections.values()
		)
	historic_ids = set(frappe.get_all("Fleet Tyre Event", filters={"vehicle": vehicle}, pluck="tyre"))
	historic_ids.difference_update(position.active_tyre for position in positions)
	historic = frappe.get_all(
		"Fleet Tyre", filters={"name": ["in", sorted(historic_ids)]},
		fields=["name", "reference", "state"], order_by="reference asc",
	) if historic_ids else []
	for tyre in historic:
		tyre.awaiting_disposal = tyre.state == "Retired" and bool(frappe.db.get_value(
			"Serial No", frappe.db.get_value("Fleet Tyre", tyre.name, "serial_no"), "warehouse",
		))
	return {
		"positions": positions, "odometer": odometer, "historic": historic,
		"operation_time": now_datetime().strftime("%Y-%m-%d %H:%M:%S"),
	}


@frappe.whitelist()
def history(vehicle, tyre):
	current = authorised_vehicle(vehicle, "read")
	if frappe.db.get_value("Fleet Tyre", tyre, "company") != current.company:
		frappe.throw(_("The tyre belongs to another company."), frappe.PermissionError)
	return [event for event in tyre_history(tyre) if event.vehicle == vehicle]


def latest_inspections(events):
	return {event.inspection_type: event for event in events if event.operation == "Inspection"}


def mounted_mileage(events, start, odometer):
	return sum(event.distance or 0 for event in events) + max(0, odometer - start.odometer)


@frappe.whitelist(methods=["POST"])
def inspect(vehicle, position, notes, inspection_type="Visual Inspection", interval_days=None, interval_km=None):
	current = authorised_vehicle(vehicle, "write")
	position = position_for(vehicle, position)
	if not position.active_tyre or not (notes or "").strip():
		frappe.throw(_("Choose a mounted tyre and enter inspection observations."))
	if inspection_type not in ("Pressure Check", "Visual Inspection", "Tread Inspection", "Repair", "Puncture"):
		frappe.throw(_("Choose a valid intervention type."))
	tyre = frappe.get_doc("Fleet Tyre", position.active_tyre, for_update=True)
	events = tyre_history(tyre.name)
	last = latest_inspections(events).get(inspection_type)
	days = reading(interval_days) if interval_days not in (None, "") else (last.interval_days if last else 0)
	distance = reading(interval_km) if interval_km not in (None, "") else (last.interval_km if last else 0)
	odometer = known_odometer(vehicle, current.last_odometer)
	start = next(event for event in reversed(events) if event.operation == "Mount")
	now = now_datetime()
	with managed_write():
		append_event(
			tyre, position, "Inspection", odometer, now, notes=notes, inspection_type=inspection_type,
			interval_days=days, interval_km=distance,
			next_date=add_days(now.date(), days) if days else None,
			next_odometer=mounted_mileage(events, start, odometer) + distance if distance else None,
		)


def prevent_stock_cancellation(entry, method=None):
	if frappe.db.exists("Fleet Tyre Event", {"stock_entry": entry.name}):
		frappe.throw(_("This stock entry belongs to the tyre operation history."))


@frappe.whitelist()
def available_tyres(vehicle):
	current = authorised_vehicle(vehicle, "read")
	candidates = frappe.get_all("Fleet Tyre", filters={
		"company": current.company, "state": ["in", ["Available", "Removed"]],
	}, fields=["name", "reference", "state"], order_by="reference asc")
	available = []
	for tyre in candidates:
		if tyre.state == "Available":
			available.append(tyre)
			continue
		events = tyre_history(tyre.name)
		last_removal = max(index for index, event in enumerate(events) if event.operation == "Remove")
		if any(event.inspection_type == "Return to Service" for event in events[last_removal + 1:]):
			available.append(tyre)
	return available


@frappe.whitelist()
def costs(vehicle):
	current = authorised_vehicle(vehicle, "read")
	require_accounts()
	tyre_ids = set(frappe.get_all(
		"Fleet Tyre Event", filters={"vehicle": vehicle, "operation": "Mount"}, pluck="tyre",
	))
	rows = []
	for tyre_id in sorted(tyre_ids):
		tyre = frappe.get_doc("Fleet Tyre", tyre_id)
		events = tyre_history(tyre_id)
		distances = {}
		for event in events:
			distances[event.vehicle] = distances.get(event.vehicle, 0) + (event.distance or 0)
		if tyre.state == "Mounted":
			start = next(event for event in reversed(events) if event.operation == "Mount")
			end = known_odometer(start.vehicle, frappe.db.get_value("Vehicle", start.vehicle, "last_odometer"))
			distances[start.vehicle] += max(0, end - start.odometer)
		first_receipt = frappe.db.sql("""
			SELECT DATE(bundle.posting_datetime) AS posting_date, bundle.voucher_type, bundle.voucher_no, entry.incoming_rate
			FROM `tabSerial and Batch Bundle` bundle
			JOIN `tabSerial and Batch Entry` entry ON entry.parent = bundle.name
			LEFT JOIN `tabStock Entry` stock ON bundle.voucher_type = 'Stock Entry'
				AND stock.name = bundle.voucher_no AND stock.docstatus = 1
			WHERE entry.serial_no = %(serial)s AND bundle.company = %(company)s
				AND bundle.docstatus = 1 AND bundle.is_cancelled = 0
				AND bundle.type_of_transaction = 'Inward'
				AND (bundle.voucher_type = 'Purchase Receipt' OR stock.purpose = 'Material Receipt')
			ORDER BY bundle.posting_datetime, bundle.creation
			LIMIT 1
		""", {"serial": tyre.serial_no, "company": tyre.company}, as_dict=True)
		receipt = first_receipt[0] if first_receipt else None
		expenses = frappe.db.sql("""
			SELECT allocation.vehicle, allocation.category, allocation.invoice, line.base_net_amount
			FROM `tabFleet Tyre Expense` allocation
			JOIN `tabPurchase Invoice` invoice ON invoice.name = allocation.invoice AND invoice.docstatus = 1
			JOIN `tabPurchase Invoice Item` line ON line.name = allocation.invoice_item
				AND line.parent = invoice.name
			WHERE allocation.tyre = %s
		""", tyre_id, as_dict=True)
		service_total = sum(expense.base_net_amount for expense in expenses)
		vehicle_service_cost = sum(e.base_net_amount for e in expenses if e.vehicle == vehicle)
		total = sum(distances.values())
		vehicle_distance = distances[vehicle]
		retirement = next((e for e in events if e.operation == "Retire" and e.vehicle == vehicle), None)
		first_mount = next(e for e in events if e.operation == "Mount")
		rows.append({
			"tyre": tyre.name, "reference": tyre.reference, "vehicle_distance": vehicle_distance,
			"total_distance": total, "service_cost": service_total, "vehicle_service_cost": vehicle_service_cost,
			"acquisition": receipt,
			"cost_per_km": (receipt.incoming_rate + service_total) / total if receipt and total else None,
			"allocated_acquisition_cost": (
				receipt.incoming_rate * vehicle_distance / total if receipt and total else None
			),
			"replaced_on_vehicle": bool(retirement),
			"days_to_retirement": (retirement.recorded_at - first_mount.recorded_at).total_seconds() / 86400
			if retirement else None,
		})
	replaced = [row for row in rows if row["replaced_on_vehicle"]]
	return {
		"currency": frappe.db.get_value("Company", current.company, "default_currency"),
		"rows": rows,
		"allocated_acquisition_cost": sum(row["allocated_acquisition_cost"] or 0 for row in rows),
		"vehicle_service_cost": sum(row["vehicle_service_cost"] for row in rows),
		"replaced_count": len(replaced),
		"average_retired_distance": sum(row["total_distance"] for row in replaced) / len(replaced)
		if replaced else None,
		"average_days_to_retirement": sum(row["days_to_retirement"] for row in replaced) / len(replaced)
		if replaced else None,
	}


def protect_managed_stock(bundle, method=None):
	if frappe.flags.fleet_tyres_write:
		return
	serials = [entry.serial_no for entry in bundle.entries if entry.serial_no]
	if serials and frappe.db.exists("Fleet Tyre", {
		"serial_no": ["in", serials], "state": ["in", ["Mounted", "Retired"]],
	}):
		frappe.throw(_("Use Fleet Tyres to move a mounted tyre. Retired tyres cannot be moved."))


def require_accounts():
	if not {"Accounts Manager", "Accounts User", "System Manager"}.intersection(frappe.get_roles()):
		frappe.throw(_("Accounting access is required for tyre costs."), frappe.PermissionError)


@frappe.whitelist()
def service_invoice_items(vehicle, invoice):
	current = authorised_vehicle(vehicle, "read")
	require_accounts()
	doc = frappe.get_doc("Purchase Invoice", invoice)
	doc.check_permission("read")
	if doc.docstatus != 1 or doc.company != current.company or doc.is_return or doc.get("custom_vehicle_immobilisation"):
		frappe.throw(_("Choose a submitted purchase invoice from the vehicle company without a fleet immobilisation allocation."))
	return [
		{"name": item.name, "label": item.item_name, "amount": item.base_net_amount}
		for item in doc.items
		if item.expense_account and item.base_net_amount > 0
		and not frappe.db.get_value("Item", item.item_code, "is_stock_item")
		and not frappe.db.exists("Fleet Tyre Expense", identity(item.name))
	]


@frappe.whitelist(methods=["POST"])
def allocate_expense(vehicle, tyre, invoice, invoice_item, category):
	authorised_vehicle(vehicle, "write")
	if not frappe.db.exists("Fleet Tyre Event", {"vehicle": vehicle, "tyre": tyre, "operation": "Mount"}):
		frappe.throw(_("Choose a tyre that has been mounted on this vehicle."))
	if not any(item["name"] == invoice_item for item in service_invoice_items(vehicle, invoice)):
		frappe.throw(_("Choose an unallocated service invoice line."))
	with managed_write():
		doc = frappe.get_doc({
			"doctype": "Fleet Tyre Expense", "tyre": tyre, "vehicle": vehicle, "invoice": invoice,
			"invoice_item": invoice_item, "category": category,
		})
		doc.insert(ignore_permissions=True, set_name=identity(invoice_item))
	return doc.name



@frappe.whitelist(methods=["POST"])
def scrap(vehicle, tyre, notes):
	authorised_vehicle(vehicle, "write")
	tyre = frappe.get_doc("Fleet Tyre", tyre, for_update=True)
	retirement = latest_event({"tyre": tyre.name}, ("Retire", "Scrap"))
	if (
		tyre.state != "Retired" or not retirement or retirement.operation != "Retire"
		or retirement.vehicle != vehicle or not (notes or "").strip()
	):
		frappe.throw(_("Choose a retired tyre awaiting disposal and enter the reason."))
	position = position_for(vehicle, retirement.position)
	with managed_write():
		stock_entry = move_stock(tyre, None, issue=True)
		append_event(tyre, position, "Scrap", retirement.odometer, now_datetime(),
			notes=notes, stock_entry=stock_entry)



@frappe.whitelist(methods=["POST"])
def approve_removed(vehicle, tyre, notes):
	authorised_vehicle(vehicle, "write")
	tyre = frappe.get_doc("Fleet Tyre", tyre, for_update=True)
	removal = latest_event({"tyre": tyre.name}, ("Remove",))
	if tyre.state != "Removed" or not removal or removal.vehicle != vehicle or not (notes or "").strip():
		frappe.throw(_("Choose a removed tyre from this vehicle and record the inspection findings."))
	position = position_for(vehicle, removal.position)
	with managed_write():
		append_event(tyre, position, "Inspection", removal.odometer, now_datetime().replace(microsecond=0),
			notes=notes, inspection_type="Return to Service")
