import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { promisify } from "node:util";
import { chromium } from "playwright";

const exec = promisify(execFile);
const [baseURL, fixtureFile, artifacts] = process.argv.slice(2);
const fixture = JSON.parse(await readFile(fixtureFile, "utf8"));
assert(["localhost", "127.0.0.1"].includes(new URL(baseURL).hostname));
assert(process.env.FLEET_TEST_PASSWORD);
assert(process.env.DISPLAY, "Use an isolated X server running at 1920 × 1080");
const browser = await chromium.launch({
	headless: false,
	args: ["--ozone-platform=x11", "--window-position=0,0", "--window-size=1920,1080"],
});
try {
	const context = await browser.newContext({ baseURL, viewport: null });
	await context.route("**/*", route =>
		route.request().url().startsWith(baseURL) ? route.continue() : route.abort());
	const login = await context.request.post("/api/method/login", {
		form: { usr: "Administrator", pwd: process.env.FLEET_TEST_PASSWORD },
	});
	assert(login.ok(), "Desk login failed");

	const page = await context.newPage();
	async function capture(scenario, name) {
		const folder = join(artifacts, scenario);
		await mkdir(folder, { recursive: true });
		await page.bringToFront();
		const { stdout } = await exec("xwininfo", ["-root", "-tree"]);
		const match = stdout.match(/^\s*(0x[\da-f]+)\s+"[^"\n]+":\s+\("[^"]*" "[Cc]hromium[^"]*"\)/m);
		assert(match, "Expected a Chromium window");
		await exec("xdotool", ["windowmove", match[1], "0", "0", "windowsize", "--sync", match[1], "1920", "1080"]);
		const geometry = await exec("xwininfo", ["-id", match[1]]);
		assert.match(geometry.stdout, /Width: 1920/);
		assert.match(geometry.stdout, /Height: 1080/);
		await exec("ffmpeg", ["-y", "-loglevel", "error", "-f", "x11grab",
			"-window_id", match[1], "-i", process.env.DISPLAY,
			"-frames:v", "1", join(folder, name + ".png")]);
	}
	async function openForm(slug, name) {
		await page.goto("/desk/" + slug + "/" + encodeURIComponent(name));
		await page.waitForFunction(expected => window.cur_frm?.doc?.name === expected, name);
	}
	const tripForm = name => openForm("transport-trip", name);
	const action = name => page.getByRole("button", { name, exact: true }).filter({ visible: true }).first();
	async function submitViaAPI() {
		const url = "/api/resource/Transport%20Trip/" + encodeURIComponent(fixture.pendingTrip);
		const response = await context.request.get(url);
		assert(response.ok());
		const { data: doc } = await response.json();
		return page.evaluate(async doc => {
			try {
				await frappe.call({ method: "frappe.client.submit", args: { doc } });
				return true;
			} catch {
				return false;
			}
		}, doc);
	}

	async function enterReadings(end) {
		const departure = page.locator('input[data-fieldname="departure_odometer"]');
		const arrival = page.locator('input[data-fieldname="arrival_odometer"]');
		await departure.fill("85000");
		await departure.press("Tab");
		await arrival.fill(end);
		await arrival.press("Tab");
		await page.waitForFunction(expected => cur_frm.doc.arrival_odometer === expected && cur_frm.is_dirty(), end);
		await action("Update").click();
		await page.waitForFunction(expected => cur_frm.doc.arrival_odometer === expected && !cur_frm.is_dirty(), end);
	}
	async function arrive(distance) {
		await page.locator(".inner-group-button[data-label=Actions] button:visible").click();
		await page.getByText("Advance Status", { exact: true }).filter({ visible: true }).click();
		await page.locator(".modal.show select[data-fieldname=to_status]").selectOption("Arrived");
		await page.locator(".modal.show").getByRole("button", { name: "Submit", exact: true }).click();
		await page.waitForFunction(expected => cur_frm.doc.status === "Arrived" && cur_frm.doc.actual_distance === expected, distance);
	}
	async function submitFromDesk() {
		await action("Submit").click();
		const confirm = page.locator(".modal.show").getByRole("button", { name: "Yes", exact: true });
		await confirm.click();
		const postingDate = page.locator(".modal.show").filter({ hasText: "Posting Date will change" });
		const completed = page.waitForFunction(() => cur_frm.doc.docstatus === 1);
		await Promise.race([completed, postingDate.waitFor()]);
		if (await postingDate.isVisible()) {
			await postingDate.getByRole("button", { name: "Yes", exact: true }).click();
		}
		await completed;
	}

	await openForm("vehicle-maintenance-schedule", fixture.schedule);
	await page.waitForFunction(() => cur_frm.doc.due_odometer === "90000");
	await capture("A-preventif", "01-echeance-initiale");
	await tripForm(fixture.maintenanceTrip);
	await enterReadings("90000");
	await arrive(5000);
	await openForm("vehicle-maintenance-schedule", fixture.schedule);
	await action("Record Maintenance").click();
	const dialog = page.locator(".modal.show");
	await dialog.locator('input[data-fieldname="odometer"]').fill("90000");
	await dialog.locator('textarea[data-fieldname="details"]').fill("Engine oil and filter replaced");
	await dialog.locator('textarea[data-fieldname="details"]').press("Tab");
	await capture("A-preventif", "02-avant-entretien");
	await dialog.getByRole("button", { name: "Submit", exact: true }).click();
	await page.waitForFunction(() => cur_frm.doc.due_odometer === "100000");
	await capture("A-preventif", "03-echeance-recalculee");

	await tripForm(fixture.trip);
	await page.locator('input[data-fieldname="departure_odometer"]').scrollIntoViewIfNeeded();
	await capture("B-kilometrage", "01-avant-releves");
	await enterReadings("85600");
	await capture("B-kilometrage", "02-releves-enregistres");
	await arrive(600);
	await capture("B-kilometrage", "03-arrivee-distance-verifiee");

	await tripForm(fixture.pendingTrip);
	await page.evaluate(({ vehicle, company }) => frappe.new_doc("Vehicle Immobilisation", {
		vehicle, company, reason: "Breakdown",
	}), fixture);
	await page.waitForFunction(() => cur_frm?.doctype === "Vehicle Immobilisation");
	const description = page.locator('textarea[data-fieldname="description"]');
	await description.fill("Fictitious brake fault");
	await description.press("Tab");
	await page.waitForFunction(() => cur_frm.doc.description === "Fictitious brake fault");
	await capture("C-immobilisation", "01-avant-declaration");
	await action("Save").click();
	await page.waitForFunction(() => cur_frm?.doctype === "Vehicle Immobilisation" && !cur_frm.is_new());
	const incidentURL = page.url();
	await capture("C-immobilisation", "02-panne-enregistree");
	await tripForm(fixture.pendingTrip);
	await capture("C-immobilisation", "02b-avant-refus-affectation");
	assert.equal(await submitViaAPI(), false, "API accepted an immobilised vehicle");
	await capture("C-immobilisation", "03-affectation-refusee");
	await page.goto(incidentURL);
	await page.waitForFunction(() => window.cur_frm?.doctype === "Vehicle Immobilisation");
	const resolution = page.locator('textarea[data-fieldname="resolution"]');
	await resolution.fill("Brake inspection completed");
	await resolution.press("Tab");
	await page.waitForFunction(() => cur_frm.doc.resolution === "Brake inspection completed");
	await capture("C-immobilisation", "04-avant-remise-en-service");
	await action("Return to Service").click();
	await page.waitForFunction(() => !!cur_frm.doc.released_at);
	await capture("C-immobilisation", "05-remise-en-service");
	await tripForm(fixture.pendingTrip);
	await capture("C-immobilisation", "05b-avant-affectation");
	assert.equal(await submitViaAPI(), true, "Released vehicle could not be assigned");
	await page.reload();
	await page.waitForFunction(() => window.cur_frm?.doc?.status === "Vehicle Assigned");
	await capture("C-immobilisation", "06-affectation-acceptee");


	async function openCostReport(expected) {
		await page.goto("/desk/query-report/Fleet%20Maintenance?company=" + encodeURIComponent(fixture.company));
		await page.waitForFunction(() => window.frappe.query_report?.report_name === "Fleet Maintenance");
		await page.waitForFunction(({ vehicle, charges }) =>
			frappe.query_report.data?.some(row => row.vehicle === vehicle && row.charges === charges),
			{ vehicle: fixture.costVehicle, charges: expected });
	}

	await openCostReport(0);
	await capture("E-couts", "01-avant-comptabilisation");
	await openForm("stock-entry", fixture.issue);
	await capture("D-reparation", "01-avant-sortie-de-stock");
	await submitFromDesk();
	await capture("D-reparation", "02-sortie-comptabilisee");
	await openForm("purchase-invoice", fixture.invoice);
	await capture("D-reparation", "03-avant-facture");
	await submitFromDesk();
	await capture("D-reparation", "04-facture-comptabilisee");
	await openCostReport(180000);
	await page.waitForFunction(vehicle =>
		frappe.query_report.data.some(row => row.vehicle === vehicle && row.cost_per_km === 300),
		fixture.costVehicle);
	await page.locator(".dt-scrollable").evaluate(table => { table.scrollLeft = table.scrollWidth; });
	await capture("E-couts", "02-charges-et-cout-par-kilometre");
} finally {
	await browser.close();
}
