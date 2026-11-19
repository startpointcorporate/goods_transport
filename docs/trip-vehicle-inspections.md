# États des lieux des véhicules

## Mise en service

Dans Desk, un responsable Fleet crée un **Modèle d’état des lieux** pour chaque société et, si nécessaire, pour chaque type de véhicule. Un modèle sans type sert de modèle général. La mission peut aussi désigner explicitement un modèle de sa société et de son type. À la soumission, Goods Transport conserve une copie des règles sur la mission.

Donnez à chaque contrôle un code stable, un libellé français et un libellé anglais. Paramétrez les contrôles obligatoires, les cas où « Non applicable » est permis, le nombre de photos et les contrôles de sécurité ou de documents. Ces deux derniers sont toujours obligatoires. Exemples de contrôles à adapter au véhicule et à la mission.

| Code | Point de contrôle | Vérification |
|---|---|---|
| carrosserie | Carrosserie | Bosses et rayures |
| vitrages | Vitrages | Fissures et impacts |
| retroviseurs | Rétroviseurs | État et fixation |
| eclairage | Éclairage | Phares, clignotants et feux |
| pneumatiques | Pneumatiques | Usure et dommages visibles |
| roues | Roues | Fixation et anomalies visibles |
| freins | Freins | Contrôle déclaré |
| cabine | Cabine | État général |
| securite | Équipements de sécurité | Présence et état |
| reservoir | Réservoir | État apparent |
| chargement | Chargement | Sécurisation selon l’étape |
| documents | Documents du véhicule | Présence et validité déclarées |

Activez **Exiger les inspections pour les nouvelles missions** par modèle. Pour les rendre obligatoires sur le site pour toutes les missions créées à partir d’une date, configurez `trip_inspection_required_from` au format `YYYY-MM-DD HH:MM:SS` dans le fuseau horaire Frappe. Renseignez les modèles de toutes les sociétés concernées avant d’activer la date. Après activation, une nouvelle mission sans modèle applicable est refusée à la soumission. Les missions déjà soumises conservent leur politique et leur historique.

## Guide opérateur

Sur smartphone, les actions de la mission sont disponibles dans le menu **⋯** de Desk.

1. Ouvrez la **Mission de transport** soumise et choisissez **État des lieux de départ**. Vérifiez le camion, le chauffeur et le lieu. Saisissez le compteur réel et renseignez chaque point.
2. Appuyez sur **Prendre une photo** pour ouvrir l’appareil photo d’un téléphone compatible ou sur **Importer une photo**. Vous pouvez associer plusieurs photos à un contrôle. Sélectionnez une vignette pour l’agrandir. Les vues générales recommandées peuvent être renseignées en complément.
3. Pour un défaut, saisissez un code stable, une gravité et une observation. Réutilisez au retour le même code si vous constatez le même défaut. Utilisez un code distinct si le défaut constaté est différent.
4. Vous pouvez enregistrer la position GPS avec le bouton prévu et l’autorisation du navigateur. La position est ponctuelle et enregistrée à la validation.
5. Cliquez sur **Valider l’état des lieux**. Une mission soumise à inspection ne peut passer **En transit** qu’après validation du départ. Une immobilisation Fleet Maintenance active bloque le départ même si l’inspection est validée.
6. Après livraison, cliquez sur **État des lieux de retour**. Saisissez le compteur réel et effectuez chaque vérification sur place. Validez avant de clôturer la mission.
7. Ouvrez **Comparer les états des lieux**. Consultez les écarts, les observations, les photos et les deux résultats de conformité. Agrandissez les photos pour contrôler les détails.
8. En cas de défaut, ouvrez l’inspection validée et utilisez **Créer une intervention de maintenance**. Avec un actif de maintenance, cette action crée un Asset Repair et requiert les droits ERPNext correspondants. Sans actif, elle ouvre une tâche Frappe liée à l’inspection afin de transmettre la demande de maintenance.
9. Pour corriger un résultat validé, un administrateur ouvre **Correction administrative**, indique le motif et valide une nouvelle révision. L’historique conserve les observations, le validateur et les photos des révisions précédentes.

## Règles de comparaison

| Situation | Résultat |
|---|---|
| Deux résultats équivalents et conformes | Inchangé |
| Défaut de même code et même gravité | Anomalie préexistante |
| Défaut de code différent ou signalé pour la première fois | Nouvelle anomalie |
| Même défaut, gravité supérieure | Aggravé |
| Même défaut, gravité inférieure | Amélioré |
| Défaut suivi d’un contrôle conforme | Résolu |
| Contrôle manquant ou changement d’applicabilité empêchant la comparaison | Non vérifié |

Un nouveau défaut ou une aggravation rend le véhicule non conforme. En l’absence d’un tel écart, une preuve ou un contrôle obligatoire manquant donne un statut **À examiner**. Un défaut préexistant de même gravité reste visible et ne s’impute pas automatiquement à la mission. La conformité opérationnelle tient compte du chauffeur, du véhicule, des inspections, du compteur, des contrôles documentaires et de sécurité et des immobilisations liées à la mission. Le POD garde ses propres règles de validation.

Un défaut critique sur un contrôle de sécurité ouvre ou référence une **Vehicle Immobilisation**. La remise en service passe par la procédure Fleet Maintenance. Les autres réparations passent par **Asset Repair**. L’état des lieux relie la réparation à la mission, au véhicule et à ses photos.

## Recette reproductible

Sur un site isolé équipé de Frappe, ERPNext, HRMS et Goods Transport, activez `allow_tests` et lancez les commandes suivantes.

```bash
bench --site inspection-qa.localhost run-tests --module goods_transport.goods_transport.tests.test_trip_inspection
bench --site inspection-qa.localhost run-tests --module goods_transport.goods_transport.tests.test_transport_recette
```

Pour la recette Desk, utilisez `tests/e2e/seed_trip_inspection.py` avec le Python du bench. Fournissez le JSON produit, le mot de passe de l’administrateur de recette dans `FLEET_TEST_PASSWORD`, deux images de test et un écran de recette 1920 × 1080. Lancez le script Playwright dans un environnement Node avec le paquet `playwright` et FFmpeg.

```bash
node tests/e2e/trip_inspection.mjs http://127.0.0.1:8000 fixtures.json captures depart.png retour.png
```
