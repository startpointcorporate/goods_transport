<template>
	<section class="flex flex-col gap-3 rounded border p-3">
		<h3 class="font-semibold">{{ text.documents }}</h3>
		<label class="flex flex-col gap-1">
			{{ text.language }}
			<select v-model="language" class="rounded border p-2">
				<option value="fr">Français</option>
				<option value="en">English</option>
			</select>
		</label>
		<button type="button" class="rounded border p-2" :disabled="offline || busy" @click="syncPdf">{{ text.sync }}</button>
		<p v-if="notice" role="status">{{ notice }}</p>
		<template v-if="pdfUrl">
			<p>{{ text.last }} {{ pdfDate }}</p>
			<div class="flex flex-wrap gap-4">
				<a :href="pdfUrl" target="_blank" rel="noopener" class="underline">{{ text.preview }}</a>
				<a :href="pdfUrl" :download="`road-sheet-${trip.name}-${language}.pdf`" class="underline">{{ text.download }}</a>
			</div>
		</template>
		<h3 class="font-semibold">{{ text.tolls }}</h3>
		<p v-if="tollDate">{{ text.last }} {{ tollDate }}</p>
		<p v-if="tolls === null">{{ text.unavailable }}</p>
		<p v-else-if="!tolls.length">{{ text.none }}</p>
		<ol v-else class="list-decimal ps-5">
			<li v-for="(toll, index) in tolls" :key="index">
				<strong>{{ toll.name }}</strong>
				<span v-if="toll.axis"> · {{ toll.axis }}</span>
				<p v-if="toll.address">{{ toll.address }}</p>
				<p v-if="toll.latitude != null && toll.longitude != null">{{ toll.latitude }}, {{ toll.longitude }}</p>
			</li>
		</ol>
	</section>
</template>

<script setup>
import { onUnmounted, ref, watch } from "vue"
import { sessionUser } from "@/data/session"
import { fleetUrl, getFleetData } from "./fleetApi"
import { readFleetSnapshot } from "./offline"
import { readRoadDocument, saveRoadDocument } from "./roadDocuments"

const props = defineProps({ trip: { type: Object, required: true }, french: Boolean, offline: Boolean })
const text = props.french ? {
	documents: "Documents de mission · Feuille de route PDF", language: "Langue",
	sync: "Synchroniser le PDF", preview: "Prévisualiser le PDF", download: "Télécharger le PDF",
	tolls: "Péages du trajet", last: "Dernière synchronisation", none: "Aucun péage identifié sur ce trajet.",
	unavailable: "Aucun plan de péages disponible.", failure: "Synchronisation du PDF indisponible.",
} : {
	documents: "Trip documents · Road sheet PDF", language: "Language",
	sync: "Sync PDF", preview: "Preview PDF", download: "Download PDF",
	tolls: "Route tolls", last: "Last sync", none: "No tolls identified on this route.",
	unavailable: "No toll plan available.", failure: "PDF synchronization unavailable.",
}

const language = ref(props.french ? "fr" : "en")
const pdfUrl = ref("")
const pdfDate = ref("")
const tolls = ref(null)
const tollDate = ref("")
const notice = ref("")
const busy = ref(false)
let pdfRequest = 0
let tollRequest = 0

function clearPdf() {
	if (pdfUrl.value) URL.revokeObjectURL(pdfUrl.value)
	pdfUrl.value = ""
	pdfDate.value = ""
}

function current(user, trip) {
	return user && user === sessionUser() && trip.name === props.trip.name && trip.modified === props.trip.modified
}

function expiry(user, trip) {
	const snapshot = readFleetSnapshot()
	if (snapshot?.user !== user || !snapshot?.trips.some(row => row.name === trip.name && row.modified === trip.modified)) return null
	return snapshot.savedAt + 12 * 60 * 60 * 1000
}

function showPdf(record) {
	clearPdf()
	if (!record) return
	pdfUrl.value = URL.createObjectURL(record.value)
	pdfDate.value = new Date(record.savedAt).toLocaleString()
}

async function loadPdf() {
	const request = ++pdfRequest
	clearPdf()
	const user = sessionUser()
	const trip = props.trip
	if (!expiry(user, trip)) return
	const record = await readRoadDocument(user, trip, language.value).catch(() => null)
	if (request === pdfRequest && current(user, trip)) showPdf(record)
}

async function syncPdf() {
	const request = ++pdfRequest
	busy.value = true
	notice.value = ""
	const user = sessionUser()
	const trip = props.trip
	const selectedLanguage = language.value
	try {
		const response = await fetch(fleetUrl("road_sheet_pdf", { trip: trip.name, language: selectedLanguage }), {
			credentials: "same-origin", cache: "no-store",
		})
		if (!response.ok || !response.headers.get("Content-Type")?.startsWith("application/pdf")) throw new Error()
		const pdf = await response.blob()
		if (pdf.size > 5 * 1024 * 1024) throw new Error()
		if (request !== pdfRequest || !current(user, trip)) return
		const expires = expiry(user, trip)
		if (expires) await saveRoadDocument(user, trip, selectedLanguage, pdf, expires)
		if (request === pdfRequest && current(user, trip)) showPdf({ value: pdf, savedAt: Date.now() })
	} catch {
		if (request === pdfRequest) notice.value = text.failure
	} finally {
		busy.value = false
	}
}

async function loadTolls() {
	const request = ++tollRequest
	const user = sessionUser()
	const trip = props.trip
	tolls.value = null
	tollDate.value = ""
	try {
		let record = expiry(user, trip) && await readRoadDocument(user, trip, "tolls").catch(() => null)
		if (!props.offline) {
			const value = await getFleetData("route_tolls", { trip: trip.name })
			if (request !== tollRequest || !current(user, trip)) return
			const expires = expiry(user, trip)
			if (value !== null) {
				record = { value, savedAt: Date.now() }
				if (expires) await saveRoadDocument(user, trip, "tolls", value, expires).catch(() => {})
			}
		}
		if (request === tollRequest && current(user, trip) && record) {
			tolls.value = record.value
			tollDate.value = new Date(record.savedAt).toLocaleString()
		}
	} catch {
		// A network or storage failure leaves an explicit unavailable state.
	}
}

watch(() => [props.trip.modified, language.value], loadPdf, { immediate: true })
watch(() => [props.trip.modified, props.offline], loadTolls, { immediate: true })
onUnmounted(() => {
	pdfRequest++
	tollRequest++
	clearPdf()
})
</script>
