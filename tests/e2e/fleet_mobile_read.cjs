const assert = require("node:assert/strict")
const fs = require("node:fs/promises")
const path = require("node:path")
const { chromium, devices } = require("playwright")

const origin = "http://localhost:8029"
const publicDir = process.env.HRMS_PUBLIC_DIR
const screenshotDir = process.env.FLEET_CAPTURE_DIR
const user = "driver@example.test"

const inspection = {
	name: "INSPECTION-TEST", phase: "Departure", submitted: false, photos: [],
	controls: [{ code: "body", label_fr: "Carrosserie", label_en: "Bodywork", min_photos: 1 }],
}

const trip = {
	name: "TRIP-TEST-001",
	origin: "Brazzaville",
	destination: "Kinkala",
	status: "Vehicle Assigned",
	inspection_configured: true,
	inspection_controls: inspection.controls,
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
		if (method === "route_tolls") return route.fulfill({ json: {} })
		const messages = {
			get_current_user_info: { name: user, first_name: "Chauffeur test", roles: ["Fleet Driver"] },
			get_current_employee_info: { name: "EMP-TEST", user_id: user, employee_name: "Chauffeur test" },
			available: true,
			local_storage_key: { user, material: Buffer.alloc(64, 7).toString("base64") },
			sync_operation: "validated",
			missions: { user, trips: [trip] },
			present_fuel_authorizations: [{ name: "CODE-TEST", station: "Station test", authorized_liters: 80 }],
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
			await page.waitForURL("**/hrms/fleet")
			await page.getByRole("heading", { name: "TRIP-TEST-001" }).waitFor()
			await page.getByText("Feuille de route", { exact: true }).click()
			await page.getByText("Documents et péages", { exact: true }).click()
			await page.getByText("Autorisations de carburant", { exact: true }).click()
			await page.getByText("Aucun plan de péages disponible.", { exact: true }).waitFor()
			await page.getByRole("button", { name: "Synchroniser le PDF" }).waitFor()
			assert.match(await page.getByRole("link", { name: "Ouvrir la navigation" }).getAttribute("href"), /maps/)
			await page.getByText("Station test", { exact: false }).waitFor()
			if (screenshotDir) {
				await fs.mkdir(screenshotDir, { recursive: true })
				await page.screenshot({ path: path.join(screenshotDir, `fleet-${name}.png`) })
			}
			await page.getByRole("button", { name: "Faire l’état des lieux de départ", exact: true }).click()
			await page.getByLabel("Kilométrage réel").fill("1200")
			await page.getByRole("group", { name: "Carrosserie" }).getByRole("button", { name: "Conforme", exact: true }).click()
			const photoPicker = page.locator('input[type="file"]').first()
			await photoPicker.setInputFiles({ name: "invalid.txt", mimeType: "text/plain", buffer: Buffer.from("invalid") })
			await page.getByText(/Photo invalide/).waitFor()
			await photoPicker.setInputFiles({ name: "huge.jpg", mimeType: "image/jpeg", buffer: Buffer.alloc(12 * 1024 * 1024 + 1) })
			await page.getByText(/Photo invalide/).waitFor()
			const image = await page.evaluate(() => {
				const canvas = document.createElement("canvas")
				canvas.width = 2500
				canvas.height = 1400
				const fill = canvas.getContext("2d")
				fill.fillStyle = "#275c67"
				fill.fillRect(0, 0, canvas.width, canvas.height)
				const uri = canvas.toDataURL("image/jpeg", 0.98)
				return uri.split(",")[1]
			})
			await photoPicker.setInputFiles({ name: "photo.jpg", mimeType: "image/jpeg", buffer: Buffer.from(image, "base64") })
			await page.getByRole("button", { name: "Accepter", exact: true }).click()
			const upload = page.waitForRequest(request => request.url().endsWith(".sync_operation"))
			const validation = page.waitForResponse(response => response.url().endsWith(".sync_operation"))
			await page.getByRole("button", { name: "Valider", exact: true }).click()
			const data = (await upload).postDataBuffer()
			const start = data.indexOf(Buffer.from([0xff, 0xd8]))
			const end = data.indexOf(Buffer.from([0xff, 0xd9]), start + 2)
			assert.ok(start >= 0 && end >= 0 && end + 2 - start < Buffer.from(image, "base64").length)
			assert.equal((await validation).ok(), true)

			await page.getByRole("button", { name: "Consulter l’autorisation active" }).click()
			await page.getByText("CODE-TEST", { exact: true }).waitFor()
			await page.getByRole("link", { name: "Mon espace RH" }).click()
			await page.waitForURL("**/hrms/home?space=hr")
			await context.close()
			console.log(`${name}: HR home → trip → inspection, bundled photo and fuel → HR home`)
		}
	} finally {
		await browser.close()
	}
}

run().catch(error => {
	console.error(error)
	process.exitCode = 1
})
