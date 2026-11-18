frappe.ui.form.on("Vehicle Maintenance Schedule", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.enabled || frm.doc.asset_maintenance || !frm.perm[0]?.write) return;
		frm.add_custom_button(__("Record Maintenance"), () => {
			frappe.prompt([
				{ fieldname: "completion_date", fieldtype: "Date", label: __("Completion Date"),
					description: __("Leave blank to use today’s date in the company system.") },
				{ fieldname: "odometer", fieldtype: "Data", label: __("Odometer (km)"), reqd: !!frm.doc.interval_km },
				{ fieldname: "details", fieldtype: "Small Text", label: __("Work Performed"), reqd: 1 },
			], async values => {
				await frappe.call({
					method: "goods_transport.goods_transport.doctype.vehicle_maintenance_schedule.vehicle_maintenance_schedule.complete_schedule",
					args: { name: frm.doc.name, ...values },
				});
				await frm.reload_doc();
			}, __("Record Maintenance"));
		});
	},
});
