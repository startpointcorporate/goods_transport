<template>
	<section class="flex flex-col gap-3 rounded-lg border p-3">
		<h3 class="font-semibold">{{ text.title }}</h3>
		<div class="flex flex-wrap gap-3">
			<button v-for="phase in phases" :key="phase" type="button" class="rounded border px-3 py-2"
				:disabled="busy" @click="open(phase)">{{ text[phase] }}</button>
		</div>
		<p v-if="error" role="alert">{{ error }}</p>
		<form v-if="inspection" class="flex flex-col gap-3" @submit.prevent="validate">
			<h4 class="font-semibold">{{ text[inspection.phase] }}</h4>
			<p v-if="inspection.submitted">{{ text.submitted }} {{ inspection.validated_at }}</p>
			<p v-if="inspection.departure_odometer">{{ text.departureOdometer }} {{ inspection.departure_odometer }}</p>
			<fieldset :disabled="busy || inspection.submitted" class="flex flex-col gap-3">
				<label class="flex flex-col gap-1">
					{{ text.odometer }}
					<input v-model="odometer" required inputmode="decimal" class="rounded border p-2" />
				</label>
				<div v-for="control in inspection.controls" :key="control.code" class="flex flex-col gap-2 border-t pt-3">
					<label class="flex flex-col gap-1">
						{{ french ? control.label_fr || control.label_en : control.label_en }}
						<select v-model="results[control.code].result" class="rounded border p-2">
							<option value="Not Checked">{{ text.unchecked }}</option>
							<option value="Pass">{{ text.pass }}</option>
							<option value="Fail">{{ text.fail }}</option>
							<option v-if="control.allow_na" value="Not Applicable">{{ text.na }}</option>
						</select>
					</label>
					<template v-if="results[control.code].result === 'Fail'">
						<label class="flex flex-col gap-1">
							{{ text.defect }}
							<input v-model="results[control.code].defect" required class="rounded border p-2" />
						</label>
						<label class="flex flex-col gap-1">
							{{ text.severity }}
							<select v-model="results[control.code].severity" required class="rounded border p-2">
								<option value="Minor">{{ text.minor }}</option>
								<option value="Major">{{ text.major }}</option>
								<option value="Critical">{{ text.critical }}</option>
							</select>
						</label>
					</template>
					<label class="flex flex-col gap-1">
						{{ text.observations }}
						<textarea v-model="results[control.code].observation"
							:required="results[control.code].result === 'Fail'" class="rounded border p-2" />
					</label>
					<div v-for="photo in photosFor(control.code)" :key="photo.name" class="flex items-start gap-2">
						<img :src="photoUrl(photo)" :alt="text.photo" class="h-20 w-24 rounded object-cover" />
						<button v-if="!inspection.submitted" class="underline" type="button" @click="remove(photo)">{{ text.remove }}</button>
					</div>
					<label v-if="!inspection.submitted" class="flex flex-col gap-1">
						{{ text.photo }} ({{ text.minimum }} {{ control.min_photos }})
						<input type="file" accept="image/jpeg,image/png,image/webp" capture="environment"
							@change="upload($event, control.code)" />
					</label>
				</div>
				<label class="flex flex-col gap-1">
					{{ text.observations }}
					<textarea v-model="observations" class="rounded border p-2" />
				</label>
				<button v-if="!inspection.submitted" class="rounded bg-gray-900 p-2 text-white" type="submit">
					{{ text.validate }}
				</button>
			</fieldset>
		</form>
	</section>
</template>

<script setup>
import { ref } from "vue"
import { fleetUrl, postFleetData } from "./fleetApi"

const props = defineProps({ trip: { type: String, required: true }, french: Boolean })
const phases = ["Departure", "Return"]
const text = props.french ? {
	title: "États des lieux", Departure: "Départ", Return: "Retour", odometer: "Kilométrage réel",
	departureOdometer: "Kilométrage au départ", submitted: "Inspection validée", unchecked: "À contrôler",
	pass: "Conforme", fail: "Anomalie", na: "Sans objet", defect: "Code anomalie", severity: "Gravité",
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
const odometer = ref("")
const observations = ref("")
const busy = ref(false)
const error = ref("")

function display(document) {
	inspection.value = document
	odometer.value = document.odometer || ""
	observations.value = document.observations || ""
	results.value = Object.fromEntries(document.controls.map(control => [control.code, {
		result: control.result || "Not Checked",
		observation: control.observation || "",
		severity: control.severity || "Minor",
		defect: control.defect || "",
	}]))
}

async function perform(operation) {
	if (busy.value) return
	error.value = ""
	busy.value = true
	try {
		await operation()
	} catch {
		error.value = text.error
	} finally {
		busy.value = false
	}
}
const open = phase => perform(async () => display(await postFleetData("open_inspection", { trip: props.trip, phase })))
const photosFor = control => inspection.value.photos.filter(photo => photo.attached_to_field === control)
const photoUrl = photo => fleetUrl("inspection_photo", { inspection: photo.inspection, photo: photo.name })
const validate = () => perform(async () => display(await postFleetData("validate_inspection", {
	inspection: inspection.value.name, odometer: odometer.value,
	results: results.value, observations: observations.value,
})))

async function upload(event, control) {
	const file = event.target.files[0]
	event.target.value = ""
	if (!file) return
	await perform(async () => {
		const body = new FormData()
		body.append("file", file)
		body.append("inspection", inspection.value.name)
		body.append("control", control)
		inspection.value.photos.push(await postFleetData("upload_photo", body))
	})
}

const remove = photo => perform(async () => {
	await postFleetData("remove_photo", { inspection: inspection.value.name, photo: photo.name })
	inspection.value.photos = inspection.value.photos.filter(item => item.name !== photo.name)
})
</script>
