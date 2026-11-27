<template>
	<section class="flex flex-col gap-3 rounded-lg border p-3">
		<h3 class="font-semibold">{{ text.title }}</h3>
		<form v-if="inspection" class="flex flex-col gap-3" @submit.prevent="validate">
			<h4 class="font-semibold">{{ text[inspection.phase] }}</h4>
			<progress :value="completed" :max="inspection.controls.length" class="w-full" :aria-label="text.unchecked" />
			<p>{{ text.unchecked }} · {{ inspection.controls.length - completed }}</p>
			<p v-if="inspection.submitted">{{ text.submitted }} {{ inspection.validated_at }}</p>
			<p v-if="inspection.departure_odometer">{{ text.departureOdometer }} {{ inspection.departure_odometer }}</p>
			<fieldset :disabled="submitting || inspection.submitted" class="flex flex-col gap-3">
				<label class="flex flex-col gap-1">
					{{ text.odometer }}
					<input v-model="odometer" required inputmode="decimal" class="rounded border p-2" />
				</label>
				<section v-for="group in groups" :key="group.label" class="flex flex-col gap-3">
					<h5 class="font-semibold">{{ group.label }}</h5>
				<fieldset v-for="control in group.controls" :key="control.code" class="flex flex-col gap-2 rounded border p-3">
					<legend>{{ french ? control.label_fr || control.label_en : control.label_en }}</legend>
					<div class="flex flex-wrap gap-2">
						<button v-for="[value, label] in choices(control)" :key="value" type="button"
							class="min-h-11 rounded border px-3" :aria-pressed="results[control.code].result === value"
							:class="{ 'bg-gray-900 text-white': results[control.code].result === value }"
							@click="results[control.code].result = value">{{ label }}</button>
					</div>
					<template v-if="results[control.code].result === 'Fail'">
						<label class="flex flex-col gap-1">
							{{ text.defect }}
							<select v-model="results[control.code].defect" required class="min-h-11 rounded border p-2">
								<option disabled value="">{{ text.defect }}</option>
								<option v-for="[value, label] in defects" :key="value" :value="value">{{ label }}</option>
							</select>
						</label>
						<div class="flex flex-wrap gap-2" :aria-label="text.severity">
							<button v-for="value in ['Minor', 'Major', 'Critical']" :key="value" type="button"
								class="min-h-11 rounded border px-3" :aria-pressed="results[control.code].severity === value"
								:class="{ 'bg-gray-900 text-white': results[control.code].severity === value }"
								@click="results[control.code].severity = value">{{ text[value.toLowerCase()] }}</button>
						</div>
						<label class="flex flex-col gap-1">
							{{ text.observations }}
							<textarea v-model="results[control.code].observation" required class="rounded border p-2" />
						</label>
					</template>
					<FleetPhotoPicker v-if="!inspection.submitted && (results[control.code].result === 'Fail' || (results[control.code].result === 'Pass' && control.min_photos))" :key="control.code"
						:french="french" :label="`${text.photo} (${text.minimum} ${control.min_photos})`"
						:maximum="Math.max(1, control.min_photos || 0)" :initial-files="localPhotos[control.code]"
						@accepted="localPhotos[control.code] = $event" />
				</fieldset>
				</section>
				<label class="flex flex-col gap-1">
					{{ text.observations }}
					<textarea v-model="observations" class="rounded border p-2" />
				</label>
				<button v-if="!inspection.submitted" class="rounded bg-gray-900 p-2 text-white" type="submit" :disabled="!ready || submitting">
					{{ french ? "Valider" : "Validate" }}
				</button>
			</fieldset>
		</form>
	</section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue"
import FleetPhotoPicker from "./FleetPhotoPicker.vue"

