# ClassLive v0.9.0 — Matrice de couverture des tests

## Objectif et périmètre

Les **68 opérations HTTP documentées par OpenAPI** et les **2 routes WebSocket** sont inventoriées. La suite couvre leur parcours nominal, les contrôles d'accès et les cas d'erreur pertinents, ainsi que le démarrage d'un **vrai serveur temporaire** sous le moteur Uvicorn.

Le test d'inventaire `test_inventaire_openapi_et_websockets` échoue si une route apparaît/disparaît sans être ajoutée à la matrice des tests. Le test `test_toutes_routes_formateur_refusent_absence_jeton_et_jeton_etudiant` essaie systématiquement chaque route protégée en étant anonyme et étudiant. La suite n'utilise **ni le port 8080, ni `/etc/classlive`, ni le workspace réel**.

## Exécution (sur Debian 13, depuis les sources extraites)

```bash
bash tests/run_suite_complete.sh
```

Le script crée un venv dédié `.venv-tests`, installe les dépendances de test, puis exécute successivement :

1. Vérification des scripts d'installation, compilation Python et manifest de routes.
2. `pytest` (seuil de couverture **100 %** via `--cov-fail-under=100`) : tests des routes, stockages, sécurité, formes de données, réponses, erreurs, **cas limites** (`test_edge_cases.py`) et **branches d'erreur ciblées** (`test_couverture_100.py` : OSError disque, symlinks, races, WS fermés, directions invalides).
3. Parcours Bash/curl **intégral**, exécuté contre un serveur *éphémère* ; il crée et supprime uniquement ses propres données temporaires.
4. Tests d'un **vrai serveur** Uvicorn avec **30 étudiants simultanés** (ou `CLASSLIVE_TEST_STUDENTS=N`), WebSockets réels, réponses concurrentes, déconnexions partielles, synchronisation, lecture/masquage des corrigés, export CSV et redémarrage pendant le Live.
5. **Soak test** court (20 s par défaut, `CLASSLIVE_SOAK_DUREE`/`CLASSLIVE_SOAK_STUDENTS`) : ping/pong continu, navigations périodiques, vérification d'absence de déconnexion.
6. Vérification de la présence de la documentation et des fichiers.

Les résultats sont journalisés dans `tests/rapports/derniere_execution.log` (répertoire ignoré par Git). Toute erreur retourne un code non nul. Pour réutiliser un environnement Python de test existant :

```bash
CLASSLIVE_TEST_PYTHON=python3 bash tests/run_suite_complete.sh
```

Ce mode exige `pytest`, `httpx`, FastAPI, PyYAML, Uvicorn et `websockets` déjà installés dans l'interpréteur donné.

## Couverture fonctionnelle, contrôles et sources

