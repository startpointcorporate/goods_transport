const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../goods_transport/public/js/transport_trip.js"), "utf8");

function refresh({ canRead, driver = "DRIVER-1", docstatus = 1 }) {
	const calls = { buttons: [], lookups: [], indicators: [] };
	let handler;
	vm.runInNewContext(script, {
		__: (message, values) => values ? message.replace("{0}", values[0]).replace("{1}", values[1]) : message,
		format_currency: (amount, currency) => `${amount} ${currency}`,
		frappe: {
			ui: { form: { on(doctype, events) {
				assert.equal(doctype, "Transport Trip");
				handler = events.refresh;
			} } },
			model: { can_read(doctype) {
				assert.equal(doctype, "Driver Trip Earning");
				return canRead;
			} },
			db: { get_value(doctype, filters, fields, callback) {
				calls.lookups.push([doctype, filters.trip, ...fields]);
				callback({ name: "EARNING-1", total_earning: 25, status: "Processed" });
			} },
		},
	});
	handler({
		doc: { docstatus, driver, name: "TRIP-1", currency: "EUR" },
		add_custom_button(label) { calls.buttons.push(label); },
		dashboard: { add_indicator(...args) { calls.indicators.push(args); } },
	});
	return calls;
}

test("a Transport User without payroll read permission triggers no payroll controls or lookup", () => {
	assert.deepEqual(refresh({ canRead: false }), { buttons: [], lookups: [], indicators: [] });
});

test("an authorised reader still sees the driver's earning", () => {
	assert.deepEqual(refresh({ canRead: true }), {
		buttons: ["Driver Earning"],
		lookups: [["Driver Trip Earning", "TRIP-1", "name", "total_earning", "status"]],
		indicators: [["Driver Earning: 25 EUR (Processed)", "green"]],
	});
});

test("draft trips and trips without a driver do not look up earnings", () => {
	assert.equal(refresh({ canRead: true, docstatus: 0 }).lookups.length, 0);
	assert.equal(refresh({ canRead: true, driver: "" }).lookups.length, 0);
});
