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
	const key = [user, trip.name, kind]
	const valid = record => record && record.modified === trip.modified &&
		Date.now() < record.expires && Date.now() >= record.savedAt
	const record = await storage("readwrite", store => {
		const read = store.get(key)
		read.onsuccess = () => {
			if (read.result && !valid(read.result)) store.delete(key)
		}
		return read
	})
	if (!valid(record)) return null
	return record
}

export function saveRoadDocument(user, trip, kind, value, expires) {
	return storage("readwrite", store => store.put(
		{ value, modified: trip.modified, savedAt: Date.now(), expires },
		[user, trip.name, kind],
	))
}

export function deleteRoadDocument(user, trip, kind) {
	return storage("readwrite", store => store.delete([user, trip.name, kind]))
}
