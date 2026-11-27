import { sessionUser } from "@/data/session"
import { postFleetData } from "./fleetApi"
import { fleetStorageIndex, fleetVaultUnlocked, openFleetData, sealFleetData } from "./fleetVault"

const database = "goods-transport:fleet-outbox:v1"
export const outboxChangeKey = database + ":changed"
const leaseDuration = 90_000
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

function announceChange() {
	try {
		localStorage.setItem(outboxChangeKey, crypto.randomUUID())
	} catch {
		// Other tabs also reload the queue when focused.
	}
}

function sameRevision(current, expected) {
	return current?.user === expected.user && current.status === expected.status
		&& (current.revision || 0) === (expected.revision || 0)
}

async function changeOperation(expected, change) {
	const currentGeneration = generation
	if (!expected.user || expected.user !== sessionUser() || !fleetVaultUnlocked()) return false
	let changed
	await transaction("readwrite", store => {
		const request = store.get(expected.id)
		request.onsuccess = () => {
			const current = request.result
			if (currentGeneration !== generation || expected.user !== sessionUser() || !fleetVaultUnlocked() || !sameRevision(current, expected)) return
			const next = change(current)
			if (next === undefined) return
			if (next === null) store.delete(current.id)
			else store.put({ ...next, revision: (current.revision || 0) + 1 })
			changed = true
		}
		return request
	})
	if (changed) announceChange()
	return Boolean(changed)
}

export function resetFleetOutboxSession() {
	generation++
}

export async function readFleetOutbox() {
	const user = sessionUser()
	if (!user || !fleetVaultUnlocked()) return []
	const records = await transaction("readonly", store => store.getAll())
	if (user !== sessionUser()) return []
	const expired = records.filter(record => record.user === user && record.status === "validated" &&
		Date.now() - (record.validatedAt || record.created) >= receiptAge)
	await Promise.all(expired.map(record => changeOperation(record, () => null)))
	const own = records.filter(record => record.user === user && !expired.includes(record))
		.sort((a, b) => a.created - b.created)
	const operations = []
	for (const record of own) {
		operations.push({ ...record, ...await openFleetData(record.sealed, record.id) })
	}
	return user === sessionUser() && fleetVaultUnlocked() ? operations : []
}

function operationKey(method, entries) {
	const field = { confirm_delivery: "bilty", record_field_event: "event", validate_inspection: "phase" }[method]
	return field ? method + ":" + entries.find(([name]) => name === field)?.[1] : null
}

async function protectOperation(record) {
	const { id, user, created, validatedAt, revision, status, lease, trip, vehicle, method, entries, error } = record
	const key = operationKey(method, entries)
	const [tripIndex, fingerprint, sealed] = await Promise.all([
		fleetStorageIndex(["trip", trip]),
		key ? fleetStorageIndex(["operation", trip, key]) : null,
		sealFleetData({ trip, vehicle, method, entries, error }, id),
	])
	return { id, user, created, validatedAt, revision, status, lease, tripIndex, fingerprint, sealed }
}

export async function enqueueFleetOperation(trip, method, body, correction) {
	const user = sessionUser()
	if (!user || !fleetVaultUnlocked()) throw new Error("Session unavailable")
	const entries = body instanceof FormData ? [...body.entries()] : Object.entries(body)
	const current = generation
	const payload = {
		id: correction?.id || crypto.randomUUID(), user,
		trip: trip.name, vehicle: trip.vehicle, method, entries, status: "pending",
	}
	const protectedRecord = await protectOperation(payload)
	let result
	let changed = false
	await transaction("readwrite", store => {
		const request = store.getAll()
		request.onsuccess = () => {
			if (current !== generation || user !== sessionUser() || !fleetVaultUnlocked()) return
			const records = request.result.filter(record => record.user === user)
			const existing = records.find(record => protectedRecord.fingerprint && record.status !== "validated"
				&& record.fingerprint === protectedRecord.fingerprint)
			if (existing && existing.id !== correction?.id) {
				if (!correction) result = existing
				return
			}
			const previous = records.find(record => correction && record.id === correction.id && record.status === "error"
				&& record.tripIndex === protectedRecord.tripIndex && sameRevision(record, correction))
			if (correction && !previous) return
			result = {
				...protectedRecord,
				created: previous?.created || records.reduce((latest, record) => Math.max(latest, record.created + 1), Date.now()),
				revision: (previous?.revision || 0) + 1,
			}
			store.put(result)
			changed = true
		}
		return request
	})
	if (changed) announceChange()
	return result || null
}

export function discardFleetOperation(record) {
	return changeOperation(record, current => ["error", "validated"].includes(current.status) ? null : undefined)
}

export function retryFleetOperation(record) {
	return changeOperation(record, current => current.status === "error"
		? { ...current, status: "pending" } : undefined)
}

async function claimNextOperation(user, current) {
	let claimed
	await transaction("readwrite", store => {
		const request = store.getAll()
		request.onsuccess = () => {
			if (current !== generation || user !== sessionUser() || !fleetVaultUnlocked()) return
			const now = Date.now()
			const records = request.result.filter(record => record.user === user && record.status !== "validated")
				.sort((left, right) => left.created - right.created)
			const seenTrips = new Set()
			for (const record of records) {
				if (seenTrips.has(record.tripIndex)) continue
				seenTrips.add(record.tripIndex)
				if (record.status !== "pending" || record.lease > now) continue
				claimed = { ...record, lease: now + leaseDuration, revision: record.revision + 1 }
				store.put(claimed)
				break
			}
		}
		return request
	})
	return claimed
}

export async function syncFleetOutbox() {
	if (sending || !fleetVaultUnlocked() || !navigator.onLine || window.frappe?.boot?.fleet_offline) return
	const user = sessionUser()
	sending = true
	const current = generation
	const run = async () => {
		while (current === generation && user === sessionUser() && fleetVaultUnlocked() && navigator.onLine) {
			const claimed = await claimNextOperation(user, current)
			if (!claimed) return
			let record
			try {
				record = { ...claimed, ...await openFleetData(claimed.sealed, claimed.id) }
			} catch (error) {
				await changeOperation(claimed, entry => ({ ...entry, lease: null }))
				throw error
			}
			if (current !== generation || user !== sessionUser() || !fleetVaultUnlocked()) return
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
				if (await postFleetData("sync_operation", body, AbortSignal.timeout(60_000)) !== "validated") {
					await changeOperation(claimed, entry => ({ ...entry, lease: null }))
					return
				}
				updated = { ...record, status: "validated", validatedAt: Date.now(), entries: [] }
			} catch (error) {
				if (!error.status || error.status >= 500 || [401, 429].includes(error.status)) {
					if (current === generation) await changeOperation(claimed, entry => ({ ...entry, lease: null }))
					return
				}
				updated = { ...record, status: "error", error: error.businessMessage || "" }
			}
			if (current !== generation || user !== sessionUser() || !fleetVaultUnlocked()) return
			const protectedRecord = await protectOperation({ ...updated, lease: null })
			if (!await changeOperation(claimed, () => protectedRecord)) return
		}
	}
	try {
		if (navigator.locks) await navigator.locks.request(database, run)
		else await run()
	} finally {
		sending = false
	}
}
