# Correctif de la suite de tests — v0.8.4 (révision 1)

Le backend reste en **version 0.8.4**. Ce correctif modifie uniquement
`tests/run_suite_complete.sh` pour prendre en compte les installations Debian
ayant des dossiers `__pycache__` créés précédemment par `root`.

Lors de l'étape [1/5], la compilation Python redirige maintenant tous ses fichiers
`.pyc` vers un répertoire temporaire au lieu de les écrire dans `classlive/` ou
`tests/`. Les autres tests désactivent également l'écriture automatique des
bytecodes et le cache de pytest. Cela évite de modifier les droits du code.

## Lancer les tests

```bash
cd ~/classlive_backend
bash tests/run_suite_complete.sh
```

Cette suite lance ses serveurs sur des ports temporaires et n'accède pas aux
données de production. **Ne pas utiliser sudo** pour la lancer.

## Alternative sans télécharger le correctif

```bash
PYTHONPYCACHEPREFIX="$(mktemp -d)" bash tests/run_suite_complete.sh
```

## Portée de la correction

Aucune modification des API, fichiers Markdown, tables SQLite ou droits d'accès.
La suite doit toujours réussir les cinq étapes pour considérer la validation
terminée. En cas d'échec, consulter `tests/rapports/derniere_execution.log`.
