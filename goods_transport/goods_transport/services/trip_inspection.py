"""Inspection evidence and rules for Transport Trip."""
import io
import math
from uuid import uuid4

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime
from PIL import Image, UnidentifiedImageError

from goods_transport.goods_transport.services.fleet_odometer import (
	lock_vehicle, reading, record_trip_readings,
)

INSPECTION = "Trip Vehicle Inspection"
TEMPLATE = "Trip Inspection Template"
RESULTS = ("Pass", "Fail", "Not Applicable", "Not Checked")
SEVERITIES = ("Minor", "Major", "Critical")
VIEWS = ("front", "rear", "left", "right", "cab", "tyres")
DEPARTURE_STATUSES = ("Vehicle Assigned", "At Loading Point", "Loaded")
ENCODED_PHOTO_SLOT = "_inspection_"


def photo_slot(control):
	# File.attached_to_field accepts word characters only. The reserved prefix
	# cannot occur in a template code, so existing attachments remain readable.
	return ENCODED_PHOTO_SLOT + control.encode("ascii").hex() if "-" in control else control


def photo_control(slot):
	if slot and slot.startswith(ENCODED_PHOTO_SLOT):
		return bytes.fromhex(slot.removeprefix(ENCODED_PHOTO_SLOT)).decode("ascii")
	return slot


def enabled(trip):
	return trip.meta.has_field("inspection_policy") and frappe.db.table_exists(INSPECTION)


def snapshot_policy(trip):
	cutoff = frappe.conf.get("trip_inspection_required_from")
	mandatory = bool(cutoff and get_datetime(trip.creation) >= get_datetime(cutoff))
	if not enabled(trip):
		if mandatory:
			frappe.throw(_("Vehicle inspections are unavailable on this site."))
		return
	vehicle_type = frappe.db.get_value("Vehicle", trip.vehicle, "vehicle_type")
	if not trip.inspection_template:
		if vehicle_type:
			matches = frappe.get_all(TEMPLATE, filters={"company": trip.company, "vehicle_type": vehicle_type}, pluck="name")
			if len(matches) > 1:
				frappe.throw(_("Select an inspection template explicitly."))
			if matches:
				trip.inspection_template = matches[0]
		if not trip.inspection_template:
			matches = frappe.get_all(TEMPLATE, filters={"company": trip.company, "vehicle_type": ["is", "not set"]}, pluck="name")
			if len(matches) > 1:
				frappe.throw(_("Select an inspection template explicitly."))
			if matches:
				trip.inspection_template = matches[0]
	trip.inspection_policy = None
	if not trip.inspection_template:
		if mandatory:
			frappe.throw(_("Select a checklist for this company and vehicle type."))
		return
	template = frappe.get_doc(TEMPLATE, trip.inspection_template)
	if template.company != trip.company or template.vehicle_type and template.vehicle_type != vehicle_type:
		frappe.throw(_("Select a checklist for this company and vehicle type."))
	keys = ("code", "label_en", "label_fr", "required_control", "allow_na", "min_photos", "safety", "documents")
	trip.inspection_policy = frappe.as_json({
		"version": 1, "required": mandatory or bool(template.require_inspections),
		"controls": [{key: row.get(key) for key in keys} for row in template.controls],
	})


def policy(trip):
	return frappe.parse_json(trip.get("inspection_policy") or "{}")


def latest(trip, phase, submitted=False):
	if not enabled(trip):
		return None
	filters = {"trip": trip.name, "phase": phase, "docstatus": 1 if submitted else ["<", 2]}
	names = frappe.get_all(INSPECTION, filters=filters, pluck="name", order_by="revision desc", limit=1)
	return frappe.get_doc(INSPECTION, names[0]) if names else None


def check_departure(trip):
	if policy(trip).get("required"):
		doc = latest(trip, "Departure", submitted=True)
		if not doc or (doc.vehicle, doc.driver) != (trip.vehicle, trip.driver):
			frappe.throw(_("Validate the departure inspection before leaving."))


def check_return(trip):
	if policy(trip).get("required"):
		doc = latest(trip, "Return", submitted=True)
		if not doc or (doc.vehicle, doc.driver) != (trip.vehicle, trip.driver) or not trip.odometer_recorded_at:
			frappe.throw(_("Validate the return inspection before closing the trip."))


