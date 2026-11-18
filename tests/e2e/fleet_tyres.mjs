import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { chromium } from "playwright";

const [baseURL, fixtureFile, artifacts] = process.argv.slice(2);
const fixture = JSON.parse(await readFile(fixtureFile, "utf8"));
assert(["localhost", "127.0.0.1", "tyres.localhost"].includes(new URL(baseURL).hostname));
assert(process.env.FLEET_TEST_PASSWORD);
await mkdir(artifacts, { recursive: true });
const browser = await chromium.launch();
try {
	const context = await browser.newContext({ baseURL, viewport: { width: 1920, height: 1080 } });
	const login = await context.request.post("/api/method/login", {
		form: { usr: "Administrator", pwd: process.env.FLEET_TEST_PASSWORD },
	});
	assert(login.ok(), "Desk login failed");
	const page = await context.newPage();
	page.on("response", async response => {
		if (response.status() >= 400 && response.url().includes(".fleet_tyres.")) {
			const result = await response.json();
			console.log(response.status(), result._server_messages || result.exc_type);
		}
	});
	await page.goto("/desk/vehicle/" + encodeURIComponent(fixture.vehicle));
	const button = (name) => page.getByRole("button", { name, exact: true }).filter({ visible: true }).first();
	const service = "goods_transport.goods_transport.services.fleet_tyres.";
	const call = (method, args) => page.evaluate(async ({ method, args }) => {
		try {
			await frappe.call({ method, args });
			return true;
		} catch {
			return false;
		}
	}, { method: service + method, args });
	const capture = (name) => page.screenshot({ path: join(artifacts, name + ".png") });
	await button("Tyres").click();
	assert(await call("fit", {
		vehicle: fixture.vehicle, position: fixture.left, odometer: 0, operation: "Mount",
		tyre: fixture.oldTyre, warehouse: fixture.mountedWarehouse,
	}));
	await page.reload();
	await button("Tyres").click();
	await page.getByText(/Left · PNEU-001/).waitFor();
	await capture("A-installation");

	await button("Replace").click();
	await page.locator('select[data-fieldname="tyre"]:visible').selectOption(fixture.newTyre);
	await page.locator('textarea[data-fieldname="notes"]:visible').fill("Worn sidewall");
	await button("Confirm").click();
	await page.getByText(/Left · PNEU-002/).waitFor();
	await capture("C-replacement");
	await button("PNEU-001").click();
	await page.getByText(/Retire.*Worn sidewall/).waitFor();
	await capture("C-retired-history");

	for (const [vehicle, position] of [[fixture.vehicle, fixture.right], [fixture.otherVehicle, fixture.other]]) {
		assert.equal(await call("fit", {
			vehicle, position, odometer: 0, operation: "Mount",
			tyre: fixture.oldTyre, warehouse: fixture.mountedWarehouse,
		}), false, "The API must refuse retirement reversal");
	}
	const directWrite = await context.request.put("/api/resource/Fleet%20Tyre/" + fixture.oldTyre, {
		data: { state: "Available" },
	});
	assert(!directWrite.ok(), "Direct document writes must also refuse retirement reversal");
	await page.reload();
	await button("Tyres").click();
	await button("Mount").click();
	const choices = await page.locator('select[data-fieldname="tyre"]:visible option').allTextContents();
	assert(choices.every(choice => !choice.includes("PNEU-001")));
	await capture("D-retired-unavailable");
} finally {
	await browser.close();
}
