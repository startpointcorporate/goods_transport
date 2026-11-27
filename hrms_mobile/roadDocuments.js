import { fleetStorageIndex, openFleetData, sealFleetData } from "./fleetVault"

const databaseName = "goods-transport:fleet-documents:v2"

function storage(mode, run) {
	return new Promise((resolve, reject) => {
		const open = indexedDB.open(databaseName, 1)
		open.onupgradeneeded = () => open.result.createObjectStore("documents")
		open.onerror = () => reject(open.error)
		open.onsuccess = () => {
			const db = open.result
			const transaction = db.transaction("documents", mode)
			const operation = run(transaction.objectStore("documents"))
			transaction.oncomplete = () => {
				db.close()
				resolve(operation.result)
			}
			transaction.onabort = () => {
				db.close()
				reject(transaction.error)
			}
		}
	})
}

export function clearLegacyRoadDocuments() {
	try {
		indexedDB.deleteDatabase("goods-transport:fleet-documents:v1")
	} catch {
		// Storage can be unavailable in restricted browser contexts.
	}
}

export async function readRoadDocument(user, trip, kind) {
	const key = await fleetStorageIndex(["document", user, trip.name, kind])
	const record = await storage("readwrite", store => {
		const read = store.get(key)
		read.onsuccess = () => {
			if (read.result && Date.now() >= read.result.expires) store.delete(key)
		}
		return read
	})
	if (!record || Date.now() >= record.expires) return null
	const value = await openFleetData(record.sealed, key)
	if (value.modified !== trip.modified || value.expires !== record.expires || Date.now() < value.savedAt) return null
	return { ...value, expires: record.expires }
}

export async function saveRoadDocument(user, trip, kind, value, expires) {
	const key = await fleetStorageIndex(["document", user, trip.name, kind])
	const sealed = await sealFleetData({ value, modified: trip.modified, savedAt: Date.now(), expires }, key)
	return storage("readwrite", store => {
		const scan = store.openCursor()
		scan.onsuccess = () => {
			const cursor = scan.result
			if (!cursor) return
			if (Date.now() >= cursor.value.expires) cursor.delete()
			cursor.continue()
		}
		return store.put({ sealed, expires }, key)
	})
}

export async function deleteRoadDocument(user, trip, kind) {
	const key = await fleetStorageIndex(["document", user, trip.name, kind])
	return storage("readwrite", store => store.delete(key))
}
