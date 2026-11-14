# ClassLive Backend v0.8.4 — API seule (Debian 13)

API REST HTTP sur `0.0.0.0:8080`, WebSockets `ws://`, stockage de slides Markdown et historique SQLite, **sans interface frontend**.

## Installation Debian 13

```bash
unzip classlive_backend.zip
cd classlive_backend
sudo bash deploy/install-debian13.sh
sudo systemctl status classlive
```

- Service `classlive`, démarrage automatique avec systemd.
- Configuration YAML : `/etc/classlive/config.yml` (les mises à jour ne l'écrasent pas).
- Identifiants formateur générés au premier déploiement : nom `formateur`, mot de passe aléatoire dans `/etc/classlive/classlive.env` (accessible root et groupe `classlive`). **Ne pas transmettre ce fichier aux étudiants.**
- Lire le mot de passe : `sudo cat /etc/classlive/classlive.env` ; après modification, `sudo systemctl restart classlive`.
- Répertoire de travail par défaut : `~/classlive_workspace` (le `~` de l’utilisateur ayant lancé `sudo`). Exemple : `/home/fabien/classlive_workspace`. Le script écrit le chemin absolu dans `/etc/classlive/config.yml`, autorise le service `classlive` à accéder à ce dossier et crée la base `classlive.db` ainsi que `Evts/`. **Si `/etc/classlive/config.yml` existe déjà, il est conservé sans modification.**
- Swagger API (outil de test uniquement) : `http://IP_DU_SERVEUR:8080/docs`.
- Vérifier : `curl http://localhost:8080/health`.
- Logs : `journalctl -u classlive -f`.
- Important : sauvegarder le répertoire de travail et `classlive.db` avant une mise à jour ; ne pas faire tourner plusieurs processus Uvicorn simultanément (WebSocket et présence en mémoire mono-processus).

### Installation déjà réalisée : déplacer le workspace

La mise à jour conserve `/etc/classlive/config.yml`. Pour migrer le workspace, arrêter le service, copier le contenu, modifier le chemin dans le YAML, puis relancer l'installateur. Il configure désormais **automatiquement** les permissions de l'utilisateur et du service et vérifie une réponse HTTP 200 sur `/health` avant d'annoncer le succès.

```bash
sudo systemctl stop classlive
mkdir -p "$HOME/classlive_workspace"
sudo cp -a /var/lib/classlive/. "$HOME/classlive_workspace/"
sudo nano /etc/classlive/config.yml
# Saisir workdir: "/home/TON_UTILISATEUR/classlive_workspace"
sudo bash deploy/install-debian13.sh
```

Ne supprime pas l'ancien workspace avant validation des données.

### Démarrage sans script (développement)

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
cp config.local.example.yml config.yml
export CLASSLIVE_TRAINER_PASSWORD='mon-mot-de-passe-local-fort'
python -m classlive
```

### Suite de tests complète (isolée, sans risque pour les événements existants)

Depuis le répertoire extrait, **sans sudo** :

```bash
bash tests/run_suite_complete.sh
```

Le script crée si besoin un environnement Python réservé aux tests (`.venv-tests`), lance les **tests pytest**, le **parcours complet curl sur un serveur éphémère**, puis **30 étudiants simultanés** sur de véritables WebSockets avec réponses concurrentes, redémarrage du service isolé pendant un Live, export CSV et réinitialisation. Aucun test de cette commande ne modifie le daemon installé sur `:8080`, le fichier `/etc/classlive/config.yml` ni le workspace de production.

Le rapport local est `tests/rapports/derniere_execution.log` ; le détail du périmètre est dans [`tests/MATRICE_COUVERTURE.md`](tests/MATRICE_COUVERTURE.md). Chaque nouvel endpoint doit être ajouté à l'inventaire des 42 opérations OpenAPI dans `tests/test_contrat_exhaustif.py`. Les tests ne garantissent pas l'absence de tout défaut et ne remplacent pas une campagne d'exploitation longue durée.

Pour exécuter seulement les tests Python : `pytest -q` (avec les dépendances de test).

## Authentification

Le mot de passe formateur vient de la variable d'environnement `CLASSLIVE_TRAINER_PASSWORD`. Sans cette variable, les routes formateur sont bloquées, sauf si `security.api_key` est configuré pour une compatibilité `X-API-Key`.

```bash
curl -X POST http://localhost:8080/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"formateur","password":"VOTRE_MOT_DE_PASSE"}'
```

Réponse : `access_token`. Pour toutes les routes formateur, envoyer `Authorization: Bearer JETON_FORMATEUR`. Jeton valide huit heures, invalidé au redémarrage du daemon. Les étudiants ne peuvent pas se connecter avec le mot de passe formateur.

**LAN seulement** : HTTP et `ws://` ne chiffrent ni les mots de passe ni les jetons. Restreindre le port 8080 au réseau local de confiance (pare-feu/VLAN), et ne pas exposer le service sur Internet.

## Arborescence et noms

```text
~/classlive_workspace/
├── GUIDE_CLASSLIVE.md
├── classlive.db
└── Evts/
    └── G001_Formation_Python/
        └── E001_Introduction/
            ├── S001_C_Bienvenue.md
            ├── S002_Q_Question.md
            └── S003_T_Capitale.md
```

Les numéros `Gxxx` sont uniques globalement ; `Exxx` au sein de leur groupe ; `Sxxx` au sein de leur événement (tous types confondus). Les numéros et noms sont modifiables depuis les routes PATCH ; les espaces deviennent `_`, apostrophes supprimées, accents retirés. Slides : `C` contenu, `A` association, `O` ordonnancement, `R` classification, `Q` QCM, `T` texte à trous. Seul le formateur peut créer, supprimer et renommer les fichiers.

## Corrigés des exercices : affichage contrôlé, sans notation

Les slides exercices **peuvent fournir un corrigé** via un en-tête YAML privé `classlive_answer` ; il est retiré de la slide envoyée aux étudiants et enregistré sous forme de snapshot SQLite au démarrage du Live.

Exemple `S002_Q_Question.md` :

```markdown
---
classlive_answer:
  selected: [B, D]
---
# Question
Sélectionnez B et D.
```

Exemple `S003_T_Capitale.md` :

```markdown
---
classlive_answer:
  blanks: [Paris]
---
# Complétez
La capitale de la France est ____.
```

Pour `A`, `O` et `R` : utiliser aussi un objet YAML sous `classlive_answer` contenant la solution à afficher. **Aucune comparaison automatique et aucun score n'est calculé**. Le formateur décide quand rendre le corrigé visible aux étudiants.

Lorsqu'un Live démarre, le Markdown public, les noms/numéros et les corrigés sont figés dans SQLite pour cette session. Une modification ultérieure du fichier Markdown n'affecte pas ses résultats ni son affichage Live.

## API : parcours formateur

Tous les exemples ci-dessous demandent `Authorization: Bearer JETON_FORMATEUR`.

| Méthode | Route (préfixe `/api/v1`) | Action |
|---|---|---|
| `POST` | `/groups` | Créer un groupe (`{"group":"Formation"}`) |
| `POST` | `/events` | Créer un événement (`{"group":"G001_Formation","title":"Introduction"}`) |
| `GET` | `/groups` | Lister les groupes |
| `GET` | `/groups/{group}/events` | Lister les événements |
| `PATCH` | `/groups/{group}` | Renommer/renuméroter un groupe (`new_name`, `new_number`) |
| `PATCH` | `/groups/{group}/events/{title}` | Renommer/renuméroter l'événement |
| `DELETE` | `/groups/{group}` | Supprimer le groupe et ses fichiers récursivement |
| `DELETE` | `/groups/{group}/events/{title}` | Supprimer l'événement et ses fichiers récursivement |
| `POST` | `/groups/{group}/events/{event}/slides` | Créer une slide (`title`, `slide_type`, `content`, `number` optionnel) |
| `GET` | `/groups/{group}/events/{event}/slides` | Lister les slides |
| `GET` | `/groups/{group}/events/{event}/slides/{slide}` | Lire un Markdown (avec corrigé : formateur uniquement) |
| `PATCH` | `/groups/{group}/events/{event}/slides/{slide}` | Modifier `new_name` / `new_number` / `new_type` |
| `PUT` | `/groups/{group}/events/{event}/slides/{slide}/content` | Remplacer le Markdown |
| `DELETE` | `/groups/{group}/events/{event}/slides/{slide}` | Supprimer une slide |
| `POST` | `/live/start` | Démarrer (`{"group":"G001_Formation","title":"E001_Introduction"}`) ; retourne `live_id`, `session_code` |
| `GET` | `/live/{live_id}/status` | Slide et état actuel |
| `POST` | `/live/{live_id}/next` | Slide suivante |
| `POST` | `/live/{live_id}/previous` | Slide précédente |
| `POST` | `/live/{live_id}/goto` | Aller à une slide (`{"number":2}`) |
| `POST` | `/live/{live_id}/correction/show` | Afficher le corrigé de l’exercice courant |
| `POST` | `/live/{live_id}/correction/hide` | Masquer le corrigé |
| `POST` | `/live/{live_id}/stop` | Terminer ; résultats conservés |
| `GET` | `/live/{live_id}/students` | Étudiants, `connected`, `disconnected`, activité |
| `GET` | `/live/{live_id}/results` | Réponses brutes enregistrées, sans notation |
| `GET` | `/live/{live_id}/stats` | Agrégats sans identité pour la slide courante (QCM : décompte par option) |
| `GET` | `/live/{live_id}/export.csv` | CSV de la session |
| `GET` | `/groups/{group}/events/{event}/sessions` | Sessions actives et terminées |
| `GET` | `/groups/{group}/events/{event}/export.csv` | CSV cumulé des sessions |
| `DELETE` | `/live/{live_id}` | Supprimer une session **terminée** et ses participations/réponses |
| `DELETE` | `/groups/{group}/events/{event}/sessions` | Réinitialiser les sessions d'un événement, seulement si aucune n'est active |

Un seul Live peut être actif par événement. Une session terminée reste archivée dans SQLite. Il faut supprimer les sessions archivées avant de renommer ou supprimer le groupe/l'événement, pour empêcher des résultats orphelins ; **la suppression des sessions ne supprime jamais les slides**. L'API de lecture historique `/player/*` reste accessible **uniquement au formateur**.

## API : parcours étudiant (sans frontend)

L'étudiant s'inscrit **lui-même**, avec nom + prénom obligatoires et code Live à six chiffres.

```http
POST /api/v1/student/join
Content-Type: application/json

{"session_code":"482916","nom":"Dupont","prenom":"Marie"}
```

Réponse : `student_session_id` (jeton secret de reconnexion), `participation_id` (ID public), `live_id`, `current`. Deux participants avec le même nom ont deux participations distinctes. Le jeton secret n'apparaît **jamais** dans la liste formateur. Le client doit le conserver ; il est stocké en base seulement sous forme de SHA-256.

Pour les appels suivants, envoyer `Authorization: Bearer STUDENT_SESSION_ID` :

| Méthode | Route | Fonction |
|---|---|---|
| `POST` | `/api/v1/student/resume` | Retrouver nom, prénom et slide actuelle sans ressaisir |
| `GET` | `/api/v1/student/current` | Voir seulement la slide courante |
| `POST` | `/api/v1/student/answers` | Répondre à la slide **exercice actuellement affichée** |

Exemple de soumission :

```json
{"answer":{"selected":["D","B"]}}
```

Aucune note n’est calculée ; le formateur peut consulter les réponses enregistrées. Après arrêt du Live, son jeton ne donne plus accès aux slides/réponses. Une nouvelle session Live nécessite une nouvelle inscription et un nouvel identifiant étudiant.

## WebSocket

- `ws://SERVEUR:8080/api/v1/student/ws` : l'étudiant se connecte, envoie **en premier message JSON** `{"token":"STUDENT_SESSION_ID"}` (ne pas transmettre le secret dans l'URL), reçoit `{"event":"current","current":{...}}` et ensuite `slide_changed` / `correction_shown` / `correction_hidden` / `live_ended`. Envoyer `{"event":"ping"}` toutes les 20 secondes ; réponse `pong`. Une connexion silencieuse depuis plus de 45 secondes est comptée déconnectée.
- `ws://SERVEUR:8080/api/v1/live/{live_id}/monitor` : le formateur envoie d'abord `{"token":"JETON_FORMATEUR"}`, reçoit `monitor`, puis `student_joined`, `student_connected`, `student_disconnected`, `answer_received`, `slide_changed`, `correction_shown`, `correction_hidden`, `live_ended`.
- Présence en ligne calculée à partir des WebSockets actifs (mémoire du serveur), les participations et leurs dernières activités persistent en SQLite. Après redémarrage du service, les étudiants sont déconnectés jusqu'à reconnexion, sans perte de réponses.

