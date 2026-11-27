import { createHash } from "node:crypto"
import assert from "node:assert/strict"
import { readFile } from "node:fs/promises"
import { chromium } from "playwright"

const source = await readFile(new URL("../../hrms_mobile/fleetOutbox.js", import.meta.url), "utf8")
const vaultSource = await readFile(new URL("../../hrms_mobile/fleetVault.js", import.meta.url), "utf8")
const url = "http://localhost:8034"
const browser = await chromium.launch()

async function scenario(useWebLocks) {
	const context = await browser.newContext()
	try {
		const driver = "first@example.test"
		await context.addCookies([{ name: "user_id", value: driver, url }])
		await context.route(url + "/**", route => {
			const name = new URL(route.request().url()).pathname
			if (name === "/outbox.js") return route.fulfill({ contentType: "application/javascript",
				body: source.replace("@/data/session", "/session.js").replace("./fleetApi", "/fleetApi.js").replace("./fleetVault", "/vault.js") })
			if (name === "/vault.js") return route.fulfill({ contentType: "application/javascript",
				body: vaultSource.replace("@/data/session", "/session.js").replace("./fleetApi", "/fleetApi.js") })
			if (name === "/session.js") return route.fulfill({ contentType: "application/javascript",
				body: 'export const sessionUser = () => new URLSearchParams(document.cookie.replaceAll("; ", "&")).get("user_id")' })
			if (name === "/fleetApi.js") return route.fulfill({ contentType: "application/javascript",
				body: 'export const postFleetData = (method, body, ...args) => method === "local_storage_key" ? window.keyFor(body.expected_user) : window.transmit(method, body, ...args)' })
			return route.fulfill({ contentType: "text/html", body: "<!DOCTYPE html>" })
		})
		const ready = async page => {
			await page.exposeFunction("keyFor", user => ({
				user, material: createHash("sha512").update(user).digest("base64"),
			}))
			await page.goto(url)
			await page.evaluate(async useWebLocks => {
				if (!useWebLocks) Object.defineProperty(navigator, "locks", { value: undefined })
				window.vault = await import("/vault.js")
				window.outbox = await import("/outbox.js")
				window.raw = id => new Promise(resolve => {
					const open = indexedDB.open("goods-transport:fleet-outbox:v1")
					open.onsuccess = () => {
						const db = open.result
						const tx = db.transaction("operations", "readonly")
						const read = tx.objectStore("operations").get(id)
						tx.oncomplete = () => { db.close(); resolve(read.result) }
					}
				})
				window.notified = 0
				window.addEventListener("storage", event => {
					if (event.key === window.outbox.outboxChangeKey) window.notified++
				})
			}, useWebLocks)
			return page
		}
		let first = await ready(await context.newPage())
		const second = await ready(await context.newPage())
		for (const page of [first, second]) await page.evaluate(() => window.vault.unlockFleetVault())
		const record = await first.evaluate(async () => {
			const form = new FormData()
			form.append("event", "at_loading")
			form.append("observations", "Private checklist details")
			form.append("photo", new File(["test image"], "photo.png", { type: "image/png" }))
			return window.outbox.enqueueFleetOperation({ name: "TRIP", vehicle: "TRUCK" }, "record_field_event", form)
		})
		await second.waitForFunction(() => window.notified > 0)
		assert.equal(await first.evaluate(async id => {
			const raw = await window.raw(id)
			const bytes = new TextDecoder().decode(raw.sealed.data)
			return raw.entries === undefined && raw.trip === undefined
				&& !JSON.stringify(raw).includes("photo.png")
				&& !bytes.includes("test image") && !bytes.includes("Private checklist details")
		}, record.id), true)
		await first.close()
		first = await ready(await context.newPage())
		assert.equal(await first.evaluate(async () => (await window.outbox.readFleetOutbox()).length), 0)
		await first.evaluate(() => window.vault.unlockFleetVault())
		assert.equal(await first.evaluate(async () => {
			const [operation] = await window.outbox.readFleetOutbox()
			return operation.entries.find(([field]) => field === "photo")[1].text()
		}), "test image")
		await second.evaluate(() => window.vault.lockFleetVault(true))
		await first.waitForFunction(() => !window.vault.fleetVaultUnlocked())
		await context.addCookies([{ name: "user_id", value: "second@example.test", url }])
		await second.evaluate(() => window.vault.unlockFleetVault())
		assert.equal(await second.evaluate(async id => {
			const raw = await window.raw(id)
			try {
				await window.vault.openFleetData(raw.sealed, id)
				return false
			} catch {
				return true
			}
		}, record.id), true)
		assert.equal(await second.evaluate(async () => (await window.outbox.readFleetOutbox()).length), 0)
		await context.addCookies([{ name: "user_id", value: driver, url }])
		for (const page of [first, second]) await page.evaluate(() => window.vault.unlockFleetVault())

		await first.evaluate(() => {
			window.transmit = async () => { throw Object.assign(new Error(), { status: 417 }) }
			return window.outbox.syncFleetOutbox()
		})
		await second.evaluate(async () => { [window.stale] = await window.outbox.readFleetOutbox() })
		await first.evaluate(async () => {
			const [error] = await window.outbox.readFleetOutbox()
			await window.outbox.enqueueFleetOperation({ name: "TRIP", vehicle: "TRUCK" },
				"record_field_event", { event: "at_loading", notes: "correction" }, error)
		})
		assert.equal(await second.evaluate(() => window.outbox.discardFleetOperation(window.stale)), false)
		assert.equal(await second.evaluate(() => window.outbox.enqueueFleetOperation({ name: "TRIP", vehicle: "TRUCK" },
			"record_field_event", { event: "at_loading", notes: "stale" }, window.stale)), null)

		let transmissions = 0
		let release
		const held = new Promise(resolve => { release = resolve })
		for (const page of [first, second]) {
			await page.exposeFunction("send", async (id, notes) => {
				transmissions++
				assert.equal(id, record.id)
				assert.equal(notes, "correction")
				await held
				return "validated"
			})
			await page.evaluate(() => {
				window.transmit = (_, body) => window.send(body.get("operation_id"), body.get("notes"))
			})
		}
		try {
			const started = first.evaluate(() => window.outbox.syncFleetOutbox())
			const competing = second.evaluate(() => window.outbox.syncFleetOutbox())
			await first.waitForFunction(async () => (await window.outbox.readFleetOutbox())[0]?.lease > Date.now())
			release()
			await Promise.all([started, competing])
		} finally {
			release()
		}
		assert.equal(transmissions, 1)
		assert.equal(await second.evaluate(() => window.outbox.retryFleetOperation(window.stale)), false)
		assert.deepEqual(await first.evaluate(async () => (await window.outbox.readFleetOutbox())
			.map(({ status, entries }) => ({ status, entries }))), [{ status: "validated", entries: [] }])
		await first.evaluate(async () => {
			const trip = { name: "DEPENDENT", vehicle: "TRUCK" }
			await window.outbox.enqueueFleetOperation(trip, "record_field_event", { event: "at_loading" })
			window.transmit = async () => { throw Object.assign(new Error(), { status: 417 }) }
			await window.outbox.syncFleetOutbox()
			await window.outbox.enqueueFleetOperation({ name: "OTHER", vehicle: "TRUCK" },
				"record_field_event", { event: "arrived" })
			await window.outbox.enqueueFleetOperation(trip, "record_field_event", { event: "loaded" })
		})
		const ordered = []
		let startOther
		let finishOther
		let startLoading
		let finishLoading
		const otherStarted = new Promise(resolve => { startOther = resolve })
		const otherHeld = new Promise(resolve => { finishOther = resolve })
		const loadingStarted = new Promise(resolve => { startLoading = resolve })
		const loadingHeld = new Promise(resolve => { finishLoading = resolve })
		for (const page of [first, second]) {
			await page.exposeFunction("sendOrdered", async event => {
				ordered.push(event)
				if (event === "arrived") { startOther(); await otherHeld }
				if (event === "at_loading") { startLoading(); await loadingHeld }
				return "validated"
			})
			await page.evaluate(() => {
				window.transmit = (_, body) => window.sendOrdered(body.get("event"))
			})
		}
		try {
			const sync = first.evaluate(() => window.outbox.syncFleetOutbox())
			await otherStarted
			assert.equal(await second.evaluate(async () => {
				const earlier = (await window.outbox.readFleetOutbox()).find(entry => entry.status === "error")
				return window.outbox.retryFleetOperation(earlier)
			}), true)
			finishOther()
			await Promise.race([loadingStarted, sync])
			assert.deepEqual(ordered, ["arrived", "at_loading"])
			const competitor = second.evaluate(() => window.outbox.syncFleetOutbox())
			if (!useWebLocks) {
				await competitor
				assert.deepEqual(ordered, ["arrived", "at_loading"])
			}
			finishLoading()
			await Promise.all([sync, competitor])
			assert.deepEqual(ordered, ["arrived", "at_loading", "loaded"])
		} finally {
			finishOther()
			finishLoading()
		}
	} finally {
		await context.close()
	}
}

try {
	for (const useWebLocks of [true, false]) {
		await scenario(useWebLocks)
		console.log("Multi-tab queue passed with " + (useWebLocks ? "Web Locks" : "IndexedDB lease"))
	}
} finally {
	await browser.close()
}
