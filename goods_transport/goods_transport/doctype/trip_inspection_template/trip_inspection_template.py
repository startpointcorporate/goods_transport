import re

import frappe
from frappe import _
from frappe.model.document import Document

from goods_transport.goods_transport.services.trip_inspection import VIEWS


class TripInspectionTemplate(Document):
	def validate(self):
		codes = set()
		for row in self.controls:
			if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", row.code or "") or row.code in codes or row.code in VIEWS:
				frappe.throw(_("Use a unique lowercase code for each inspection control."))
			codes.add(row.code)
			if row.safety or row.documents:
				row.required_control = 1
				row.allow_na = 0
