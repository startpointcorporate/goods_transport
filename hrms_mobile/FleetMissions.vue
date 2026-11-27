<template>
	<ion-page>
		<ion-header><ion-toolbar><ion-title>{{ labels.trips }}</ion-title></ion-toolbar></ion-header>
		<ion-content>
			<div class="flex flex-col gap-4 p-4 pb-16">
				<nav class="flex flex-wrap gap-2" :aria-label="labels.trips">
					<button class="fleet-button" :disabled="busy" @click="openMission(primaryMission(trips))">{{ french ? "Ma mission" : "My mission" }}</button>
					<button class="fleet-button" :disabled="busy" @click="openMission(null)">{{ labels.trips }}</button>
					<RouterLink v-if="!offline" :to="{ name: 'Home', query: { space: 'hr' } }" class="fleet-button">{{ labels.hr }}</RouterLink>
				</nav>
				<div v-if="offline" class="flex flex-wrap items-center gap-2">
					<p role="status">{{ labels.offline }}</p>
					<button v-if="offlineShell" class="fleet-button" :disabled="reconnecting" @click="reconnect">
						{{ french ? "Réessayer la connexion" : "Retry connection" }}
					</button>
				</div>
				<p v-if="lastSync">{{ labels.synced }} {{ lastSync }}</p>
				<details v-if="outbox.length" class="rounded border p-3">
					<summary class="fleet-button">{{ french ? "Opérations sur le téléphone" : "Operations on this phone" }} · {{ outbox.length }}</summary>
					<div v-for="entry in outbox" :key="entry.id" class="flex flex-wrap items-center gap-2 border-t py-2">
						<span>{{ entry.trip }} · {{ operationLabel(entry) }} · {{ outboxLabels[entry.status] }}</span>
						<p v-if="entry.error" role="alert">{{ entry.error }}</p>
						<button v-if="['draft', 'error'].includes(entry.status)" class="fleet-button" :disabled="outboxBusy"
							@click="queue(entry)">{{ french ? "Mettre en attente" : "Queue for sync" }}</button>
						<button v-if="entry.status !== 'pending'" class="fleet-button" :disabled="outboxBusy"
							@click="discard(entry)">{{ french ? "Retirer" : "Remove" }}</button>
					</div>
					<button v-if="!offline && outbox.some(entry => entry.status === 'pending')" class="fleet-button" :disabled="outboxBusy"
						@click="syncOutbox">{{ french ? "Synchroniser" : "Sync" }}</button>
				</details>
				<p v-if="outboxError" role="alert">{{ outboxError }}</p>
				<p v-if="loading" role="status">{{ labels.loading }}</p>
				<p v-else-if="error" role="alert">{{ error }}</p>
				<template v-else>
					<label v-if="!selected" class="flex flex-col gap-2">
						{{ labels.filter }}
						<select v-model="filter" class="rounded border p-2">
							<option v-for="key in filters" :key="key" :value="key">{{ labels[key] }}</option>
						</select>
					</label>
					<template v-if="!selected">
						<p v-if="!visibleTrips.length">{{ labels.empty }}</p>
						<button
							v-for="trip in visibleTrips" :key="trip.name"
							class="flex flex-col gap-1 rounded-lg border p-4 text-start"
							@click="openMission(trip)"
						>
							<strong>{{ trip.name }}</strong>
							<span>{{ trip.origin }} → {{ trip.destination }}</span>
							<span>{{ trip.vehicle_license_plate || trip.vehicle }} · {{ tripStatus(trip.status) }}</span>
							<time>{{ trip.planned_departure_at || trip.trip_date }}</time>
						</button>
					</template>
					<article v-else class="flex flex-col gap-3">
						<button class="self-start underline" @click="openMission(null)">{{ labels.back }}</button>
						<h2 class="text-lg font-semibold">{{ selected.name }}</h2>
						<p>{{ selected.vehicle_license_plate || selected.vehicle }} · {{ tripStatus(selected.status) }}</p>
						<p>{{ selected.origin }} → {{ selected.destination }}</p>
						<p>{{ selected.planned_departure_at || selected.trip_date }} / {{ selected.planned_return_at || "—" }}</p>
						<p v-if="notice" role="status">{{ notice }}</p>
						<button v-if="action && !panel" class="fleet-button bg-gray-900 text-white"
							:disabled="busy" @click="performAction">{{ actionLabels[action] }}</button>
						<FleetInspection v-if="['Departure', 'Return'].includes(panel)" :key="selected.name + panel"
							:mission="selected" :offline="offline" :trip="selected.name" :phase="panel" :french="french" @updated="updated" @draft="storeDraft" />
						<FleetOperations v-if="['delivery', 'incident'].includes(panel) || (!offline && panel === 'fuel')"
							:key="selected.name + panel" :initial-panel="panel" :offline="offline" :cached-deliveries="selected.deliveries || []" :trip="selected.name" :french="french"
							:can-deliver="['Arrived', 'Unloading', 'Delivered'].includes(selected.status)" :completing="busy"
							:can-complete="selected.status === 'Unloading'" @complete="recordEvent('delivered')" @updated="refresh" @draft="storeDraft" />
						<button v-if="panel" class="fleet-button self-start" @click="panel = ''">{{ french ? "Retour à la mission" : "Back to mission" }}</button>
						<details class="rounded border p-3">
							<summary class="fleet-button">{{ labels.road }}</summary>
							<p>{{ french ? "Plan poids lourd. Le guidage externe peut proposer un autre trajet." : "Truck route plan. External navigation may suggest a different route." }}</p>
							<div v-for="location in selected.locations" :key="location.name" class="rounded border p-3">
								<p>{{ location.location_name }}</p>
								<p>{{ location.address }}</p>
								<a v-if="navigationUrl(location)" :href="navigationUrl(location)" class="underline">
									{{ labels.navigate }}
								</a>
							</div>
							<template v-if="selected.fuel_stops.length">
								<h3 class="font-semibold">{{ labels.fuelStops }}</h3>
								<div v-for="(stop, index) in selected.fuel_stops" :key="index" class="rounded border p-3">
									<p>{{ stop.station }} · {{ stop.refill_liters }} L</p>
									<a v-if="navigationUrl(stop)" :href="navigationUrl(stop)" class="underline">
										{{ labels.navigate }}
									</a>
								</div>
							</template>
						</details>
						<details class="rounded border p-3">
							<summary class="fleet-button">{{ labels.fuel }}</summary>
							<p v-if="!selected.authorizations.length">{{ labels.noFuel }}</p>
							<div v-for="(authorization, index) in selected.authorizations" :key="index" class="rounded border p-3">
								<p>{{ authorization.station_name || authorization.station }} · {{ authorization.fuel_type }}</p>
								<p>{{ authorization.authorized_liters }} L · {{ tripStatus(authorization.status) }}</p>
								<p>{{ authorization.valid_from }} → {{ authorization.valid_until }}</p>
								<a v-if="navigationUrl(authorization)" :href="navigationUrl(authorization)" class="underline">{{ labels.navigate }}</a>
							</div>
							<button v-if="!offline" class="fleet-button" @click="panel = 'fuel'">{{ french ? "Consulter l’autorisation active" : "View active authorization" }}</button>
						</details>
						<details class="rounded border p-3">
							<summary class="fleet-button">{{ french ? "Documents et péages" : "Documents and tolls" }}</summary>
							<FleetRoadDocuments :key="selected.name" :trip="selected" :french="french" :offline="offline" />
							<FleetPrivateDocuments :key="selected.name + ':files'" :trip="selected" :french="french" :offline="offline" />
						</details>
						<div class="flex flex-wrap gap-2">
							<button class="fleet-button" @click="panel = 'delivery'">{{ french ? "Marchandises et livraisons" : "Cargo and deliveries" }}</button>
							<button class="fleet-button" @click="panel = 'incident'">{{ french ? "Signaler un incident" : "Report an incident" }}</button>
						</div>
					</article>
				</template>
			</div>
		</ion-content>
	</ion-page>
