# ClassLive

Plateforme de **sondage et d'exercices en direct** pour la classe, proche de Wooclap : un formateur anime un **Live** avec un code à six chiffres, les étudiants répondent en temps réel via WebSocket, et le formateur affiche le corrigé à la demande. **Aucune notation** n'est calculée : seules les réponses brutes sont conservées et exportables.

Le dépôt est organisé en deux parties :

- [`backend/`](backend/) — API REST + WebSockets (FastAPI, Python ≥ 3.11), stockage Markdown et SQLite. **C'est le cœur du produit, actuellement complet et validé.**
- [`frontend/`](frontend/) — interface web (Vite/React/TypeScript/Tailwind), servie par le backend sur `/app` en production.

## Fonctionnalités

- **Groupes / événements / slides** : 11 types de slides (contenu, QCM, sondage, association, ordre, catégories, texte à trous, texte libre, nuage de mots, échelle 1-5, pin sur image), médias, versions de slides, duplication, export/import ZIP.
- **Live formateur + mode autonome** : compte à rebours par question, verrouillage des réponses, corrections à la demande, planification, mode anonyme, Q&A, réactions emoji, annonces.
- **Étudiant** : auto-inscription avec nom + prénom et code à six chiffres, reconnexion par jeton secret, réponses en temps réel.
- **Exports CSV** (réponses, présence, questions, réactions) et **backup ZIP** du workspace.
- **Exploitation** : multi-comptes formateurs, journal d'audit, droit à l'oubli (RGPD), rétention/purge, rate limiting, anti zip-bomb, SQL paramétré.
- **Qualité** : 424 tests à **100 % de couverture**, CI GitHub Actions, suite complète (curl + 30 étudiants en WebSockets réels + soak + charge 100 étudiants).

## Démarrage rapide

```bash
export CLASSLIVE_TRAINER_PASSWORD='mon-mot-de-passe-local-fort'
./start.sh
```

Ce script **build le frontend** (`frontend/dist/`), configure `frontend_dir` dans `backend/config.yml`, puis lance le **backend** FastAPI sur `0.0.0.0:8080` qui sert l'application sur `/app`. Un seul port. Ctrl+C pour arrêter.

### Accès depuis le réseau LAN

Au démarrage, `start.sh` affiche l'IP LAN détectée, par exemple :

```
═══════════════════════════════════════════
  ClassLive — http://192.168.10.26:8080/app/
  Formateur : http://192.168.10.26:8080/app/
  Élèves    : http://192.168.10.26:8080/app/join?code=XXXXXX
  API/Swagger : http://192.168.10.26:8080/docs
═══════════════════════════════════════════
```

- **Formateur** : ouvrir `http://<IP_LAN>:8080/app/` → le QR code affiché dans le pilotage pointe automatiquement sur l'IP réseau.
- **Élèves** : scanner le QR code ou ouvrir `http://<IP_LAN>:8080/app/join?code=XXXXXX` sur leur téléphone.
- **Pare-feu** : un seul port à ouvrir sur le LAN, le **8080**.

Lancement manuel (sans start.sh) :

```bash
cd frontend && npm install && npm run build
cd ../backend
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
cp config.local.example.yml config.yml
# éditer config.yml : frontend_dir: "<racine>/frontend/dist"
export CLASSLIVE_TRAINER_PASSWORD='mon-mot-de-passe-local-fort'
python -m classlive
```

Le service écoute alors sur `http://0.0.0.0:8080` :

- `GET /health` — état du service
- `GET /docs` — documentation OpenAPI / Swagger
- `POST /api/v1/auth/login` — connexion formateur

## Installation serveur (Debian 13)

```bash
cd backend
sudo bash deploy/install-debian13.sh
sudo systemctl status classlive
```

Le script installe le service systemd `classlive`, génère le mot de passe formateur dans `/etc/classlive/classlive.env` et configure le workspace (`~/classlive_workspace`). La configuration YAML se trouve dans `/etc/classlive/config.yml` et n'est pas écrasée lors des mises à jour.

## Tests

Depuis `backend/`, sans sudo :

```bash
bash tests/run_suite_complete.sh
```

Lance les tests pytest, le parcours curl sur serveur éphémère, puis 30 étudiants simultanés sur de véritables WebSockets. Pour seulement les tests Python : `pytest -q`.

## Documentation

- [`backend/README.md`](backend/README.md) — documentation complète : installation, API formateur et étudiant, WebSockets, configuration, historique des versions.
- [`backend/classlive/GUIDE_CLASSLIVE.md`](backend/classlive/GUIDE_CLASSLIVE.md) — guide utilisateur, copié dans le workspace au premier démarrage et servi par `GET /api/v1/help`.
- [`backend/config.example.yml`](backend/config.example.yml) — toutes les options de configuration commentées.

## Sécurité

HTTP et WebSocket ne chiffrent ni les mots de passe ni les jetons : **réserver le service au LAN de confiance** (pare-feu/VLAN) et ne pas l'exposer sur Internet. Les noms, prénoms et réponses sont des données personnelles : informer les étudiants, protéger les sauvegardes et définir une politique de conservation.

## Licence

Projet interne. Voir les fichiers du dépôt pour plus de détails.
