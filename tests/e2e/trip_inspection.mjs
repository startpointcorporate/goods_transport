import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { promisify } from "node:util";
import { chromium, devices } from "playwright";

const exec = promisify(execFile);
const [baseURL, fixturePath, directory, departurePhoto, returnPhoto] = process.argv.slice(2);
const fixtures = JSON.parse(await readFile(fixturePath, "utf8"));
assert.equal(new URL(baseURL).hostname, "127.0.0.1");
assert(process.env.DISPLAY && process.env.FLEET_TEST_PASSWORD);
const service = "goods_transport.goods_transport.services.trip_inspection";
const lifecycle = "goods_transport.goods_transport.doctype.transport_trip.transport_trip.advance_status";
await mkdir(directory, { recursive: true });
const browser = await chromium.launch({
	headless: false,
	args: ["--ozone-platform=x11", "--kiosk", "--window-position=0,0", "--window-size=1920,1080"],
});
try {
	const context = await browser.newContext({ baseURL, viewport: null });
	context.setDefaultTimeout(15000);
	const page = await context.newPage();
	page.on("pageerror", (error) => console.error(error.message));
	const devtools = await context.newCDPSession(page);
	const { windowId } = await devtools.send("Browser.getWindowForTarget");
	const { bounds } = await devtools.send("Browser.getWindowBounds", { windowId });
	if (bounds.windowState !== "fullscreen") {
		await devtools.send("Browser.setWindowBounds", { windowId, bounds: { windowState: "fullscreen" } });
	}
	const loggedIn = await context.request.post("/api/method/login", {
		form: { usr: "Administrator", pwd: process.env.FLEET_TEST_PASSWORD },
	});
	assert(loggedIn.ok());
	async function rpc(method, values, ok = true) {
		const response = await page.evaluate(async ({ method, values }) => {
			const res = await fetch("/api/method/" + method, {
				method: "POST", credentials: "same-origin",
				headers: { "Content-Type": "application/json", "X-Frappe-CSRF-Token": frappe.csrf_token },
				body: JSON.stringify(values),
			});
			return { ok: res.ok, body: await res.json() };
		}, { method, values });
		assert.equal(response.ok, ok, JSON.stringify(response.body));
		return response.body.message;
	}
	async function capture(file) {
		const dimensions = await page.evaluate(() => [screen.width, screen.height, innerWidth, innerHeight]);
		assert.deepEqual(dimensions.slice(0, 2), [1920, 1080]);
		assert(dimensions[2] >= 1919 && dimensions[3] >= 1079);
		const output = join(directory, file + ".png");
		await exec("ffmpeg", ["-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1920x1080",
			"-i", process.env.DISPLAY + "+0,0", "-frames:v", "1", output]);
		const raster = await readFile(output);
		assert.equal(raster.readUInt32BE(16), 1920);
		assert.equal(raster.readUInt32BE(20), 1080);
	}
	async function route(mission) {
		await page.goto("/desk/transport-trip/" + encodeURIComponent(mission.trip));
		await page.waitForFunction((name) => window.cur_frm?.doc?.name === name, mission.trip);
		await page.getByRole("button", { name: "Departure Inspection", exact: true }).waitFor();
	}
	function modal() {
		return page.locator(".modal.show").last();
	}
	async function open(phase) {
		await page.getByRole("button", { name: phase + " Inspection", exact: true }).click();
		await modal().getByRole("heading", { name: "Bodywork", exact: true }).waitFor();
	}
	async function fill(odometer, observation, critical = false) {
		await modal().getByLabel("Actual Odometer (km)").fill(String(odometer));
		for (const code of ["body", "brakes", "papers"]) {
			const row = modal().locator('[data-control="' + code + '"]');
			const anomaly = critical ? code === "brakes" : observation && code === "body";
			await row.getByLabel("Result").selectOption(anomaly ? "Fail" : "Pass");
			if (anomaly) {
				await row.getByLabel("Defect Code").fill(critical ? "brake-failure" : observation);
				await row.getByLabel("Severity").selectOption(critical ? "Critical" : "Minor");
				await row.getByLabel("Observation", { exact: true }).fill(critical ? "Critical braking defect" : observation);
			}
		}
	}
	async function upload(file, camera = false) {
		const row = modal().locator('[data-control="body"]');
		const input = camera ? row.locator('input[capture="environment"]') : row.locator('input[type="file"]:not([capture])');
		await input.setInputFiles(file);
		await row.getByRole("button", { name: "Enlarge photograph" }).waitFor();
		await row.getByRole("button", { name: "Enlarge photograph" }).scrollIntoViewIfNeeded();
		await row.locator("img").evaluate((img) => img.decode());
	}
	async function validate() {
		await modal().getByRole("button", { name: "Validate Inspection", exact: true }).click();
		await modal().getByText("Validated", { exact: true }).waitFor();
	}
	async function close() {
		await modal().getByRole("button", { name: "Close", exact: true }).first().click();
		await page.locator(".modal.show").waitFor({ state: "hidden" });
	}
	async function deliver(mission) {
		await rpc(lifecycle, { trip: mission.trip, to_status: "In Transit" });
		await rpc(lifecycle, { trip: mission.trip, to_status: "Unloading" });
		await rpc("frappe.client.insert", { doc: {
			doctype: "Proof of Delivery", bilty: mission.bilty, delivered_quantity: 1000, receiver_name: "Test receiver", docstatus: 1,
		} });
		await rpc(lifecycle, { trip: mission.trip, to_status: "Delivered" });
		await page.reload();
	}

	for (const scenario of ["B", "A", "C"]) {
		const mission = fixtures[scenario];
		const detailed = scenario === "B";
		await route(mission);
		await rpc(lifecycle, { trip: mission.trip, to_status: "In Transit" }, false);
		await open("Departure");
		await fill(100, scenario === "C" ? "Existing scratch" : null);
		if (detailed) await capture("01-etat-depart");
		await upload(departurePhoto, true);
		if (detailed) await capture("02-photo-depart");
		await validate();
		if (detailed) await capture("03-depart-valide");
		await close();
		await deliver(mission);
		await rpc(lifecycle, { trip: mission.trip, to_status: "Closed" }, false);
		await open("Return");
		await fill(680, scenario === "A" ? null : scenario === "B" ? "New impact" : "Existing scratch");
		await upload(returnPhoto);
		if (detailed) await capture("04-etat-retour");
		await validate();
		await close();
		await page.getByRole("button", { name: "Compare Vehicle Inspections", exact: true }).click();
		await modal().getByText("Actual Distance (km) · 580", { exact: true }).waitFor();
		const expected = scenario === "A" ? "Unchanged" : scenario === "B" ? "New Defect" : "Existing Defect";
		await modal().getByText("Bodywork · " + expected).waitFor();
		if (detailed) {
			await capture("05-synthese-conformite");
			await modal().getByText("Bodywork · New Defect").scrollIntoViewIfNeeded();
			await capture("06-comparaison");
			const bodywork = modal().locator("section").filter({ hasText: "Bodywork · New Defect" });
			await bodywork.getByRole("button", { name: "Enlarge photograph" }).last().click();
			await page.locator("dialog[open]").getByRole("button", { name: "Close" }).click();
			await close();
			await open("Return");
			await modal().getByLabel("Observation", { exact: true }).first().scrollIntoViewIfNeeded();
			await capture("07-nouvelle-anomalie");
			await modal().getByRole("button", { name: "Create Maintenance Repair" }).click();
			await page.waitForURL(/asset-repair/);
			await page.getByText("Trip Vehicle Inspection", { exact: true }).waitFor();
			await capture("08-intervention-maintenance");
			const data = await rpc(service + ".compare", { trip: mission.trip });
			const anonymous = await browser.newContext({ baseURL });
			assert(!(await anonymous.request.get(data.after.photos[0].file_url)).ok(), "A guest can retrieve inspection evidence");
			assert(!(await anonymous.request.get("/api/method/" + service + ".compare?trip=" + encodeURIComponent(mission.trip))).ok());
			await anonymous.close();
			await rpc(service + ".upload_photo", { inspection: data.after.name, control: "body" }, false);
			await rpc("frappe.client.set_value", { doctype: "Trip Vehicle Inspection", name: data.after.name, fieldname: "observations", value: "Tampered" }, false);
		} else {
			await modal().getByText("Vehicle Compliance · Compliant").waitFor();
			await close();
		}
	}
	await route(fixtures.D);
	const incomplete = await rpc(service + ".open_inspection", { trip: fixtures.D.trip, phase: "Departure" });
	await rpc(service + ".validate_inspection", { inspection: incomplete.name, odometer: "100", results: {} }, false);
	await route(fixtures.E);
	await open("Departure");
	await fill(100);
	await upload(departurePhoto);
	await validate();
	await close();
	await deliver(fixtures.E);
	const incoherent = await rpc(service + ".open_inspection", { trip: fixtures.E.trip, phase: "Return" });
	await rpc(service + ".validate_inspection", { inspection: incoherent.name, odometer: "99", results: {} }, false);
	await route(fixtures.F);
	await open("Departure");
	await fill(100, null, true);
	await upload(departurePhoto);
	await validate();
	await close();
	await rpc(lifecycle, { trip: fixtures.F.trip, to_status: "In Transit" }, false);
	const mobile = await browser.newContext({ ...devices["iPhone 13"], baseURL, storageState: await context.storageState() });
	const phone = await mobile.newPage();
	await phone.goto("/desk/transport-trip/" + encodeURIComponent(fixtures.B.trip));
	await phone.waitForFunction((name) => window.cur_frm?.doc?.name === name, fixtures.B.trip);
	await phone.locator(".page-actions .menu-btn-group button:visible").first().click();
	await phone.getByText("Compare Vehicle Inspections", { exact: true }).filter({ visible: true }).click();
	await phone.getByText("Bodywork · New Defect").waitFor();
	await mobile.close();
	console.log("Inspection Desk A–G passed");
} catch (error) {
	for (const context of browser.contexts()) {
		for (const page of context.pages()) {
			console.error(page.url(), await page.title(), (await page.locator("body").innerText()).slice(0, 1600));
			console.error(await page.evaluate(() => ({name: window.cur_frm?.doc?.name, policy: Boolean(window.cur_frm?.doc?.inspection_policy)})));
		}
	}
	throw error;
} finally {
	await browser.close();
}
