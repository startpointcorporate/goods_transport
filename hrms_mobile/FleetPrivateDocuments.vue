<template>
	<section class="flex flex-col gap-3 rounded border p-3">
		<h3 class="font-semibold">{{ french ? "Autres documents autorisés" : "Other approved documents" }}</h3>
		<p v-if="error" role="status">{{ french ? "Documents indisponibles." : "Documents unavailable." }}</p>
		<ul class="flex flex-col gap-3">
			<li v-for="row in documents" :key="row.name">
				<p>{{ row.file_name }}</p>
				<button v-if="!offline" type="button" class="underline" :disabled="busy" @click="sync(row)">
					{{ french ? "Synchroniser" : "Sync" }}
				</button>
				<div v-if="row.url">
					<p>{{ french ? "Dernière synchronisation" : "Last sync" }} {{ new Date(row.savedAt).toLocaleString() }}</p>
					<a :href="row.url" :download="row.file_name" class="underline">{{ french ? "Télécharger" : "Download" }}</a>
					<a :href="row.url" target="_blank" rel="noopener" class="ms-3 underline">{{ french ? "Consulter" : "View" }}</a>
				</div>
			</li>
		</ul>
	</section>
</template>

<script setup>
import { onUnmounted, ref, watch } from "vue"
import { sessionUser } from "@/data/session"
import { fleetUrl, getFleetData } from "./fleetApi"
import { readFleetSnapshot } from "./offline"
import { deleteRoadDocument, readRoadDocument, saveRoadDocument } from "./roadDocuments"

const props = defineProps({ trip: { type: Object, required: true }, french: Boolean, offline: Boolean })
const documents = ref([])
const busy = ref(false)
const error = ref(false)
let revision = 0

function clear() {
	for (const item of documents.value) if (item.url) URL.revokeObjectURL(item.url)
	documents.value = []
}
function context() {
	const user = sessionUser()
	const snapshot = readFleetSnapshot()
	const trip = props.trip
	if (!user || snapshot?.user !== user || !snapshot.trips.some(row => row.name === trip.name && row.modified === trip.modified)) return null
	return { user, trip, expires: snapshot.savedAt + 12 * 60 * 60 * 1000 }
}
function current(ctx, version) {
	return ctx.user === sessionUser() && ctx.trip.name === props.trip.name &&
		ctx.trip.modified === props.trip.modified && version === revision
}
function publish(attachments) {
	clear()
	documents.value = attachments.map(row => ({
		...row, url: row.pdf ? URL.createObjectURL(row.pdf) : "",
	}))
}

async function refresh() {
	const version = ++revision
	clear()
	error.value = false
	const ctx = context()
	if (!ctx) return
	try {
		const cached = await readRoadDocument(ctx.user, ctx.trip, "private-pdfs")
		if (!current(ctx, version)) return
		if (props.offline) {
			publish(cached?.value.filter(row => row.pdf) || [])
			return
		}
		const allowed = await getFleetData("mission_files", { trip: ctx.trip.name })
		if (!current(ctx, version)) return
		const entries = allowed.map(row => cached?.value.find(
			previous => previous.name === row.name && previous.modified === row.modified,
		) || row)
		if (cached) await saveRoadDocument(ctx.user, ctx.trip, "private-pdfs", entries, cached.expires)
		if (current(ctx, version)) publish(entries)
	} catch (failure) {
		if (!current(ctx, version)) return
		if (!(failure instanceof TypeError)) await deleteRoadDocument(ctx.user, ctx.trip, "private-pdfs").catch(() => {})
		error.value = true
	}
}

async function sync(row) {
	const ctx = context()
	if (!ctx || busy.value || props.offline) return
	const version = revision
	busy.value = true
	error.value = false
	try {
		const response = await fetch(fleetUrl("mission_file", {
			trip: ctx.trip.name, file: row.name, modified: row.modified,
		}), { credentials: "same-origin", cache: "no-store" })
		if (!response.ok || !response.headers.get("Content-Type")?.startsWith("application/pdf")) throw new Error()
		const pdf = await response.blob()
		if (pdf.size > 5 * 1024 * 1024) throw new Error()
		if (!current(ctx, version)) return
		const entries = documents.value.map(item => {
			const { url, ...entry } = item
			return item.name === row.name ? { ...entry, pdf, savedAt: Date.now() } : entry
		})
		await saveRoadDocument(ctx.user, ctx.trip, "private-pdfs", entries, ctx.expires)
		if (current(ctx, version)) publish(entries)
	} catch {
		if (current(ctx, version)) {
			await refresh()
			error.value = true
		}
	} finally {
		busy.value = false
	}
}

watch(() => [props.trip.modified, props.offline], refresh, { immediate: true })
onUnmounted(() => { revision++; clear() })
</script>
