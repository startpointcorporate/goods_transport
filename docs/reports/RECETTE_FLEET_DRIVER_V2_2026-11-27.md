# Recette Fleet Driver V2 — 27 novembre 2026

La recette utilise le site Frappe isolé `journey-test.localhost` avec Goods
Transport, le bundle HRMS 16.53.2 (`ba5371c`) et le thème Solvronix. Les comptes
Fleet Driver et Employee sont des comptes Frappe réels alimentés par des
données fictives. Le bench local utilise l’image de base ERPNext 16.53.0.

| Scénario | Résultat observé |
| --- | --- |
| Connexion chauffeur | Redirection vers Ma mission. Test JS de priorité à une mission active et du tri de la prochaine affectation. |
| Inspection départ | Les choix sont vides à l’ouverture. Une photo obligatoire et le compteur sont envoyés. |
| Chargement et départ | Actions contextualisées jusqu’à En transit. Une action hors séquence est rejetée en HTTP 417. |
| Feuille de route | PDF généré et prévisualisable. Les fixtures Playwright couvrent les péages et le PDF privé hors ligne. |
| Autorisation carburant | Code actif lu en ligne, volume autorisé conservé dans la projection et absence du code dans l’instantané local. |
| Incident informatif | Incident de pneumatique préparé hors ligne, mis en attente puis accepté au retour réseau. |
| Incident immobilisant | Panne mécanique confirmée avec création d’une immobilisation via le service Fleet. |
| Livraison complète | Quantité attendue reprise. La preuve soumise rend possible le passage à Livré. |
| Livraison partielle | Quantité réelle 8, manquant 2. La preuve est soumise. Le serveur rejette le passage à Livré jusqu’au traitement de l’écart par l’exploitation. |
| Inspection retour et fin terrain | Compteur supérieur à celui du départ, photo obligatoire et enregistrement de la fin terrain. |
| Événements et rejeu | Test HTTP du rejeu de l’inspection avec photo, d’un événement et d’une preuve. Rejet d’une seconde preuve soumise sous un autre identifiant. |
| Coupure réseau | Android 390 px avec bascule en cours de session. Brouillon, attente et validation observés sur l’incident. |
| Déconnexion et compte suivant | Déconnexion dans le profil HRMS, instantané purgé et absence de l’opération du premier chauffeur. |
| Séparation des chauffeurs | Requêtes croisées refusées en HTTP 403 dans les deux sens. |
| HRMS standard | Connexion d’un employé sans rôle Fleet et affichage de l’accueil HRMS standard. |

## Vérifications complémentaires

- Python : huit tests du service Fleet et un test d’isolation Frappe avec comptes réels.
- JavaScript : deux tests de sélection de mission et de progression des actions.
- Build Vite : bundle HRMS 16.53.2 avec Solvronix et précache Workbox.
- Infra : suite statique de 32 tests.
- Écrans : Chromium en Android 360 et 390 px, WebKit en émulation iPhone 13 et iPad. Le parcours métier complet a été exécuté sur Android 390 px. Les trois autres formats couvrent la connexion, le rendu de la mission et l’absence de débordement horizontal.

## Captures

[Mission 390 px](assets/fleet-driver-v2/mission-390.png) ·
[Mission 360 px](assets/fleet-driver-v2/mission-android-360.png) ·
[iPhone](assets/fleet-driver-v2/mission-iphone.png) ·
[Tablette](assets/fleet-driver-v2/mission-tablette.png) ·
[Inspection départ](assets/fleet-driver-v2/inspection-départ.png) ·
[Inspection retour](assets/fleet-driver-v2/inspection-retour.png) ·
[Livraison complète](assets/fleet-driver-v2/livraison-complete.png) ·
[Livraison partielle](assets/fleet-driver-v2/livraison-partielle.png) ·
[Incident](assets/fleet-driver-v2/incident.png).

## Validation du déploiement

La recette locale couvre le candidat applicatif. La recette d’acceptation sur
Transport Demo, le contrôle des autres sites avec l’image commune et les essais
sur téléphones physiques restent à exécuter avant promotion. L’image commune
en service n’a pas été modifiée.
