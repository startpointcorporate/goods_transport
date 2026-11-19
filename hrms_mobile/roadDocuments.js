const databaseName = "goods-transport:fleet-documents:v1"

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

export function clearRoadDocuments() {
	void storage("readwrite", store => store.clear()).catch(() => {})
}

export async function readRoadDocument(user, trip, kind) {
	const record = await storage("readonly", store => store.get([user, trip.name, kind]))
	if (!record || record.modified !== trip.modified || Date.now() >= record.expires || Date.now() < record.savedAt) {
		return null
	}
	return record
}

export function saveRoadDocument(user, trip, kind, value, expires) {
	return storage("readwrite", store => store.put(
		{ value, modified: trip.modified, savedAt: Date.now(), expires },
		[user, trip.name, kind],
	))
}
