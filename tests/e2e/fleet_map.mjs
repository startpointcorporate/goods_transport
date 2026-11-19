import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { chromium } from "playwright";

const [base, fixturePath, screenshots] = process.argv.slice(2);
const fixture = JSON.parse(await readFile(fixturePath, "utf8"));
const endpoint = "/api/method/goods_transport.goods_transport.services.fleet_map.mission";
const browser = await chromium.launch({
	executablePath: process.env.FLEET_CHROMIUM || undefined,
	args: ["--no-sandbox"],
});
await mkdir(screenshots, { recursive: true });

async function screenshot(page, name) {
	await page.screenshot({ path: screenshots + "/" + name + ".png" });
}

async function login(user, pwd) {
	const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
	// Use fixture tiles for repeated CI runs and leave network tiles enabled for manual recipe captures.
	if (!process.env.FLEET_REAL_TILES) await context.route("https://tile.openstreetmap.org/**", (route) =>
		route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#eaf0ed"/></svg>' }));
	const result = await context.request.post(base + "/api/method/login", { form: { usr: user, pwd } });
	assert.equal(result.status(), 200, await result.text());
	return context;
}

async function mission(context, name) {
	const result = await context.request.get(base + endpoint, { params: { trip_name: name } });
	assert.equal(result.status(), 200, (await result.text()).slice(0, 500));
	return (await result.json()).message;
}

async function language(page, lang) {
	await page.evaluate(async (lang) => {
		await frappe.xcall("frappe.client.set_value", {
			doctype: "User", name: frappe.session.user, fieldname: "language", value: lang,
		});
	}, lang);
	await page.reload();
	await page.waitForFunction((lang) => frappe.boot.lang === lang, lang);
}

try {
	const admin = await login("Administrator", process.env.FLEET_TEST_PASSWORD);
	const page = await admin.newPage();
	page.on("pageerror", (error) => console.error(error.message));
	await page.goto(base + "/app/fleet-map");
	await page.waitForFunction(() => window.frappe?.boot?.lang);
	await language(page, "en");
	await page.getByText("Select a transport trip", { exact: false }).waitFor();
	await page.locator("[data-fleet-map] .leaflet-tile-loaded").first().waitFor();
	await screenshot(page, "01-fleet-overview-en");

	const data = await mission(admin, fixture.trip);
	assert.ok(data.routes.truck.distance > 500000);
	assert.ok(data.routes.car.geometry.coordinates.length > 100);
	assert.deepEqual(data.points.map((point) => point.kind), ["origin", "via", "destination"]);
	assert.ok(data.tolls.some((toll) => toll.amount === 15000 && toll.currency === "XAF"));
	assert.ok(data.tolls.some((toll) => toll.amount == null));
	assert.deepEqual(data.tolls.map((toll) => toll.position_m), data.tolls.map((toll) => toll.position_m).sort((a, b) => a - b));
	assert.ok(data.stations.some((station) => station.state === "selected" && station.planned_liters > 0 && station.authorized_liters === 100));
	assert.ok(data.stations.some((station) => station.state === "available" && station.reserves.length));
	assert.ok(data.stations.some((station) => station.state === "unavailable"));
	assert.ok(!JSON.stringify(data).includes("MAP-QA-RESERVE-4"));
	assert.ok(!JSON.stringify(data).includes("étrangère"));
	assert.equal(data.gps.state, "recent");

	await page.goto(base + "/app/transport-trip/" + fixture.trip);
	await page.getByRole("button", { name: "View on map" }).click();
	await page.getByText("Truck route ·", { exact: false }).first().waitFor();
	await page.locator("[data-fleet-map] .leaflet-overlay-pane path").first().waitFor();
	const road = page.locator("[data-fleet-map] .leaflet-overlay-pane path").first();
	await page.locator("[data-fleet-map] .leaflet-tile-loaded").first().waitFor();
	await screenshot(page, "02-mission-en");
	await page.getByRole("button", { name: /Péage QA vérifié/ }).scrollIntoViewIfNeeded();
	await screenshot(page, "03-tolls-stations-fuel-en");

	await page.evaluate(async ({ name, via }) => {
		const doc = (await frappe.xcall("frappe.client.get", { doctype: "Transport Trip", name }));
		const args = { ...JSON.parse(doc.fuel_plan_inputs), via };
		await frappe.xcall("frappe.client.set_value", {
			doctype: "Transport Trip", name, fieldname: "fuel_plan_inputs", value: JSON.stringify(args),
		});
	}, { name: fixture.trip, via: fixture.changedVia });
	const current = await mission(admin, fixture.trip);
	assert.equal(current.points[1].name, fixture.changedVia);
	assert.notDeepEqual(current.routes.truck.geometry.coordinates, data.routes.truck.geometry.coordinates);
	await page.getByRole("button", { name: "Refresh map" }).click();
	await page.getByRole("button", { name: /Nouvelle étape RN1/ }).waitFor();
	assert.ok(await road.count());
	await screenshot(page, "04-recalculated-route-en");

	await language(page, "fr");
	await page.getByText("Dernier relevé", { exact: false }).first().waitFor();
	await page.getByText("Itinéraire poids lourd ·", { exact: false }).first().waitFor();
	await page.locator("[data-fleet-map] .leaflet-tile-loaded").first().waitFor();
	await screenshot(page, "05-mission-position-recente-fr");
	await page.goto(base + "/app/fleet-map/" + fixture.stale);
	await page.locator("[data-gps-status=stale]").getByText(/Position ancienne/).waitFor();
	assert.equal((await mission(admin, fixture.stale)).gps.age_minutes, 25);
	await screenshot(page, "06-position-ancienne-fr");
	await page.goto(base + "/app/fleet-map/" + fixture.missing);
	await page.getByText("Dernière position connue indisponible", { exact: true }).waitFor();
	await screenshot(page, "07-position-indisponible-fr");

	const restricted = await login("fleet-map-no-access@example.test", process.env.FLEET_RESTRICTED_PASSWORD);
	const forbidden = await restricted.request.get(base + endpoint, { params: { trip_name: fixture.trip } });
	assert.equal(forbidden.status(), 403);
	const guest = await browser.newContext();
	const denied = await guest.request.get(base + endpoint, { params: { trip_name: fixture.trip } });
	assert.ok([401, 403].includes(denied.status()));
	console.log("Desk, OSRM, tolls, stations, refresh, permissions, EN/FR and GPS passed.");
} finally {
	await browser.close();
}