## Export CSV

Uniquement CSV `;` avec encodage UTF-8 BOM pour Excel, colonnes : `live_id;nom;prenom;date_session;slide;reponse_json;date_reponse`. Export de session ou export de toutes les sessions de l'événement. Aucune route d'export JSON n'est prévue (les routes de consultation des résultats retournent naturellement du JSON).

## Sécurité et exploitation

Les noms/prénoms/réponses sont des données personnelles : informer les étudiants, protéger les sauvegardes, limiter l'accès au serveur et définir une politique de conservation. HTTP non chiffré : LAN de confiance exclusivement. Limiter l'accès au port 8080 et ne pas partager les jetons. Le service n'est **pas** prévu pour un déploiement à plusieurs workers ou plusieurs instances ; les sessions et résultats, eux, sont persistants en SQLite.

## v0.8.0 — Correction à la demande, sans notation

- Aucun calcul de point, score ou note : seuls les résultats bruts sont conservés.
- Corrigé privé au format YAML `classlive_answer` dans le Markdown de l'exercice.
- `POST /api/v1/live/{live_id}/correction/show` (formateur) : rend le corrigé visible à tous les étudiants de la session et diffuse `correction_shown` via WebSocket.
- `POST /api/v1/live/{live_id}/correction/hide` (formateur) : masque le corrigé et diffuse `correction_hidden`.
- Les commandes `next`, `previous`, `goto` masquent automatiquement le corrigé.
- La soumission de réponses pendant l'affichage du corrigé est refusée (409).
- Les réponses restent exportables en CSV uniquement, sans colonnes de notation.
- Le guide complet est copié au premier lancement dans `<workdir>/GUIDE_CLASSLIVE.md` et accessible en Markdown via `GET /api/v1/help` ; il n'est pas écrasé lors des mises à jour.
- Migration SQLite automatique des anciennes bases v0.7.0 (sauvegarder `classlive.db` avant mise à jour recommandée).


