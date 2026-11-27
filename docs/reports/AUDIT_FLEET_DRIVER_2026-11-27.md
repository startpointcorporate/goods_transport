# Audit initial Fleet Driver — 27 novembre 2026

Base examinée : `goods_transport` main `d6ca00c`.

| Écran ou module | Actions existantes | Contrôles et limites |
| --- | --- | --- |
| FleetLink et integrate.py | Lien depuis l’accueil RH vers la liste Fleet. Route ajoutée au build HRMS et service worker sous /hrms. | Disponibilité conditionnée par le rôle et l’affectation. Authentification HRMS unique. |
| FleetMissions | Liste filtrable, détail, emplacements, guidage, arrêts et autorisations carburant. | Toutes les sections sont montées ensemble. Aucun ordre des actions terrain. |
| FleetInspection et FleetPhotoPicker | Ouvrir départ ou retour, saisir le compteur, qualifier les contrôles, joindre des photos privées, valider. | Les deux phases sont proposées. Les contrôles utilisent des listes. Le serveur exige code, gravité et observation en anomalie. |
| FleetOperations | Présenter les codes carburant actifs, confirmer une livraison, déclarer un incident. | Lettre de voiture sélectionnée sans distinguer les preuves déjà validées. Quantités saisies à la main. Catégorie et immobilisation couplées. |
| FleetRoadDocuments, FleetPrivateDocuments, roadDocuments | Consulter le PDF, les péages et les fichiers autorisés. Synchronisation locale des documents. | Fichiers privés filtrés et revérifiés côté serveur. Stockage associé au compte et à la version de mission. |
| fleetApi, offline.js et offlineWorker.js | Requêtes session/CSRF, instantané de consultation et shell HRMS hors connexion. | Durée de 12 heures pour l’instantané. Purge à la connexion et déconnexion. Écritures uniquement en ligne. |

Le service Fleet exige un rôle Fleet Driver, un employé actif et un chauffeur actif uniques, puis filtre les trajets soumis par chauffeur et société. Une permission utilisateur Company applicable restreint également l’accès. Le chauffeur ne reçoit aucune permission générique sur Transport Trip. Les lectures sélectionnent les champs opérationnels. Les codes carburant sont exposés par un POST ciblé et ne figurent pas dans l’instantané.

Transport Trip passe de Planned à Vehicle Assigned à la soumission. L’exploitation peut avancer vers At Loading Point, Loaded, In Transit, Arrived, Unloading et Delivered. Le franchissement de In Transit vérifie l’affectation, la disponibilité et l’inspection. La transition Delivered vérifie les lettres et les preuves exigées. Trip Settlement règle la mission. Closed exige aussi l’inspection de retour selon la politique et les pièces comptables. Les écritures génériques ne peuvent changer librement le statut d’un trajet soumis.

Trip Inspection copie la politique du modèle à la soumission du trajet. Le départ est autorisé jusqu’à Loaded, le retour après Delivered ou Settled et après une inspection de départ validée. Les contrôles obligatoires, N/A, photos distinctes et anomalies sont validés côté serveur. Une anomalie critique peut immobiliser le véhicule. Fleet Odometer verrouille le véhicule, contrôle la monotonie et enregistre les lectures vérifiées.

Bilty soumise rattache les marchandises à la mission. Proof of Delivery limite la quantité à celle expédiée, calcule le manquant et interdit plusieurs preuves soumises pour une même lettre. Fleet ajoute le contrôle de l’affectation, du statut, de la quantité endommagée et du réceptionnaire. Vehicle Immobilisation reste piloté par l’exploitation pour la levée.

Truck Plan calcule l’itinéraire et les arrêts à partir du véhicule et des contraintes de chargement. La projection Fleet élimine les coûts. Le guidage GPS externe vise une coordonnée. Fuel gère réservation, période, distribution et péremption via les opérations exploitation et station. Fleet accède à la présentation de l’autorisation seulement.