const props = defineProps({ phase: { type: String, required: true }, mission: Object, correction: Object, submitting: Boolean, french: Boolean })
const emit = defineEmits(["validate"])
const text = props.french ? {
	title: "États des lieux", Departure: "Départ", Return: "Retour", odometer: "Kilométrage réel",
	departureOdometer: "Kilométrage au départ", submitted: "Inspection validée", unchecked: "À contrôler",
	pass: "Conforme", fail: "Non conforme", na: "Non applicable", defect: "Code anomalie", severity: "Gravité",
	minor: "Mineure", major: "Majeure", critical: "Critique", observations: "Observations",
	photo: "Photographie", minimum: "minimum", remove: "Retirer", validate: "Valider l’inspection",
	error: "L’opération a échoué. Vérifiez la phase, les contrôles obligatoires et la connexion.",
} : {
	title: "Vehicle inspections", Departure: "Departure", Return: "Return", odometer: "Actual odometer",
	departureOdometer: "Departure odometer", submitted: "Inspection validated", unchecked: "Not checked",
	pass: "Pass", fail: "Defect", na: "Not applicable", defect: "Defect code", severity: "Severity",
	minor: "Minor", major: "Major", critical: "Critical", observations: "Notes",
	photo: "Photograph", minimum: "minimum", remove: "Remove", validate: "Validate inspection",
	error: "The operation failed. Check the phase, required controls and network connection.",
}
const inspection = ref(null)
const results = ref({})
const localPhotos = ref({})
const odometer = ref("")
const observations = ref("")

function display(document) {
	inspection.value = document
	odometer.value = document.odometer || ""
	observations.value = document.observations || ""
	results.value = Object.fromEntries(document.controls.map(control => [control.code, {
		result: control.result || "Not Checked",
		observation: control.observation || "",
		severity: control.severity || "",
		defect: control.defect || "",
	}]))
}

const completed = computed(() => inspection.value?.controls.filter(control =>
	results.value[control.code].result !== "Not Checked").length || 0)
const groups = computed(() => {
	const categories = new Map()
	for (const control of inspection.value?.controls || []) {
		const label = control.documents ? (props.french ? "Documents" : "Documents")
			: control.safety ? (props.french ? "Sécurité" : "Safety") : (props.french ? "Véhicule" : "Vehicle")
		if (!categories.has(label)) categories.set(label, [])
		categories.get(label).push(control)
	}
	return Array.from(categories, ([label, controls]) => ({ label, controls }))
})
const defects = [
	["damaged", props.french ? "Endommagé" : "Damaged"],
	["missing", props.french ? "Manquant" : "Missing"],
	["worn", props.french ? "Usé" : "Worn"],
	["inoperative", props.french ? "Hors service" : "Inoperative"],
	["other", props.french ? "Autre" : "Other"],
]
function choices(control) {
	const options = [["Pass", text.pass], ["Fail", text.fail]]
	if (control.allow_na) options.push(["Not Applicable", text.na])
	return options
}
const ready = computed(() => inspection.value?.controls.every(control => {
	const result = results.value[control.code]
	if (result.result === "Not Checked") return !control.required_control
	if (result.result === "Not Applicable") return true
	if ((localPhotos.value[control.code]?.length || 0) < control.min_photos) return false
	return result.result !== "Fail" || (result.defect && result.severity && result.observation.trim())
}))
const validate = () => {
	const form = new FormData()
	form.set("phase", props.phase)
	form.set("odometer", odometer.value)
	form.set("results", JSON.stringify(results.value))
	form.set("observations", observations.value)
	for (const [control, files] of Object.entries(localPhotos.value)) {
		for (const file of files) form.append("photo:" + control, file)
	}
	emit("validate", "validate_inspection", form)
}

function showLocalChecklist() {
	display({
		phase: props.phase, photos: [], controls: props.mission.inspection_controls || [],
		odometer: props.phase === "Departure" ? props.mission.departure_odometer : props.mission.arrival_odometer,
		departure_odometer: props.phase === "Return" ? props.mission.departure_odometer : "",
	})
}

onMounted(() => {
	showLocalChecklist()
	if (!props.correction) return
	const entries = props.correction.entries
	const form = new Map(entries)
	odometer.value = form.get("odometer") || ""
	observations.value = form.get("observations") || ""
	const previous = JSON.parse(form.get("results") || "{}")
	for (const code of Object.keys(results.value)) {
		if (previous[code]) results.value[code] = previous[code]
		localPhotos.value[code] = entries.filter(([key]) => key === "photo:" + code).map(([, file]) => file)
	}
})

</script>