</template>

<script setup>
import { computed, inject, onMounted, onUnmounted, ref, shallowRef } from "vue"
import { RouterLink } from "vue-router"
import { IonPage, IonHeader, IonToolbar, IonTitle, IonContent } from "@ionic/vue"
import { purgeFleetSnapshot, readFleetSnapshot, saveFleetSnapshot } from "./offline"
import { nextStep, primaryMission } from "./missionFlow.mjs"
import { discardFleetDraft, queueFleetDraft, readFleetOutbox, saveFleetDraft, syncFleetOutbox } from "./fleetOutbox"
import { getFleetData, postFleetData } from "./fleetApi"
import FleetInspection from "./FleetInspection.vue"
import FleetOperations from "./FleetOperations.vue"
import FleetRoadDocuments from "./FleetRoadDocuments.vue"
import FleetPrivateDocuments from "./FleetPrivateDocuments.vue"

const offlineShell = Boolean(window.frappe?.boot?.fleet_offline)
const offline = ref(offlineShell || !navigator.onLine)
const reconnecting = ref(false)
const french = (readFleetSnapshot()?.lang || document.documentElement.lang || navigator.language).startsWith("fr")
const tripStatus = inject("$translate")
const labels = french ? {
	trips: "Mes missions", hr: "Mon espace RH", loading: "Chargement des missions…", filter: "Filtrer les missions",
	all: "Toutes", upcoming: "À venir", active: "En cours", finished: "Terminées",
	empty: "Aucune mission dans cette catégorie.", back: "Toutes les missions",
	road: "Feuille de route", fuelStops: "Arrêts carburant", navigate: "Ouvrir la navigation", fuel: "Autorisations de carburant",
	offline: "Hors ligne. Vous pouvez préparer des brouillons.", synced: "Dernière synchronisation",
	noFuel: "Aucune autorisation de carburant.", unavailable: "Les missions sont indisponibles.",
} : {
	trips: "My trips", hr: "HR home", loading: "Loading trips…", filter: "Filter trips",
	all: "All", upcoming: "Upcoming", active: "In progress", finished: "Completed",
	empty: "No trips in this category.", back: "All trips", road: "Road sheet", fuelStops: "Fuel stops",
	navigate: "Open navigation", fuel: "Fuel authorizations", noFuel: "No fuel authorizations.",
	offline: "Offline. You can prepare drafts.", synced: "Last sync",
	unavailable: "Trips are unavailable.",
}

