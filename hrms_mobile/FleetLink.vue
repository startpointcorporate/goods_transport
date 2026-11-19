<template>
	<RouterLink v-if="available" :to="{ name: 'FleetDriverMissions' }" class="w-full rounded-lg border p-4 font-medium">
		{{ french ? "Mes missions" : "My trips" }}
	</RouterLink>
</template>

<script setup>
import { onMounted, ref } from "vue"
import { RouterLink } from "vue-router"
import { getFleetData } from "./fleetApi"

const french = document.documentElement.lang.startsWith("fr")
const available = ref(false)

onMounted(async () => {
	try {
		available.value = await getFleetData("available")
	} catch {
		available.value = false
	}
})
</script>
