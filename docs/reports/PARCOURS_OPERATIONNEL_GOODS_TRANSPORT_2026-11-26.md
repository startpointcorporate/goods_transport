# Recette du parcours opérationnel Goods Transport

## Correctifs

| Anomalie | Résultat |
| --- | --- |
| La quantité de marchandises multipliait le tarif par mission | La commande calcule une quantité facturable selon la base choisie. À 450 000 XAF par mission, huit unités de marchandise donnent 450 000 XAF de fret avant frais. |
| Les bases variables utilisaient la même quantité | Le nombre de véhicules, le poids en kilogrammes ou en tonnes, le nombre de colis et la distance en kilomètres alimentent chacun le calcul correspondant. Le forfait compte pour une unité. |
| Le passage commande → mission perdait la quantité affectée | La mission reprend les lieux, l’étape, la distance indicative et la date de chargement proposée. Elle mémorise plusieurs commandes et calcule leur poids prévu au prorata des quantités affectées. |
| La création de la lettre exigeait des ressaisies | Le parcours reprend le véhicule et le conducteur de la mission, puis le client, les lieux, la marchandise, la devise et le tarif de la commande. Le poids ou les colis de la lettre peuvent alimenter directement sa quantité facturable. |
| Une affectation ou une facture incohérente pouvait être enregistrée | Les filtres Desk orientent la sélection. Le serveur contrôle la société, le véhicule et le conducteur, ainsi que les données commerciales et l’identité du client sur les documents concernés. Il contrôle aussi le disponible à l’expédition lors de la validation d’une lettre. |
| La preuve de livraison dépendait des champs chargés par Desk | Le serveur reprend le client, la destination, la mission et la quantité expédiée de la lettre. Une seule preuve validée par lettre alimente la progression. Un manque constaté rouvre la quantité correspondante à l’expédition. |
| Les actions étaient dispersées ou redondantes | Les menus de la mission regroupent création, planification, carburant, inspections, suivi et finances. Les raccourcis rechargent la mission après une mise à jour par un document lié, dont le règlement. |
| Les connexions de la mission étaient incomplètes | Les liens Frappe affichent le nombre de lettres, autorisations, avances, dépenses, règlements, inspections, immobilisations et rémunérations. Les listes utilisent le filtre de la mission, vérifié en ouvrant la liste des lettres depuis une mission clôturée. |
| « Settled » apparaissait comme « Colonisé » | Le catalogue français fournit « Réglé » et les libellés des nouvelles actions. |

## Preuves et périmètre

- La recette navigateur utilise un site ERPNext/HRMS jetable avec des sociétés, véhicules, clients, stations et pièces comptables fictifs. Le serveur OSRM de test produit des itinéraires déterministes et distingue les distances voiture et poids lourd.
- Le flux nominal crée et valide la commande, affecte la mission, calcule l’itinéraire et les péages, enregistre un plan carburant et autorise son arrêt. Il crée la lettre, l’avance et la dépense, réalise les inspections départ et retour, enregistre la livraison, valide la facture et le règlement, clôture la mission et ouvre sa rentabilité.
- La recette contrôle une lettre, une autorisation, une avance, une dépense, un règlement et deux inspections dans les connexions. Les compteurs d’immobilisation et de rémunération sont à zéro dans ce cas nominal.
- 56 tests Python et 3 tests JavaScript ont réussi. Les tests serveur couvrent les sept bases, le groupage multi-clients, la livraison à un arrêt intermédiaire, la répartition entre missions, le reliquat après livraison partielle, la facturation et les droits restreints.
- Les écritures comptables se limitent à la base jetable. Aucune opération n’a été exécutée sur `transportdemo.konektag.eu`. Les documents d’audit sont préservés.

## Rejouer

Sur un Bench de recette avec Frappe, ERPNext, HRMS et Goods Transport, appliquer la migration, compiler le catalogue français et activer le contrôle financier ainsi que les options de routage et de plan carburant. Pour le scénario fictif, lancer `journey_osrm_stub.mjs` sur les ports 5000 et 5001, puis configurer les URL OSRM voiture et poids lourd sur ces services.

```sh
bench --site <site-local> migrate
bench compile-po-to-mo --app goods_transport --locale fr
bench --site <site-local> run-tests --module goods_transport.goods_transport.tests.test_operational_journey
node --test tests/transport_trip_permissions.test.cjs
```

Lancer `tests/e2e/seed_operational_journey.py` avec l’interpréteur du Bench, sur le site jetable indiqué par `JOURNEY_QA_SITE`. Enregistrer sa sortie JSON et lancer Playwright depuis un environnement où le paquet est installé.

```sh
node tests/e2e/operational_journey.mjs http://127.0.0.1:<port> <fixture.json>
```

Le navigateur lit le mot de passe de l’administrateur local dans `JOURNEY_QA_PASSWORD`.

## Points ouverts pour le cours C3

- Prévoir une validation de la version déployée avec la configuration réelle des graphes, des tarifs de péage et du thème Desk avant de reprendre le chapitre 2. La recette isolée utilise des réponses de routage simulées et le thème du Bench local.
- Les montants des commandes déjà validées restent ceux enregistrés. Le poids repris pour les nouveaux calculs est exprimé en kilogrammes. Vérifier la saisie d’origine avant de réviser une ancienne commande par le processus métier.
- La création de facture sous-traitant et la déclaration de panne conservent leurs services existants. Le scénario navigateur nominal ne crée ni panne ni facture sous-traitant.