def protect_trip(trip, before):
	if not before or not (trip.get("inspection_policy") or before.get("inspection_policy")):
		return
	if any(trip.get(key) != before.get(key) for key in ("inspection_template", "inspection_policy", "vehicle", "driver")):
		frappe.throw(_("The inspection policy and assignment are fixed for this trip."))
	for phase, field in (("Departure", "departure_odometer"), ("Return", "arrival_odometer")):
		inspection = latest(trip, phase, submitted=True)
		if inspection and reading(trip.get(field)) != reading(inspection.odometer):
			frappe.throw(_("The odometer reading is already validated by an inspection."))


def _trip(name, permission, lock=False, authorize=None):
	trip = frappe.get_doc("Transport Trip", name, for_update=lock)
	if authorize:
		authorize(trip)
	else:
		trip.check_permission(permission)
	if not enabled(trip):
		frappe.throw(_("Vehicle inspections are unavailable on this site."))
	return trip


def _inspection(name, permission, lock=False, authorize=None):
	doc = frappe.get_doc(INSPECTION, name)
	trip = _trip(doc.trip, permission, lock, authorize)
	if lock:
		doc = frappe.get_doc(INSPECTION, name, for_update=True)
	if authorize and (doc.driver, doc.vehicle) != (trip.driver, trip.vehicle):
		frappe.throw(_("The inspection belongs to a different assignment."), frappe.PermissionError)
	return doc, trip


def has_permission(doc, ptype=None, user=None, **kwargs):
	return bool(ptype in (None, "read", "select") and frappe.has_permission(
		"Transport Trip", "read", doc=doc.trip, user=user,
	))


def permission_query(user=None):
	try:
		readable_trips = frappe.get_list("Transport Trip", fields=["name"], user=user, run=False, order_by=None)
	except frappe.PermissionError:
		return "1=0"
	return frappe.qb.DocType(INSPECTION).trip.isin(readable_trips)


def file_permission(doc, ptype=None, user=None, **kwargs):
	if doc.attached_to_doctype != INSPECTION:
		return True
	return ptype in ("read", "select") and has_permission(
		frappe.get_doc(INSPECTION, doc.attached_to_name), ptype, user,
	)


def file_permission_query(user=None):
	return "COALESCE(`tabFile`.`attached_to_doctype`, '') != 'Trip Vehicle Inspection'"


def _phase(trip, phase):
	if trip.docstatus != 1 or phase not in ("Departure", "Return"):
		frappe.throw(_("Select an inspection phase on a submitted trip."))
	statuses = DEPARTURE_STATUSES if phase == "Departure" else ("Delivered", "Settled")
	if trip.status not in statuses:
		frappe.throw(_("This phase cannot be inspected at the current trip status."))


@frappe.whitelist(methods=["POST"])
def open_inspection(trip, phase, correction_reason=None):
	return _open_inspection(trip, phase, correction_reason)


def _open_inspection(trip, phase, correction_reason=None, authorize=None):
	trip = _trip(trip, "read", True, authorize)
	if phase not in ("Departure", "Return"):
		frappe.throw(_("Invalid inspection phase."))
	current = latest(trip, phase)
	if current and not correction_reason:
		if authorize and (current.driver, current.vehicle) != (trip.driver, trip.vehicle):
			frappe.throw(_("The inspection belongs to a different assignment."), frappe.PermissionError)
		if current.docstatus != 1 and not authorize:
			trip.check_permission("write")
		return _view(current)
	if not authorize:
		trip.check_permission("write")
	if correction_reason:
		if not current or current.docstatus != 1 or "System Manager" not in frappe.get_roles() or not correction_reason.strip():
			frappe.throw(_("A system manager must provide a correction reason for a validated inspection."), frappe.PermissionError)
	else:
		_phase(trip, phase)
	controls = policy(trip).get("controls")
	if not controls:
		frappe.throw(_("Assign an inspection template before submitting this trip."))
	departure = latest(trip, "Departure", submitted=True) if phase == "Return" else None
	if authorize and departure and (departure.driver, departure.vehicle) != (trip.driver, trip.vehicle):
		frappe.throw(_("The inspection belongs to a different assignment."), frappe.PermissionError)
	if phase == "Return" and not departure:
		frappe.throw(_("Validate the departure inspection first."))
	initial = current or None
	doc = frappe.get_doc({
		"doctype": INSPECTION, "trip": trip.name, "vehicle": trip.vehicle,
		"plate": trip.vehicle_license_plate or frappe.db.get_value("Vehicle", trip.vehicle, "license_plate"),
		"driver": trip.driver, "phase": phase, "revision": current.revision + 1 if current else 1,
		"location": trip.origin if phase == "Departure" else trip.destination,
		"departure": departure.name if departure else None,
		"previous_revision": current.name if current else None, "correction_reason": correction_reason,
		"odometer": (initial.odometer if initial else
			trip.departure_odometer if phase == "Departure" else trip.arrival_odometer),
		"controls": initial.controls if initial else frappe.as_json(controls),
		"position": initial.position if initial else None,
		"observations": initial.observations if initial else None,
	})
	doc.flags.inspection_service = True
	doc.insert(ignore_permissions=True)
	return _view(doc)


