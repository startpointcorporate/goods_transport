# Fleet Driver dans Frappe HR Mobile

Sur une copie de build jetable de HRMS 16.53.2, appliquer l’intégration avant de compiler le frontend.

```sh
python3 apps/goods_transport/hrms_mobile/integrate.py apps/hrms
bench build --app hrms
```

Le script ajoute le lien à l’accueil RH, la route `/hrms/fleet`, la purge à la connexion et à la déconnexion, et le repli de navigation Workbox. Il vérifie les points d’ancrage et peut être relancé sur la même copie. Conserver l’identifiant et le manifeste d’installation de HRMS. Le build HRMS d’origine ne doit pas être utilisé avec les nouveaux écrans.

Le rôle Fleet Driver est créé à l’installation et par migration. Attribuer le rôle aux utilisateurs reliés à un Employee actif et à un Driver actif uniques. Les missions validées doivent être affectées au Driver dans la société de l’Employee. Les User Permissions de société applicables à Transport Trip restent prises en compte. Les rôles d’exploitation donnent des droits supplémentaires et doivent être réservés aux profils qui en ont besoin.

| Surface | Droits Fleet Driver |
| --- | --- |
| Accueil RH | Lien visible pour les comptes disposant d’une identité Fleet |
| Missions | Données opérationnelles des missions affectées |
| Inspection et kilométrage | Ouverture, photos privées et validation selon les règles de départ et de retour existantes |
| POD | Quantités, photo et image de signature. Contrôleur Frappe et lien Bilty vérifié côté serveur |
| Carburant | Consultation. Présentation en ligne des codes actifs. Confirmation du retrait réservée au compte station |
| Incident critique | Déclaration depuis une mission ouverte, avec immobilisation native. Levée réservée à l’exploitation |
| Finance et accès documentaire générique | Aucun DocPerm supplémentaire |

## Guide chauffeur

Se connecter à `/hrms` puis ouvrir **Mes missions** sur l’accueil. Sélectionner une mission pour consulter les lieux, la feuille de route résumée, le camion et les informations de carburant. Le bouton de navigation ouvre l’application compatible avec le téléphone.

Pour installer la PWA, ouvrir HRMS dans Chrome sur Android et choisir **Installer l’application** si l’option est disponible. Sur iOS, ouvrir HRMS dans Safari puis choisir **Sur l’écran d’accueil** dans le menu de partage. Ouvrir une première fois **Mes missions** avec une connexion pour préparer la lecture hors ligne.

En ligne, utiliser **États des lieux** pour saisir les contrôles et le kilométrage réel. L’exploitant conserve les changements de statut de la mission. À l’arrivée, **Preuve de livraison** permet de confirmer les quantités et de joindre des preuves. Utiliser **Signaler une panne critique** pour signaler un événement qui immobilise le véhicule.

## Hors ligne

L’API de synchronisation renvoie une projection de lecture qui exclut les coûts, les codes de retrait et les pièces jointes. À la première synchronisation, Goods Transport enregistre le worker issu du build HRMS avec la portée `/hrms`. Le worker précache les ressources publiques et retourne le HTML public du build avec une initialisation neutre quand la navigation réseau échoue. Les API métier et le HTML authentifié restent hors du précache.

Les missions synchronisées sont conservées dans le stockage local de l’origine pour le compte courant, avec une durée maximale de 12 heures. Le changement d’identité, la déconnexion HRMS, l’expiration ou le refus serveur lors d’une actualisation invalident la copie. Afficher la date de synchronisation et actualiser quand la connexion revient. Les opérations d’écriture ne sont accessibles qu’en ligne.

La révocation distante ne peut être connue du téléphone tant qu’il est hors ligne. Le stockage local dépend des règles d’éviction du navigateur. La feuille de route est consultable sous forme de données et de liens GPS. Le PDF chauffeur et les péages sont décrits ci-dessous. L’accès aux autres pièces jointes reste à intégrer. Les incidents généraux non immobilisants restent à couvrir.

## Recette

```sh
bench --site inspection-qa.localhost run-tests --module goods_transport.goods_transport.tests.test_fleet_driver_site
HRMS_PUBLIC_DIR=apps/hrms/hrms/public node apps/goods_transport/tests/e2e/fleet_mobile_offline.cjs
HRMS_PUBLIC_DIR=apps/hrms/hrms/public node apps/goods_transport/tests/e2e/fleet_mobile_read.cjs
```

Le test serveur utilise des comptes Frappe sur un site isolé. Les scripts Playwright utilisent le build HRMS et des réponses API de test. Les environnements ont des objectifs complémentaires. Une recette HTTP authentifiée sur l’image candidate et le contrôle des cinq autres sites restent nécessaires pour valider le déploiement partagé.

## Documents de route et péages

Dans le détail d’une mission, sélectionner la langue puis **Synchroniser le PDF**. Le PDF chauffeur réutilise le moteur de rendu de la feuille de route Goods Transport avec une projection distincte des données autorisées. Les deux langues sont stockées séparément dans IndexedDB dans la limite de 5 Mio par fichier. Le cache PDF et péages suit l’identité du compte, la révision de la mission et l’expiration du lot correspondant. Il est effacé avec le lot lors d’une déconnexion ou d’un changement d’identité.

Les péages proviennent du calcul existant de correspondance avec la géométrie poids lourds. Le document et l’API ne chargent aucun tarif. Un plan confirmé utilise ses points enregistrés. Si le graphe a changé ou si les coordonnées sont absentes, l’interface indique que le plan est indisponible.

Cette tranche ne publie aucune pièce jointe générique. Il reste à définir quels documents privés d’une mission sont destinés au chauffeur et comment cette autorisation sera renseignée dans Goods Transport.
