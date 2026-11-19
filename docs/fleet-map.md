# Carte de la flotte

Dans Frappe Desk, ouvrez **Goods Transport → Carte de la flotte** et choisissez une mission dans le champ **Mission de transport**. Sur une fiche de mission enregistrée, utilisez **Voir sur la carte** pour ouvrir directement la même page. **Ouvrir la mission** revient à la fiche.

Utilisez la molette, les boutons de zoom et le glisser-déposer pour parcourir la carte. Cliquez sur un marqueur ou sur son libellé sous la carte pour consulter les détails. Un marqueur chiffré regroupe des points proches et s’ouvre en zoomant. Les péages rapprochés du tracé sont numérotés dans l’ordre du passage estimé. Lorsqu’un tarif est disponible pour la catégorie poids lourd et la date de mission, il s’affiche avec sa devise.

Le trait continu représente le poids lourd et le trait pointillé la voiture. Pour afficher un plan poids lourd enregistré, sélectionnez les arrêts dans le plan de route sur la fiche de mission. Après une modification enregistrée, cliquez sur **Actualiser la carte**. Vérifiez les restrictions locales de circulation et les postes de pesage avant le départ.

Les stations distinguent les arrêts prévus, les stations disponibles pour le carburant du véhicule et les stations sans réserve utilisable. Les quantités planifiées et autorisées répondent à des usages distincts. Les soldes accessibles sont relus lors de chaque ouverture ou actualisation. Les droits Frappe de l’utilisateur et la société de la mission déterminent les données affichées.

La dernière position affiche son heure et, si le fournisseur les transmet, sa précision et son ancienneté. Un relevé de 15 minutes ou plus est signalé comme ancien. Chaque actualisation lit le dernier relevé disponible.

## Fleet Map

In Desk, open **Goods Transport → Fleet Map**, then choose a **Transport Trip**. From a saved trip, select **View on map**. Click a marker or its label to view details. The solid line shows the truck route and the dashed line shows the car route. Select **Refresh map** after saving a route change to reload the route, fuel data and last known position. Check local truck restrictions and weigh stations before departure.

## Configuration du site

- `goods_transport_osrm_url` active la carte. `goods_transport_truck_osrm_url` et `goods_transport_partner_fuel` activent les couches métier correspondantes.
- `goods_transport_map_tile_url` définit un modèle HTTPS avec `{z}/{x}/{y}`. Par défaut, la carte affiche les tuiles publiques OpenStreetMap. `goods_transport_map_tile_attribution` ajoute le crédit du fournisseur. Le navigateur charge les tuiles visibles avec son cache HTTP. [Politique des tuiles OpenStreetMap](https://operations.osmfoundation.org/policies/tiles/)
- `goods_transport_osrm_graph_revision` permet de renouveler les clés de cache lors d’un changement de graphe sur la même URL. Les réponses OSRM de la carte expirent après cinq minutes.
- Les ateliers utilisent l’adresse principale d’un fournisseur associé à une immobilisation du camion dans la même société. L’adresse doit déjà comporter des coordonnées `longitude` et `latitude`, ou `custom_longitude` et `custom_latitude`.
- Un fournisseur GPS côté serveur peut s’enregistrer avec le hook `goods_transport_last_position`. Il reçoit la mission dont l’accès a été contrôlé et renvoie le dernier relevé avec `trip`, `vehicle`, `longitude`, `latitude`, `recorded_at` dans le fuseau du site et `accuracy_m` facultatif.
