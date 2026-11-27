"""Apply the Goods Transport extension to a disposable HRMS 16.53.2 build tree."""

import argparse
import shutil
from pathlib import Path

EXTENSION = Path(__file__).resolve().parent
ROUTER = Path("router/index.js")
HOME = Path("views/Home.vue")
EDITS = (
	(
		Path("../../hrms/www/hrms.py"),
		'"default_route": get_default_route(),',
		'"default_route": get_default_route(),\n'
		'\t\t\t"goods_transport_fleet_photos": frappe.conf.get("goods_transport_fleet_photos") or {},',
	),
	(
		Path("main.js"),
		'if (session?.isLoggedIn && !employeeResource?.data) {',
		'if (!window.frappe?.boot?.fleet_offline && session?.isLoggedIn && !employeeResource?.data) {',
	),
	(
		Path("main.js"),
		'router.beforeEach(async (to, _, next) => {',
		'router.beforeEach(async (to, from, next) => {\n'
		'\tif (window.frappe?.boot?.fleet_offline) {\n'
		'\t\treturn next(to.name === "FleetDriverMissions" ? undefined : { name: "FleetDriverMissions" })\n'
		'\t}',
	),
	(
		Path("main.js"),
		'} else if (["Login", "ForgotPassword"].includes(to.name)) {',
		'} else if ((to.name === "Home" && (!from.name || from.name === "Login") && to.query.space !== "hr" || to.name === "Login") &&\n'
		'\t\t    userResource.data?.roles?.includes("Fleet Driver") && await fleetAvailable()) {\n'
		'\t\t    next({ name: "FleetDriverMissions" })\n'
		'\t\t} else if (["Login", "ForgotPassword"].includes(to.name)) {',
	),
	(
		Path("main.js"),
		'router.isReady().then(async () => {',
		'import { getFleetData } from "@/fleet_driver/fleetApi"\n\n'
		'function fleetAvailable() {\n'
		'    return getFleetData("available").catch(() => false)\n'
		'}\n\nrouter.isReady().then(async () => {',
	),
	(
		Path("data/session.js"),
		'import router from "@/router"',
		'import router from "@/router"\nimport { purgeFleetSnapshot } from "@/fleet_driver/offline"\n'
		'import { resetFleetOutboxSession } from "@/fleet_driver/fleetOutbox"',
	),
	(
		Path("data/session.js"),
		'function handleLogin(response) {',
		'async function handleLogin(response) {',
	),
	(
		Path("data/session.js"),
		'if (response.message === "Logged In") {',
		'if (response.message === "Logged In") {\n\t\tpurgeFleetSnapshot()\n\t\tresetFleetOutboxSession()',
	),
	(
		Path("data/session.js"),
		'url: "logout",\n\t\tonSuccess() {',
		'url: "logout",\n\t\tasync onSuccess() {\n\t\t\tpurgeFleetSnapshot()\n\t\t\tresetFleetOutboxSession()',
	),
	(
		Path("../public/sw.js"),
		'precacheAndRoute(self.__WB_MANIFEST)',
		'precacheAndRoute(self.__WB_MANIFEST.map(entry => ({\n'
		'\t...entry, url: new URL(entry.url, self.location.origin + "/assets/hrms/frontend/").href,\n'
		'})))\n\n' + (EXTENSION / "offlineWorker.js").read_text(),
	),
	(
		ROUTER,
		'\t\t\t{\n\t\t\t\tpath: "/dashboard/attendance",',
		'\t\t\t{\n\t\t\t\tpath: "/fleet",\n\t\t\t\tname: "FleetDriverMissions",'
		'\n\t\t\t\tcomponent: () => import("@/fleet_driver/FleetMissions.vue"),\n\t\t\t},'
		'\n\t\t\t{\n\t\t\t\tpath: "/dashboard/attendance",',
	),
	(HOME, "<CheckInPanel />", "<CheckInPanel />\n\t\t\t\t<FleetLink />"),
	(
		HOME,
		'import CheckInPanel from "@/components/CheckInPanel.vue"',
		'import CheckInPanel from "@/components/CheckInPanel.vue"\n'
		'import FleetLink from "@/fleet_driver/FleetLink.vue"',
	),
)


def integrate(hrms):
	source = hrms / "frontend" / "src"
	files = {}
	for path, anchor, replacement in EDITS:
		file = source / path
		content = files.get(file)
		if content is None:
			content = file.read_text()
		if replacement in content:
			continue
		if content.count(anchor) != 1:
			raise ValueError(f"Unexpected HRMS source in {file}")
		files[file] = content.replace(anchor, replacement, 1)

	fleet = source / "fleet_driver"
	fleet.mkdir(exist_ok=True)
	for asset in ("FleetLink.vue", "FleetMissions.vue", "missionFlow.mjs", "fleetOutbox.js", "fleetApi.js", "offline.js", "FleetInspection.vue", "FleetOperations.vue", "FleetRoadDocuments.vue", "roadDocuments.js", "FleetPhotoPicker.vue", "FleetPrivateDocuments.vue"):
		shutil.copyfile(EXTENSION / asset, fleet / asset)
	for path, content in files.items():
		path.write_text(content)


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("hrms", type=Path)
	integrate(parser.parse_args().hrms)
