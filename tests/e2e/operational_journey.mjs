import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium } from "playwright";

const [baseURL, fixturePath] = process.argv.slice(2);
assert.equal(new URL(baseURL).hostname, "127.0.0.1");
assert(process.env.JOURNEY_QA_PASSWORD);
const fixture = JSON.parse(await readFile(fixturePath, "utf8"));
const browser = await chromium.launch();
const context = await browser.newContext({ baseURL, locale: "en-US" });
const page = await context.newPage();
page.on("pageerror", (error) => console.error(error.message));
page.setDefaultTimeout(15000);
const operations = "goods_transport.goods_transport.services.operations.";
const modal = () => page.locator(".modal.show").last();
const button = (text) => page.getByRole("button", { name: text, exact: true }).first();

async function rpc(method, data) {
	return page.evaluate(({ method, data }) => frappe.xcall(method, data), { method, data });
}
async function form(doctype, name) {
	await page.waitForFunction(({ doctype, name }) => window.cur_frm?.doctype === doctype
		&& (!name || window.cur_frm.docname === name), { doctype, name });
	return page.evaluate(() => ({ ...cur_frm.doc }));
}
async function group(name, action) {
	await button(name).click();
	await page.getByRole("menuitem", { name: action, exact: true }).last().click();
}
async function dialogValues(values) {
	await page.waitForFunction(() => !!window.cur_dialog);
	await page.evaluate(async (values) => {
		for (const [field, value] of Object.entries(values)) await cur_dialog.set_value(field, value);
	}, values);
	await modal().locator(".modal-title").click();
}
async function fields(values) {
	await page.evaluate((values) => cur_frm.set_value(values), values);
}
async function save(action = "Save") {
	await page.evaluate((action) => cur_frm.save(action), action);
}
async function closeModal() {
	await modal().getByRole("button", { name: "Close", exact: true }).first().click();
}
async function status(value) {
	await group("Tracking", "Advance Status");
	await dialogValues({ to_status: value });
	await modal().locator(".btn-modal-primary").click();
	await page.waitForFunction((value) => cur_frm.doc.status === value, value);
}
async function inspect(phase, odometer) {
	await group("Inspections", phase + " Inspection");
	await modal().getByText("Bodywork", { exact: true }).waitFor();
	await modal().getByLabel("Actual Odometer (km)").fill(String(odometer));
	await modal().locator('[data-control="body"]').getByLabel("Result").selectOption("Pass");
	await modal().getByRole("button", { name: "Validate Inspection", exact: true }).click();
	await modal().getByText("Validated", { exact: true }).waitFor();
	await closeModal();
}

