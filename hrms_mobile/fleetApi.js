const service = "/api/method/goods_transport.goods_transport.services.fleet_driver."

export async function getFleetData(method) {
	const response = await fetch(service + method, {
		credentials: "same-origin",
		cache: "no-store",
		headers: { Accept: "application/json" },
	})
	if (!response.ok) throw new Error(String(response.status))
	const payload = await response.json()
	return payload.message
}
