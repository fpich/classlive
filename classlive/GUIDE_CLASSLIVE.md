# Guide ClassLive — API v0.8.4

Par défaut sur Debian 13, le workspace est `~/classlive_workspace` du compte ayant lancé l’installation avec `sudo` (par exemple `/home/fabien/classlive_workspace`). Le chemin absolu est enregistré dans `/etc/classlive/config.yml`.

Ce fichier est copié au premier démarrage dans **`<workdir>/GUIDE_CLASSLIVE.md`**.
Il est disponible par **`GET /api/v1/help`** (réponse `text/markdown`). Toute modification du fichier du workspace est immédiatement visible par cette API. Les mises à jour n'écrasent pas un guide existant.

## 1. Accès

ClassLive fonctionne sur Debian 13, par défaut à `http://IP_DU_SERVEUR:8080`. Réservé au LAN de confiance : HTTP et WebSocket ne chiffrent pas les jetons. Aucun frontend n'est fourni.

- `GET /health` : état du service
- `GET /api/v1/help` : ce guide en Markdown
- `GET /docs` : documentation OpenAPI / Swagger
- `POST /api/v1/auth/login` : `{ "username":"formateur", "password":"..." }`, retourne `access_token`
- Routes formateur : `Authorization: Bearer <access_token>` ; ne pas transmettre ce jeton aux étudiants.

## 2. Organisation des fichiers

```
<workdir>/
├── GUIDE_CLASSLIVE.md
├── classlive.db
└── Evts/
    └── G001_Formation_Python/
        └── E001_Introduction/
            ├── S001_C_Presentation.md
            └── S002_Q_Question.md
```

Les noms sont normalisés : sans accents ni apostrophes, espaces remplacés par `_`. Les numéros de groupe sont uniques globalement, ceux des événements dans leur groupe et ceux des slides dans leur événement.

## 3. Créer une slide exercice avec correction

Fichier `S002_Q_Question.md` :

```markdown
---
classlive_answer:
  selected: [B]
---
# Quelle est la capitale de la France ?

- A : Lyon
- B : Paris
- C : Marseille
```

Le `classlive_answer` du frontmatter YAML n'est jamais inclus dans la question diffusée avant l'autorisation du formateur. Les réponses possibles suivent la convention du type d'exercice : `selected` (Q QCM, P sondage), `pairs` (A), `order` (O), `categories` (R), `blanks` (T texte à trous), `text` (F texte libre), `words` (N nuage de mots, 1 à 5 mots), `value` (L échelle 1 à 5). Aucun point ni score n'est calculé.

## 3bis. Types de slides

| Lettre | Type | Réponse attendue |
|---|---|---|
| `C` | Contenu | aucune (pas un exercice) |
| `Q` | QCM | `{"selected":["B"]}` (avec ou sans corrigé) |
| `P` | Sondage | `{"selected":["A"]}` (jamais de corrigé) |
| `A` | Association | `{"pairs":{...}}` |
| `O` | Ordre | `{"order":["C","A"]}` |
| `R` | Catégories | `{"categories":{...}}` |
| `T` | Texte à trous | `{"blanks":[...]}` |
| `F` | Texte libre | `{"text":"..."}` (5000 car max, contenu jamais exposé dans les stats) |
| `N` | Nuage de mots | `{"words":["mot",...]}` (1 à 5 mots de 30 car max) |
| `L` | Échelle 1-5 | `{"value":3}` |

Les médias (images, PDF) se placent dans le sous-dossier `media/` de l'événement (upload via `POST /api/v1/groups/{g}/events/{e}/media?filename=...`) et sont servis publiquement sur `/media/{g}/{e}/{fichier}` pour être référencés dans le Markdown.

Une slide exercice peut ne pas avoir de `classlive_answer` : les réponses restent enregistrables, mais l'affichage de correction renverra HTTP 409.

## 4. Démarrer et piloter un Live

**Formateur** :