const actionLabels = french ? {
	Departure: "Faire l’état des lieux de départ", Return: "Faire l’état des lieux de retour",
	at_loading: "Je suis au point de chargement", loaded: "Le chargement est terminé",
	departed: "Je prends la route", arrived: "Je suis arrivé", unloaded: "Le déchargement est terminé",
	delivery: "Confirmer les livraisons", finished: "Je termine ma mission",
} : {
	Departure: "Start departure inspection", Return: "Start return inspection",
	at_loading: "I am at the loading point", loaded: "Loading is complete",
	departed: "I am leaving", arrived: "I have arrived", unloaded: "Unloading is complete",
	delivery: "Confirm deliveries", finished: "Finish my mission",
}
const outbox = shallowRef([])
const outboxBusy = ref(false)
const outboxError = ref("")
const outboxLabels = french ? {
	draft: "Brouillon local", pending: "En attente de synchronisation", validated: "Validé", error: "En erreur",
} : { draft: "Local draft", pending: "Pending sync", validated: "Validated", error: "Sync error" }

function operationLabel(entry) {
	if (entry.method === "record_field_event") return actionLabels[entry.entries.find(([key]) => key === "event")?.[1]] || (french ? "Étape terrain" : "Field event")
	if (entry.method === "validate_inspection") return french ? "État des lieux" : "Inspection"
	if (entry.method === "confirm_delivery") return french ? "Preuve de livraison" : "Proof of delivery"
	return french ? "Incident" : "Incident"
}

async function loadOutbox() {
	outbox.value = error.value ? [] : await readFleetOutbox().catch(() => [])
}

async function manageOutbox(operation) {
	if (outboxBusy.value) return
	outboxBusy.value = true
	outboxError.value = ""
	try {
		await operation()
		await loadOutbox()
	} catch {
		outboxError.value = french ? "Impossible d’accéder aux opérations sur le téléphone." : "Could not access operations on this phone."
	} finally {
		outboxBusy.value = false
	}
}

const discard = entry => manageOutbox(() => discardFleetDraft(entry))
const syncOutbox = () => manageOutbox(async () => {
	await syncFleetOutbox()
	await refresh()
})
const queue = entry => manageOutbox(async () => {
	await queueFleetDraft(entry)
	if (!offline.value) {
		await syncFleetOutbox()
		await refresh()
	}
})

function storeDraft(method, body) {
	return manageOutbox(async () => {
		await saveFleetDraft(selected.value, method, body)
		panel.value = ""
		notice.value = outboxLabels.draft
	})
}

const panel = ref("")
const busy = ref(false)
const notice = ref("")
let initial = true

function openMission(trip) {
	initial = false
	selected.value = trip
	panel.value = ""
	notice.value = ""
}

const action = computed(() => selected.value && nextStep(selected.value))
function performAction() {
	if (["Departure", "Return", "delivery"].includes(action.value)) panel.value = action.value
	else void recordEvent(action.value)
}