## Alignement Wooclap et simplifications (v0.8.4 révision 2)

Le cœur du produit reste volontairement proche de Wooclap : **un Live, un code à six chiffres, des slides/exercices, des réponses en temps réel, un corrigé affiché à la demande, aucune notation**. Les ajouts de cette révision renforcent la robustesse sans ajouter de fonctionnalités superflues :

- **Stats agrégées en direct** (`GET /api/v1/live/{live_id}/stats`) : décompte des réponses pour la slide courante, par option pour les QCM, sans aucune identité — comme l'affichage des résultats Wooclap.
- **Redirection `/` → `/docs`** : accès rapide à Swagger depuis un navigateur.
- **Rate limiting** sur `POST /api/v1/auth/login` : 5 tentatives max par minute et par IP, puis HTTP 429.
- **Health check enrichi** : `/health` vérifie aussi l'accès à la base SQLite (`database: true`).
- **Journalisation des requêtes** : chaque requête HTTP est loguée (méthode, chemin, statut, durée).
- **Tests de cas limites** (`tests/test_edge_cases.py`) : validation config, tailles maximales, expiration des jetons, limites internes, compteurs corrompus.
- **Soak test** (`tests/test_soak.py`) : stabilité d'un Live avec ping/pong continu.
- **Test de charge 100 étudiants** (`tests/test_charge_100.py`).
- **CI GitHub Actions** (`.github/workflows/tests.yml`) et **pre-commit** (`.pre-commit-config.yaml`).
- Couverture exigée : **100 %** des lignes (`--cov-fail-under=100`, 1 273 lignes).

