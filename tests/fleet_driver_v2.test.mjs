import assert from "node:assert/strict"
import test from "node:test"
import { nextStep, primaryMission } from "../hrms_mobile/missionFlow.mjs"

test("first assigned mission uses planned departure, with active mission taking precedence", () => {
	const later = { name: "late", status: "Vehicle Assigned", planned_departure_at: "2026-11-28 08:00" }
	const next = { name: "next", status: "Vehicle Assigned", planned_departure_at: "2026-11-27 08:00" }
	const active = { name: "active", status: "In Transit" }
	assert.equal(primaryMission([later, next]), next)
	assert.equal(primaryMission([later, next, active]), active)
})

test("inspection and driver completion follow the assigned phase", () => {
	assert.equal(nextStep({ status: "Loaded", inspection_configured: true }), "Departure")
	assert.equal(nextStep({ status: "Loaded", inspection_configured: true, departure_inspected: true }), "departed")
	assert.equal(nextStep({ status: "Delivered", inspection_configured: true, departure_inspected: true }), "Return")
	assert.equal(nextStep({ status: "Delivered", driver_finished: true }), null)
	assert.equal(nextStep({ status: "Closed" }), null)
})
