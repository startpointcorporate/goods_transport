import { sessionUser } from "@/data/session"
import { postFleetData } from "./fleetApi"

const database = "goods-transport:fleet-outbox:v1"
const receiptAge = 7 * 24 * 60 * 60 * 1000
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
			tx.oncomplete = () => {
				connection.close()
				resolve(request?.result)
			}
			tx.onabort = () => {
				connection.close()
				reject(tx.error)
			}
			let request
			try {
				request = work(tx.objectStore("operations"))
			} catch (error) {
				tx.abort()
				reject(error)
			}
		}
	})
}

export function resetFleetOutboxSession() {
	generation++
}

export async function readFleetOutbox() {
	const user = sessionUser()
	if (!user) return []
	const records = await transaction("readonly", store => store.getAll())
	if (user !== sessionUser()) return []
	const expired = records.filter(record => record.status === "validated" &&
		Date.now() - (record.validatedAt || record.created) >= receiptAge)
	if (expired.length) {
		await transaction("readwrite", store => {
			for (const record of expired) store.delete(record.id)
		})
	}
	return user === sessionUser()
		? records.filter(record => record.user === user && !expired.includes(record)).sort((a, b) => a.created - b.created)
		: []
}

function operationKey(method, entries) {
	const field = { confirm_delivery: "bilty", record_field_event: "event", validate_inspection: "phase" }[method]
	return field ? method + ":" + entries.find(([name]) => name === field)?.[1] : null
}

export async function enqueueFleetOperation(trip, method, body, correction) {
	const user = sessionUser()
	if (!user) throw new Error("Session unavailable")
	const entries = body instanceof FormData ? [...body.entries()] : Object.entries(body)
	const key = operationKey(method, entries)
	const current = generation
	let result
	await transaction("readwrite", store => {
		const request = store.getAll()
		request.onsuccess = () => {
			if (current !== generation || user !== sessionUser()) return
			const records = request.result.filter(record => record.user === user)
			const existing = records.find(record => key && record.trip === trip.name && record.status !== "validated"
				&& operationKey(record.method, record.entries) === key)
			if (existing && existing.id !== correction) {
				result = existing
				return
			}
			const previous = records.find(record => record.id === correction && record.status === "error" && record.trip === trip.name)
			if (correction && !previous) return
			result = {
				id: previous?.id || crypto.randomUUID(), user, trip: trip.name, vehicle: trip.vehicle, method, entries,
				created: previous?.created || records.reduce((latest, record) => Math.max(latest, record.created + 1), Date.now()),
				status: "pending",
			}
			store.put(result)
		}
		return request
	})
	if (!result) throw new Error("Operation unavailable")
	return result
}

export function discardFleetOperation(record) {
	if (record.user === sessionUser() && ["error", "validated"].includes(record.status)) {
		return transaction("readwrite", store => store.delete(record.id))
	}
}

export function retryFleetOperation(record) {
	if (record.user === sessionUser() && record.status === "error") {
		return transaction("readwrite", store => store.put({ ...record, status: "pending", error: "" }))
	}
}

export async function syncFleetOutbox() {
	if (sending || !navigator.onLine || window.frappe?.boot?.fleet_offline) return
	sending = true
	const current = generation
	const run = async () => {
		const blocked = new Set()
		for (const record of await readFleetOutbox()) {
			if (current !== generation || record.user !== sessionUser()) return
			if (record.status === "error") blocked.add(record.trip)
			if (blocked.has(record.trip) || !["pending", "draft"].includes(record.status)) continue
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
				if (await postFleetData("sync_operation", body) !== "validated") return
				updated = { ...record, status: "validated", validatedAt: Date.now(), entries: [] }
			} catch (error) {
				if (!error.status || error.status >= 500 || [401, 429].includes(error.status)) return
				updated = { ...record, status: "error", error: error.businessMessage || "" }
				blocked.add(record.trip)
			}
			if (current !== generation || record.user !== sessionUser()) return
			await transaction("readwrite", store => store.put(updated))
		}
	}
	try {
		if (navigator.locks) await navigator.locks.request(database, run)
		else await run()
	} finally {
		sending = false
	}
}
