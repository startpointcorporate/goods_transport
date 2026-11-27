import { sessionUser } from "@/data/session"
import { postFleetData } from "./fleetApi"

export const vaultSessionKey = "goods-transport:fleet-session:changed"
const encoder = new TextEncoder()
const decoder = new TextDecoder()
let active
let unlocking
let epoch = 0

export function lockFleetVault(notify = false) {
	epoch++
	active = null
	unlocking = null
	if (notify) {
		try {
			localStorage.setItem(vaultSessionKey, crypto.randomUUID())
		} catch {
			// The account cookie is also checked on every operation.
		}
	}
}

window.addEventListener("storage", event => {
	if (event.key === vaultSessionKey) lockFleetVault()
})

export function fleetVaultUnlocked() {
	return Boolean(active && active.user === sessionUser())
}

export async function unlockFleetVault() {
	const user = sessionUser()
	if (fleetVaultUnlocked()) return
	if (!user || !navigator.onLine || window.frappe?.boot?.fleet_offline) return
	if (unlocking?.user === user) return unlocking.promise
	const ticket = { user }
	const currentEpoch = epoch
	ticket.promise = (async () => {
		const result = await postFleetData("local_storage_key", { expected_user: user })
		if (result?.user !== user) throw new Error("Fleet identity changed")
		const secret = Uint8Array.from(atob(result.material), value => value.charCodeAt(0))
		let key
		let index
		try {
			[key, index] = await Promise.all([
				crypto.subtle.importKey("raw", secret.subarray(0, 32), "AES-GCM", false, ["encrypt", "decrypt"]),
				crypto.subtle.importKey("raw", secret.subarray(32), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]),
			])
		} finally {
			secret.fill(0)
		}
		if (currentEpoch !== epoch || sessionUser() !== user) throw new Error("Fleet identity changed")
		active = { user, key, index }
	})()
	unlocking = ticket
	try {
		await ticket.promise
	} finally {
		if (unlocking === ticket) unlocking = null
	}
}

function vault() {
	if (!fleetVaultUnlocked()) throw new Error("Fleet storage is locked")
	return active
}

function check(key) {
	if (active !== key || !fleetVaultUnlocked()) throw new Error("Fleet identity changed")
}

export async function fleetStorageIndex(value) {
	const key = vault()
	const tag = await crypto.subtle.sign("HMAC", key.index, encoder.encode(JSON.stringify(value)))
	check(key)
	return Array.from(new Uint8Array(tag), byte => byte.toString(16).padStart(2, "0")).join("")
}

export async function sealFleetData(value, purpose) {
	const key = vault()
	const files = []
	const manifest = encoder.encode(JSON.stringify(value, (_, item) => {
		if (!(item instanceof Blob)) return item
		const index = files.push(item) - 1
		return { fleetBlob: index, size: item.size, type: item.type, name: item.name }
	}))
	const header = new ArrayBuffer(4)
	new DataView(header).setUint32(0, manifest.length)
	const plaintext = await new Blob([header, manifest, ...files]).arrayBuffer()
	const iv = crypto.getRandomValues(new Uint8Array(12))
	try {
		const data = await crypto.subtle.encrypt({
			name: "AES-GCM", iv, additionalData: encoder.encode(purpose),
		}, key.key, plaintext)
		check(key)
		return { iv, data }
	} finally {
		new Uint8Array(plaintext).fill(0)
	}
}

export async function openFleetData(record, purpose) {
	const key = vault()
	const plaintext = await crypto.subtle.decrypt({
		name: "AES-GCM", iv: record.iv, additionalData: encoder.encode(purpose),
	}, key.key, record.data)
	try {
		check(key)
		const length = new DataView(plaintext).getUint32(0)
		let offset = 4 + length
		return JSON.parse(decoder.decode(new Uint8Array(plaintext, 4, length)), (_, item) => {
			if (!Number.isInteger(item?.fleetBlob)) return item
			const bytes = plaintext.slice(offset, offset + item.size)
			offset += item.size
			return item.name === undefined ? new Blob([bytes], { type: item.type })
				: new File([bytes], item.name, { type: item.type })
		})
	} finally {
		new Uint8Array(plaintext).fill(0)
	}
}
