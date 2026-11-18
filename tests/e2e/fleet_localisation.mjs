import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { promisify } from "node:util";
import { chromium } from "playwright";

const [baseURL, site, fixturePath, artifacts] = process.argv.slice(2);
assert(["127.0.0.1", "localhost"].includes(new URL(baseURL).hostname));
assert(["fleet-maint.localhost", "tyres.localhost"].includes(site));
assert(process.env.FLEET_TEST_PASSWORD);
assert(process.env.DISPLAY, "Use an isolated X11 display of 1920 × 1080");
const fixture = JSON.parse(await readFile(fixturePath, "utf8"));
await mkdir(artifacts, { recursive: true });
const exec = promisify(execFile);
const browser = await chromium.launch({
	headless: false,
	args: ["--ozone-platform=x11", "--window-position=0,0", "--window-size=1920,1080"],
});
try {
	const context = await browser.newContext({
		baseURL,
		extraHTTPHeaders: { "X-Frappe-Site-Name": site },
		viewport: null,
	});
	await context.route("**/*", route =>
		route.request().url().startsWith(baseURL + "/") ? route.continue() : route.abort());
	const login = await context.request.post("/api/method/login", {
		form: { usr: "Administrator", pwd: process.env.FLEET_TEST_PASSWORD },
	});
	assert(login.ok());
	const page = await context.newPage();
	const open = url => page.goto(url, { waitUntil: "domcontentloaded" });
	const button = name => page.getByRole("button", { name, exact: true }).filter({ visible: true }).first();
	const field = name => page.locator(`[data-fieldname="${name}"]:is(input,select,textarea):visible`).first();
	const text = value => page.getByText(value, { exact: typeof value === "string" })
		.filter({ visible: true }).first().waitFor();
	async function windowId() {
		await page.bringToFront();
		const { stdout } = await exec("xwininfo", ["-root", "-tree"]);
		const window = stdout.match(/^\s*(0x[\da-f]+)\s+"[^"\n]+":\s+\("[^"]*" "[Cc]hromium[^"]*"\)/m);
		assert(window, "Expected a Chromium window");
		await exec("xdotool", ["windowmove", window[1], "0", "0", "windowsize", "--sync", window[1], "1920", "1080"]);
		const geometry = await exec("xwininfo", ["-id", window[1]]);
		assert.match(geometry.stdout, /Width: 1920/);
		assert.match(geometry.stdout, /Height: 1080/);
		return window[1];
	}
	async function capture(name) {
		const id = await windowId();
		await exec("ffmpeg", ["-y", "-loglevel", "error", "-f", "x11grab",
			"-window_id", id, "-i", process.env.DISPLAY,
			"-frames:v", "1", join(artifacts, name + ".png")]);
		console.log(name);
	}
	const call = (method, args) => page.evaluate(async ({ method, args }) =>
		(await frappe.call({ method, args })).message, { method, args });
	const form = async (doctype, name) => {
		await open("/desk/" + doctype + "/" + encodeURIComponent(name));
		await page.waitForFunction(expected => window.cur_frm?.doc?.name === expected, name);
	};
	async function setLanguage(language) {
		const route = site === "tyres.localhost"
			? "/desk/vehicle/" + encodeURIComponent(fixture.vehicle)
			: "/desk/query-report/Fleet%20Maintenance?company=" + encodeURIComponent(fixture.company);
		await open(route);
		const token = await page.waitForFunction(() => window.frappe?.csrf_token);
		const response = await context.request.put("/api/resource/User/Administrator", {
			headers: { "X-Frappe-CSRF-Token": await token.jsonValue() },
			data: { language },
		});
		assert(response.ok(), "Failed to change the Desk user's language");
	}
	async function report(title) {
		await open("/desk/query-report/Fleet%20Maintenance?company=" + encodeURIComponent(fixture.company));
		await page.waitForFunction(() => window.frappe?.query_report?.data?.length > 0);
		await text(title);
	}
	async function tyres(label) {
		await form("vehicle", fixture.vehicle);
		await button(label).click();
		await text(label === "Tyres" ? "Fleet Tyres" : "Pneumatiques de la flotte");
	}

	await windowId();
	await setLanguage("fr");
	if (site === "tyres.localhost") {
		await tyres("Pneumatiques");
		await text("Essieu 1");
		await button("Monter").click();
		await field("tyre").selectOption(fixture.oldTyre);
		await field("warehouse").fill(fixture.mountedWarehouse);
		await field("warehouse").press("Tab");
		await button("Confirmer").click();
		await text(/PNEU-001.*Monté.*Kilométrage cumulé/);
		await capture("B-01-montage");

		await button("Permuter").click();
		await field("destination").selectOption(fixture.right);
		await field("odometer").fill("100");
		await button("Confirmer").click();
		await text(/Droite.*PNEU-001.*Kilométrage cumulé : 100 km/);
		await capture("B-02-kilometrage-cumule");

		await button("Remplacer").click();
		await field("tyre").selectOption(fixture.newTyre);
		await field("odometer").fill("100");
		await field("notes").fill("Usure du flanc");
		await button("Confirmer").click();
		await text("Le remplacement du pneu a été enregistré.");
		await text(/PNEU-002.*Monté/);
		await capture("B-03-remplacement");
		await button("PNEU-001").click();
		await text(/Remplacement définitif.*100 km.*Usure du flanc/);
		await capture("B-04-historique");

		await assert.rejects(call("goods_transport.goods_transport.services.fleet_tyres.fit", {
			vehicle: fixture.vehicle, position: fixture.left, odometer: 100,
			operation: "Mount", tyre: fixture.oldTyre, warehouse: fixture.mountedWarehouse,
		}));
		await text(/Ce pneu a été définitivement remplacé et ne peut plus être utilisé/);
		await capture("B-05-refus-remontage");

		await setLanguage("en");
		await tyres("Tyres");
		await button("Inspection").click();
		await field("inspection_type").selectOption("Pressure Check");
		await field("notes").fill("Recorded in the English Desk");
		await Promise.all([
			page.waitForResponse(response => response.url().endsWith(".fleet_tyres.overview") && response.ok()),
			button("Confirm").click(),
		]);
		await field("notes").waitFor({ state: "hidden" });
		await button("History").click();
		await text(/Inspection.*Pressure Check.*Recorded in the English Desk/);
		await capture("C-pneumatiques-anglais");
		await setLanguage("fr");
		await tyres("Pneumatiques");
		await text(/PNEU-002.*Monté.*Kilométrage cumulé/);
		await button("Historique").click();
		await text(/Inspection.*Contrôle de la pression/);
		await capture("D-pneumatiques-retour-francais");
	} else {
		await report("Maintenance de la flotte");
		await text("Véhicule disponible");
		await capture("A-01-tableau-de-bord");
		await form("vehicle", fixture.vehicle);
		await text("Actif suivi pour la maintenance");

		await form("vehicle-maintenance-schedule", fixture.schedule);
		await text("Échéance kilométrique (km)");
		await field("interval_km").fill("11000");
		await field("interval_km").press("Tab");
		await button("Enregistrer").click();
		await page.waitForFunction(() => cur_frm.doc.due_odometer === "91000" && !cur_frm.is_dirty());
		await capture("A-02-plan-et-echeance");

		await form("transport-trip", fixture.maintenanceTrip);
		await field("departure_odometer").fill("85000");
		await field("arrival_odometer").fill("90000");
		await field("arrival_odometer").press("Tab");
		await page.locator(".primary-action:visible").first().click();
		await page.waitForFunction(() => cur_frm.doc.arrival_odometer === "90000" && !cur_frm.is_dirty());
		await capture("A-03-releve");
		await call("goods_transport.goods_transport.doctype.transport_trip.transport_trip.advance_status", {
			trip: fixture.maintenanceTrip, to_status: "Arrived",
		});

		await form("vehicle-maintenance-schedule", fixture.schedule);
		await button("Enregistrer un entretien").click();
		await field("odometer").fill("90000");
		await field("details").fill("Vidange et remplacement du filtre");
		await page.locator(".modal:visible .btn-modal-primary:visible").click();
		await page.waitForFunction(() => cur_frm.doc.due_odometer === "101000");
		await capture("A-04-entretien");

		await page.evaluate(({ vehicle, company }) => frappe.new_doc("Vehicle Immobilisation", {
			vehicle, company, reason: "Breakdown",
		}), fixture);
		await text("Gravité");
		await field("description").fill("Défaut de freinage fictif");
		await field("description").press("Tab");
		await button("Enregistrer").click();
		await page.waitForFunction(() => cur_frm.doctype === "Vehicle Immobilisation" && !cur_frm.is_new());
		await text("Remise en service");
		await capture("A-05-panne");
		const incident = page.url();
		await form("transport-trip", fixture.pendingTrip);
		const trip = await call("frappe.client.get", { doctype: "Transport Trip", name: fixture.pendingTrip });
		await assert.rejects(call("frappe.client.submit", { doc: trip }));
		await text(/est immobilisé/);
		await capture("A-06-refus-affectation");
		await open(incident);
		await text("Remise en service");
		for (const [route, doctype, name] of [
			["stock-entry", "Stock Entry", fixture.issue],
			["purchase-invoice", "Purchase Invoice", fixture.invoice],
		]) {
			await form(route, name);
			const doc = await call("frappe.client.get", { doctype, name });
			await call("frappe.client.submit", { doc });
		}
		await form("purchase-invoice", fixture.invoice);
		await text("Catégorie de coût de maintenance");
		await capture("A-07-facture-reparation");
		await report("Maintenance de la flotte");
		await text("Coût de maintenance");
		await page.waitForFunction(vehicle =>
			frappe.query_report.data.some(row => row.vehicle === vehicle && row.charges === 180000),
			fixture.costVehicle);
		await capture("A-08-couts");

		await setLanguage("en");
		await report("Fleet Maintenance");
		await text("Maintenance Charges");
		await form("vehicle-maintenance-schedule", fixture.schedule);
		await button("Record Maintenance").click();
		await text("Work Performed");
		await capture("C-maintenance-anglais");
		await field("odometer").fill("90000");
		await field("details").fill("Maintenance recorded in the English Desk");
		await page.locator(".modal:visible .btn-modal-primary:visible").click();
		await text("Maintenance recorded in the English Desk");
		await setLanguage("fr");
		await report("Maintenance de la flotte");
		await text("Coût de maintenance");
		await capture("D-maintenance-retour-francais");
	}
} finally {
	await browser.close();
}
