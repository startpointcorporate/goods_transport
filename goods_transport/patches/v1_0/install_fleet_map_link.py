import frappe


def execute():
	workspace = "Goods Transport"
	if not frappe.db.exists("Workspace", workspace):
		return
	doc = frappe.get_doc("Workspace", workspace)
	if not any(link.link_type == "Page" and link.link_to == "fleet-map" for link in doc.links):
		index = next((i + 1 for i, link in enumerate(doc.links) if link.label == "Operations"), 0)
		row = doc.append("links", {"type": "Link", "label": "Fleet Map", "link_type": "Page", "link_to": "fleet-map"})
		doc.links.remove(row)
		doc.links.insert(index, row)
		for idx, link in enumerate(doc.links, 1):
			link.idx = idx
		doc.save(ignore_permissions=True)
