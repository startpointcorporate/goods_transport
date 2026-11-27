"""Driver self-service projections. The role has no generic trip DocPerm."""

import json

import frappe
from frappe import _
from frappe.permissions import get_user_permissions
from frappe.utils import now_datetime

from . import trip_inspection

from goods_transport.setup.install_fleet_driver import ROLE

TRIP_FIELDS = (
	"name", "modified", "trip_date", "status", "vehicle", "vehicle_license_plate", "origin",
	"destination", "planned_departure_at", "planned_return_at", "departure_time",
	"arrival_time", "actual_distance", "departure_odometer", "arrival_odometer",
)
FIELD_EVENTS = {
	"at_loading": ("Vehicle Assigned", "At Loading Point"),
	"loaded": ("At Loading Point", "Loaded"),
	"departed": ("Loaded", "In Transit"),
	"arrived": ("In Transit", "Arrived"),
	"unloaded": ("Arrived", "Unloading"),
	"delivered": ("Unloading", "Delivered"),
	"finished": ("Delivered", None),
}
AUTHORIZATION_FIELDS = (
	"station", "fuel_type", "authorized_liters", "delivered_liters", "valid_from",
	"valid_until", "status",
)


def _assignment():
	user = frappe.session.user
	if user == "Guest" or ROLE not in frappe.get_roles(user):
		return None
	employees = frappe.get_all(
		"Employee", filters={"user_id": user, "status": "Active"},
		fields=["name", "company"], limit_page_length=2,
	)
	if len(employees) != 1 or not employees[0].company:
		return None
	employee = employees[0]
	drivers = frappe.get_all(
		"Driver", filters={"employee": employee.name, "status": "Active"},
		pluck="name", limit_page_length=2,
	)
	if len(drivers) != 1:
		return None
	company_permissions = get_user_permissions(user).get("Company", ())
	companies = {
		entry["doc"] for entry in company_permissions
		if entry.get("applicable_for") in (None, "", "Transport Trip")
	}
	if companies and employee.company not in companies:
		return None
	return {"driver": drivers[0], "company": employee.company, "docstatus": 1}


@frappe.whitelist(methods=["GET"])
def available():
	return bool(_assignment())


def _project_trip(trip, assignment):
	locations = []
	stored_plan = json.loads(trip.fuel_plan_inputs or "{}")
	for name in dict.fromkeys((trip.origin, stored_plan.get("via"), trip.destination)):
		if not name:
			continue
		location = frappe.db.get_value(
			"Transport Location", name,
			["name", "location_name", "address", "latitude", "longitude"], as_dict=True,
		)
		if location:
			locations.append(location)
	authorizations = frappe.get_all(
		"Fuel Authorization",
		filters={
			"trip": trip.name, "driver": assignment["driver"],
			"company": assignment["company"], "vehicle": trip.vehicle,
		},
		fields=AUTHORIZATION_FIELDS,
		order_by="valid_from asc, creation asc",
	)
	for authorization in authorizations:
		station = frappe.db.get_value("Fuel Partner Station", {
			"name": authorization.station, "company": assignment["company"],
		}, ["station_name", "latitude", "longitude"], as_dict=True)
		if station:
			authorization.update(station)
	forecast = stored_plan.get("confirmed_forecast") or {}
	stop_fields = ("station", "latitude", "longitude", "refill_liters")
	stops = [{field: stop.get(field) for field in stop_fields} for stop in forecast.get("stops", [])]
	result = {field: trip.get(field) for field in TRIP_FIELDS}
	controls = trip_inspection.policy(trip).get("controls", []) if frappe.db.table_exists("Trip Vehicle Inspection") else []
	def inspected(phase):
		return bool(controls and frappe.db.exists("Trip Vehicle Inspection", {
			"trip": trip.name, "phase": phase, "docstatus": 1,
			"vehicle": trip.vehicle, "driver": assignment["driver"],
		}))

	return {
		**result, "locations": locations, "fuel_stops": stops, "authorizations": authorizations,
		"deliveries": _delivery_rows(trip.name, assignment["company"]) if trip.status in (
			"Vehicle Assigned", "At Loading Point", "Loaded", "In Transit", "Arrived", "Unloading", "Delivered",
		) else [],
		"inspection_configured": bool(controls), "departure_inspected": inspected("Departure"),
		"return_inspected": inspected("Return"), "inspection_controls": controls,
		"driver_finished": bool(trip.status == "Delivered" and _field_event_exists(trip, "finished", assignment["driver"])),
	}


