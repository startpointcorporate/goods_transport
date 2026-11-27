<template>
	<section class="flex flex-col gap-3 rounded border p-3">
		<h3 class="font-semibold">{{ text[panel] }}</h3>
		<p v-if="error" role="alert">{{ error }}</p>
		<p v-if="correction?.error" role="alert">{{ correction.error }}</p>
		<div v-if="panel === 'fuel'">
			<p v-if="!codes.length">{{ text.noCodes }}</p>
			<p v-for="code in codes" :key="code.name">{{ code.station }} · <strong>{{ code.name }}</strong> · {{ code.authorized_liters }} L</p>
		</div>
		<div v-if="panel === 'delivery'" class="flex flex-col gap-3">
			<p v-if="!deliveries.length">{{ local("Aucune lettre de voiture disponible.", "No waybill available.") }}</p>
			<button v-for="doc in deliveries" :key="doc.name" type="button" :disabled="busy || submitting"
				:aria-pressed="bilty === doc.name" class="min-h-11 rounded border p-3 text-start"
				:class="{ 'bg-gray-900 text-white': bilty === doc.name }" @click="bilty = doc.name">
				<strong class="block">{{ doc.consignee || doc.customer_name || doc.customer }}</strong>
				<span class="block">{{ doc.destination }} · {{ doc.name }}</span>
				<span class="block">{{ local("Quantité attendue", "Expected quantity") }} · {{ doc.total_quantity }}</span>
				<span class="block">{{ deliveryLabel(doc.delivery_state) }}</span>
				<span v-if="doc.delivery_state === 'partial'" class="block">{{ local("Traitement par l’exploitation requis", "Dispatch action required") }}</span>
			</button>
			<div v-if="selected" class="flex flex-col gap-2">
				<ul>
					<li v-for="(item, index) in selected.items" :key="index">
						{{ item.description || item.item }} · {{ item.quantity }} {{ item.uom }}
					</li>
				</ul>
				<template v-if="selected.proof">
					<p>{{ text.delivered }} · {{ selected.proof.delivered_quantity }}</p>
					<p>{{ local("Quantité manquante", "Missing quantity") }} · {{ selected.proof.short_quantity }}</p>
					<p>{{ text.damaged }} · {{ selected.proof.damaged_quantity }}</p>
				</template>
			</div>
			<form v-if="selected && selected.delivery_state === 'pending' && canDeliver" :key="bilty"
				class="flex flex-col gap-3" @submit.prevent="submit('confirm_delivery', $event)">
				<fieldset :disabled="busy || submitting" class="flex flex-col gap-3">
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
						<input v-model="damaged" name="damaged_quantity" required type="number" inputmode="decimal" min="0" step="any"
							:max="actualQuantity" class="rounded border p-2" />
					</label>
					<label>{{ text.receiver }} <input v-model="receiver" name="receiver_name" required class="rounded border p-2" /></label>
					<details><summary class="min-h-11">{{ text.notes }}</summary>
						<textarea v-model="remarks" name="remarks" :aria-label="text.notes" class="rounded border p-2" />
					</details>
					<FleetPhotoPicker :maximum="1" :label="text.photo" :french="french" :initial-files="photos" @accepted="photos = $event" />
					<FleetPhotoPicker :maximum="1" :label="text.signature" :french="french" :initial-files="signatures" @accepted="signatures = $event" />
					<button type="submit" :disabled="busy || submitting || !deliveryMode || (deliveryMode === 'partial' && Number(actualQuantity) >= Number(selected.total_quantity))"
						class="min-h-11 rounded bg-gray-900 p-2 text-white">{{ local("Valider", "Validate") }}</button>
				</fieldset>
			</form>
			<button v-if="canComplete"
				type="button" :disabled="busy || completing || submitting" class="min-h-11 rounded bg-gray-900 p-2 text-white"
				@click="emit('complete')">{{ local("Terminer les livraisons", "Finish deliveries") }}</button>
		</div>
		<form v-if="panel === 'incident'" class="flex flex-col gap-3" @submit.prevent="submitIncident">
			<p v-if="critical">{{ text.blocks }}</p>
			<fieldset class="grid grid-cols-2 gap-2" :disabled="busy || submitting">
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
					<textarea v-model="description" name="description" :required="category === 'other'" maxlength="1800" class="rounded border p-2" />
				</label>
			</template>
			<FleetPhotoPicker v-if="category" :key="critical" :label="text.photo" :french="french"
				:maximum="critical ? 1 : 4" :initial-files="photos" @accepted="photos = $event" />
			<button type="submit" :disabled="busy || submitting || !category" class="min-h-11 rounded bg-gray-900 p-2 text-white">{{ local("Valider", "Validate") }}</button>
		</form>
	</section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue"
import FleetPhotoPicker from "./FleetPhotoPicker.vue"
import { postFleetData } from "./fleetApi"

const props = defineProps({ trip: { type: String, required: true }, french: Boolean, initialPanel: String,
	correction: Object, submitting: Boolean, cachedDeliveries: Array, canDeliver: Boolean, canComplete: Boolean, completing: Boolean })
