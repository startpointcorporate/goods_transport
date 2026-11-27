<template>
	<section class="flex flex-col gap-3 rounded border p-3">
		<h3 class="font-semibold">{{ text[panel] }}</h3>
		<p v-if="error" role="alert">{{ error }}</p>
		<p v-if="saved" role="status">{{ text.saved }} {{ saved }}</p>
		<div v-if="panel === 'fuel'">
			<p v-if="!codes.length">{{ text.noCodes }}</p>
			<p v-for="code in codes" :key="code.name">{{ code.station }} · <strong>{{ code.name }}</strong> · {{ code.authorized_liters }} L</p>
		</div>
		<div v-if="panel === 'delivery'" class="flex flex-col gap-3">
			<button v-for="doc in deliveries" :key="doc.name" type="button" :disabled="busy"
				:aria-pressed="bilty === doc.name" class="min-h-11 rounded border p-3 text-start"
				:class="{ 'bg-gray-900 text-white': bilty === doc.name }" @click="bilty = doc.name">
				{{ doc.name }} · {{ doc.total_quantity }}<br v-if="doc.pod_status === 'Received'" />
				<span v-if="doc.pod_status === 'Received'">{{ local("Livraison confirmée", "Delivery confirmed") }}</span>
			</button>
			<ul v-if="selected">
				<li v-for="(item, index) in selected.items" :key="index">{{ item.item }} · {{ item.quantity }}</li>
			</ul>
			<form v-if="selected && selected.pod_status !== 'Received' && canDeliver" :key="bilty"
				class="flex flex-col gap-3" @submit.prevent="submit('confirm_delivery', $event)">
				<fieldset :disabled="busy" class="flex flex-col gap-3">
					<legend>{{ text.delivery }}</legend>
					<label class="min-h-11 rounded border p-3">
						<input v-model="deliveryMode" type="radio" value="complete" />
						{{ local("Livraison complète", "Full delivery") }} · {{ selected.total_quantity }}
					</label>
					<label class="min-h-11 rounded border p-3">
						<input v-model="deliveryMode" type="radio" value="partial" />
						{{ local("Livraison partielle", "Partial delivery") }}
					</label>
					<label v-if="deliveryMode === 'partial'">
						{{ text.delivered }}
						<input v-model="delivered" required type="number" inputmode="decimal" min="0" step="any"
							:max="selected.total_quantity" class="rounded border p-2" />
						<span>{{ local("Quantité manquante", "Missing quantity") }} · {{ shortQuantity }}</span>
					</label>
					<label class="min-h-11">
						<input v-model="hasDamage" type="checkbox" /> {{ local("Marchandises endommagées", "Damaged goods") }}
					</label>
					<label v-if="hasDamage">{{ text.damaged }}
						<input name="damaged_quantity" required type="number" inputmode="decimal" min="0" step="any"
							:max="actualQuantity" class="rounded border p-2" />
					</label>
					<label>{{ text.receiver }} <input name="receiver_name" required class="rounded border p-2" /></label>
					<details><summary class="min-h-11">{{ text.notes }}</summary>
						<textarea name="remarks" :aria-label="text.notes" class="rounded border p-2" />
					</details>
					<FleetPhotoPicker :maximum="1" :label="text.photo" :french="french" @accepted="photos = $event" />
					<FleetPhotoPicker :maximum="1" :label="text.signature" :french="french" @accepted="signatures = $event" />
					<button type="submit" :disabled="busy || !deliveryMode || (deliveryMode === 'partial' && Number(actualQuantity) >= Number(selected.total_quantity))"
						class="min-h-11 rounded bg-gray-900 p-2 text-white">{{ offline ? local("Enregistrer le brouillon", "Save draft") : text.confirm }}</button>
				</fieldset>
			</form>
			<button v-if="canComplete && loadedDeliveries && deliveries.every(doc => !doc.pod_required || doc.pod_status === 'Received')"
				type="button" :disabled="busy || completing" class="min-h-11 rounded bg-gray-900 p-2 text-white"
				@click="emit('complete')">{{ local("Terminer les livraisons", "Finish deliveries") }}</button>
		</div>
		<form v-if="panel === 'incident'" class="flex flex-col gap-3" @submit.prevent="submitIncident">
			<p v-if="critical">{{ text.blocks }}</p>
			<fieldset class="grid grid-cols-2 gap-2" :disabled="busy">
				<legend>{{ text.category }}</legend>
				<label v-for="[key, label] in categories" :key="key" class="min-h-11 rounded border p-2">
					<input v-model="category" type="radio" required :value="key" /> {{ label }}
				</label>
			</fieldset>
			<template v-if="category">
				<label class="min-h-11"><input v-model="critical" type="checkbox" />
					{{ local("Le véhicule doit être immobilisé", "The vehicle must be immobilised") }}
				</label>
				<label class="flex flex-col">{{ category === 'other' ? text.description : text.notes }}
					<textarea name="description" :required="category === 'other'" maxlength="1800" class="rounded border p-2" />
				</label>
			</template>
			<FleetPhotoPicker v-if="category" :key="critical" :label="text.photo" :french="french"
				:maximum="critical ? 1 : 4" @accepted="photos = $event" />
			<button type="submit" :disabled="busy || !category" class="min-h-11 rounded bg-gray-900 p-2 text-white">{{ offline ? local("Enregistrer le brouillon", "Save draft") : text.confirm }}</button>
		</form>
	</section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue"