| Bloc | Vérifications automatiques | Tests |
|---|---|---|
| HTTP système / aide | `/health`, OpenAPI, lecture et actualisation du Markdown workspace | `test_api.py`, `test_correction_help.py`, `test_contrat_exhaustif.py`, `test_classlive_curl.sh` |
| Authentification | mot de passe correct/incorrect, absence de mot de passe, `X-API-Key`, jeton étudiant interdit sur toutes les routes formateur, jeton formateur interdit sur les routes étudiant | `test_contrat_exhaustif.py`, `test_live.py`, `test_classlive_curl.sh` |
| Groupes | CRUD, normalisation, apostrophes/accents/espaces, numérotation globale, conflits, réutilisation des numéros, redémarrage, suppression récursive | `test_api.py`, `test_mutations.py`, `test_numbers.py`, `test_classlive_curl.sh` |
| Événements | CRUD, unicité `Exxx` par groupe, arborescence, renommages, protection contre suppression des archives, redémarrage | `test_api.py`, `test_mutations.py`, `test_numbers.py`, `test_classlive_curl.sh` |
| Slides | six types `C/A/O/R/Q/T`, `Sxxx`, unicité par événement, création idempotente, lecture/édition/renommage/suppression, numéros sautés, liens symboliques, noms interdits | `test_slides.py`, `test_navigation.py`, `test_classlive_curl.sh` |
| Lecteur indépendant | sélectionner, suivant/précédent, limites, fermer, 404 après fermeture | `test_navigation.py`, `test_classlive_curl.sh` |
| Live | start/stop/status, second Live refusé, navigation, goto, limites, snapshot immuable, archive, réutilisation | `test_live.py`, `test_correction_help.py`, `test_classlive_curl.sh`, `test_reseau_multiclients.py` |
| Étudiants | join avec code et identité, erreurs, deux homonymes distincts, reconnexion par jeton, cloisonnement entre Live, révocation après stop | `test_live.py`, `test_contrat_exhaustif.py`, `test_reseau_multiclients.py` |
| Exercices | réponses des cinq types, JSON structuré, limite 64 Kio, historique des modifications, dernière réponse affichée, aucune note/point | `test_contrat_exhaustif.py`, `test_live.py`, `test_classlive_curl.sh` |
| Corrigés | format Markdown YAML, absence de fuite, show/hide exclusivement formateur, 409 si aucun corrigé, désactivation des réponses, erreurs YAML = 422 | `test_correction_help.py`, `test_contrat_exhaustif.py`, `test_classlive_curl.sh`, `test_reseau_multiclients.py` |
| Résultats et CSV | identité et participation, export session/événement, BOM UTF-8, séparateur `;`, données JSON, sans points, archive et suppression | `test_correction_help.py`, `test_live.py`, `test_contrat_exhaustif.py`, `test_classlive_curl.sh`, `test_reseau_multiclients.py` |
| Stats agrégées | `GET /live/{id}/stats` : décompte par option pour QCM, total seul pour les autres types, aucune identité, 401 sans jeton, 404 Live inconnu ; `?all=1` pour toutes les slides | `test_edge_cases.py`, `test_front_ready.py` |
| Préparation front | CORS (origines libres/restreintes), `/live/active`, kick (404, CASCADE, fermeture WS au ping, notif moniteur), duplicate (conflits de nom, symlink rejeté, OSError), liste globale `/events`, change-password (401/422/503/429, invalidation tokens), `student-results` (homonymes, multi-sessions, strip) | `test_front_ready.py` |
| Scénarios extrêmes | CSV échappement (`;`, `"`, emoji, BOM), stats options exotiques, limites de champs (120/150/100), emoji rejeté, join live terminé 404, stop idempotent, goto 0, réponse vide, frontmatter limite/null, double WS même token, WS sans ping, nav après rename/suppression, login username vide, change-password 8 car | `test_scenarios_extremes.py` |
| Mode autonome | start étendu (mode/timing/correction validés), règle next (bloqué exercice non répondu), verrouillage réponse (409 resoumission), previous libre, fin auto (dernière slide/deadline/stop), timers par question (expiration → lock), corrections jamais/après_question/à_la_fin, récap `student/results`, positions indépendantes par élève, archivage identique au live, WS `slide_changed`/`session_ended`/`student_finished` perso | `test_autonome.py` |
| Profondeur | concurrence (submit/start/stop simultanés), WS autonome (slide_changed/answer_locked/session_ended/student_finished), faille WS moniteur après change-password (corrigée : fermeture 1008), restart en autonome (progress/locks/timers persistés), présence 45 s, timer non redémarré, deadline pendant next, results jamais/timeout, mix live+autonome dans student-results, token >512, 500 slides, 2 sessions autonomes simultanées | `test_profondeur.py` |
| WebSocket étudiant et moniteur | ouverture, rejet jetons invalides 1008, présence, ping/pong, diffusion des slides et corrections, suivi des réponses, déconnexion | `test_contrat_exhaustif.py`, `test_live.py`, `ws_live_smoke.py`, `test_reseau_multiclients.py` |
| Concurrence et redémarrage | **30 étudiants en parallèle** : inscriptions, connexions, réponses, absence de mélange, déconnexions partielles, reprise après arrêt du processus avec SQLite persistant | `test_reseau_multiclients.py` |
| Charge | **100 étudiants** (`test_charge_100.py`) : mêmes vérifications qu'à 30 | `test_charge_100.py` |
| Stabilité (soak) | ping/pong continu + navigations périodiques, aucune déconnexion | `test_soak.py` |
| Rate limiting | 5 tentatives max/60 s sur `/auth/login` → 429, reset après fenêtre | `test_edge_cases.py` |
| Santé enrichie | `/health` vérifie aussi l'accès SQLite (`database: true/false`) | `test_edge_cases.py` |
| Cas limites | config YAML invalide (tous champs, y compris `session.*`, `audit.*`, `export.*`, `security.trainer_accounts`), contenu > 2 Mo, réponse > 64 Ko, limite 10 000 sessions player, expiration jeton 8 h, compteurs corrompus, caractères de contrôle nom/prénom | `test_edge_cases.py` |
| Fonctionnalités v0.8.5–v0.9.0 | multi-comptes formateurs (login/401/503, audit login_failed), audit (DB + fichier JSON-lines, désactivé, fichier illisible, limites), droit à l'oubli RGPD (cascade, 422, 404, jeton révoqué), export/import ZIP (aller-retour, idempotence, 422/413/404, manifest invalide, ZIP corrompu), duplicate groupe (suffixes, 100 conflits, OSError), versions de slides (cycle, plafond 50, restore, 404), max_students (409, 0=illimité), rétention (purge manuel/startup/désactivé), stats d'usage, Q&A (cycle, limites 1000/50/2000 caractères, 404/409/401), réactions emoji (compteurs, 422, 401), compteur `online` (WS + repli last_seen) | `test_features.py` |
| Installation | validité Bash, composants attendus, santé du vrai serveur isolé | `run_suite_complete.sh`, `test_reseau_multiclients.py` |

