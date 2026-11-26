// Deterministic OSRM-compatible responses for the disposable UI scenario.
import { createServer } from "node:http";

createServer((request, response) => {
	const path = new URL(request.url, "http://localhost").pathname;
	const [, service, , , coordinates] = path.split("/");
	const points = coordinates.split(";").map((pair) => pair.split(",").map(Number));
	const truck = request.headers.host.endsWith(":5001");
	const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]) * (truck ? 120000 : 100000);
	const legs = points.slice(1).map((point, index) => ({ distance: distance(points[index], point) }));
	const payload = service === "table" ? { distances: points.map((a) => points.map((b) => distance(a, b))) } : {
		waypoints: points.map((location) => ({ location })),
		routes: [{
			legs, geometry: { type: "LineString", coordinates: points },
			distance: legs.reduce((total, leg) => total + leg.distance, 0), duration: 1800,
		}],
	};
	response.writeHead(200, { "Content-Type": "application/json" });
	response.end(JSON.stringify({ code: "Ok", ...payload }));
}).listen(Number(process.argv[2]), "0.0.0.0");