const emit = defineEmits(["complete", "validate"])
const local = (fr, en) => props.french ? fr : en
const text = props.french ? {
	fuel: "Présenter une autorisation", delivery: "Preuve de livraison", incident: "Signaler un incident",
	error: "L’opération a échoué. Vérifiez la connexion et le statut de la mission.",
	saved: "Enregistré", noCodes: "Aucune autorisation active.", consignment: "Lettre de voiture",
	delivered: "Quantité livrée", damaged: "Quantité endommagée", receiver: "Nom du réceptionnaire",
	notes: "Observations", description: "Description", photo: "Photographie", signature: "Photo de la signature",
	confirm: "Confirmer", blocks: "L’exploitation reçoit la demande après transmission. Hors connexion, contactez-la directement si nécessaire.", category: "Catégorie",
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
	blocks: "Dispatch receives the request after transmission. If offline, contact them directly if needed.", category: "Category",
	choose: "Select a category", Breakdown: "Critical breakdown", Other: "Other critical issue",
	minor_anomaly: "Minor anomaly", mechanical: "Non-blocking mechanical incident",
	material_damage: "Material damage", loading: "Loading problem", trip_difficulty: "Difficulty during the trip",
}
const panel = props.initialPanel
const categories = [
	["mechanical", local("Panne mécanique", "Mechanical breakdown")],
	["tyre", local("Problème de pneumatique", "Tyre problem")],
	["accident", local("Accident", "Accident")],
	["other", local("Autre incident", "Other incident")],
]
const category = ref("")
const critical = ref(false)
const photos = ref([])
const signatures = ref([])
watch(critical, () => { photos.value = [] }, { flush: "sync" })

function submitIncident(event) {
	void submit(critical.value ? "report_critical_incident" : "report_incident", event)
}
const codes = ref([])
const deliveries = computed(() => props.cachedDeliveries || [])
const bilty = ref("")
const deliveryMode = ref("")
const delivered = ref("")
const hasDamage = ref(false)
const busy = ref(false)
const error = ref("")
const description = ref("")
const receiver = ref("")
const remarks = ref("")
const damaged = ref("")

function deliveryLabel(state) {
	return {
		pending: local("À livrer", "To deliver"),
		complete: local("Livraison complète", "Full delivery"),
		partial: local("Livraison partielle", "Partial delivery"),
		unavailable: local("Traitée par l’exploitation", "Handled by dispatch"),
	}[state]
}
const selected = computed(() => deliveries.value.find(document => document.name === bilty.value))
const actualQuantity = computed(() => deliveryMode.value === "complete" ? selected.value?.total_quantity : delivered.value)
const shortQuantity = computed(() => Math.max(0, Number(selected.value?.total_quantity) - Number(actualQuantity.value)).toLocaleString())
watch(bilty, () => {
	deliveryMode.value = ""
	delivered.value = ""
	hasDamage.value = false
	photos.value = []
	signatures.value = []
	receiver.value = ""
	remarks.value = ""
	damaged.value = ""
}, { flush: "sync" })

async function perform(operation) {
	if (busy.value) return
	error.value = ""
	busy.value = true
	try {
		await operation()
	} catch (failure) {
		error.value = failure.businessMessage || text.error
	} finally {
		busy.value = false
	}
}

function loadDeliveries() {
	const remaining = deliveries.value.filter(doc => doc.delivery_state === "pending")
	if (remaining.length === 1) bilty.value = remaining[0].name
	else if (deliveries.value.length === 1) bilty.value = deliveries.value[0].name
}

onMounted(() => perform(async () => {
	if (panel === "fuel") codes.value = await postFleetData("present_fuel_authorizations", { trip: props.trip })
	if (panel === "delivery") loadDeliveries()
	if (props.correction) restoreOperation()
}))

function restoreOperation() {
	const entries = props.correction.entries
	const values = new Map(entries)
	if (panel === "delivery") {
		bilty.value = values.get("bilty") || ""
		delivered.value = values.get("delivered_quantity") || ""
		deliveryMode.value = Number(delivered.value) === Number(selected.value?.total_quantity) ? "complete" : "partial"
		damaged.value = values.get("damaged_quantity") || ""
		hasDamage.value = Number(damaged.value) > 0
		receiver.value = values.get("receiver_name") || ""
		remarks.value = values.get("remarks") || ""
	} else {
		critical.value = props.correction.method === "report_critical_incident"
		const detail = values.get("description") || ""
		const original = categories.find(([, label]) => detail === label || detail.startsWith(label + " — "))
		category.value = values.get("incident_category") || original?.[0] || "other"
		description.value = original ? detail.slice(original[1].length).replace(/^ — /, "") : detail
	}
	photos.value = entries.filter(([name]) => name === "photo").map(([, file]) => file)
	signatures.value = entries.filter(([name]) => name === "signature").map(([, file]) => file)
}

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
		form.set("incident_category", category.value)
		form.set("category", critical.value ? (category.value === "mechanical" ? "Breakdown" : "Other") : category.value)
		form.set("description", notes ? label + " — " + notes : label)
	}
	form.set("trip", props.trip)
	emit("validate", method, form)
}
</script>
