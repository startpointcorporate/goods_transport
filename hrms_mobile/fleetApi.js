const service = "/api/method/goods_transport.goods_transport.services.fleet_driver."

export function fleetUrl(method, query) {
	return service + method + (query ? "?" + new URLSearchParams(query) : "")
}

async function request(method, options = {}, query) {
	const response = await fetch(fleetUrl(method, query), {
		credentials: "same-origin",
		cache: "no-store",
		headers: { Accept: "application/json" },
		...options,
	})
	if (!response.ok) throw new Error(String(response.status))
	const payload = await response.json()
	return payload.message
}

export const getFleetData = (method, query) => request(method, {}, query)

export function postFleetData(method, body) {
	if (!navigator.onLine || window.frappe?.boot?.fleet_offline || !window.csrf_token) {
		throw new Error("An online Frappe session is required")
	}
	const headers = { Accept: "application/json", "X-Frappe-CSRF-Token": window.csrf_token }
	const isUpload = body instanceof FormData
	if (!isUpload) headers["Content-Type"] = "application/json"
	return request(method, { method: "POST", headers, body: isUpload ? body : JSON.stringify(body) })
}
