const assert = require("node:assert/strict")
const { readFile } = require("node:fs/promises")
const http = require("node:http")
const path = require("node:path")
const { chromium, devices } = require("playwright")

const publicDir = process.env.HRMS_PUBLIC_DIR
const driver = "driver-a@example.test"
const otherDriver = "driver-b@example.test"
const suffix = "goods_transport.goods_transport.services.fleet_driver."
const mime = { ".js": "application/javascript", ".css": "text/css", ".html": "text/html" }
let revision = 1

async function serve(request, response) {
	const pathname = new URL(request.url, "http://localhost").pathname
	if (pathname === "/api/method/" + suffix + "service_worker") {
		response.setHeader("Service-Worker-Allowed", "/hrms")
		response.setHeader("Content-Type", "application/javascript")
		response.end(await readFile(path.join(publicDir, "frontend/sw.js")))
	} else if (pathname.startsWith("/assets/hrms/")) {
		const asset = pathname.slice("/assets/hrms/".length)
		if (mime[path.extname(asset)]) response.setHeader("Content-Type", mime[path.extname(asset)])
		response.end(await readFile(path.join(publicDir, asset)))
	} else if (pathname.startsWith("/hrms")) {
		const html = (await readFile(path.join(publicDir, "frontend/index.html"), "utf8"))
			.replace("{{ csrf_token }}", "fixture")
			.replace("{{ site_name }}", "localhost")
			.replace("{{ boot }}", JSON.stringify({ lang: "fr", __messages: {}, site_name: "localhost" }))
		response.setHeader("Cache-Control", "no-store")
		response.setHeader("Content-Type", "text/html")
		response.end(html)
	} else if (pathname.startsWith("/api/method/")) {
		const user = new URLSearchParams((request.headers.cookie || "").replaceAll("; ", "&")).get("user_id")
		const trip = {
			name: user === driver ? "TEST-A-" + revision : "TEST-B",
			modified: "revision-" + revision,
			status: "In Transit", origin: "Départ", destination: "Destination",
			locations: [{ name: "Destination", location_name: "Destination" }],
			fuel_stops: [], authorizations: [],
		}
		const method = pathname.split(".").pop()
		if (method === "road_sheet_pdf" || method === "mission_file") {
			response.setHeader("Content-Type", "application/pdf")
			return response.end("%PDF-1.4 fixture")
		}
		const fixtures = {
			mission_files: revision === 1 ? [{ name: "FILE-1", file_name: "Consigne privée.pdf", modified: "version-1" }] : [],
			route_tolls: [{ name: "Péage test", axis: "RN1", latitude: -4.3, longitude: 15.1 }],
			get_current_employee_info: { name: "EMP-TEST", user_id: user },
			get_current_user_info: { name: user, roles: ["Fleet Driver"] },
			available: true,
			missions: { user, trips: [trip] },
		}
		response.setHeader("Content-Type", "application/json")
		response.end(JSON.stringify({ message: fixtures[method] ?? [] }))
	} else {
		response.writeHead(404).end()
	}
}

async function run() {
	assert.ok(publicDir, "Set HRMS_PUBLIC_DIR to a compiled HRMS public directory")
	const server = http.createServer((req, res) => {
		serve(req, res).catch(() => res.writeHead(404).end())
	})
	await new Promise(resolve => server.listen(0, "127.0.0.1", resolve))
	const origin = "http://127.0.0.1:" + server.address().port
	let browser
	try {
		browser = await chromium.launch({ executablePath: process.env.FLEET_BROWSER_PATH })
		const context = await browser.newContext(devices["Pixel 7"])
		const setUser = user => context.addCookies([{ name: "user_id", value: user, url: origin }])
		await setUser(driver)
		let page = await context.newPage()
		await page.goto(origin + "/hrms/fleet")
		await page.getByRole("heading", { name: "TEST-A-1" }).waitFor()
		await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller))
		await page.getByText("Documents et péages", { exact: true }).click()
		await page.getByText("Péage test", { exact: true }).waitFor()
		await page.getByRole("button", { name: "Synchroniser le PDF" }).click()
		await page.getByRole("link", { name: "Télécharger le PDF" }).waitFor()
		await page.getByRole("button", { name: "Synchroniser", exact: true }).click()
		await page.getByRole("link", { name: "Consulter", exact: true }).waitFor()
		await page.close()
		await context.setOffline(true)
		page = await context.newPage()
		await page.goto(origin + "/hrms")
		await page.getByText(/Hors ligne/).waitFor()
		await page.getByText("Documents et péages", { exact: true }).click()
		await page.getByText("Péage test", { exact: true }).waitFor()
		await page.getByRole("link", { name: "Prévisualiser le PDF" }).waitFor()
		await page.getByText("Consigne privée.pdf", { exact: true }).waitFor()
		await page.getByRole("link", { name: "Consulter", exact: true }).waitFor()
		assert.equal(await page.getByRole("button", { name: "Synchroniser le PDF" }).isDisabled(), true)
		assert.equal(await page.getByRole("button", { name: "Marchandises et livraisons" }).count(), 1)
		assert.equal(await page.getByRole("button", { name: "Départ", exact: true }).count(), 0)
		assert.equal(await page.getByRole("link", { name: "Mon espace RH" }).count(), 0)
		revision++
		await context.setOffline(false)
		const mission = page.getByRole("heading", { name: "TEST-A-2" })
		const retry = page.getByRole("button", { name: "Réessayer la connexion" })
		await mission.or(retry).first().waitFor()
		if (await retry.isVisible()) await retry.click()
		await mission.waitFor()
		await page.getByText("Documents et péages", { exact: true }).click()
		await page.getByRole("heading", { name: "Autres documents autorisés" }).waitFor()
		assert.equal(await page.getByText("Consigne privée.pdf", { exact: true }).count(), 0)
		await page.close()
		await setUser(otherDriver)
		await context.setOffline(true)
		page = await context.newPage()
		await page.goto(origin + "/hrms")
		await page.getByRole("alert").waitFor()
		assert.equal(await page.getByRole("button", { name: /TEST-A/ }).count(), 0)
		assert.equal(await page.evaluate(() => localStorage.getItem("goods-transport:fleet-snapshot:v1")), null)
		console.log("Chromium Pixel 7: cold offline navigation, reconnect and account isolation passed")
	} finally {
		await browser?.close()
		server.close()
	}
}

run().catch(error => {
	console.error(error)
	process.exitCode = 1
})