import FleetPhotoPicker from "./FleetPhotoPicker.vue"
import { getFleetData, postFleetData } from "./fleetApi"

const props = defineProps({ trip: { type: String, required: true }, french: Boolean, initialPanel: String,
	offline: Boolean, cachedDeliveries: Array, canDeliver: Boolean, canComplete: Boolean, completing: Boolean })
const emit = defineEmits(["complete", "updated", "draft"])
const local = (fr, en) => props.french ? fr : en
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
const panel = props.initialPanel
const categories = [
	["mechanical", local("Panne mécanique", "Mechanical breakdown")],
	["tyre", local("Problème de pneumatique", "Tyre problem")],
	["loading", local("Problème de chargement", "Loading problem")],
	["material_damage", local("Dommages matériels", "Material damage")],
	["trip_difficulty", local("Difficulté sur la route", "Road difficulty")],
	["accident", local("Accident", "Accident")],
	["other", local("Autre incident", "Other incident")],
]
const category = ref("")
const critical = ref(false)
const photos = ref([])
const signatures = ref([])
watch(critical, () => { photos.value = [] })

function submitIncident(event) {
	void submit(critical.value ? "report_critical_incident" : "report_incident", event)
}
const codes = ref([])
const deliveries = ref([])
const loadedDeliveries = ref(false)
const bilty = ref("")
const deliveryMode = ref("")
const delivered = ref("")
const hasDamage = ref(false)
const busy = ref(false)
const error = ref("")
const saved = ref("")
const selected = computed(() => deliveries.value.find(document => document.name === bilty.value))
const actualQuantity = computed(() => deliveryMode.value === "complete" ? selected.value?.total_quantity : delivered.value)
const shortQuantity = computed(() => Math.max(0, Number(selected.value?.total_quantity) - Number(actualQuantity.value)).toLocaleString())
watch(bilty, () => {
	deliveryMode.value = ""
	delivered.value = ""
	hasDamage.value = false
	photos.value = []
	signatures.value = []
})

async function perform(operation) {
	if (busy.value) return
	error.value = ""
	saved.value = ""
	busy.value = true
	try {
		await operation()
	} catch (failure) {
		error.value = failure.businessMessage || text.error
	} finally {
		busy.value = false
	}
}

async function loadDeliveries() {
	deliveries.value = props.offline ? props.cachedDeliveries : await getFleetData("delivery_documents", { trip: props.trip })
	const remaining = deliveries.value.filter(doc => doc.pod_status !== "Received")
	if (remaining.length === 1) bilty.value = remaining[0].name
	else if (selected.value?.pod_status === "Received") bilty.value = ""
	loadedDeliveries.value = true
}

onMounted(() => perform(async () => {
	if (panel === "fuel") codes.value = await postFleetData("present_fuel_authorizations", { trip: props.trip })
	if (panel === "delivery") await loadDeliveries()
}))

function submit(method, event) {
	const form = new FormData(event.currentTarget)
	for (const file of photos.value) form.append("photo", file)
	if (panel === "delivery") {
		if (!selected.value || !deliveryMode.value) return
		form.set("bilty", bilty.value)
		form.set("delivered_quantity", actualQuantity.value)
		if (signatures.value[0]) form.append("signature", signatures.value[0])
	} else {
		const notes = form.get("description")?.trim()
		const label = categories.find(([key]) => key === category.value)?.[1]
		form.set("category", critical.value ? (category.value === "mechanical" ? "Breakdown" : "Other") : category.value)
		form.set("description", notes ? label + " — " + notes : label)
	}
	form.set("trip", props.trip)
	if (props.offline) return emit("draft", method, form)
	return perform(async () => {
		saved.value = await postFleetData(method, form)
		if (panel === "delivery") await loadDeliveries()
		else {
			category.value = ""
			critical.value = false
			photos.value = []
		}
		emit("updated")
	})
}
</script>
