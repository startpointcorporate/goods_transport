import { sessionUser } from "@/data/session"
import { clearLegacyRoadDocuments } from "./roadDocuments"
import { fleetVaultUnlocked, lockFleetVault } from "./fleetVault"

const maximumAge = 12 * 60 * 60 * 1000
const workerUrl = "/api/method/goods_transport.goods_transport.services.fleet_driver.service_worker"
let snapshot

export function purgeFleetSnapshot(notify = false) {
	snapshot = null
	lockFleetVault(notify)
	clearLegacyRoadDocuments()
	try {
		localStorage.removeItem("goods-transport:fleet-snapshot:v1")
	} catch {
		// Storage can be unavailable in restricted browser contexts.
	}
}

// The old snapshot contained plaintext mission information and no unsent operations.
purgeFleetSnapshot()

export function readFleetSnapshot() {
	if (!fleetVaultUnlocked() || snapshot?.user !== sessionUser()) return null
	const age = Date.now() - snapshot.savedAt
	return age >= 0 && age < maximumAge ? snapshot : null
}

export async function saveFleetSnapshot(value) {
	if (!fleetVaultUnlocked() || !value.user || value.user !== sessionUser()) return
	snapshot = { ...value, savedAt: Date.now(), lang: document.documentElement.lang }
	try {
		await navigator.serviceWorker?.register(workerUrl, {
			scope: "/hrms",
			updateViaCache: "none",
		})
	} catch (error) {
		console.warn("Fleet offline setup failed", error)
	}
}
