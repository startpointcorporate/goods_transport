<template>
	<section class="flex flex-col gap-3 rounded border p-3">
		<div class="flex flex-wrap gap-2">
			<button type="button" class="rounded border p-2" :disabled="busy" @click="showFuel">{{ text.fuel }}</button>
			<button type="button" class="rounded border p-2" :disabled="busy" @click="showDelivery">{{ text.delivery }}</button>
			<button type="button" class="rounded border p-2" :disabled="busy" @click="panel = 'incident'">{{ text.incident }}</button>
		</div>
		<p v-if="error" role="alert">{{ text.error }}</p>
		<p v-if="saved" role="status">{{ text.saved }} {{ saved }}</p>
		<div v-if="panel === 'fuel'">
			<p v-if="!codes.length">{{ text.noCodes }}</p>
			<p v-for="code in codes" :key="code.name">{{ code.station }} · <strong>{{ code.name }}</strong> · {{ code.authorized_liters }} L</p>
		</div>
		<form v-if="panel === 'delivery'" class="flex flex-col gap-3" @submit.prevent="submit('confirm_delivery', $event)">
			<label class="flex flex-col gap-1">
				{{ text.consignment }}
				<select v-model="bilty" required name="bilty" class="rounded border p-2">
					<option v-for="doc in deliveries" :key="doc.name" :value="doc.name">
						{{ doc.name }} · {{ doc.total_quantity }}
					</option>
				</select>
			</label>
			<ul v-if="selected">
				<li v-for="(item, index) in selected.items" :key="index">{{ item.item }} · {{ item.quantity }}</li>
			</ul>
			<label>{{ text.delivered }} <input name="delivered_quantity" required type="number" min="0" step="any" class="rounded border p-2" /></label>
			<label>{{ text.damaged }} <input name="damaged_quantity" required type="number" value="0" min="0" step="any" class="rounded border p-2" /></label>
			<label>{{ text.receiver }} <input name="receiver_name" required class="rounded border p-2" /></label>
			<label class="flex flex-col">{{ text.notes }} <textarea name="remarks" class="rounded border p-2" /></label>
			<FleetPhotoPicker :label="text.photo" :french="french" @accepted="photos = $event" />
			<FleetPhotoPicker :label="text.signature" :french="french" @accepted="signatures = $event" />
			<button type="submit" :disabled="busy || !bilty" class="rounded bg-gray-900 p-2 text-white">{{ text.confirm }}</button>
		</form>
		<form v-if="panel === 'incident'" class="flex flex-col gap-3" @submit.prevent="submitIncident">
			<p v-if="critical">{{ text.blocks }}</p>
			<label>{{ text.category }}
				<select v-model="category" name="category" required class="rounded border p-2">
					<option disabled value="">{{ text.choose }}</option>
					<option v-for="key in categories" :key="key" :value="key">{{ text[key] }}</option>
				</select>
			</label>
			<label class="flex flex-col">{{ text.description }}
				<textarea name="description" required maxlength="2000" class="rounded border p-2" />
			</label>
			<FleetPhotoPicker :key="critical" :label="text.photo" :french="french"
				:maximum="critical ? 1 : 4" @accepted="photos = $event" />
			<button type="submit" :disabled="busy" class="rounded bg-gray-900 p-2 text-white">{{ text.confirm }}</button>
		</form>
	</section>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import FleetPhotoPicker from "./FleetPhotoPicker.vue"
import { getFleetData, postFleetData } from "./fleetApi"

const props = defineProps({ trip: { type: String, required: true }, french: Boolean })
const text = props.french ? {
	fuel: "Présenter une autorisation", delivery: "Preuve de livraison", incident: "Signaler un incident",
	error: "L’opération a échoué. Vérifiez la connexion et le statut de la mission.",
	saved: "Enregistré", noCodes: "Aucune autorisation active.", consignment: "Lettre de voiture",
	delivered: "Quantité livrée", damaged: "Quantité endommagée", receiver: "Nom du réceptionnaire",
	notes: "Observations", description: "Description", photo: "Photographie", signature: "Photo de la signature",
	confirm: "Confirmer", blocks: "Cette déclaration immobilise le véhicule.", category: "Catégorie",
	choose: "Choisir une catégorie", Breakdown: "Panne critique", Other: "Autre problème critique",
	minor_anomaly: "Anomalie mineure", mechanical: "Incident mécanique non bloquant",
	material_damage: "Dommage matériel", loading: "Problème de chargement",
	trip_difficulty: "Difficulté pendant la mission",
} : {
	fuel: "Present fuel authorization", delivery: "Proof of delivery", incident: "Report an incident",
	error: "The operation failed. Check the connection and trip status.", saved: "Saved",
	noCodes: "No active authorizations.", consignment: "Waybill", delivered: "Delivered quantity",
	damaged: "Damaged quantity", receiver: "Receiver name", notes: "Notes", description: "Description",
	photo: "Photograph", signature: "Signature photograph", confirm: "Confirm",
	blocks: "Reporting this incident immobilises the vehicle.", category: "Category",
	choose: "Select a category", Breakdown: "Critical breakdown", Other: "Other critical issue",
	minor_anomaly: "Minor anomaly", mechanical: "Non-blocking mechanical incident",
	material_damage: "Material damage", loading: "Loading problem", trip_difficulty: "Difficulty during the trip",
}
const panel = ref("")
const categories = ["minor_anomaly", "mechanical", "material_damage", "loading", "trip_difficulty", "Breakdown", "Other"]
const category = ref("")
const critical = computed(() => ["Breakdown", "Other"].includes(category.value))
const photos = ref([])
const signatures = ref([])
watch(panel, () => { photos.value = []; signatures.value = [] })
watch(critical, () => { photos.value = [] })

function submitIncident(event) {
	submit(critical.value ? "report_critical_incident" : "report_incident", event)
}
const codes = ref([])
const deliveries = ref([])
const bilty = ref("")
const busy = ref(false)
const error = ref(false)
const saved = ref("")
const selected = computed(() => deliveries.value.find(document => document.name === bilty.value))

async function perform(operation) {
	if (busy.value) return
	error.value = false
	saved.value = ""
	busy.value = true
	codes.value = []
	try {
		await operation()
	} catch {
		error.value = true
	} finally {
		busy.value = false
	}
}

const showFuel = () => perform(async () => {
	panel.value = "fuel"
	codes.value = await postFleetData("present_fuel_authorizations", { trip: props.trip })
})

const showDelivery = () => perform(async () => {
	panel.value = "delivery"
	deliveries.value = await getFleetData("delivery_documents", { trip: props.trip })
	bilty.value = deliveries.value[0]?.name || ""
})

function submit(method, event) {
	const form = new FormData(event.currentTarget)
	for (const file of photos.value) form.append("photo", file)
	if (panel.value === "delivery" && signatures.value[0]) form.append("signature", signatures.value[0])
	form.set("trip", props.trip)
	return perform(async () => {
		saved.value = await postFleetData(method, form)
		panel.value = ""
	})
}
</script>
