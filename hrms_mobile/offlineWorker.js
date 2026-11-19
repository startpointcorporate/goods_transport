import { matchPrecache } from "workbox-precaching"

const RELEASE_HTML = "/assets/hrms/frontend/index.html"

// Use only the public, precached build output for fallback. A live HRMS
// response contains session-specific bootstrap data and must never be stored.
self.addEventListener("fetch", event => {
	const url = new URL(event.request.url)
	if (event.request.mode !== "navigate" || url.origin !== self.location.origin) return
	if (url.pathname !== "/hrms" && !url.pathname.startsWith("/hrms/")) return
	event.respondWith(fetch(event.request).catch(async () => {
		const entry = await matchPrecache(RELEASE_HTML)
		if (!entry) return Response.error()
		const html = (await entry.text())
			.replace("{{ csrf_token }}", "")
			.replace("{{ site_name }}", "")
			.replace("{{ boot }}", JSON.stringify({
				__messages: {}, lang: "", fleet_offline: true,
			}))
		return new Response(html, {
			headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
		})
	}))
})
