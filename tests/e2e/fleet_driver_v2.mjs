import assert from "node:assert/strict"
import { mkdir, readFile } from "node:fs/promises"
import { chromium, devices, webkit } from "playwright"

const origin = process.env.FLEET_QA_URL
const fixtures = JSON.parse(await readFile(process.env.FLEET_QA_FIXTURE, "utf8"))
const captures = process.env.FLEET_CAPTURE_DIR
await mkdir(captures, { recursive: true })
const api = "/api/method/goods_transport.goods_transport.services.fleet_driver."
const photo = Buffer.from(
	"iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFElEQVR4nGNkYPjPgA0wYRUdtBIAy0MBD1YkjLoAAAAASUVORK5CYII=", "base64",
)

async function login(page, account) {
	await page.goto(origin + "/hrms")
	await page.locator('input[autocomplete="username"]').fill(account.user)
	await page.locator('input[autocomplete="current-password"]').fill(process.env.FLEET_QA_PASSWORD)
	const installationHint = page.locator("#frappeui-popper-root svg").first()
	if (await installationHint.isVisible()) await installationHint.click()
	await page.locator("form button").first().click()
}

async function openTrip(page, trip) {
	await page.getByRole("button", { name: "Mes missions", exact: true }).click()
	await page.getByRole("button", { name: new RegExp(trip) }).click()
}

async function inspect(page, phase, reading, anomaly = false) {
	await page.getByRole("button", { name: new RegExp("Faire l’état des lieux de " + phase) }).click()
	await page.getByText("Kilométrage réel", { exact: true }).waitFor()
	await page.getByRole("button", { name: "Valider" }).waitFor()
	assert.equal(await page.getByRole("button", { name: "Valider" }).isDisabled(), true)
	const control = page.getByRole("group", { name: "Carrosserie" })
	for (const check of ["Freins", "Documents du véhicule"]) {
		await page.getByRole("group", { name: check }).getByRole("button", { name: "Conforme", exact: true }).click()
	}
	await control.getByRole("button", { name: "Conforme", exact: true }).click()
	await control.locator('input[type="file"]').setInputFiles({ name: "test.png", mimeType: "image/png", buffer: photo })
	await control.getByRole("button", { name: "Accepter" }).click()
	if (anomaly) {
		await control.getByRole("button", { name: "Non conforme" }).click()
		await control.locator("select").selectOption("worn")
		await control.getByRole("button", { name: "Mineure" }).click()
		await control.getByLabel("Observations").fill("Usure observée")
	}

	await page.getByText("Kilométrage réel", { exact: true }).locator("input").fill(String(reading))
	await page.screenshot({ path: captures + "/inspection-" + phase + ".png", fullPage: true })
	await page.getByRole("button", { name: "Valider" }).click()
}

async function driveToDelivery(page) {
	for (const step of [
		"Je suis au point de chargement", "Le chargement est terminé", "Je prends la route",
		"Je suis arrivé", "Le déchargement est terminé",
	]) {
		await page.getByRole("button", { name: step }).click()
	}
	await page.getByRole("button", { name: "Confirmer les livraisons" }).click()
}

async function delivery(page, partial) {
	await page.getByRole("radio", { name: partial ? "Livraison partielle" : "Livraison complète" }).check()
	if (partial) {
		await page.getByLabel("Quantité livrée").fill("8")
		await page.getByText("Quantité manquante · 2").waitFor()
	}
	await page.getByLabel("Nom du réceptionnaire").fill("Réceptionnaire de test")
	await page.screenshot({ path: captures + (partial ? "/livraison-partielle.png" : "/livraison-complete.png"), fullPage: true })
	await page.getByRole("button", { name: "Valider", exact: true }).click()
	await page.getByRole("button", { name: "Marchandises et livraisons" }).click()
	await page.getByText(partial ? "Traitement par l’exploitation requis" : "Livraison complète", { exact: true }).waitFor()
}

async function captureLayout(page, name) {
	await login(page, fixtures.other)
	await page.getByRole("heading", { name: fixtures.other.trip }).waitFor()
	const content = await page.locator("ion-content").filter({ has: page.getByRole("heading", { name: fixtures.other.trip }) }).evaluate(element =>
		element.getScrollElement().then(scroll => ({ content: scroll.scrollWidth, viewport: scroll.clientWidth })))
	assert.ok(content.content <= content.viewport, name + " must fit horizontally")
	await page.screenshot({ path: captures + "/mission-" + name + ".png" })
	console.log(name + ": mission visible and fits the viewport")
}