@frappe.whitelist(methods=["GET"])
def missions():
	assignment = _assignment()
	if assignment is None:
		frappe.throw(_("Fleet Driver access is unavailable."), frappe.PermissionError)
	fields = [*TRIP_FIELDS, "fuel_plan_inputs"]
	if frappe.get_meta("Transport Trip").has_field("inspection_policy"):
		fields.append("inspection_policy")
	rows = frappe.get_all(
		"Transport Trip", filters=assignment, fields=fields,
		order_by="trip_date desc, name desc",
	)
	return {
		"user": frappe.session.user,
		"trips": [_project_trip(row, assignment) for row in rows],
		"synced_at": now_datetime().isoformat(),
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def service_worker():
	"""Serve the public HRMS build under an explicitly allowed navigation scope."""
	from pathlib import Path

	from werkzeug.wrappers import Response

	file = Path(frappe.get_app_path("hrms", "public", "frontend", "sw.js"))
	return Response(file.read_bytes(), mimetype="application/javascript", headers={
		"Service-Worker-Allowed": "/hrms",
		"Cache-Control": "no-cache",
	})


def _authorize_trip(trip):
	assignment = _assignment()
	if not assignment or any(trip.get(field) != value for field, value in assignment.items()):
		frappe.throw(_("Fleet Driver access is unavailable."), frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def open_inspection(trip: str, phase: str):
	from . import trip_inspection

	return trip_inspection._open_inspection(trip, phase, authorize=_authorize_trip)


@frappe.whitelist(methods=["POST"])
def validate_inspection(inspection: str, odometer: str, results, observations: str | None = None):
	from . import trip_inspection

	return trip_inspection._validate_inspection(
		inspection, odometer, results, observations, authorize=_authorize_trip,
	)


@frappe.whitelist(methods=["POST"])
def upload_photo(inspection: str, control: str):
	from . import trip_inspection

	return trip_inspection._upload_photo(inspection, control, authorize=_authorize_trip)


@frappe.whitelist(methods=["POST"])
def remove_photo(inspection: str, photo: str):
	from . import trip_inspection

	trip_inspection._remove_photo(inspection, photo, authorize=_authorize_trip)


@frappe.whitelist(methods=["GET"])
def inspection_photo(inspection: str, photo: str):
	from mimetypes import guess_type

	from werkzeug.wrappers import Response

	from . import trip_inspection

	document, _trip = trip_inspection._inspection(inspection, "read", authorize=_authorize_trip)
	file = frappe.get_doc("File", photo)
	if not file.is_private or (file.attached_to_doctype, file.attached_to_name) != (document.doctype, document.name):
		frappe.throw(_("Fleet Driver access is unavailable."), frappe.PermissionError)
	mime = guess_type(file.file_name)[0]
	if mime not in ("image/jpeg", "image/png", "image/webp"):
		frappe.throw(_("Fleet Driver access is unavailable."), frappe.PermissionError)
	return Response(file.get_content(), mimetype=mime, headers={
		"Cache-Control": "private, no-store",
		"X-Content-Type-Options": "nosniff",
	})


def _assigned_trip(name, lock=False):
	trip = frappe.get_doc("Transport Trip", name, for_update=lock)
	_authorize_trip(trip)
	return trip


def _field_event_exists(trip, event, driver):
	return frappe.db.exists("Comment", {
		"reference_doctype": "Transport Trip", "reference_name": trip.name,
		"content": f"Fleet Driver · {event} · {driver}",
	})


@frappe.whitelist(methods=["POST"])
def record_field_event(trip: str, event: str):
	from ..doctype.transport_trip.transport_trip import _advance_status
	from . import trip_inspection
	from .fleet_availability import validate_assignment

	doc = _assigned_trip(trip, lock=True)
	if event not in FIELD_EVENTS:
		frappe.throw(_("Unknown driver event."))
	source, target = FIELD_EVENTS[event]
	if _field_event_exists(doc, event, doc.driver):
		return doc.status
	if doc.status != source:
		frappe.throw(_("The mission has moved to another step. Refresh it before continuing."))
	if event in ("loaded", "departed"):
		trip_inspection.check_departure(doc)
	if event in ("at_loading", "loaded"):
		validate_assignment(doc)
	if target:
		_advance_status(doc, target)
	else:
		doc.validate_delivery()
		trip_inspection.check_return(doc)
	doc.add_comment(text=f"Fleet Driver · {event} · {doc.driver}")
	return doc.status


@frappe.whitelist(methods=["GET"])
def delivery_documents(trip: str):
	trip = _assigned_trip(trip)
	return _delivery_rows(trip.name, trip.company)


def _delivery_rows(trip, company):
	rows = frappe.get_all(
		"Bilty", filters={"transport_trip": trip, "company": company, "docstatus": 1},
		fields=["name", "total_quantity", "pod_status", "pod_required"], order_by="creation asc",
	)
	for row in rows:
		row.items = frappe.get_all(
			"Bilty Item", filters={"parent": row.name, "parenttype": "Bilty", "parentfield": "items"},
			fields=["item", "description", "quantity"], order_by="idx asc",
		)
	return rows


@frappe.whitelist(methods=["POST"])
def sync_operation(trip: str, operation: str, operation_id: str, captured_at: str, expected_user: str, vehicle: str):
	"""Replay one field operation after rechecking the current assignment and business rules."""
	from datetime import datetime
	from uuid import UUID

	try:
		if str(UUID(operation_id)) != operation_id:
			raise ValueError
		captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
		if not captured.tzinfo:
			raise ValueError
	except (ValueError, TypeError):
		frappe.throw(_("Invalid offline operation identifier or time."))
	doc = _assigned_trip(trip, lock=True)
	if expected_user != frappe.session.user or vehicle != doc.vehicle:
		frappe.throw(_("The session or vehicle assignment changed."), frappe.PermissionError)
	form = frappe.form_dict
	receipt = f"Fleet Sync · {operation_id} · {doc.driver} · {captured.isoformat()}"
	if frappe.db.exists("Comment", {
		"reference_doctype": doc.doctype, "reference_name": doc.name, "content": receipt,
	}):
		return "validated"
	if operation == "record_field_event":
		record_field_event(trip, form.get("event"))
	elif operation == "confirm_delivery":
		if frappe.db.exists("Proof of Delivery", {"trip": trip, "bilty": form.get("bilty"), "docstatus": 1}):
			frappe.throw(_("This delivery was already confirmed. Review the existing proof."))
		confirm_delivery(trip, form.get("bilty"), form.get("delivered_quantity"),
			form.get("damaged_quantity", 0), form.get("receiver_name", ""), form.get("remarks", ""))
	elif operation in ("report_incident", "report_critical_incident"):
		service = report_incident if operation == "report_incident" else report_critical_incident
		service(trip, form.get("category", ""), form.get("description", ""))
	elif operation == "validate_inspection":
		phase = form.get("phase")
		inspection = trip_inspection._open_inspection(trip, phase, authorize=_authorize_trip)
		if inspection["submitted"]:
			frappe.throw(_("This inspection was already validated. Review the existing inspection."))
		results = frappe.parse_json(form.get("results"))
		if not isinstance(results, dict) or set(results) != {control["code"] for control in inspection["controls"]}:
			frappe.throw(_("The checklist changed. Start a new inspection."))
		uploads = frappe.request.files
		for control in results:
			for upload in uploads.getlist(f"photo:{control}"):
				trip_inspection._upload_photo(inspection["name"], control, authorize=_authorize_trip, upload=upload)
		validate_inspection(inspection["name"], form.get("odometer"), results, form.get("observations"))
	else:
		frappe.throw(_("Unknown offline operation."))
	doc.add_comment(text=receipt)
	return "validated"


def _attach_evidence(doc, upload, field=None):
	if not upload:
		return
	from uuid import uuid4

	from .trip_inspection import validate_image_upload

	content, suffix = validate_image_upload(upload)
	evidence = frappe.get_doc({
		"doctype": "File", "file_name": f"fleet-{uuid4().hex}.{suffix}", "content": content,
		"is_private": 1, "attached_to_doctype": doc.doctype, "attached_to_name": doc.name,
		"attached_to_field": field,
	}).insert(ignore_permissions=True)
	evidence.db_set("owner", "Administrator", update_modified=False)
	if field:
		doc.set(field, evidence.file_url)
	return evidence


@frappe.whitelist(methods=["POST"])
def confirm_delivery(trip: str, bilty: str, delivered_quantity, damaged_quantity=0,
		receiver_name: str = "", remarks: str = ""):
	from math import isfinite

	from frappe.utils import today

	trip = _assigned_trip(trip, lock=True)
	source = frappe.get_doc("Bilty", bilty, for_update=True)
	if source.transport_trip != trip.name or source.company != trip.company or source.docstatus != 1:
		frappe.throw(_("Invalid delivery assignment."), frappe.PermissionError)
	if trip.status not in ("Arrived", "Unloading", "Delivered") or source.status in ("Billed", "Closed", "Cancelled"):
		frappe.throw(_("This mission is not ready for a proof of delivery."))
	existing = frappe.db.get_value(
		"Proof of Delivery", {"bilty": source.name, "docstatus": ["!=", 2]}, ["name", "docstatus"],
		as_dict=True,
	)
	if existing:
		if existing.docstatus == 1:
			return existing.name
		frappe.throw(_("A draft proof of delivery already exists."))
	try:
		delivered = float(delivered_quantity)
		damaged = float(damaged_quantity)
	except (ValueError, TypeError, OverflowError):
		frappe.throw(_("Enter valid delivered and damaged quantities."))
	if not (isfinite(delivered) and isfinite(damaged) and 0 <= damaged <= delivered) or not receiver_name.strip():
		frappe.throw(_("Enter valid quantities and the receiver name."))
	document = frappe.get_doc({
		"doctype": "Proof of Delivery", "trip": trip.name, "bilty": source.name,
		"delivery_date": today(), "delivery_time": now_datetime().time(), "delivered_quantity": delivered,
		"damaged_quantity": damaged, "receiver_name": receiver_name.strip(), "remarks": remarks,
	})
	document.insert(ignore_permissions=True)
	_attach_evidence(document, frappe.request.files.get("photo"), "pod_image")
	_attach_evidence(document, frappe.request.files.get("signature"), "signature_attachment")
	document.flags.ignore_permissions = True
	document.submit()
	return document.name


@frappe.whitelist(methods=["POST"])
def report_incident(trip: str, category: str, description: str):
	from html import escape

	doc = _assigned_trip(trip, lock=True)
	categories = {
		"minor_anomaly": _("Minor anomaly"),
		"mechanical": _("Non-blocking mechanical incident"),
		"material_damage": _("Material damage"),
		"loading": _("Loading problem"),
		"trip_difficulty": _("Difficulty during the trip"),
		"tyre": _("Tyre problem"),
		"accident": _("Accident"),
		"other": _("Other incident"),
	}
	description = description.strip()
	if category not in categories or not description or len(description) > 2000:
		frappe.throw(_("Select a category and describe the incident in up to 2000 characters."))
	if doc.status in ("Delivered", "Settled", "Closed", "Cancelled"):
		frappe.throw(_("This trip is already finished."))
	photos = [photo for photo in frappe.request.files.getlist("photo") if photo.filename]
	if len(photos) > 4:
		frappe.throw(_("Add no more than four photographs."))

	evidence = [_attach_evidence(doc, photo) for photo in photos]
	links = "".join(
		f'<li><a href="{escape(file.file_url)}">{escape(_("Photograph"))} {index}</a></li>'
		for index, file in enumerate(evidence, 1)
	)
	text = (
		f"<p><strong>{escape(_('Non-blocking incident'))} — {escape(categories[category])}</strong></p>"
		f"<p>{escape(_('Vehicle'))}: {escape(doc.vehicle or '')} · {escape(_('Driver'))}: {escape(doc.driver)}</p>"
		f"<p>{escape(description).replace(chr(10), '<br>')}</p>"
	)
	comment = doc.add_comment(text=text + (f"<ul>{links}</ul>" if links else ""))
	return comment.name


@frappe.whitelist(methods=["POST"])
def report_critical_incident(trip: str, category: str, description: str):
	from .fleet_odometer import lock_vehicle

	trip = _assigned_trip(trip, lock=True)
	if category not in ("Breakdown", "Other") or not description.strip() or len(description) > 2000:
		frappe.throw(_("Select a category and describe the incident."))
	if trip.status in ("Delivered", "Settled", "Closed", "Cancelled"):
		frappe.throw(_("This trip is already finished."))
	lock_vehicle(trip.vehicle)
	existing = frappe.db.get_value("Vehicle Immobilisation", {
		"transport_trip": trip.name, "vehicle": trip.vehicle, "company": trip.company,
		"released_at": ["is", "not set"],
	})
	if existing:
		return existing
	doc = frappe.get_doc({
		"doctype": "Vehicle Immobilisation", "company": trip.company, "vehicle": trip.vehicle,
		"transport_trip": trip.name, "reason": category, "description": description,
		"severity": "Critical", "start_at": now_datetime(),
	}).insert(ignore_permissions=True)
	_attach_evidence(doc, frappe.request.files.get("photo"))
	return doc.name


@frappe.whitelist(methods=["POST"])
def present_fuel_authorizations(trip: str):
	trip = _assigned_trip(trip)
	now = now_datetime()
	return frappe.get_all("Fuel Authorization", filters={
		"trip": trip.name, "company": trip.company, "driver": trip.driver, "vehicle": trip.vehicle,
		"status": "Reserved", "valid_from": ["<=", now], "valid_until": [">", now],
	}, fields=["name", "station", "authorized_liters", "valid_until"])


def _route_tolls(trip, projection):
	from frappe.utils import getdate

	from .road_sheet import INPUTS
	from .truck_plan import fetch_route, plan_signature, planned_tolls

	url = frappe.conf.get("goods_transport_truck_osrm_url")
	points = [(row.longitude, row.latitude) for row in projection["locations"]]
	if not url or len(points) < 2 or any(
		lon is None or lat is None or (lon, lat) == (0, 0)
		or not (-180 <= lon <= 180 and -90 <= lat <= 90) for lon, lat in points
	):
		return None
	stored = json.loads(trip.fuel_plan_inputs or "{}")
	forecast = stored.get("confirmed_forecast")
	args = {key: stored.get(key) for key in INPUTS}
	confirmed = bool(forecast and stored.get("signature") == plan_signature(trip, args, forecast))
	try:
		route = fetch_route(url, forecast["waypoints"] if confirmed else points, fuel_stop=confirmed)
	except frappe.ValidationError:
		return None
	if not route or (confirmed and abs(route["distance"] - forecast["distance"]) > 1):
		return None
	stations = {
		row.name: row for row in frappe.get_all("Transport Location",
			filters={"location_type": "Péage", "is_active": 1},
			fields=["name", "location_name", "address", "latitude", "longitude",
				"custom_toll_accuracy_m", "custom_toll_precision"])
	}
	for station in stations.values():
		station.custom_toll_rates = []
	rows = planned_tolls(route["geometry"]["coordinates"], stations.values(), getdate(trip.trip_date), None)
	return [{
		"name": stations[row["name"]].location_name or row["name"],
		"axis": trip.route, "address": stations[row["name"]].address,
		"latitude": row["latitude"], "longitude": row["longitude"], "precision": row["precision"],
	} for row in rows]


@frappe.whitelist(methods=["GET"])
def route_tolls(trip: str):
	doc = _assigned_trip(trip)
	return _route_tolls(doc, _project_trip(doc, {"driver": doc.driver, "company": doc.company}))


@frappe.whitelist(methods=["GET"])
def road_sheet_pdf(trip: str, language: str):
	from .road_sheet import fleet_pdf

	doc = _assigned_trip(trip)
	if language not in ("fr", "en"):
		frappe.throw(_("Select French or English."))
	projection = _project_trip(doc, {"driver": doc.driver, "company": doc.company})
	return fleet_pdf(projection, _route_tolls(doc, projection), language)


def _approved_trip_files(trip):
	"""Intersect explicit operational clearance with the assigned trip and private storage."""
	approved = frappe.conf.get("goods_transport_fleet_documents") or {}
	allowed = [name for name, category in approved.items() if category in ("transport", "mission")]
	if not allowed:
		return []
	return [
		row for row in frappe.get_all("File", filters={
			"name": ["in", allowed], "is_private": 1, "is_folder": 0,
			"attached_to_doctype": "Transport Trip", "attached_to_name": trip.name,
		}, fields=["name", "file_name", "file_url", "modified", "file_size"], order_by="file_name asc")
		if row.file_url and row.file_url.startswith("/private/files/")
		and row.file_name.lower().endswith(".pdf") and 0 < (row.file_size or 0) <= 5 * 1024 * 1024
	]


@frappe.whitelist(methods=["GET"])
def mission_files(trip: str):
	doc = _assigned_trip(trip)
	return [
		{field: row[field] for field in ("name", "file_name", "modified", "file_size")}
		for row in _approved_trip_files(doc)
	]


@frappe.whitelist(methods=["GET"])
def mission_file(trip: str, file: str, modified: str):
	from frappe.utils import get_datetime
	from werkzeug.wrappers import Response

	doc = _assigned_trip(trip)
	candidate = next(
		(row for row in _approved_trip_files(doc) if row.name == file
			and get_datetime(row.modified) == get_datetime(modified)), None,
	)
	if candidate is None:
		frappe.throw(_("This mission document is unavailable."), frappe.PermissionError)

	document = frappe.get_doc("File", candidate.name)
	if (document.is_private != 1 or document.attached_to_doctype != doc.doctype
		or document.attached_to_name != doc.name or document.file_url != candidate.file_url
		or document.modified != candidate.modified):
		frappe.throw(_("This mission document is unavailable."), frappe.PermissionError)
	content = document.get_content(encodings=())
	if not isinstance(content, bytes) or not content.startswith(b"%PDF-") or len(content) > 5 * 1024 * 1024:
		frappe.throw(_("This mission document is not a supported PDF."))
	return Response(content, mimetype="application/pdf", headers={
		"Cache-Control": "private, no-store", "Content-Disposition": "attachment",
		"X-Content-Type-Options": "nosniff",
	})
