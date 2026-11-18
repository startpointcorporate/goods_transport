frappe.provide("goods_transport.trip_finance");

goods_transport.trip_finance.open = async function (frm) {
	const endpoint = "goods_transport.goods_transport.services.trip_finance.";
	const { message: data } = await frappe.call({
		method: endpoint + "overview", args: { trip_name: frm.doc.name }, freeze: true,
	});
	const dialog = new frappe.ui.Dialog({
		title: __("Contrôle financier de la mission"), size: "extra-large",
		fields: [{ fieldname: "content", fieldtype: "HTML" }],
	});
	const body = dialog.fields_dict.content.$wrapper;
	const money = (value, currency = data.currency) => value == null
		? __("Indisponible") : format_currency(value, currency);
	const percent = (value) => value == null ? "—" : `${value.toFixed(1)} %`;
	const link = (type, name, label = name) => name
		? $("<a>").attr("href", frappe.utils.get_form_link(type, name)).text(label) : "";
	const table = (title, headers, rows) => {
		$("<h5>").addClass("mt-4").text(title).appendTo(body);
		if (!rows.length) {
			$("<p>").text(__("Aucun document enregistré")).appendTo(body);
			return;
		}
		const container = $("<div>").addClass("table-responsive").appendTo(body);
		const grid = $("<table>").addClass("table table-sm table-bordered").appendTo(container);
		const head = $("<tr>").appendTo($("<thead>").appendTo(grid));
		for (const header of headers) $("<th>").text(header).appendTo(head);
		const tbody = $("<tbody>").appendTo(grid);
		for (const row of rows) {
			const tr = $("<tr>").appendTo(tbody);
			for (const value of row) {
				const td = $("<td>").appendTo(tr);
				if (value?.jquery) td.append(value);
				else td.text(value ?? "—");
			}
		}
	};
	const indicator = data.provisional ? __("Provisoire") : __("Clôturé");
	$("<p>").addClass("font-weight-bold").text(indicator).appendTo(body);
	$("<p>").text(__("Statut de la mission · {0}", [__(data.operational_status)])).appendTo(body);
	table(__("Prévision et coût économique"), [__("Poste"), __("Budget"), __("Réalisé"), __("Écart"), "%", __("État")],
		[...data.rows, { category: __("Total"), ...data.total }].map((r) => [
			r.category, money(r.planned), money(r.actual), money(r.delta), percent(r.percent), r.status,
		]));
	table(__("Rentabilité et trésorerie"), [__("Indicateur"), __("Montant")], [
		[__("Facturé TTC"), money(data.billed)],
		[__("Chiffre d’affaires reconnu"), money(data.recognized)],
		[__("Coûts identifiés"), money(data.known_cost)],
		[__("Dont coûts imputés au grand livre"), money(data.ledger_cost)],
		[__("Dont valorisation des retraits hors grand livre"), money(data.operational_fuel_cost)],
		[__("Marge sur coûts identifiés"), money(data.margin)],
		[__("Taux de marge"), percent(data.margin_rate)],
		[__("Encaissements attribués à la mission"), money(data.cash_in)],
		[__("Décaissements attribués à la mission"), money(data.cash_out)],
	]);
	if (data.route.km != null) {
		$("<p>").text(__("Plan de référence · {0} km · classe {1} · {2} L/100 km · {3} L prévus", [
			data.route.km.toFixed(1), data.route.category, data.route.rate ?? "—",
			data.route.required_liters?.toFixed(1) ?? "—",
		])).appendTo(body);
	}
	table(__("Péages"), [__("Gare"), __("Estimé"), __("Coûts imputés"), __("Payé directement"), __("État")],
		data.tolls.map((r) => [r.name, money(r.amount, "XAF"), money(r.actual), money(r.paid), r.status]));
	table(__("Ravitaillements planifiés"), [__("Station"), __("Volume (L)"), __("Prix/L")],
		(data.route.stops || []).map((r) => [r.station, r.refill_liters, money(r.unit_price, data.route.currency)]));
	table(__("Retraits confirmés"), [__("Station"), __("Réserve contractuelle"), __("Camion"), __("Chauffeur"), __("Volume (L)"),
		__("Prix/L"), __("Valeur"), __("Imputation")],
		data.withdrawals.map((r) => [r.station, link("Fuel Contract Reserve", r.reserve), r.vehicle, r.driver, r.delivered_liters,
			money(r.unit_price, r.price_currency), money(r.value), r.basis]));
	table(__("Dépenses et justificatifs"), [__("Dépense"), __("Type"), __("Montant"), __("Mode"),
		__("Pièce comptable"), __("Justificatif"), __("État")], data.expenses.map((r) => [
		link("Trip Expense", r.name), r.expense_type, money(r.amount || (r.docstatus ? 0 : null), r.currency),
		r.payment_mode, r.purchase_invoice ? link("Purchase Invoice", r.purchase_invoice) : link("Journal Entry", r.journal_entry),
		r.receipt ? link("Trip Expense", r.name, __("Ouvrir la pièce")) : __("Absent"),
		data.pending.includes(r.name) ? __("À justifier") : r.posted ? __("Imputé") : __("À imputer"),
	]));
	table(__("Avances et règlements"), [__("Document"), __("Montant / solde"), __("État")], [
		...data.advances.map((r) => [link("Trip Advance", r.name), money(r.amount, r.currency), r.status]),
		...data.settlements.map((r) => [link("Trip Settlement", r.name), money(r.outstanding_from_driver, r.currency),
			r.docstatus ? __("Soumis") : __("Brouillon")]),
	]);
	table(__("Factures client"), [__("Document"), __("TTC en devise société"), __("Solde facture")],
		data.invoices.map((r) => [link("Sales Invoice", r.name), money(r.base_grand_total),
			money(r.outstanding_amount, r.currency)]));
	table(__("Paiements rapprochés aux factures"), [__("Document"), __("Type"), __("Attribution")],
		data.payments.map((r) => [link("Payment Entry", r.name), r.payment_type,
			r.attributed ? __("Attribué à la mission") : __("Montant mission indéterminé")]));
	if (frm.perm[0]?.write && !["Settled", "Closed", "Cancelled"].includes(frm.doc.status)) {
		dialog.set_secondary_action_label(__("Budgéter les frais complémentaires"));
		dialog.set_secondary_action(() => {
			const editor = new frappe.ui.Dialog({
				title: __("Frais complémentaires en {0}", [frm.doc.currency]),
				fields: [{
					fieldname: "lines", fieldtype: "Table", label: __("Frais"), in_place_edit: true,
					data: data.budget.extra || [],
					fields: [
						{ fieldname: "type", fieldtype: "Link", options: "Trip Expense Type",
							label: __("Type de frais"), reqd: 1, in_list_view: 1 },
						{ fieldname: "amount", fieldtype: "Data",
							label: __("Montant (vide si inconnu)"), in_list_view: 1 },
					],
				}],
				primary_action_label: __("Enregistrer"),
				async primary_action({ lines }) {
					await frappe.call({
						method: endpoint + "save_budget", freeze: true,
						args: { trip_name: frm.doc.name, extra: JSON.stringify(lines || []) },
					});
					editor.hide();
					dialog.hide();
					await frm.reload_doc();
					await goods_transport.trip_finance.open(frm);
				},
			});
			editor.show();
		});
	}
	dialog.show();
};
