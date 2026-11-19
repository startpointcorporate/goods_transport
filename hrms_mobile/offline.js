import { sessionUser } from "@/data/session"
import { clearRoadDocuments } from "./roadDocuments"

const key = "goods-transport:fleet-snapshot:v1"
const maximumAge = 12 * 60 * 60 * 1000
const workerUrl = "/api/method/goods_transport.goods_transport.services.fleet_driver.service_worker"

export function purgeFleetSnapshot() {
	clearRoadDocuments()
	try {
		localStorage.removeItem(key)
	} catch {
		// Storage can be unavailable in restricted browser contexts.
	}
}

export function readFleetSnapshot() {
	try {
		const snapshot = JSON.parse(localStorage.getItem(key))
		if (!snapshot) return null
		const age = Date.now() - snapshot.savedAt
		if (!sessionUser() || snapshot.user !== sessionUser() || !(age >= 0 && age < maximumAge)) {
			purgeFleetSnapshot()
			return null
		}
		return snapshot
	} catch {
		purgeFleetSnapshot()
		return null
	}
}

export async function saveFleetSnapshot(snapshot) {
	if (!snapshot.user || snapshot.user !== sessionUser()) {
		purgeFleetSnapshot()
		return
	}
	try {
		localStorage.setItem(key, JSON.stringify({ ...snapshot, savedAt: Date.now(), lang: document.documentElement.lang }))
		await navigator.serviceWorker?.register(workerUrl, {
			scope: "/hrms",
			updateViaCache: "none",
		})
	} catch (error) {
		console.warn("Fleet offline setup failed", error)
	}
}
