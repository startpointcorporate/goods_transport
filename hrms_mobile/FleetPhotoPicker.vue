<template>
	<div class="flex flex-col gap-2">
		<label>{{ label }}
			<input type="file" :accept="formats.join(',')" capture="environment" :multiple="maximum > 1"
				:disabled="busy" @change="select" />
		</label>
		<p v-if="message" role="status">{{ message }}</p>
		<div v-for="(item, index) in previews" :key="item.url" class="flex flex-wrap items-center gap-2">
			<img :src="item.url" :alt="label" class="h-24 w-32 rounded object-contain" />
			<span>{{ Math.ceil(item.file.size / 1024) }} {{ french ? "Kio" : "KiB" }}</span>
			<button v-if="!item.accepted" type="button" :disabled="busy" class="underline" @click="accept(item)">
				{{ french ? "Accepter" : "Accept" }}
			</button>
			<button type="button" :disabled="busy" class="underline" @click="remove(index)">
				{{ french ? "Supprimer" : "Remove" }}
			</button>
		</div>
		<button v-if="send && previews.some(item => item.accepted)" type="button" :disabled="busy"
			class="self-start rounded border p-2" @click="upload">{{ french ? "Envoyer la photo" : "Send photo" }}</button>
	</div>
</template>

<script setup>
import { onUnmounted, ref } from "vue"

const props = defineProps({
	label: String, french: Boolean, maximum: { type: Number, default: 1 }, send: Function, initialFiles: Array,
})
const emit = defineEmits(["accepted"])
const formats = ["image/jpeg", "image/png", "image/webp"]
const limit = 12 * 1024 * 1024
const config = window.frappe?.boot?.goods_transport_fleet_photos || {}
const edge = Math.max(1200, Math.min(3200, Number(config.long_edge) || 2000))
const quality = Math.max(0.8, Math.min(0.98, Number(config.jpeg_quality) || 0.88))
const previews = ref((props.initialFiles || []).map(file => ({ file, url: URL.createObjectURL(file), accepted: true })))
const busy = ref(false)
const message = ref("")
let disposed = false

function notify() {
	emit("accepted", previews.value.filter(item => item.accepted).map(item => item.file))
}

function accept(item) {
	item.accepted = true
	notify()
}

function remove(index) {
	URL.revokeObjectURL(previews.value[index].url)
	previews.value.splice(index, 1)
	notify()
}

async function optimize(file) {
	if (file.size < 700 * 1024 && file.type !== "image/jpeg") return file
	const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" })
	try {
		const scale = Math.min(1, edge / Math.max(bitmap.width, bitmap.height))
		if (scale === 1 && file.size < 700 * 1024) return file
		const canvas = document.createElement("canvas")
		canvas.width = Math.max(1, Math.round(bitmap.width * scale))
		canvas.height = Math.max(1, Math.round(bitmap.height * scale))
		canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height)
		const blob = await new Promise(resolve => canvas.toBlob(resolve, file.type, quality))
		return blob && blob.type === file.type && blob.size < file.size
			? new File([blob], file.name, { type: blob.type }) : file
	} finally {
		bitmap.close()
	}
}

async function select(event) {
	const files = Array.from(event.target.files)
	event.target.value = ""
	if (!files.length || busy.value) return
	if (props.maximum === 1) while (previews.value.length) remove(0)
	busy.value = true
	message.value = ""
	try {
		for (const file of files) {
			if (disposed) return
			if (previews.value.length >= props.maximum) {
				message.value = props.french ? "Nombre maximal de photos atteint." : "Photo limit reached."
				break
			}
			if (!formats.includes(file.type) || !file.size || file.size > limit) {
				message.value = props.french ? "Photo invalide. JPEG, PNG ou WebP, 12 Mio maximum." : "Invalid photo. JPEG, PNG or WebP, up to 12 MiB."
				continue
			}
			let optimized = file
			try {
				optimized = await optimize(file)
			} catch {
				message.value = props.french ? "Optimisation indisponible. Taille d’origine conservée." : "Optimization unavailable. Original size retained."
			}
			if (!disposed) previews.value.push({ file: optimized, url: URL.createObjectURL(optimized), accepted: false })
		}
	} finally {
		busy.value = false
	}
}

async function upload() {
	const index = previews.value.findIndex(item => item.accepted)
	if (index < 0 || !navigator.onLine) return
	busy.value = true
	try {
		await props.send(previews.value[index].file)
		if (!disposed) remove(index)
		message.value = props.french ? "Photo enregistrée." : "Photo saved."
	} catch {
		message.value = props.french ? "Envoi échoué. Vérifiez la connexion et réessayez." : "Upload failed. Check the connection and try again."
	} finally {
		busy.value = false
	}
}

onUnmounted(() => {
	disposed = true
	for (const item of previews.value) URL.revokeObjectURL(item.url)
})
</script>