async function recordEvent(event) {
	if (busy.value) return
	if (offline.value) return storeDraft("record_field_event", { event })
	busy.value = true
	notice.value = ""
	try {
		await postFleetData("record_field_event", { trip: selected.value.name, event })
		await updated()
	} catch (error) {
		notice.value = error.businessMessage || (french ? "Impossible d’enregistrer cette étape. Vérifiez la connexion ou contactez l’exploitation." : "Could not record this step. Check your connection or contact dispatch.")
	} finally {
		busy.value = false
	}
}

async function updated() {
	panel.value = ""
	await refresh()
}

const trips = ref([])
const selected = ref(null)
const loading = ref(true)
const lastSync = ref("")
let request = 0
const error = ref("")
const filters = ["all", "upcoming", "active", "finished"]
const filter = ref("all")
const visibleTrips = computed(() => trips.value.filter(trip => {
	if (filter.value === "all") return true
	const category = trip.status === "Vehicle Assigned" ? "upcoming" : nextStep(trip) ? "active" : "finished"
	return category === filter.value
}))

function showSnapshot(snapshot) {
	trips.value = snapshot?.trips || []
	selected.value = trips.value.find(trip => trip.name === selected.value?.name) || null
	if (initial && snapshot) {
		selected.value = primaryMission(trips.value)
		initial = false
	}
	if (!snapshot) outbox.value = []
	lastSync.value = snapshot?.savedAt ? new Date(snapshot.savedAt).toLocaleString() : ""
	error.value = snapshot ? "" : labels.unavailable
}

async function refresh() {
	const current = ++request
	offline.value = !navigator.onLine || offlineShell
	if (offline.value) {
		showSnapshot(readFleetSnapshot())
		loading.value = false
		return
	}
	try {
		const snapshot = await getFleetData("missions")
		if (current !== request) return
		showSnapshot({ ...snapshot, savedAt: Date.now() })
		void saveFleetSnapshot(snapshot)
	} catch (failure) {
		if (current !== request) return
		if (failure instanceof TypeError) {
			offline.value = true
			showSnapshot(readFleetSnapshot())
		} else {
			purgeFleetSnapshot()
			showSnapshot(null)
		}
	} finally {
		if (current === request) loading.value = false
	}
}

async function reconnect() {
	if (!offlineShell) {
		await refresh()
		if (!offline.value) await syncOutbox()
		return
	}
	// Rebuild the session only once requests can reach Frappe again.
	if (reconnecting.value) return
	reconnecting.value = true
	try {
		for (let attempt = 0; attempt < 3; attempt++) {
			try {
				await getFleetData("available")
				window.location.reload()
				return
			} catch (error) {
				if (!(error instanceof TypeError)) {
					window.location.reload()
					return
				}
				await new Promise(resolve => setTimeout(resolve, 350))
			}
		}
	} finally {
		reconnecting.value = false
	}
}

function storageChanged() {
	if (offline.value) showSnapshot(readFleetSnapshot())
}

onMounted(() => {
	window.addEventListener("online", reconnect)
	window.addEventListener("offline", refresh)
	window.addEventListener("storage", storageChanged)
	void refresh().then(() => loadOutbox()).then(() => {
		if (!offline.value && outbox.value.some(entry => entry.status === "pending")) return syncOutbox()
	})
})
onUnmounted(() => {
	request++
	window.removeEventListener("online", reconnect)
	window.removeEventListener("offline", refresh)
	window.removeEventListener("storage", storageChanged)
})

function navigationUrl(location) {
	const { latitude, longitude } = location
	if (latitude == null || longitude == null || latitude === "" || longitude === "") return null
	if (!Number.isFinite(Number(latitude)) || !Number.isFinite(Number(longitude))) return null
	if (Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return null
	if (Number(latitude) === 0 && Number(longitude) === 0) return null
	const coordinates = encodeURIComponent(`${latitude},${longitude}`)
	return /iPhone|iPad|iPod/.test(navigator.userAgent)
		? `https://maps.apple.com/?daddr=${coordinates}`
		: `https://www.google.com/maps/dir/?api=1&destination=${coordinates}`
}
</script>

<style scoped>
.fleet-button {
	display: inline-flex;
	align-items: center;
	min-height: 44px;
	border: 1px solid currentColor;
	border-radius: 0.5rem;
	padding: 0.5rem 0.75rem;
}
summary.fleet-button { display: list-item; cursor: pointer; }
</style>
