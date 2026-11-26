import assert from "node:assert/strict";
import { chromium } from "playwright";

// Post-deployment smoke test. The reference documents are only read.
const baseURL = "https://transportdemo.konektag.eu";
const { TRANSPORT_DEMO_USER, TRANSPORT_DEMO_PASSWORD } = process.env;
assert(TRANSPORT_DEMO_USER && TRANSPORT_DEMO_PASSWORD, "Set the Transport Demo login credentials.");

const browser = await chromium.launch();
try {
	const context = await browser.newContext({ baseURL });
	const login = await context.request.post("/api/method/login", {
		form: { usr: TRANSPORT_DEMO_USER, pwd: TRANSPORT_DEMO_PASSWORD },
	});
	assert(login.ok(), "Transport Demo authentication failed.");
	const page = await context.newPage();
	await page.goto("/desk/transport-trip/TRIP-2026-00035");
	await page.waitForFunction(() => window.cur_frm?.docname === "TRIP-2026-00035");
	const planning = page.getByRole("button", { name: /^(Planning|Planification)$/ }).first();
	await planning.click();
	await page.getByRole("menuitem", { name: "Plan de route poids lourd", exact: true }).last().click();
	await page.waitForFunction(() => window.cur_dialog?.get_value("vehicle") === "FORM-CAMION-001");
	const defaults = await page.evaluate(() => ({
		weight: cur_dialog.get_value("cargo_kg"),
		volume: cur_dialog.fields_dict.cargo_m3.$input.val(),
		fuel: cur_dialog.fields_dict.departure_liters?.$input.val() || "",
	}));
	assert.deepEqual(defaults, { weight: 8000, volume: "", fuel: "" });
	const preview = page.waitForResponse((response) => response.url().includes("truck_plan.preview"));
	await page.getByRole("button", { name: "Calculer le plan", exact: true }).click();
	const response = await preview;
	assert(response.ok(), "Truck plan calculation failed.");
	const { message: plan } = await response.json();
	assert.equal(plan.gross_kg, 20000);
	assert.equal(plan.volume_checked, false);
	assert.equal(plan.fuel, null);
	assert(plan.truck.distance > 0 && Array.isArray(plan.tolls));
	await page.getByText(/La conformité volumétrique n’a pas été vérifiée|Volumetric compliance has not been verified/).waitFor();
	console.log("Transport Demo: itinerary, toll calculation and volume warning verified.");
} finally {
	await browser.close();
}
