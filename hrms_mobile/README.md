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

Se connecter à `/hrms`. **Ma mission** affiche la mission active ou la prochaine affectation disponible. **Mes missions** donne accès aux autres affectations et à l’historique. **Mon espace RH** ouvre l’accueil RH habituel. Le bouton principal de la mission indique la prochaine action terrain.

Pour installer la PWA, ouvrir HRMS dans Chrome sur Android et choisir **Installer l’application** si l’option est disponible. Sur iOS, ouvrir HRMS dans Safari puis choisir **Sur l’écran d’accueil** dans le menu de partage. Ouvrir une première fois **Mes missions** avec une connexion pour préparer la lecture hors ligne.

Suivre le bouton principal pour faire l’état des lieux, confirmer le chargement, le départ, l’arrivée et le déchargement. Dans la checklist, choisir explicitement le résultat de chaque contrôle, relever le compteur et joindre les photos demandées. Une anomalie demande un type, une gravité et une observation.

Dans **Marchandises et livraisons**, choisir la lettre de voiture si plusieurs livraisons restent ouvertes. **Livraison complète** reprend la quantité attendue. **Livraison partielle** calcule le manquant à partir de la quantité réelle. Renseigner le réceptionnaire et ajouter les preuves disponibles. Une preuve partielle reste enregistrée. Les contrôles existants demandent à l’exploitation de traiter l’écart avant le passage à **Livré**.

Le bouton **Je termine ma mission** enregistre la fin terrain après les contrôles de livraison et de retour. Le règlement et la clôture relèvent de l’exploitation. Pour un incident, sélectionner la catégorie, indiquer si le véhicule doit être immobilisé et ajouter une observation ou une photo. Un véhicule immobilisé reste sous le contrôle de l’exploitation.

## Hors ligne

L’API de synchronisation renvoie une projection de lecture qui exclut les coûts, les codes de retrait et les pièces jointes. À la première synchronisation, Goods Transport enregistre le worker issu du build HRMS avec la portée `/hrms`. Le worker précache les ressources publiques et retourne le HTML public du build avec une initialisation neutre quand la navigation réseau échoue. Les API métier et le HTML authentifié restent hors du précache.

Les missions synchronisées restent en mémoire pour le compte déverrouillé pendant au plus 12 heures. Le changement d’identité, la déconnexion HRMS, l’expiration ou le refus serveur lors d’une actualisation invalident la copie. Afficher la date de synchronisation et actualiser quand la connexion revient. Les inspections, preuves de livraison et incidents peuvent être préparés avec leurs photos. Un événement terrain proposé par la copie locale peut aussi être enregistré en brouillon.

Appuyer sur **Valider** pour enregistrer et transmettre l’opération dans le même parcours. Les opérations **En attente de synchronisation** sont conservées sur le téléphone et reprises automatiquement au retour du réseau. Une réponse métier refusée donne **En erreur**. Le chauffeur peut consulter l’erreur, la corriger ou retirer l’opération explicitement. Une erreur bloque les envois suivants de la même mission jusqu’à son traitement. Le serveur vérifie le compte, le véhicule, l’affectation et l’étape. **Validé** confirme que le serveur a accepté l’opération.

Les opérations en attente et leurs photos restent accessibles au même chauffeur après une nouvelle connexion en ligne. Les autres comptes utilisent leur propre liste. Une opération validée libère immédiatement ses photos et son formulaire. Le reçu local expire après sept jours. Les opérations en attente ou refusées restent conservées jusqu’à leur traitement ou à leur retrait explicite. Pour un incident immobilisant dont la réception reste en attente, contacter directement l’exploitation si nécessaire.

La révocation distante ne peut être connue du téléphone tant qu’il est hors ligne. Le stockage local dépend des règles d’éviction du navigateur. La feuille de route est consultable sous forme de données et de liens GPS. Le PDF chauffeur et les péages sont décrits ci-dessous. Les autres pièces jointes doivent être explicitement autorisées. Les incidents non immobilisants sont enregistrés dans le fil de la mission avec le chauffeur, le véhicule, l’horodatage Frappe et jusqu’à quatre photos privées.

### Onglets et reprise des envois

Les corrections, mises en attente, suppressions et réponses de synchronisation
vérifient la révision et l’état dans la transaction IndexedDB qui écrit.
Chaque envoi réserve l’opération. Web Locks sérialise la synchronisation
lorsqu’il est disponible. Une réservation atomique IndexedDB protège aussi les
navigateurs sans Web Locks et expire après 90 secondes si un onglet disparaît.
Le serveur conserve son contrôle d’idempotence pour les requêtes dont la réponse
a été perdue. Les autres onglets reçoivent un signal de changement sans données
métier et relisent leur liste.

### Confidentialité locale sur téléphone partagé

La clé de compte est délivrée par un POST authentifié à une session HRMS qui
dispose d’une affectation Fleet. La réponse utilise `Cache-Control: private, no-store`.
Le serveur dérive deux clés distinctes à partir d’un secret du site, du site et
du compte. Le navigateur les importe en mémoire via Web Crypto pour AES-GCM et
HMAC. Il conserve uniquement les données chiffrées dans IndexedDB, avec des
index métier opaques. Les métadonnées d’ordonnancement de la file restent
visibles dans IndexedDB, dont le compte, l’identifiant d’opération, l’état
et les dates techniques. Les formulaires, photos, erreurs détaillées,
références de mission et documents sont chiffrés. L’instantané de mission
reste en mémoire. Le code de retrait carburant reste consultable en ligne.

