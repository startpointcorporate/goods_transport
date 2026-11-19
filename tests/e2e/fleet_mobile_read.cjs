const assert = require("node:assert/strict")
const fs = require("node:fs/promises")
const path = require("node:path")
const { chromium, devices } = require("playwright")

const origin = "http://localhost:8029"
const publicDir = process.env.HRMS_PUBLIC_DIR
const screenshotDir = process.env.FLEET_CAPTURE_DIR
const user = "driver@example.test"

const trip = {
	name: "TRIP-TEST-001",
	origin: "Brazzaville",
	destination: "Kinkala",
	status: "In Transit",
	vehicle_license_plate: "TEST-001",
	planned_departure_at: "2026-11-19 08:30",
	locations: [{ name: "Kinkala", location_name: "Kinkala", latitude: -4.36, longitude: 14.77 }],
	fuel_stops: [],
	authorizations: [{ station: "Station test", fuel_type: "Diesel", authorized_liters: 80 }],
}

async function configure(context) {
	await context.addCookies([{ name: "user_id", value: user, url: origin }])
	const html = (await fs.readFile(path.join(publicDir, "frontend/index.html"), "utf8"))
		.replace("{{ csrf_token }}", "fixture")
		.replace("{{ site_name }}", "localhost")
		.replace("{{ boot }}", JSON.stringify({ lang: "fr", __messages: {}, site_name: "localhost" }))

	await context.route(origin + "/**", async route => {
		const pathname = new URL(route.request().url()).pathname
		if (pathname.startsWith("/hrms")) return route.fulfill({ contentType: "text/html", body: html })
		if (pathname.startsWith("/assets/hrms/")) {
			const relative = pathname.slice("/assets/hrms/".length)
			return route.fulfill({ path: path.join(publicDir, relative) }).catch(() => route.abort())
		}
		if (!pathname.startsWith("/api/method/")) return route.abort()
		const method = pathname.split("/").pop().split(".").pop()
		const messages = {
			get_current_user_info: { name: user, first_name: "Chauffeur test", roles: ["Fleet Driver"] },
			get_current_employee_info: { name: "EMP-TEST", user_id: user, employee_name: "Chauffeur test" },
			available: true,
			missions: { user, trips: [trip] },
		}
		return route.fulfill({ json: { message: messages[method] ?? [] } })
	})
}

async function run() {
	assert.ok(publicDir, "Set HRMS_PUBLIC_DIR to a compiled HRMS public directory")
	const browser = await chromium.launch({ executablePath: process.env.FLEET_BROWSER_PATH })
	try {
		for (const [name, options] of [
			["desktop", { viewport: { width: 1920, height: 1080 } }],
			["pixel7", devices["Pixel 7"]],
		]) {
			const context = await browser.newContext({ ...options, serviceWorkers: "block" })
			await configure(context)
			const page = await context.newPage()
			await page.goto(origin + "/hrms/home")
			await page.getByRole("link", { name: "Mes missions" }).click()
			await page.waitForURL("**/hrms/fleet")
			await page.getByRole("button", { name: /TRIP-TEST-001/ }).click()
			await page.getByRole("heading", { name: "Feuille de route" }).waitFor()
			assert.match(await page.getByRole("link", { name: "Ouvrir la navigation" }).getAttribute("href"), /maps/)
			await page.getByText("Station test", { exact: false }).waitFor()
			if (screenshotDir) {
				await fs.mkdir(screenshotDir, { recursive: true })
				await page.screenshot({ path: path.join(screenshotDir, `fleet-${name}.png`) })
			}
			await page.getByRole("link", { name: "Espace RH" }).click()
			await page.waitForURL("**/hrms/home")
			await context.close()
			console.log(`${name}: HR home → trip → location and fuel → HR home`)
		}
	} finally {
		await browser.close()
	}
}

run().catch(error => {
	console.error(error)
	process.exitCode = 1
})
