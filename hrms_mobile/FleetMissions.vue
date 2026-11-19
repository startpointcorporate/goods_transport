<template>
	<ion-page>
		<ion-header><ion-toolbar><ion-title>{{ labels.trips }}</ion-title></ion-toolbar></ion-header>
		<ion-content>
			<div class="flex flex-col gap-4 p-4 pb-16">
				<RouterLink v-if="!offline" :to="{ name: 'Home' }" class="underline">{{ labels.hr }}</RouterLink>
				<p v-if="offline" role="status">{{ labels.offline }}</p>
				<p v-if="lastSync">{{ labels.synced }} {{ lastSync }}</p>
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
							@click="selected = trip"
						>
							<strong>{{ trip.name }}</strong>
							<span>{{ trip.origin }} → {{ trip.destination }}</span>
							<span>{{ trip.vehicle_license_plate || trip.vehicle }} · {{ tripStatus(trip.status) }}</span>
							<time>{{ trip.planned_departure_at || trip.trip_date }}</time>
						</button>
					</template>
					<article v-else class="flex flex-col gap-3">
						<button class="self-start underline" @click="selected = null">{{ labels.back }}</button>
						<h2 class="text-lg font-semibold">{{ selected.name }}</h2>
						<p>{{ selected.vehicle_license_plate || selected.vehicle }} · {{ tripStatus(selected.status) }}</p>
						<p>{{ selected.origin }} → {{ selected.destination }}</p>
						<p>{{ selected.planned_departure_at || selected.trip_date }} / {{ selected.planned_return_at || "—" }}</p>
						<h3 class="font-semibold">{{ labels.road }}</h3>
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
						<h3 class="font-semibold">{{ labels.fuel }}</h3>
						<p v-if="!selected.authorizations.length">{{ labels.noFuel }}</p>
						<div v-for="(authorization, index) in selected.authorizations" :key="index" class="rounded border p-3">
							<p>{{ authorization.station }} · {{ authorization.fuel_type }}</p>
							<p>{{ authorization.authorized_liters }} L · {{ tripStatus(authorization.status) }}</p>
							<p>{{ authorization.valid_until }}</p>
						</div>
						<FleetRoadDocuments :key="selected.name" :trip="selected" :french="french" :offline="offline" />
						<FleetInspection v-if="!offline" :key="selected.name" :trip="selected.name" :french="french" />
						<FleetOperations v-if="!offline" :key="selected.name" :trip="selected.name" :french="french" />
					</article>
				</template>
			</div>
		</ion-content>
	</ion-page>
</template>

<script setup>
import { computed, inject, onMounted, onUnmounted, ref } from "vue"
import { RouterLink } from "vue-router"
import { IonPage, IonHeader, IonToolbar, IonTitle, IonContent } from "@ionic/vue"
import { purgeFleetSnapshot, readFleetSnapshot, saveFleetSnapshot } from "./offline"
import { getFleetData } from "./fleetApi"
import FleetInspection from "./FleetInspection.vue"
import FleetOperations from "./FleetOperations.vue"
import FleetRoadDocuments from "./FleetRoadDocuments.vue"

const offlineShell = Boolean(window.frappe?.boot?.fleet_offline)
const offline = ref(offlineShell || !navigator.onLine)
const french = (readFleetSnapshot()?.lang || document.documentElement.lang || navigator.language).startsWith("fr")
const tripStatus = inject("$translate")
const labels = french ? {
	trips: "Mes missions", hr: "Espace RH", loading: "Chargement des missions…", filter: "Filtrer les missions",
	all: "Toutes", upcoming: "À venir", active: "En cours", finished: "Terminées",
	empty: "Aucune mission dans cette catégorie.", back: "Toutes les missions",
	road: "Feuille de route", fuelStops: "Arrêts carburant", navigate: "Ouvrir la navigation", fuel: "Autorisations de carburant",
	offline: "Hors ligne. Les opérations nécessitent une connexion.", synced: "Dernière synchronisation",
	noFuel: "Aucune autorisation de carburant.", unavailable: "Les missions sont indisponibles.",
} : {
	trips: "My trips", hr: "HR home", loading: "Loading trips…", filter: "Filter trips",
	all: "All", upcoming: "Upcoming", active: "In progress", finished: "Completed",
	empty: "No trips in this category.", back: "All trips", road: "Road sheet", fuelStops: "Fuel stops",
	navigate: "Open navigation", fuel: "Fuel authorizations", noFuel: "No fuel authorizations.",
	offline: "Offline. Operations require a connection.", synced: "Last sync",
	unavailable: "Trips are unavailable.",
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
	const category = ["Delivered", "Settled", "Closed"].includes(trip.status)
		? "finished"
		: ["At Loading Point", "Loaded", "In Transit", "Arrived", "Unloading"].includes(trip.status)
			? "active" : "upcoming"
	return category === filter.value
}))

function showSnapshot(snapshot) {
	trips.value = snapshot?.trips || []
	selected.value = trips.value.find(trip => trip.name === selected.value?.name) || null
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
		return
	}
	// Rebuild the session only once requests can reach Frappe again.
	for (let attempt = 0; attempt < 3 && navigator.onLine; attempt++) {
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
}

function storageChanged() {
	if (offline.value) showSnapshot(readFleetSnapshot())
}

onMounted(() => {
	window.addEventListener("online", reconnect)
	window.addEventListener("offline", refresh)
	window.addEventListener("storage", storageChanged)
	void refresh()
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
