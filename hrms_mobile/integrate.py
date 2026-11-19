"""Apply the Goods Transport extension to a disposable HRMS 16.53.2 build tree."""

import argparse
import shutil
from pathlib import Path

EXTENSION = Path(__file__).resolve().parent
ROUTER = Path("router/index.js")
HOME = Path("views/Home.vue")
EDITS = (
	(
		Path("main.js"),
		'if (session?.isLoggedIn && !employeeResource?.data) {',
		'if (!window.frappe?.boot?.fleet_offline && session?.isLoggedIn && !employeeResource?.data) {',
	),
	(
		Path("main.js"),
		'router.beforeEach(async (to, _, next) => {',
		'router.beforeEach(async (to, _, next) => {\n'
		'\tif (window.frappe?.boot?.fleet_offline) {\n'
		'\t\treturn next(to.name === "FleetDriverMissions" ? undefined : { name: "FleetDriverMissions" })\n'
		'\t}',
	),
	(
		Path("data/session.js"),
		'import router from "@/router"',
		'import router from "@/router"\nimport { purgeFleetSnapshot } from "@/fleet_driver/offline"',
	),
	(
		Path("data/session.js"),
		'if (response.message === "Logged In") {',
		'if (response.message === "Logged In") {\n\t\tpurgeFleetSnapshot()',
	),
	(
		Path("data/session.js"),
		'url: "logout",\n\t\tonSuccess() {',
		'url: "logout",\n\t\tonSuccess() {\n\t\t\tpurgeFleetSnapshot()',
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
	for asset in ("FleetLink.vue", "FleetMissions.vue", "fleetApi.js", "offline.js", "FleetInspection.vue", "FleetOperations.vue", "FleetRoadDocuments.vue", "roadDocuments.js"):
		shutil.copyfile(EXTENSION / asset, fleet / asset)
	for path, content in files.items():
		path.write_text(content)


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("hrms", type=Path)
	integrate(parser.parse_args().hrms)