@frappe.whitelist()
def read_inspection(inspection):
	doc, _trip_doc = _inspection(inspection, "read")
	if doc.docstatus != 1:
		frappe.throw(_("This inspection is awaiting validation."))
	return _view(doc)


def attachments(doc):
	rows = frappe.get_all("File", filters={"attached_to_doctype": INSPECTION, "attached_to_name": doc.name, "is_private": 1},
		fields=["name", "file_url", "attached_to_name", "attached_to_field", "content_hash"])
	if doc.previous_revision:
		parent = frappe.get_doc(INSPECTION, doc.previous_revision)
		original = attachments(parent)
		original.update({row.name: row for row in rows})
		return original
	return {row.name: row for row in rows}


def _view(doc):
	revisions = frappe.get_all(INSPECTION, filters={"trip": doc.trip, "phase": doc.phase, "docstatus": 1},
		fields=["name", "revision", "correction_reason"], order_by="revision desc")
	return {
		"name": doc.name, "phase": doc.phase, "trip": doc.trip, "vehicle": doc.vehicle, "plate": doc.plate,
		"driver": doc.driver, "location": doc.location, "created": doc.creation,
		"inspector": doc.owner, "revisions": revisions,
		"odometer": doc.odometer, "validated_at": doc.validated_at, "validated_by": doc.validated_by,
		"departure": doc.departure, "departure_odometer": frappe.db.get_value(INSPECTION, doc.departure, "odometer") if doc.departure else None,
		"revision": doc.revision, "submitted": doc.docstatus == 1, "observations": doc.observations,
		"position": frappe.parse_json(doc.position or "null"),
		"controls": frappe.parse_json(doc.controls), "photos": [{
			"name": photo.name, "file_url": photo.file_url, "inspection": photo.attached_to_name,
			"attached_to_field": photo_control(photo.attached_to_field),
		} for photo in attachments(doc).values()],
		"repair": doc.repair, "maintenance_task": doc.maintenance_task, "immobilisation": doc.immobilisation,
	}


@frappe.whitelist(methods=["POST"])
def upload_photo(inspection, control):
	return _upload_photo(inspection, control)


def _upload_photo(inspection, control, authorize=None):
	doc, trip = _inspection(inspection, "write", True, authorize)
	allowed = set(VIEWS) | {row["code"] for row in policy(trip).get("controls", [])}
	if doc.docstatus or control not in allowed:
		frappe.throw(_("This inspection cannot receive that photograph."))
	upload = frappe.request.files.get("file")
	if not upload:
		frappe.throw(_("Select a photograph."))
	content, suffix = validate_image_upload(upload)
	frappe.flags.trip_inspection_upload = doc.name
	try:
		file = frappe.get_doc({
			"doctype": "File", "file_name": f"inspection-{uuid4().hex}.{suffix}", "content": content,
			"is_private": 1, "attached_to_doctype": INSPECTION,
			"attached_to_name": doc.name, "attached_to_field": photo_slot(control),
		})
		file.flags.ignore_duplicate_entry_error = True
		file.insert(ignore_permissions=True)
		file.db_set("owner", "Administrator", update_modified=False)
	finally:
		frappe.flags.trip_inspection_upload = None
	return {"name": file.name, "file_url": file.file_url, "attached_to_field": control, "inspection": doc.name}


