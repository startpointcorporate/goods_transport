"""Billable units for an estimate or a consignment."""


CARGO_BASES = ("Per Ton", "Per Kg", "Per Package")


def billable_quantity(basis, *, weight_kg=0, packages=0, distance_km=0, vehicles=1):
	if basis == "Per Vehicle":
		return float(vehicles or 0)
	if basis == "Per Ton":
		return float(weight_kg or 0) / 1000
	if basis == "Per Kg":
		return float(weight_kg or 0)
	if basis == "Per Package":
		return float(packages or 0)
	if basis == "Per KM":
		return float(distance_km or 0)
	return 1.0
