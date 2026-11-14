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

Le rapport local est `tests/rapports/derniere_execution.log` ; le détail du périmètre est dans [`tests/MATRICE_COUVERTURE.md`](tests/MATRICE_COUVERTURE.md). Chaque nouvel endpoint doit être ajouté à l'inventaire des 51 opérations OpenAPI dans `tests/test_contrat_exhaustif.py`. Les tests ne garantissent pas l'absence de tout défaut et ne remplacent pas une campagne d'exploitation longue durée.

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
| `POST` | `/live/start` | Démarrer (`{"group","title"}`) ; retourne `live_id`, `session_code`, `join_url`. Options : `mode:"live|autonome"`, `timing` (`live`: `none|par_question` avec `timing_seconds` = compte à rebours par slide ; `autonome`: `none|par_question|par_evenement`), `correction:"jamais|après_question|à_la_fin"` (autonome), `start_at` (ISO futur = planification), `anonymous:true` (résultats sans identités) |
| `GET` | `/live/{live_id}/status` | Slide et état actuel |
| `POST` | `/live/{live_id}/next` | Slide suivante |
| `POST` | `/live/{live_id}/previous` | Slide précédente |
| `POST` | `/live/{live_id}/goto` | Aller à une slide (`{"number":2}`) |
| `POST` | `/live/{live_id}/correction/show` | Afficher le corrigé de l’exercice courant |
| `POST` | `/live/{live_id}/correction/hide` | Masquer le corrigé |
| `POST` | `/live/{live_id}/stop` | Terminer ; résultats conservés |
| `GET` | `/live/{live_id}/students` | Étudiants, `connected`, `disconnected`, activité |
| `GET` | `/live/{live_id}/results` | Réponses brutes enregistrées, sans notation |
| `GET` | `/live/{live_id}/stats` | Agrégats sans identité pour la slide courante (QCM : décompte par option) ; `?all=1` pour toutes les slides |
| `GET` | `/live/active` | Liste des Lives en cours (pour retrouver la session après un refresh) |
| `DELETE` | `/live/{live_id}/students/{participation_id}` | Retirer un participant (ses réponses sont supprimées) |
| `GET` | `/events` | Liste globale de tous les événements de tous les groupes |
| `POST` | `/groups/{group}/events/{event}/duplicate` | Dupliquer un événement avec toutes ses slides (`new_title` optionnel) |
| `POST` | `/groups/{group}/duplicate` | Dupliquer un groupe entier (événements + slides, `new_title` optionnel) |
| `GET` | `/groups/{group}/events/{event}/export.zip` | Exporter l'événement en ZIP (`manifest.json` + slides Markdown) |
| `POST` | `/groups/{group}/import.zip` | Importer un ZIP d'événement (corps brut `application/zip`, taille limitée par `export.max_zip_mb`) |
| `DELETE` | `/groups/{group}/events/{event}/students-data?nom=&prenom=` | Droit à l'oubli (RGPD) : supprime toutes les participations/réponses/questions/réactions de l'élève sur l'événement |
| `GET` | `/groups/{group}/events/{event}/slides/{slide}/versions` | Historique des éditions d'une slide (50 versions max conservées) |
| `GET` | `/groups/{group}/events/{event}/slides/{slide}/versions/{vid}` | Lire le contenu d'une ancienne version |
| `POST` | `/groups/{group}/events/{event}/slides/{slide}/versions/{vid}/restore` | Restaurer une ancienne version (l'état courant est archivé d'abord) |
| `GET` | `/live/{live_id}/questions` | Toutes les questions des élèves du Live |
| `POST` | `/live/{live_id}/questions/{qid}/answer` | Répondre à une question (l'élève est notifié en WebSocket) |
| `POST` | `/live/{live_id}/questions/{qid}/toggle` | Basculer le statut répondu/non répondu |
| `GET` | `/live/{live_id}/reactions` | Compteurs d'emoji du Live |
| `GET` | `/stats/usage` | Statistiques d'usage globales (sessions, participations, questions, réactions, par événement) |
| `POST` | `/admin/purge` | Purge manuelle des sessions terminées selon `session.retention_days` |
| `GET` | `/admin/backup.zip` | Archive ZIP complète du workspace (Evts/, classlive.db, audit.log) |
| `GET` | `/audit?limit=200` | Journal d'audit (max 1000 entrées) |
| `POST` | `/groups/{group}/events/{event}/media?filename=x.png` | Uploader un média (corps brut, limite `media.max_file_mb`, 413) |
| `GET` | `/groups/{group}/events/{event}/media` | Lister les médias de l'événement |
| `DELETE` | `/groups/{group}/events/{event}/media/{filename}` | Supprimer un média |
| `GET` | `/media/{group}/{event}/{filename}` | Télécharger un média (**public**, référencé dans le Markdown des slides) |
| `POST` | `/groups/{group}/events/{event}/slides/{slide}/duplicate` | Dupliquer une slide (`new_title` optionnel, numéro max+1) |
| `GET` | `/groups/{group}/student-results?nom=&prenom=` | Toutes les réponses d'un élève sur **tous les événements** du groupe |
| `POST` | `/live/start` avec `start_at` | Planifier un Live (ISO 8601 futur) : `scheduled` puis activation auto |
| `GET` | `/live/scheduled` | Sessions planifiées (non encore démarrées) |
| `POST` | `/live/{live_id}/announce` | Annonce texte à tous les élèves (persistée + WS `announcement`) |
| `GET` | `/live/{live_id}/presence.csv` | CSV de présence (statut, rejoint_le, dernière activité, réponses) |
| `GET` | `/live/{live_id}/questions.csv` | CSV des questions/réponses du Live |
| `GET` | `/live/{live_id}/reactions.csv` | CSV des compteurs d'emoji |
| `POST` | `/auth/change-password` | Changer le mot de passe formateur en mémoire (effectif jusqu'au redémarrage ; invalide tous les jetons) |
| `GET` | `/live/{live_id}/export.csv` | CSV de la session |
| `GET` | `/groups/{group}/events/{event}/sessions` | Sessions actives et terminées |
| `GET` | `/groups/{group}/events/{event}/export.csv` | CSV cumulé des sessions |
| `GET` | `/groups/{group}/events/{event}/student-results?nom=&prenom=` | Toutes les réponses d'un élève sur toutes les sessions de l'événement |
| `DELETE` | `/live/{live_id}` | Supprimer une session **terminée** et ses participations/réponses |
| `DELETE` | `/groups/{group}/events/{event}/sessions` | Réinitialiser les sessions d'un événement, seulement si aucune n'est active |
| `POST` | `/player/select` | Démarrer une lecture séquentielle indépendante (`{"group","title"}`) |
| `POST` | `/player/{session_id}/next` | Slide suivante du lecteur |
| `POST` | `/player/{session_id}/previous` | Slide précédente du lecteur |
| `GET` | `/player/{session_id}` | Slide courante du lecteur |
| `DELETE` | `/player/{session_id}` | Fermer la session de lecture |

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
| `POST` | `/api/v1/student/answers` | Répondre à la slide **exercice actuellement affichée** (en autonome : verrouille la réponse, une seule fois) |
| `POST` | `/api/v1/student/next` | Avancer (autonome uniquement ; bloqué sur un exercice tant qu'aucune réponse validée) |
| `POST` | `/api/v1/student/previous` | Reculer (toujours autorisé, lecture seule) |
| `GET` | `/api/v1/student/results` | Son propre récapitulatif (autonome, session perso terminée uniquement) |
| `POST` | `/api/v1/student/questions` | Poser une question au formateur (`{"text"}`, 1000 caractères max, 50 max par élève) |
| `GET` | `/api/v1/student/questions` | Ses propres questions et les réponses reçues |
| `POST` | `/api/v1/student/reaction` | Envoyer une réaction emoji (`{"emoji"}`, 8 caractères max), diffusée à tous |

`GET /api/v1/student/current` retourne aussi `online` (nombre d'élèves connectés en WebSocket) et `announcement` (dernière annonce du formateur). `POST /live/start` retourne `join_url` (`/app/join?code=...` si `server.frontend_dir` est configuré, sinon `/join?code=...`).

Exemple de soumission :

```json
{"answer":{"selected":["D","B"]}}
```

Aucune note n’est calculée ; le formateur peut consulter les réponses enregistrées. Après arrêt du Live, son jeton ne donne plus accès aux slides/réponses. Une nouvelle session Live nécessite une nouvelle inscription et un nouvel identifiant étudiant.

## WebSocket

- `ws://SERVEUR:8080/api/v1/student/ws` : l'étudiant se connecte, envoie **en premier message JSON** `{"token":"STUDENT_SESSION_ID"}` (ne pas transmettre le secret dans l'URL), reçoit `{"event":"current","current":{...}}` et ensuite `slide_changed` / `correction_shown` / `correction_hidden` / `live_ended` / `question_answered` / `reaction` / `announcement`. Envoyer `{"event":"ping"}` toutes les 20 secondes ; réponse `pong`. Une connexion silencieuse depuis plus de 45 secondes est comptée déconnectée.
- `ws://SERVEUR:8080/api/v1/live/{live_id}/monitor` : le formateur envoie d'abord `{"token":"JETON_FORMATEUR"}`, reçoit `monitor`, puis `student_joined`, `student_connected`, `student_disconnected`, `answer_received`, `question_asked`, `question_updated`, `slide_changed`, `correction_shown`, `correction_hidden`, `live_ended`, `announcement`.
- Présence en ligne calculée à partir des WebSockets actifs (mémoire du serveur), les participations et leurs dernières activités persistent en SQLite. Après redémarrage du service, les étudiants sont déconnectés jusqu'à reconnexion, sans perte de réponses.

## Export CSV

Uniquement CSV `;` avec encodage UTF-8 BOM pour Excel, colonnes : `live_id;nom;prenom;date_session;slide;reponse_json;date_reponse`. Export de session ou export de toutes les sessions de l'événement. Aucune route d'export JSON n'est prévue (les routes de consultation des résultats retournent naturellement du JSON).

## Sécurité et exploitation

Les noms/prénoms/réponses sont des données personnelles : informer les étudiants, protéger les sauvegardes, limiter l'accès au serveur et définir une politique de conservation. HTTP non chiffré : LAN de confiance exclusivement. Limiter l'accès au port 8080 et ne pas partager les jetons. Le service n'est **pas** prévu pour un déploiement à plusieurs workers ou plusieurs instances ; les sessions et résultats, eux, sont persistants en SQLite.

## Configuration (`config.yml`)

Toutes les fonctionnalités ont des **paramètres par défaut** ; tout ce qui est paramétrable est modifiable dans le fichier YAML (voir `config.example.yml`) :

```yaml
classlive:
  server:
    frontend_dir: null           # build du frontend servi sur /app (relatif au workdir ou absolu)
  security:
    trainer_accounts:            # comptes formateurs additionnels (password min 8 caractères)
      - { username: "prof2", password: "mot-de-passe-min-8-car" }
  session:
    max_students: 300            # 0 = illimité ; join au-delà -> 409 "Session pleine"
    retention_days: 365          # purge auto des sessions terminées (0 = désactivé)
    join_rate_limit: 300         # tentatives de join max/min/IP (0 = désactivé) -> 429
  audit:
    enabled: true                # journal d'audit en SQLite + fichier JSON-lines
    file: null                   # défaut : <workdir>/audit.log
  export:
    max_zip_mb: 50               # taille max d'un export/import ZIP d'événement
  media:
    max_file_mb: 10              # taille max d'un média uploadé par événement
```

## v1.0.0 — Release figée

Version **figée et validée end-to-end** : 80 routes publiques, 11 types de slides, 2 WebSockets, **424 tests à 100 % de couverture**, suite complète (curl + 30 étudiants en WS réels + soak) et charge 100 étudiants toutes vertes. Aucun changement fonctionnel après cette release sans bump de version.

Périmètre livré : groupes/événements/slides (10 types d'exercices + contenu), médias, versions de slides, live formateur + mode autonome (verrouillage, timers par question/événement, corrections), compte à rebours live, Q&A, réactions, annonces, planification, mode anonyme, exports CSV (réponses/présence/questions/réactions) + ZIP événement + backup workspace, RGPD (oubli élève), audit, multi-comptes formateurs, rétention/purge, stats d'usage, frontend statique sur `/app`, durcissement (rate limits, tailles plafonnées, anti zip-bomb, SQL paramétré, symlinks rejetés).

## v0.9.2 — Pin sur image, compte à rebours live, résultats anonymes

- **Type de slide `I` (pin sur image)** : réponse `{"x":0.25,"y":0.5}` (position relative 0–1 sur un média de l'événement, validation 422 hors bornes). Stats : `pins` (liste des points) + `center` (centre de gravité). Verrouillage identique aux autres exercices en autonome.
- **Compte à rebours par slide en mode live** : `POST /live/start` accepte désormais `timing:"par_question"` + `timing_seconds` en mode live. La `deadline` est fixée au start, **renouvelée à chaque navigation**, exposée dans `GET /live/{id}/status` et dans `GET /student/current` (`expires_at`, `time_expired`) ; passé l'expiry, toute soumission → **409 « Temps écoulé »**. Calculée à l'activation si la session est planifiée.
- **Mode anonyme** : `anonymous:true` au start masque nom/prénom dans `GET /live/{id}/results` et l'export CSV (`anonymous:true` exposé, `participation_id` conservé). Le récap perso de l'élève, `student-results` par nom et le droit à l'oubli RGPD continuent de fonctionner sur les identités réelles.
- 11 types de slides, 80 routes, **424 tests, couverture 100 %**.

## v0.9.x — Toutes les fonctionnalités restantes (front-ready complet)

- **10 types de slides** : `C` contenu, `Q` QCM, `P` sondage, `A` association, `O` ordre, `R` catégories, `T` texte à trous, `F` **texte libre** (`{"text":...}`, 5000 car, contenu jamais exposé), `N` **nuage de mots** (`{"words":[...]}`, 5 mots de 30 car), `L` **échelle 1-5** (`{"value":3}`). Stats agrégées : options (Q/P), mots (N), distribution (L), simple compteur (F).
- **Médias par événement** : `POST /groups/{g}/events/{e}/media?filename=schema.png` (corps brut, `media.max_file_mb`, 413 précoce sur `Content-Length`), liste `GET .../media`, `DELETE .../media/{f}`, téléchargement **public** `GET /media/{group}/{event}/{filename}` (référençable dans le Markdown). Copiés avec l'événement dupliqué.
- **Frontend servi par le backend** : `server.frontend_dir` (relatif au workdir ou absolu) → build servi sur `/app` avec fallback SPA sur `index.html`. `POST /live/start` retourne `join_url` (`/app/join?code=...` si frontend configuré).
- **Annonce formateur** : `POST /live/{id}/announce` (`{"text"}`, 500 car max), persistée, incluse dans `status` et `student/current`, diffusée en WS (`announcement`).
- **Planification** : `POST /live/start` avec `start_at` (ISO 8601 futur) → session `scheduled`, `GET /live/scheduled`, join refusé (404) tant que planifiée, activation auto (thread daemon, réarmée au redémarrage), deadline `par_evenement` calculée à l'activation, `stop` annule une planification, `start` en double → 409.
- **Exports CSV** : `GET /live/{id}/presence.csv` (statut en ligne, rejoint_le, dernière activité, nb réponses), `.../questions.csv`, `.../reactions.csv`.
- **Résultats élève cross-événements** : `GET /groups/{group}/student-results?nom=&prenom=` agrège toutes les sessions de tous les événements du groupe.
- **Backup workspace** : `GET /api/v1/admin/backup.zip` (Evts/, classlive.db, audit.log ; restauration = dézipper à la place du workdir service arrêté).
- **Duplication de slide** : `POST /groups/{g}/events/{e}/slides/{slide}/duplicate` (`new_title` optionnel, `_copie` auto-incrémenté).
- 80 routes publiques inventoriées, 418 tests, couverture 100 %.

## v0.9.0 — Release : durcissement et prêt pour le frontend

- **Durcissement import ZIP** : refus 413 précoce sur l'en-tête `Content-Length` (le corps n'est plus lu en mémoire si l'en-tête annonce trop gros), 422 sur en-tête illisible, et **protection anti zip-bomb** (taille décompressée totale plafonnée à `export.max_zip_mb`).
- **Anti brute-force sur le join** : `session.join_rate_limit` (300 tentatives/min/IP par défaut, 0 = désactivé) → 429 au-delà, protégeant le code Live à 6 chiffres.
- **Versions de slides** : un `PUT` au contenu identique n'archive plus de version inutile.
- Audit de sécurité : toutes les requêtes SQL paramétrées (pas d'injection), noms de fichiers validés par expressions régulières strictes (`Gxxx_`, `Exxx_`, `Sxxx_[CAORQT]_*.md`), liens symboliques rejetés, tailles plafonnées (contenu 2 Mo, réponse 64 Ko, question 1000 car, emoji 8 car), rate limiting login/change-password/join, jetons `secrets.token_urlsafe` stockés uniquement en SHA-256, WS authentifiées avec timeout 10 s, erreurs 500 génériques (pas de fuite d'interne).
- **Prêt pour un frontend** : CORS configurable (`security.cors_origins`), OpenAPI complet (68 routes documentées), `/health`, `/live/active` pour retrouver un Live après refresh, flux étudiant autonome (`join` → `current`/`next`/`previous`/`answers`/`results`), WebSockets documentés (`student/ws`, `live/{id}/monitor`) avec événements `slide_changed`, `question_asked`, `question_answered`, `reaction`, `student_joined`, etc.
- Tests : **388 tests, couverture 100 %**, suite complète (curl + réseau réel 30 étudiants + soak) et charge **100 étudiants** toutes vertes.

## v0.8.5 — Exploitation, RGPD et temps réel

- **Multi-comptes formateurs** : `security.trainer_accounts` ajoute des comptes en plus de `CLASSLIVE_TRAINER_PASSWORD`.
- **Journal d'audit** : connexions (succès/échec), démarrages/arrêts de Live, expulsions, droit à l'oubli, imports ZIP, restaurations de slides et purges — en table SQLite (`GET /api/v1/audit`) et en fichier JSON-lines (`audit.file`).
- **Droit à l'oubli (RGPD)** : `DELETE /groups/{g}/events/{e}/students-data?nom=&prenom=` supprime en cascade toutes les participations, réponses, questions et réactions de l'élève sur l'événement.
- **Export/import ZIP** : `GET .../export.zip` / `POST /groups/{group}/import.zip` (corps brut `application/zip`, `manifest.json` + slides `Sxxx_*.md`, contrôle de taille et de nommage strict).
- **Q&A en live** : l'élève pose des questions (`POST /student/questions`), le formateur liste/répond/bascule (`/live/{id}/questions...`) ; notifications WebSocket `question_asked` (moniteur), `question_answered` (élève), `question_updated` (moniteur).
- **Réactions emoji** : `POST /student/reaction`, compteurs `GET /live/{id}/reactions`, diffusion WebSocket `reaction` à tous.
- **Limite d'élèves** : `session.max_students` (409 au-delà), **rétention** : `session.retention_days` avec purge au démarrage et `POST /admin/purge`.
- **Stats d'usage** : `GET /api/v1/stats/usage`.
- **Duplication de groupe** : `POST /groups/{group}/duplicate`.
- **Versions de slides** : chaque `PUT .../content` archive l'ancien contenu (50 versions max par slide), consultables et restaurables (`.../versions`, `.../versions/{vid}`, `.../versions/{vid}/restore`).
- **Compteur en ligne** : `online` dans `GET /student/current` (WebSockets actifs).

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


## Session autonome (self-paced, v0.8.4 révision 4)

Un événement peut être lancé en **mode autonome** : chaque élève avance à son rythme avec le même code à 6 chiffres, ses réponses sont **verrouillées à la première soumission** (revenir en arrière = lecture seule, resoumettre → 409), et `next` est bloqué sur un exercice tant qu'aucune réponse n'est validée (les slides contenu passent librement). La session perso se termine quand toutes les slides sont vues, à la deadline (`timing: "par_evenement"`), à l'expiration d'un timer (`timing: "par_question"`, durée identique pour toutes les questions), ou au `stop` du formateur. L'élève reçoit alors son récap via `GET /api/v1/student/results`. Le corrigé est diffusé selon `correction` : `jamais`, `après_question` (dès la réponse verrouillée), ou `à_la_fin`. Les sessions autonomes sont archivées comme les Live (mêmes `results`, `export.csv`, `student-results`). Aucun score n'est calculé.

## Préparation frontend (v0.8.4 révision 3)

- **CORS** : middleware actif, origines configurables via `classlive.security.cors_origins` (`["*"]` par défaut, LAN uniquement). Un front Vite/React sur un autre port peut appeler l'API directement.
- **`/live/active`** : retrouver le Live en cours après un refresh navigateur.
- **Kick d'un participant** : `DELETE /live/{id}/students/{pid}`, notifié par WebSocket (`student_kicked`), sa connexion WS est fermée au prochain ping.
- **Duplication d'événement** : `POST .../duplicate` copie slides et sous-dossiers vers un nouvel `Exxx` (nom `_copie` auto-incrémenté en cas de conflit).
- **Stats complètes** : `GET /live/{id}/stats?all=1` retourne les agrégats de toutes les slides (récap de fin de session).
- **Liste globale** : `GET /api/v1/events` pour la page d'accueil.
- **Change-password** : `POST /auth/change-password` (mémoire, min 8 caractères, rate limité, invalide les jetons actifs). Au redémarrage, retombe sur `CLASSLIVE_TRAINER_PASSWORD`.

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