- `POST /api/v1/live/start` avec `{ "group":"G001_Formation_Python", "title":"E001_Introduction" }` : retourne `live_id` et `session_code`.
- `POST /api/v1/live/{live_id}/next` ou `/previous` : changer de slide, masque automatiquement la correction précédente.
- `POST /api/v1/live/{live_id}/goto` avec `{ "number": 2 }` : aller à S002, correction masquée.
- `POST /api/v1/live/{live_id}/correction/show` : afficher le corrigé de l'exercice courant aux étudiants.
- `POST /api/v1/live/{live_id}/correction/hide` : revenir à la question sans correction.
- `GET /api/v1/live/{live_id}/status` : slide actuelle et état de la correction.
- `POST /api/v1/live/{live_id}/stop` : terminer la session.

La correction n'est affichable que si la slide courante est un exercice et possède un corrigé. Quand la correction est visible, les nouvelles réponses sont bloquées (HTTP 409). Un WebSocket étudiant reçoit `correction_shown`, `correction_hidden` ou `slide_changed`.

## 5. Étudiant : inscription et réponses

1. `POST /api/v1/student/join` avec `{ "session_code":"123456", "nom":"Dupont", "prenom":"Marie" }` : reçoit le **`student_session_id` secret**.
2. Le client garde cet identifiant secret et l'envoie dans `Authorization: Bearer <student_session_id>`.
3. `POST /api/v1/student/resume` : reconnexion avec le même identifiant ; pas de nouvelle inscription.
4. `GET /api/v1/student/current` : question seule, ou question plus `correction` si le formateur l'a autorisé.
5. `POST /api/v1/student/answers` avec `{ "answer": { "selected": ["B"] } }` : enregistre la réponse de l'exercice courant (uniquement avant l'affichage du corrigé).
6. `ws://IP_DU_SERVEUR:8080/api/v1/student/ws` : envoi de `{ "token":"<student_session_id>" }` juste après connexion ; `{"event":"ping"}` pour maintien de présence.

Le jeton étudiant est personnel : le protéger même sur le LAN et ne pas le partager.

## 6. Suivi des étudiants et export

- `GET /api/v1/live/{live_id}/students` : nom, prénom, participation, présence et nombre de slides répondues.
- `GET /api/v1/live/{live_id}/results` : réponses brutes par étudiant, **sans points ni notes**.
- `GET /api/v1/live/{live_id}/export.csv` : CSV d'une session, colonnes `live_id;nom;prenom;date_session;slide;reponse_json;date_reponse`.
- `GET /api/v1/groups/{group}/events/{event}/export.csv` : CSV pour toutes les sessions de l'événement.
- `GET /api/v1/groups/{group}/events/{event}/sessions` : sessions archivées et actives.
- `DELETE /api/v1/live/{live_id}` : supprimer une session **terminée**, et ses participations/réponses.
- `DELETE /api/v1/groups/{group}/events/{event}/sessions` : supprimer toutes les sessions **terminées** de l'événement, sans effacer les slides.

## 7. Remarques

Les slides et les corrigés sont figés dans SQLite au lancement d'une session Live. Modifier le Markdown après lancement n'affecte pas cette session. Après un redémarrage serveur, l'état du Live et l'affichage du corrigé restent disponibles ; les connexions WebSocket doivent être rétablies.

Les anciennes sessions et réponses SQLite sont préservées lors de la migration v0.7.0 vers v0.8.0. Les anciennes colonnes de notation sont retirées ; l'export CSV ne contient plus de notes.

Installer avec `sudo bash deploy/install-debian13.sh`, vérifier `sudo systemctl status classlive` et lire les journaux avec `journalctl -u classlive -f`.


## Tests de validation

Après installation, depuis le dossier des sources :

```bash
bash tests/test_classlive_curl.sh
```

Ce script crée des groupes, événements et slides dédiés aux tests, lance une
session Live, inscrit un étudiant, teste la navigation, la correction,
l'enregistrement des réponses, le CSV, puis supprime les données créées en cas
de succès. Les WebSockets sont vérifiés avec `tests/ws_live_smoke.py`.
Une sauvegarde reste recommandée avant les tests sur un environnement utilisé.
