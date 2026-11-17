frappe.listview_settings["Transport Location"] = {
	onload(list) {
		if (!frappe.boot.goods_transport_route_preview) return;
		list.page.add_inner_button(__("Carte des péages"), async () => {
			const { message: tolls } = await frappe.call({
				method: "goods_transport.goods_transport.services.toll_routing.list_tolls", freeze: true,
			});
			await frappe.require("/assets/goods_transport/js/toll_map.js");
			await goods_transport.toll_map.show({ tolls });
		});
	},
};
