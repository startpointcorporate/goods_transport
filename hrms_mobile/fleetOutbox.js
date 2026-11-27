import { sessionUser } from "@/data/session"
import { postFleetData } from "./fleetApi"

const database = "goods-transport:fleet-outbox:v1"
let generation = 0
let sending = false

function transaction(mode, work) {
	return new Promise((resolve, reject) => {
		const opening = indexedDB.open(database, 1)
		opening.onupgradeneeded = () => opening.result.createObjectStore("operations", { keyPath: "id" })
		opening.onerror = () => reject(opening.error)
		opening.onsuccess = () => {
			const connection = opening.result
			const tx = connection.transaction("operations", mode)
			const request = work(tx.objectStore("operations"))
			tx.oncomplete = () => {
				connection.close()
				resolve(request.result)
			}
			tx.onabort = () => {
				connection.close()
				reject(tx.error)
			}
		}
	})
}

export function clearFleetOutbox() {
	generation++
	return transaction("readwrite", store => store.clear()).catch(() => {})
}

export async function readFleetOutbox() {
	const user = sessionUser()
	const records = await transaction("readonly", store => store.getAll())
	return user && user === sessionUser()
		? records.filter(record => record.user === user).sort((left, right) => left.created - right.created)
		: []
}

export async function saveFleetDraft(trip, method, body) {
	const user = sessionUser()
	if (!user) throw new Error("Session unavailable")
	const entries = body instanceof FormData ? [...body.entries()] : Object.entries(body)
	const record = {
		id: crypto.randomUUID(), user, trip: trip.name, vehicle: trip.vehicle, method, entries, created: Date.now(), status: "draft",
	}
	await transaction("readwrite", store => store.add(record))
	return record
}

export function discardFleetDraft(record) {
	return transaction("readwrite", store => store.delete(record.id))
}

export async function queueFleetDraft(record) {
	if (record.user !== sessionUser()) return
	await transaction("readwrite", store => store.put({ ...record, status: "pending", error: "" }))
}

export async function syncFleetOutbox() {
	if (sending || !navigator.onLine) return
	sending = true
	const current = generation
	try {
		for (const record of await readFleetOutbox()) {
			if (current !== generation || record.user !== sessionUser()) return
			if (record.status !== "pending") continue
			const body = new FormData()
			for (const [name, value] of record.entries) body.append(name, value)
			body.set("trip", record.trip)
			body.set("expected_user", record.user)
			body.set("vehicle", record.vehicle)
			body.set("operation", record.method)
			body.set("operation_id", record.id)
			body.set("captured_at", new Date(record.created).toISOString())
			let updated
			try {
				await postFleetData("sync_operation", body)
				updated = { ...record, status: "validated", entries: [] }
			} catch (error) {
				if (error instanceof TypeError) return
				updated = { ...record, status: "error", error: error.businessMessage || "" }
			}
			if (current !== generation || record.user !== sessionUser()) return
			await transaction("readwrite", store => store.put(updated))
		}
	} finally {
		sending = false
	}
}