La déconnexion ou la connexion d’un autre utilisateur révoque les références
de clés en mémoire et signale le verrouillage aux autres onglets. Après
fermeture complète, une connexion en ligne est nécessaire pour rouvrir les
données. Tant que la page reste déverrouillée, elle peut travailler hors
ligne. Une connexion du même compte récupère ses opérations non transmises.
Les clés doivent rester stables entre les sessions. Utiliser le secret stable
`goods_transport_fleet_cache_key` s’il est configuré, ou la clé de chiffrement
Frappe du site. Le secret dédié doit être généré aléatoirement avec au moins 256 bits d’entropie. Préserver ce secret lors des sauvegardes et restaurations.
Changer le secret ou le nom du site sans plan de migration rend les opérations
existantes indéchiffrables. Si aucun secret n’est configuré, le déverrouillage
échoue explicitement.

Lors de la mise à niveau, les anciens instantanés de mission et documents
consultables sont supprimés. Une opération historique en clair est migrée
dans une transaction atomique après chiffrement lorsque son propriétaire
se reconnecte. En cas d’échec, elle est conservée. Avant de remettre un
ancien téléphone partagé en circulation, fermer les anciens onglets et
faire reconnecter chaque compte avec des opérations historiques en attente.
Ces anciennes données restent en clair jusqu’à leur migration.

Le chiffrement protège la lecture ordinaire du stockage après verrouillage.
Une session déjà ouverte, un script hostile de la même origine pendant le
déverrouillage ou un profil compromis restent hors de cette garantie.
L’effacement du stockage navigateur peut perdre les opérations jamais
transmises. Une suppression logique ne garantit pas l’effacement physique
des anciennes copies. [Modèle de sécurité Web Crypto](https://www.w3.org/TR/webcrypto/#security-considerations)

## Recette

```sh
bench --site inspection-qa.localhost run-tests --module goods_transport.goods_transport.tests.test_fleet_driver_site
node --test apps/goods_transport/tests/fleet_driver_v2.test.mjs
node apps/goods_transport/tests/e2e/fleet_outbox_tabs.mjs
FLEET_QA_SITE=inspection-qa.localhost FLEET_QA_PASSWORD=local-test \
  env/bin/python apps/goods_transport/tests/e2e/seed_fleet_driver_v2.py > /tmp/fleet-fixture.json
FLEET_QA_URL=http://127.0.0.1:8000 FLEET_QA_FIXTURE=/tmp/fleet-fixture.json \
  FLEET_QA_PASSWORD=local-test FLEET_CAPTURE_DIR=/tmp/fleet-captures \
  node apps/goods_transport/tests/e2e/fleet_driver_v2.mjs
```

Le test serveur utilise des comptes Frappe sur un site isolé. Le parcours Playwright V2 utilise le build HRMS, des comptes Frappe réels et des données fictives sur un site jetable. Une recette HTTP authentifiée sur l’image candidate et le contrôle des cinq autres sites restent nécessaires pour valider le déploiement partagé.

## Documents de route et péages

Dans le détail d’une mission, sélectionner la langue puis **Synchroniser le PDF**. Le PDF chauffeur réutilise le moteur de rendu de la feuille de route Goods Transport avec une projection distincte des données autorisées. Les deux langues sont stockées séparément dans IndexedDB dans la limite de 5 Mio par fichier. Le cache PDF et péages est chiffré et suit le compte, la révision de la mission et l’expiration du lot. La déconnexion verrouille le cache.

Les péages proviennent du calcul existant de correspondance avec la géométrie poids lourds. Le document et l’API ne chargent aucun tarif. Un plan confirmé utilise ses points enregistrés. Si le graphe a changé ou si les coordonnées sont absentes, l’interface indique que le plan est indisponible.

Les pièces jointes génériques restent dans le Desk. Consulter les règles d’autorisation ci-dessous.

### Photos et pièces jointes privées

Les photos JPEG, PNG et WebP sont prévisualisées avec la taille à envoyer avant acceptation. Le téléphone applique l’orientation décodée, puis conserve l’original si l’optimisation échoue ou augmente la taille. Les valeurs par défaut sont 2 000 pixels sur le grand côté et une qualité JPEG de 0,88. Configurer le site avec `goods_transport_fleet_photos`, par exemple `{"long_edge": 2000, "jpeg_quality": 0.88}`. Le serveur garde sa validation et sa limite de 12 Mio. Les aperçus du formulaire restent en mémoire. Une opération en attente garde les fichiers acceptés dans IndexedDB jusqu’à sa validation ou sa purge.

Pour autoriser un PDF opérationnel de transport, un administrateur ajoute le nom du document Frappe **File** à `goods_transport_fleet_documents`, par exemple `{"nom-du-file": "transport"}`. Les seules catégories acceptées sont `transport` et `mission`. Cette classification doit être réservée aux pièces opérationnelles. Chaque fichier doit être un PDF privé d’au plus 5 Mio, stocké localement et attaché directement à la mission concernée. L’API vérifie l’affectation, l’autorisation explicite du fichier, son rattachement et sa version à chaque téléchargement. Elle ne délivre pas de lien direct. Les PDF hors ligne suivent la limite de 12 heures du lot et la liste en ligne écarte les versions qui ont changé ou ont été retirées.
