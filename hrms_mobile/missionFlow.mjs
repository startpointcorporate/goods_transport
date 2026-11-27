export const steps = {
	"Vehicle Assigned": "at_loading",
	"At Loading Point": "loaded",
	Loaded: "departed",
	"In Transit": "arrived",
	Arrived: "unloaded",
	Unloading: "delivery",
	Delivered: "finished",
}

export function nextStep(trip) {
	if (trip.driver_finished) return null
	if (trip.inspection_configured) {
		if (["Vehicle Assigned", "At Loading Point", "Loaded"].includes(trip.status) && !trip.departure_inspected) {
			return "Departure"
		}
		if (["Delivered", "Settled"].includes(trip.status) && trip.departure_inspected && !trip.return_inspected) {
			return "Return"
		}
	}
	return steps[trip.status] || null
}

export function primaryMission(trips) {
	const active = trips.find(trip => nextStep(trip) && trip.status !== "Vehicle Assigned")
	return active || trips.filter(trip => trip.status === "Vehicle Assigned").sort((left, right) =>
		(left.planned_departure_at || left.trip_date || "").localeCompare(right.planned_departure_at || right.trip_date || ""),
	)[0] || null
}