try {
	const login = await context.request.post("/api/method/login", {
		form: { usr: "Administrator", pwd: process.env.JOURNEY_QA_PASSWORD },
	});
	assert(login.ok());
	await page.goto("/desk/transport-order");
	await page.waitForFunction(() => window.frappe?.app && frappe.boot.setup_complete);
	await page.evaluate(() => frappe.new_doc("Transport Order"));
	await form("Transport Order");
	await fields({
		company: fixture.company, customer: fixture.customer, currency: "EUR", origin: fixture.origin,
		destination: fixture.destination, via: fixture.via, commodity: fixture.cargo,
		uom: "Kg", quantity: 8, cargo_volume: 12, rate_basis: "Per Trip", rate: 450000, pod_required: 1,
	});
	await button("Itinéraire et péages").click();
	await modal().getByRole("button", { name: "Calculer", exact: true }).click();
	await modal().getByText(fixture.toll, { exact: false }).first().waitFor();
	await closeModal();
	await save();
	const order = await form("Transport Order");
	assert.equal(order.billable_quantity, 1);
	assert.equal(order.grand_total, 450000);
	assert(order.estimated_distance > 0);
	await save("Submit");
	await group("Create", "Transport Trip");
	await dialogValues({ vehicle: fixture.vehicle });
	await modal().getByRole("button", { name: "Create Trip", exact: true }).click();
	const trip = await form("Transport Trip");
	assert.equal(trip.driver, fixture.driver);
	assert.equal(trip.via, fixture.via);
	await fields({ freight_item: fixture.freight });
	await save();
	await save("Submit");

	await group("Planning", "Plan de route poids lourd");
	await modal().getByRole("button", { name: "Calculer le plan", exact: true }).waitFor();
	await page.waitForFunction(() => !!window.cur_dialog);
	assert.deepEqual(await page.evaluate(() => ["vehicle", "via", "cargo_kg", "cargo_m3"].map(
		(field) => cur_dialog.get_value(field))), [fixture.vehicle, fixture.via, 8, 12]);
	await modal().getByRole("button", { name: "Calculer le plan", exact: true }).click();
	await modal().getByText(/Classe LCR 3b/).waitFor();
	await modal().getByText(fixture.toll, { exact: false }).first().waitFor();
	assert.equal(await modal().locator("[data-fuel-stops]").count(), 0);
	await closeModal();

	await group("Planning", "Plan de route poids lourd");
	await modal().locator('[data-fieldname="cargo_m3"] input').fill("");
	await modal().getByRole("button", { name: "Calculer le plan", exact: true }).click();
	await modal().getByText("Cargo volume is unknown. Volumetric compliance has not been verified.").waitFor();
	await closeModal();

	await group("Planning", "Plan de route poids lourd");
	await dialogValues({ departure_liters: 5 });
	await modal().getByRole("button", { name: "Calculer le plan", exact: true }).click();
	await modal().getByText(/Classe LCR 3b/).waitFor();
	await modal().getByText(fixture.toll, { exact: false }).first().waitFor();
	await modal().locator("[data-fuel-stops] li").first().waitFor();
	await modal().getByRole("button", { name: "Enregistrer le plan", exact: true }).click();
	await page.waitForFunction(() => !!cur_frm.doc.fuel_stop_reserve);
	await group("Planning", "Plan de route poids lourd");
	await page.waitForFunction(() => window.cur_dialog?.get_value("departure_liters") === 5);
	assert.deepEqual(await page.evaluate(() => ["cargo_m3", "departure_liters"].map(
		(field) => cur_dialog.get_value(field))), [12, 5]);
	await modal().getByRole("button", { name: "Calculer le plan", exact: true }).click();
	await modal().locator("[data-fuel-stops] li").first().waitFor();
	await closeModal();
	await group("Carburant", "Autoriser les arrêts du plan");
	const validUntil = await page.evaluate(() => frappe.datetime.add_days(frappe.datetime.now_date(), 1) + " 23:59:00");
	await dialogValues({ valid_until: validUntil });
	await modal().locator(".btn-modal-primary").click();
	await page.waitForURL(/fuel-authorization/);
	await page.getByText(trip.name, { exact: true }).filter({ visible: true }).last().waitFor();
	await page.goto("/desk/transport-trip/" + encodeURIComponent(trip.name));
	await form("Transport Trip", trip.name);

	console.log("Order, trip, route, toll and fuel authorization verified");
	await group("Create", "Bilty");
	await page.waitForFunction((order) => window.cur_dialog?.get_value("transport_order") === order, order.name);
	await modal().getByRole("button", { name: "Create Bilty", exact: true }).click();
	const bilty = await form("Bilty");
	assert.equal(bilty.total_quantity, 8);
	assert.equal(bilty.grand_total, 450000);
	assert.equal(bilty.customer, fixture.customer);
	await save("Submit");
	await group("Related Documents", "Transport Trip");
	await form("Transport Trip", trip.name);
	await group("Create", "Trip Advance");
	assert.equal((await form("Trip Advance")).driver, fixture.driver);
	await fields({ amount: 30, paying_account: fixture.cash, advance_account: fixture.advance_account });
	await save();
	await save("Submit");
	const advance = await form("Trip Advance");
	await group("Related Documents", "Transport Trip");
	await form("Transport Trip", trip.name);
	await group("Create", "Trip Expense");
	assert.equal((await form("Trip Expense")).trip, trip.name);
	await fields({
		expense_type: fixture.expense_type, amount: 15, expense_account: fixture.expense_account,
		payment_mode: "Trip Advance", trip_advance: advance.name, toll_location: fixture.toll,
	});
	await save();
	await save("Submit");
	await group("Related Documents", "Transport Trip");
	await form("Transport Trip", trip.name);

	console.log("Bilty, advance and expense verified");
	await status("At Loading Point");
	await status("Loaded");
	await inspect("Departure", 100);
	await status("In Transit");
	await status("Arrived");
	await status("Unloading");
	await page.goto("/desk/bilty/" + encodeURIComponent(bilty.name));
	await form("Bilty", bilty.name);
	await group("Actions", "Record POD");
	await dialogValues({ receiver_name: "FICTITIOUS JOURNEY QA" });
	await modal().locator(".btn-modal-primary").click();
	await page.waitForFunction(() => cur_frm.doc.pod_status === "Received");
	await closeModal();
	await group("Create", "Sales Invoice");
	const invoice = await form("Sales Invoice");
	assert.equal(invoice.customer, fixture.customer);
	assert.equal(invoice.grand_total, 450000);
	await save("Submit");

	await page.goto("/desk/transport-trip/" + encodeURIComponent(trip.name));
	await form("Transport Trip", trip.name);
	console.log("Departure inspection, proof of delivery and invoice verified");
	await status("Delivered");
	await inspect("Return", 130);
	await group("Inspections", "Compare Vehicle Inspections");
	await modal().getByText("Bodywork", { exact: false }).first().waitFor();
	await closeModal();
	await group("Create", "Trip Settlement");
	const settlement = await form("Trip Settlement");
	assert.equal(settlement.total_revenue, 450000);
	assert.equal(settlement.total_expenses, 15);
	await save("Submit");
	await group("Related Documents", "Transport Trip");
	await form("Transport Trip", trip.name);
	await status("Closed");
	await group("Finances", "Contrôle financier");
	await modal().getByText("Marge sur coûts identifiés", { exact: true }).waitFor();
	await closeModal();
	const items = ["Bilty", "Fuel Authorization", "Trip Advance", "Trip Expense", "Trip Settlement",
		"Trip Vehicle Inspection", "Vehicle Immobilisation", "Driver Trip Earning"];
	const counts = await rpc("frappe.desk.notifications.get_open_count", { doctype: "Transport Trip", name: trip.name, items });
	const linked = Object.fromEntries(counts.count.external_links_found.map(({ doctype, count }) => [doctype, count]));
	for (const doctype of items) assert(doctype in linked, doctype);
	for (const doctype of items.slice(0, 6)) assert(linked[doctype] >= 1, doctype);
	assert((await rpc(operations + "get_order_trips", { transport_order: order.name })).includes(trip.name));
	const connection = page.locator('.document-link[data-doctype="Bilty"]');
	assert.equal(await connection.count(), 1);
	await connection.getByText("Bilty", { exact: true }).click();
	await page.waitForURL(/\/bilty(?:\/|$)/);
	await page.getByText(bilty.name, { exact: true }).waitFor();
	assert(await page.evaluate((name) => cur_list.filter_area.get().some(
		([doctype, field, comparison, value]) =>
			doctype === "Bilty" && field === "transport_trip" && comparison === "=" && value === name
	), trip.name));
	console.log(JSON.stringify({ order: order.name, trip: trip.name, bilty: bilty.name, invoice: invoice.name, linked }));
} catch (error) {
	await page.screenshot({ path: "/tmp/operational-journey-failure.png" });
	console.error((await page.locator("body").innerText()).split("\n").slice(-22).join("\n"));
	throw error;
} finally {
	await browser.close();
}
