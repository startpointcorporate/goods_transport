# Fleet Driver dans le build Frappe HR

Sur une copie de build jetable de HRMS 16.53.2, avant le build du frontend, exécuter

```sh
python3 apps/goods_transport/hrms_mobile/integrate.py apps/hrms
```

L'intégration ajoute la route `/hrms/fleet` et une entrée sur l'accueil RH. Le script vérifie les points d'ancrage et peut être relancé sur la même copie. Le site appelle les méthodes Goods Transport sur la même origine avec sa session Frappe.

## Périmètre de cette tranche

Le rôle Fleet Driver est créé à l'installation et par une migration. Le rôle donne accès à la projection mobile si l'utilisateur correspond à un Employee actif et à un Driver actif uniques. Les missions validées doivent être affectées à ce Driver dans la société de l'Employee. Les User Permissions de société applicables à Transport Trip sont prises en compte. L'attribution du rôle se fait individuellement après vérification des liens.

| Surface | Droits ajoutés par le rôle |
| --- | --- |
| Accueil RH | Affichage du lien selon l'identité reconnue |
| Missions | Liste et détail dans la projection mobile |
| Carburant | Consultation de l'autorisation sans code, réserve ni montant |
| DocTypes Transport, carburant et finance | Aucun DocPerm ajouté |
| Opérations de mission | Aucune mutation ajoutée par cette tranche |

Frappe cumule les rôles. Éviter d'attribuer un rôle d'exploitation à un compte qui doit avoir un périmètre chauffeur uniquement.

L'écran affiche les lieux enregistrés, le camion, les arrêts carburant confirmés et les autorisations. Le document PDF, les péages, les opérations en ligne et le démarrage hors ligne restent à intégrer. Le script de build n'est pas raccordé à l'image partagée.
