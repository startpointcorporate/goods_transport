"""Fuel allocations for one ordered OSRM route, in integer millilitres."""

from collections import deque
from decimal import Decimal, ROUND_CEILING


def demand(meters, rate):
	return int((Decimal(str(meters)) * rate).to_integral_value(rounding=ROUND_CEILING))


def allocate(legs, supplies, prices, initial, capacity):
	"""Find the minimum-cost flow through the tank and the successive legs."""
	if any(leg > capacity for leg in legs):
		return None
	size = len(legs)
	source, sink = size, size + 1
	graph = [[] for _ in range(size + 2)]

	def edge(start, end, volume, cost=0):
		forward = [end, len(graph[end]), volume, cost]
		graph[start].append(forward)
		graph[end].append([start, len(graph[start]) - 1, 0, -cost])
		return forward

	# Prefer the fuel physically in the tank even when a supplier has a zero price.
	edge(source, 0, initial, -1)
	purchases = []
	for i, leg in enumerate(legs):
		edge(i, sink, leg)
		if i + 1 < size:
			edge(i, i + 1, capacity - leg)
		if i:
			purchases.append(edge(source, i, supplies[i - 1], prices[i - 1]))
	remaining = sum(legs)
	while remaining:
		costs = [None] * len(graph)
		previous = [None] * len(graph)
		costs[source] = 0
		queue = deque([source])
		queued = {source}
		while queue:
			node = queue.popleft()
			queued.remove(node)
			for index, (target, _, volume, price) in enumerate(graph[node]):
				price += costs[node]
				if volume and (costs[target] is None or price < costs[target]):
					costs[target] = price
					previous[target] = node, index
					if target not in queued:
						queue.append(target)
						queued.add(target)
		if previous[sink] is None:
			return None
		chain = []
		node = sink
		while node != source:
			start, index = previous[node]
			link = graph[start][index]
			chain.append(link)
			node = start
		volume = min(remaining, *(link[2] for link in chain))
		for target, reverse, _, _ in chain:
			link = graph[target][reverse]
			graph[link[0]][link[1]][2] -= volume
			link[2] += volume
		remaining -= volume
	return [supply - link[2] for supply, link in zip(supplies, purchases)]


def find_paths(nodes, matrix, initial, capacity, rate, limit=24):
	"""Keep a bounded set of low-detour paths and high-fuel alternatives at each node."""
	labels = [[(0, initial, (0,))]]
	for target in range(1, len(nodes)):
		offers = []
		for start, starts in enumerate(labels):
			if any(node.get("mandatory") for node in nodes[start + 1:target]):
				continue
			meters = matrix[start][target]
			if meters is None:
				continue
			required = demand(meters, rate)
			for distance, fuel, path in starts:
				if fuel < required:
					continue
				after = min(capacity, fuel - required + nodes[target].get("supply", 0))
				offers.append((distance + meters, after, (*path, target)))
		shortest = sorted(offers, key=lambda x: (x[0], len(x[2]), -x[1], x[2]))
		fullest = sorted(offers, key=lambda x: (-x[1], x[0], len(x[2]), x[2]))
		labels.append(list(dict.fromkeys(shortest[:limit] + fullest[:limit // 2])))
	return [path for _, _, path in labels[-1]][:limit]