const browser = await chromium.launch()
try {
	if (process.env.FLEET_QA_LAYOUT_ONLY !== "1") {
		const context = await browser.newContext({ ...devices["Pixel 7"], locale: "fr-FR", viewport: { width: 390, height: 844 } })
		const page = await context.newPage()
		const keyResponse = page.waitForResponse(response => response.url().endsWith(".local_storage_key") && response.ok())
		await login(page, fixtures.driver)
		assert.equal((await keyResponse).headers()["cache-control"], "private, no-store")
		assert.equal(await page.evaluate(async ({ path, other }) => {
			const response = await fetch(path + "local_storage_key", {
				method: "POST", headers: { "Content-Type": "application/json", "X-Frappe-CSRF-Token": window.csrf_token },
				body: JSON.stringify({ expected_user: other }),
			})
			return response.status
		}, { path: api, other: fixtures.other.user }), 403)
		await page.getByRole("button", { name: "Ma mission", exact: true }).waitFor()
		await page.screenshot({ path: captures + "/mission-390.png" })
		await openTrip(page, fixtures.driver.trip)
		assert.equal((await context.request.get(origin + api + "delivery_documents", {
			params: { trip: fixtures.other.trip },
		})).status(), 403)
		await page.getByText("Documents et péages", { exact: true }).click()
		await page.getByRole("button", { name: "Synchroniser le PDF" }).click()
		await page.getByRole("link", { name: "Prévisualiser le PDF" }).waitFor()
		await page.getByText("Documents et péages", { exact: true }).click()
		await page.getByText("Autorisations de carburant", { exact: true }).click()
		await page.getByRole("button", { name: "Consulter l’autorisation active" }).click()
		await page.getByText(fixtures.driver.fuel_code, { exact: true }).waitFor()
		assert.equal(await page.evaluate(code => JSON.stringify(localStorage).includes(code), fixtures.driver.fuel_code), false)
		await page.getByRole("button", { name: "Retour à la mission" }).click()
		await inspect(page, "départ", 100)
		await driveToDelivery(page)
		await delivery(page, false)
		await page.getByRole("button", { name: "Terminer les livraisons" }).click()
		await inspect(page, "retour", 90)
		await page.getByText(/kilométrage.*(arrivée|retour)|arrival odometer/i).first().waitFor()
		await page.getByText(/Opérations sur le téléphone/).click()
		await page.getByRole("button", { name: "Corriger" }).click()
		await page.getByText("Kilométrage réel", { exact: true }).locator("input").fill("120")
		await page.getByRole("button", { name: "Valider", exact: true }).click()
		await page.getByText(/Opérations sur le téléphone/).click()
		await page.getByRole("button", { name: "Je termine ma mission" }).click()
		await page.getByRole("button", { name: "Je termine ma mission" }).waitFor({ state: "hidden" })

		await openTrip(page, fixtures.driver.other_mission)
		await inspect(page, "départ", 100, true)
		await driveToDelivery(page)
		await delivery(page, true)
		assert.equal(await page.getByRole("button", { name: "Terminer les livraisons" }).count(), 0)
		await page.getByRole("button", { name: "Retour à la mission" }).click()
		await page.getByRole("button", { name: "Signaler un incident" }).click()
		await page.getByRole("radio", { name: "Problème de pneumatique" }).check()

		// Let Frappe accept the first transmission, then lose its response.
		const endpoint = "**/*.sync_operation"
		let finishedTransmission
		const interrupted = new Promise(resolve => { finishedTransmission = resolve })
		await page.route(endpoint, async route => {
			const response = await route.fetch()
			const lost = route.request().postDataBuffer()
			assert.equal(response.status(), 200)
			await route.abort("internetdisconnected")
			finishedTransmission(lost)
		}, { times: 1 })
		await page.getByRole("button", { name: "Valider", exact: true }).click()
		await page.getByText("En attente de synchronisation", { exact: true }).waitFor()
		await page.waitForFunction(() => document.body.textContent.includes("Opérations sur le téléphone"))
		assert.ok((await interrupted)?.includes(Buffer.from("report_incident")))

		await page.getByRole("button", { name: "Signaler un incident" }).click()
		await page.getByRole("radio", { name: "Panne mécanique" }).check()
		await page.getByLabel("Le véhicule doit être immobilisé").check()
		await context.setOffline(true)
		await page.getByRole("button", { name: "Valider", exact: true }).click()
		await page.getByText(/Opérations sur le téléphone/).click()
		await page.getByText(/réception.*n’est pas confirmée/).waitFor()
		// Keep automatic attempts offline until a new session is established.
		await page.close()
		await context.setOffline(false)
		const shared = await context.newPage()
		const logout = async () => {
			await shared.goto(origin + "/hrms/profile")
			await shared.getByRole("button", { name: /Log Out|Déconnexion|Se déconnecter/i }).click()
			await shared.locator('input[autocomplete="username"]').waitFor()
		}
		await logout()
		await login(shared, fixtures.other)
		await shared.getByRole("heading", { name: fixtures.other.trip }).waitFor()
		assert.equal(await shared.getByText(/Opérations sur le téléphone/).count(), 0)
		assert.equal((await context.request.get(origin + api + "delivery_documents", {
			params: { trip: fixtures.driver.trip },
		})).status(), 403)
		await logout()
		await login(shared, fixtures.driver)
		await shared.getByText(/Opérations sur le téléphone/).click()
		await shared.getByText(/Incident · Validé/).last().waitFor()
		assert.equal(await shared.getByText(/Incident · Validé/).count(), 2)
		await context.close()

		const employee = await browser.newPage({ locale: "fr-FR" })
		await login(employee, fixtures.employee)
		await employee.waitForURL("**/hrms/home")
		await employee.getByText(/Home|Accueil/).first().waitFor()
		assert.doesNotMatch(employee.url(), /\/fleet$/)
		await employee.close()
		console.log("android-390: full driver flow, account switch and standard HRMS verified")
	}

	const android = await browser.newPage({ ...devices["Pixel 7"], locale: "fr-FR", viewport: { width: 360, height: 800 } })
	await captureLayout(android, "android-360")
	await android.close()

	const safari = await webkit.launch()
	try {
		for (const [name, descriptor] of [
			["iphone", devices["iPhone 13"]],
			["tablette", devices["iPad (gen 7)"]],
		]) {
			const screen = await safari.newPage({ ...descriptor, locale: "fr-FR" })
			await captureLayout(screen, name)
			await screen.close()
		}
	} finally {
		await safari.close()
	}

} finally {
	await browser.close()
}
