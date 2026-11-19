<template>
	<BaseLayout :page-title="labels.trips">
		<template #body>
			<div class="flex flex-col gap-4 p-4 pb-16">
				<RouterLink :to="{ name: 'Home' }" class="underline">{{ labels.hr }}</RouterLink>
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
					</article>
				</template>
			</div>
		</template>
	</BaseLayout>
</template>

<script setup>
import { computed, inject, onMounted, ref } from "vue"
import { RouterLink } from "vue-router"
import BaseLayout from "@/components/BaseLayout.vue"
import { getFleetData } from "./fleetApi"

const french = document.documentElement.lang.startsWith("fr")
const tripStatus = inject("$translate")
const labels = french ? {
	trips: "Mes missions", hr: "Espace RH", loading: "Chargement des missions…", filter: "Filtrer les missions",
	all: "Toutes", upcoming: "À venir", active: "En cours", finished: "Terminées",
	empty: "Aucune mission dans cette catégorie.", back: "Toutes les missions",
	road: "Feuille de route", fuelStops: "Arrêts carburant", navigate: "Ouvrir la navigation", fuel: "Autorisations de carburant",
	noFuel: "Aucune autorisation de carburant.", unavailable: "Les missions sont indisponibles.",
} : {
	trips: "My trips", hr: "HR home", loading: "Loading trips…", filter: "Filter trips",
	all: "All", upcoming: "Upcoming", active: "In progress", finished: "Completed",
	empty: "No trips in this category.", back: "All trips", road: "Road sheet", fuelStops: "Fuel stops",
	navigate: "Open navigation", fuel: "Fuel authorizations", noFuel: "No fuel authorizations.",
	unavailable: "Trips are unavailable.",
}

const trips = ref([])
const selected = ref(null)
const loading = ref(true)
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

onMounted(async () => {
	try {
		const snapshot = await getFleetData("missions")
		trips.value = snapshot.trips
	} catch {
		error.value = labels.unavailable
	} finally {
		loading.value = false
	}
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