## Tests fonctionnels HTTP + WebSocket sur Debian

Le script `tests/test_classlive_curl.sh` teste les routes REST avec `curl` et la
synchronisation WebSocket réelle grâce à `tests/ws_live_smoke.py` (Python et
`websockets`, désormais installé avec le backend).

```bash
cd classlive_backend
bash tests/test_classlive_curl.sh
```

Sur le serveur, le script demande le mot de passe du formateur. Il peut également
être fourni via `CLASSLIVE_PASSWORD`. Pour cibler un autre serveur :
`CLASSLIVE_URL=http://192.168.1.100:8080 bash tests/test_classlive_curl.sh`.

Les fichiers CSV de test sont enregistrés dans le répertoire d'exécution.
Le script génère des groupes de test propres et les supprime à la fin s'il
réussit. **Si le test échoue, des données de test peuvent rester dans le
workspace** : rechercher les groupes `Test_API_*` avant de les supprimer.
Ne pas utiliser ce scénario destructif sur un environnement en production sans
sauvegarde. Les compteurs automatiques sont susceptibles d'avancer.

Les tests de cas limites, de redémarrage et de sécurité approfondie restent
également assurés par la suite de tests Python `pytest -q` ; un scénario
fonctionnel, même étendu, ne démontre pas l'absence de défauts.


## Correctif du lanceur de tests (v0.8.4 révision 1)

Le lanceur `tests/run_suite_complete.sh` redirige la compilation Python vers
un cache temporaire et évite la création de fichiers `.pyc` sous les dossiers
`classlive/` et `tests/` ; voir `CORRECTIF_TESTS_PERMISSIONS.md`.