## Routes couvertes (OpenAPI)

- Authentification et étudiants : `POST /auth/login`, `POST /student/join`, `POST /student/resume`, `GET /student/current`, `POST /student/answers`.
- Formateur Live : `POST /live/start`, `POST /live/{id}/next`, `previous`, `goto`, `correction/show`, `correction/hide`, `stop` ; `GET /live/active`, `GET /live/{id}/status`, `students`, `results`, `stats` (`?all=1`), `export.csv` ; `DELETE /live/{id}`, `DELETE /live/{id}/students/{pid}`.
- Événements : `GET /events` (liste globale), `POST /groups/{g}/events/{e}/duplicate`, `GET /groups/{g}/events/{e}/student-results?nom=&prenom=` (réponses d'un élève sur toutes les sessions).
- Auth : `POST /auth/change-password` (rate limité, invalide les jetons).
- CORS : origines via `security.cors_origins`.
- Sessions d'événement : `GET /groups/{group}/events/{event}/sessions`, `export.csv` ; `DELETE /groups/{group}/events/{event}/sessions`.
- Groupes et événements : `GET/POST /groups`, `POST /events`, `PATCH/DELETE /groups/{group}`, `GET /groups/{group}/events`, `PATCH/DELETE /groups/{group}/events/{title}`.
- Slides : `GET/POST /groups/{group}/events/{event}/slides`, `GET/PATCH/DELETE /groups/{group}/events/{event}/slides/{slide}`, `PUT /groups/{group}/events/{event}/slides/{slide}/content`.
- Lecteur : `POST /player/select`, `POST /player/{session_id}/next`, `previous`, `GET /player/{session_id}`, `DELETE /player/{session_id}`.
- Système : `GET /health`, `GET /api/v1/help`.
- WebSocket : `/api/v1/student/ws`, `/api/v1/live/{live_id}/monitor`.

*Sauf `/health` et `/api/v1/help`, les routes ci-dessus utilisent le préfixe `/api/v1`.* Les alias `/api/...` des routes historiques sont aussi validés sur plusieurs scénarios.

## Limites assumées

Les tests sont conçus pour couvrir **toutes les fonctionnalités exposées**, pas toutes les valeurs possibles de chaque paramètre. Ils ne constituent pas une preuve formelle d'absence de bug. Ils ne réalisent pas une installation APT/systemd complète sur un Debian 13 vierge (votre installation l'a déjà validée), ni une charge durable sur plusieurs heures, ni une coupure physique d'un routeur, ni un audit de sécurité externe. L'application est destinée au LAN HTTP sans chiffrement.

**Si un test échoue, considérer la version non validée** et transmettre `tests/rapports/derniere_execution.log` pour diagnostic.
