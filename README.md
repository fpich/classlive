# ClassLive

Plateforme de **sondage et d'exercices en direct** pour la classe, proche de Wooclap : un formateur anime un **Live** avec un code à six chiffres, les étudiants répondent en temps réel via WebSocket, et le formateur affiche le corrigé à la demande. **Aucune notation** n'est calculée : seules les réponses brutes sont conservées et exportables.

Le dépôt est organisé en deux parties :

- [`backend/`](backend/) — API REST + WebSockets (FastAPI, Python ≥ 3.11), stockage Markdown et SQLite. **C'est le cœur du produit, actuellement complet et validé.**
- [`frontend/`](frontend/) — interface web (Vite/React), **pas encore implémentée** (dossier vide, prêt à recevoir le build).

## Fonctionnalités

- **Groupes / événements / slides** : 11 types de slides (contenu, QCM, sondage, association, ordre, catégories, texte à trous, texte libre, nuage de mots, échelle 1-5, pin sur image), médias, versions de slides, duplication, export/import ZIP.
- **Live formateur + mode autonome** : compte à rebours par question, verrouillage des réponses, corrections à la demande, planification, mode anonyme, Q&A, réactions emoji, annonces.
- **Étudiant** : auto-inscription avec nom + prénom et code à six chiffres, reconnexion par jeton secret, réponses en temps réel.
- **Exports CSV** (réponses, présence, questions, réactions) et **backup ZIP** du workspace.
- **Exploitation** : multi-comptes formateurs, journal d'audit, droit à l'oubli (RGPD), rétention/purge, rate limiting, anti zip-bomb, SQL paramétré.
- **Qualité** : 424 tests à **100 % de couverture**, CI GitHub Actions, suite complète (curl + 30 étudiants en WebSockets réels + soak + charge 100 étudiants).

## Démarrage rapide (développement)

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
cp config.local.example.yml config.yml
export CLASSLIVE_TRAINER_PASSWORD='mon-mot-de-passe-local-fort'
python -m classlive
```

Le service écoute alors sur `http://localhost:8080` :

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