def validate_image_upload(upload):
	content = upload.stream.read(12 * 1024 * 1024 + 1)
	if len(content) > 12 * 1024 * 1024:
		frappe.throw(_("The photograph exceeds 12 MB."))
	try:
		with Image.open(io.BytesIO(content)) as photo:
			image_format = photo.format
			if image_format not in ("JPEG", "PNG", "WEBP"):
				frappe.throw(_("Use a JPEG, PNG or WebP photograph."))
			photo.verify()
	except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
		frappe.throw(_("The photograph could not be read."))
	return content, {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[image_format]


@frappe.whitelist(methods=["POST"])
def remove_photo(inspection, photo):
	return _remove_photo(inspection, photo)


def _remove_photo(inspection, photo, authorize=None):
	doc, _trip_doc = _inspection(inspection, "write", True, authorize)
	file = frappe.get_doc("File", photo, for_update=True)
	if doc.docstatus or (file.attached_to_doctype, file.attached_to_name) != (INSPECTION, doc.name):
		frappe.throw(_("Only a photograph attached to this draft can be removed."))
	frappe.flags.trip_inspection_remove = file.name
	try:
		file.delete(ignore_permissions=True)
	finally:
		frappe.flags.trip_inspection_remove = None


class InspectionFile:
	def save_file(self, *args, **kwargs):
		if self.attached_to_doctype == INSPECTION:
			kwargs["ignore_existing_file_check"] = True
		return super().save_file(*args, **kwargs)


def protect_file(file, method=None):
	before = file.get_doc_before_save()
	related = [item for item in (file, before) if item and item.attached_to_doctype == INSPECTION]
	if not related:
		if method in ("before_insert", "before_validate", "validate") and file.file_url and frappe.db.exists("File", {
			"file_url": file.file_url, "attached_to_doctype": INSPECTION,
		}):
			frappe.throw(_("Inspection evidence cannot be copied to another record."))
		return
	if method == "on_trash" and frappe.flags.trip_inspection_remove == file.name:
		return
	if method != "on_trash" and file.is_new() and file.is_private and frappe.flags.trip_inspection_upload == file.attached_to_name:
		return
	frappe.throw(_("Inspection evidence is managed through the trip inspection."))


def validate_controls(config, results, files):
	if not isinstance(results, dict) or set(results) - {row["code"] for row in config}:
		frappe.throw(_("The inspection controls do not match the trip checklist."))
	out = []
	for rule in config:
		row = results.get(rule["code"], {})
		if not isinstance(row, dict) or any(value is not None and not isinstance(value, str) for value in row.values()):
			frappe.throw(_("Invalid result for control {0}.").format(rule["label_en"]))
		result = row.get("result") or "Not Checked"
		if result not in RESULTS or result == "Not Applicable" and not rule["allow_na"]:
			frappe.throw(_("Invalid result for control {0}.").format(rule["label_en"]))
		if rule["required_control"] and result == "Not Checked":
			frappe.throw(_("Complete the required control {0}.").format(rule["label_en"]))
		observation = (row.get("observation") or "").strip()
		severity = row.get("severity") if result == "Fail" else None
		defect = (row.get("defect") or "").strip().casefold() if result == "Fail" else ""
		if result == "Fail" and (not observation or not defect or severity not in SEVERITIES):
			frappe.throw(_("Provide a defect code, severity and observation for {0}.").format(rule["label_en"]))
		photos = {
			file.content_hash for file in files.values() if file.attached_to_field == photo_slot(rule["code"])
		}
		if result not in ("Not Applicable", "Not Checked") and len(photos) < rule["min_photos"]:
			frappe.throw(_("Add the required photographs for {0}.").format(rule["label_en"]))
		out.append(dict(rule, result=result, severity=severity, defect=defect, observation=observation))
	return out


def _position(value):
	if not value:
		return None
	try:
		latitude, longitude, accuracy = (float(value[key]) for key in ("latitude", "longitude", "accuracy"))
		if -90 <= latitude <= 90 and -180 <= longitude <= 180 and math.isfinite(accuracy) and accuracy >= 0:
			return frappe.as_json(dict(latitude=latitude, longitude=longitude, accuracy=accuracy))
	except (ValueError, TypeError, KeyError, OverflowError):
		pass
	frappe.throw(_("Invalid inspection GPS position."))


def _immobilise(doc, trip):
	if not any(row["safety"] and row["severity"] == "Critical" for row in frappe.parse_json(doc.controls)):
		return
	existing = frappe.db.get_value("Vehicle Immobilisation", {
		"vehicle": trip.vehicle, "released_at": ["is", "not set"], "start_at": ["<=", now_datetime()],
	})
	if existing:
		doc.immobilisation = existing
		return
	event = frappe.get_doc({
		"doctype": "Vehicle Immobilisation", "vehicle": trip.vehicle, "company": trip.company,
		"transport_trip": trip.name, "start_at": now_datetime(), "odometer": doc.odometer,
		"reason": "Breakdown",
		"description": _("Critical safety defect in inspection {0}").format(doc.name),
	})
	event.insert(ignore_permissions=True)
	doc.immobilisation = event.name


@frappe.whitelist(methods=["POST"])
def validate_inspection(inspection, odometer, results, observations=None, position=None):
	return _validate_inspection(inspection, odometer, results, observations, position)


def _validate_inspection(inspection, odometer, results, observations=None, position=None, authorize=None):
	doc, trip = _inspection(inspection, "write", True, authorize)
	if doc.docstatus == 1:
		return _view(doc)
	if doc.previous_revision:
		if authorize or "System Manager" not in frappe.get_roles():
			frappe.throw(_("Only a system manager may validate a correction."), frappe.PermissionError)
	else:
		_phase(trip, doc.phase)
	if (doc.vehicle, doc.driver) != (trip.vehicle, trip.driver):
		frappe.throw(_("The vehicle or driver assignment differs from the inspection."))
	end = reading(odometer)
	if end is None:
		frappe.throw(_("Enter the actual odometer."))
	vehicle = lock_vehicle(trip.vehicle)
	if doc.previous_revision and end != reading(frappe.db.get_value(INSPECTION, doc.previous_revision, "odometer")):
		frappe.throw(_("An inspection revision must preserve the verified odometer."))
	if doc.phase == "Departure" and not doc.previous_revision and end < (vehicle.last_odometer or 0):
		frappe.throw(_("The departure odometer is below the last recorded vehicle reading."))
	if doc.phase == "Return":
		start = reading(frappe.db.get_value(INSPECTION, doc.departure, "odometer"))
		if start is None or end < start:
			frappe.throw(_("The arrival odometer must be greater than or equal to the departure odometer."))
		if trip.odometer_recorded_at and (start, end) != (reading(trip.departure_odometer), reading(trip.arrival_odometer)):
			frappe.throw(_("The inspection readings must match the verified trip readings."))
	files = attachments(doc)
	rows = validate_controls(policy(trip)["controls"], frappe.parse_json(results), files)
	doc.odometer = str(end)
	doc.controls = frappe.as_json(rows)
	doc.position = _position(frappe.parse_json(position))
	doc.observations = observations
	doc.validated_at = now_datetime()
	doc.validated_by = frappe.session.user
	_immobilise(doc, trip)
	doc.flags.inspection_service = True
	doc.flags.ignore_permissions = True
	doc.submit()
	if not doc.previous_revision:
		field = "departure_odometer" if doc.phase == "Departure" else "arrival_odometer"
		trip.db_set(field, str(end))
		if doc.phase == "Return":
			record_trip_readings(trip)
	return _view(doc)


def difference(before, after):
	if not before or not after or "Not Checked" in (before["result"], after["result"]):
		return "Not Checked"
	old, new = before["result"], after["result"]
	if new == "Fail":
		if old != "Fail":
			return "New Defect"
		if before["defect"] != after["defect"]:
			return "New Defect"
		if SEVERITIES.index(after["severity"]) > SEVERITIES.index(before["severity"]):
			return "Worsened"
		if SEVERITIES.index(after["severity"]) < SEVERITIES.index(before["severity"]):
			return "Improved"
		return "Existing Defect"
	if old == "Fail":
		return "Resolved" if new == "Pass" else "Not Checked"
	return "Unchanged" if old == new else "Not Checked"


@frappe.whitelist()
def compare(trip):
	trip = _trip(trip, "read")
	departure = latest(trip, "Departure", submitted=True)
	returned = latest(trip, "Return", submitted=True)
	before = _view(departure) if departure else None
	after = _view(returned) if returned else None
	prior = {row["code"]: row for row in before["controls"]} if before else {}
	final = {row["code"]: row for row in after["controls"]} if after else {}
	rows = [
		dict(rule, before=prior.get(rule["code"]), after=final.get(rule["code"]),
			evolution=difference(prior.get(rule["code"]), final.get(rule["code"])))
		for rule in policy(trip).get("controls", [])
	]
	incomplete = not (before and after and trip.odometer_recorded_at) or any(
		row["required_control"] and row["evolution"] == "Not Checked" for row in rows
	)
	damaged = any(row["evolution"] in ("New Defect", "Worsened") for row in rows)
	vehicle = "Non-compliant" if damaged else "Review Required" if incomplete else "Compliant"
	assignment = bool(trip.driver) and all(
		(doc.vehicle, doc.driver) == (trip.vehicle, trip.driver) for doc in (departure, returned) if doc
	)
	safety_failure = any(
		control and (row["safety"] or row["documents"]) and control["result"] == "Fail"
		for row in rows for control in (row["before"], row["after"])
	)
	incident = frappe.db.exists("Vehicle Immobilisation", {"transport_trip": trip.name})
	operational = (
		"Non-compliant" if safety_failure or incident else
		"Review Required" if incomplete or not assignment else "Compliant"
	)
	return dict(
		trip=trip.name, before=before, after=after, rows=rows,
		distance=trip.actual_distance if trip.odometer_recorded_at else None,
		vehicle=vehicle, operational=operational,
		overall="Compliant" if vehicle == operational == "Compliant" else "Review Required",
	)


@frappe.whitelist(methods=["POST"])
def create_repair(inspection):
	doc, trip = _inspection(inspection, "write", True)
	if doc.docstatus != 1 or not any(row["result"] == "Fail" for row in frappe.parse_json(doc.controls)):
		frappe.throw(_("Validate an inspection with a defect before creating a repair."))
	if doc.repair or doc.maintenance_task:
		doctype, name = ("Asset Repair", doc.repair) if doc.repair else ("ToDo", doc.maintenance_task)
		frappe.get_doc(doctype, name).check_permission("read")
		return {"doctype": doctype, "name": name}
	asset = frappe.db.get_value("Vehicle", trip.vehicle, "custom_maintenance_asset")
	if not asset:
		task = frappe.get_doc({
			"doctype": "ToDo", "allocated_to": frappe.session.user, "assigned_by": frappe.session.user,
			"reference_type": INSPECTION, "reference_name": doc.name,
			"description": _("Maintenance follow-up for inspection {0}. Link a maintenance asset to enable an Asset Repair.").format(doc.name),
		}).insert()
		doc.db_set("maintenance_task", task.name)
		return {"doctype": task.doctype, "name": task.name}
	event = doc.immobilisation
	if event and frappe.db.get_value("Vehicle Immobilisation", event, "transport_trip") != trip.name:
		event = None
	repair = frappe.get_doc({
		"doctype": "Asset Repair", "asset": asset, "company": trip.company,
		"failure_date": doc.validated_at, "repair_status": "Pending",
		"description": _("Defect recorded during inspection {0}").format(doc.name),
		"custom_trip_vehicle_inspection": doc.name, "custom_vehicle_immobilisation": event,
	})
	repair.insert()
	doc.db_set("repair", repair.name)
	if event:
		immobilisation = frappe.get_doc("Vehicle Immobilisation", event, for_update=True)
		if not immobilisation.asset_repair and not immobilisation.released_at:
			immobilisation.asset_repair = repair.name
			immobilisation.save()
	return {"doctype": repair.doctype, "name": repair.name}
