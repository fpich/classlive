#!/usr/bin/env bash
# ClassLive: 1 commande, tests pytest + parcours curl + réseau 30 étudiants.
# AVERTISSEMENT: tests 100 % isolés, aucun accès aux données de production.
set -Eeuo pipefail
# Éviter toute écriture de cache bytecode dans les sources (éventuellement root-owned).
export PYTHONDONTWRITEBYTECODE=1
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
OUT="$ROOT/tests/rapports"
mkdir -p "$OUT"
REPORT="$OUT/derniere_execution.log"
exec > >(tee "$REPORT") 2>&1
start="$(date -Is)"
trap 'ret=$?; if [[ $ret != 0 ]]; then echo "[ÉCHEC] Suite interrompue (code $ret). Détails : $REPORT"; fi' EXIT

echo "=== ClassLive : tests de non-régression complets ==="
echo "Début : $start"
echo 'Workspace de production : JAMAIS UTILISÉ'
echo
if [[ -n "${CLASSLIVE_TEST_PYTHON:-}" ]]; then
  PY="$CLASSLIVE_TEST_PYTHON"
else
  PY="$ROOT/.venv-tests/bin/python"
  if [[ ! -x "$PY" ]]; then
    echo '[PRÉPARATION] Création de l’environnement indépendant .venv-tests'
    python3 -m venv "$ROOT/.venv-tests"
  fi
  echo '[PRÉPARATION] Installation des dépendances de test dans .venv-tests'
  "$PY" -m pip install --disable-pip-version-check -q -e '.[test]'
fi
"$PY" -c 'import pytest,fastapi,httpx,websockets'

echo '[1/6] Contrôle syntaxique installateur / scripts'
for script in deploy/install-debian13.sh test_classlive_curl.sh tests/test_classlive_curl.sh tests/run_suite_complete.sh; do
  bash -n "$script"
done
# compileall écrit normalement dans classlive/__pycache__ et tests/__pycache__.
# Sur une installation mise à jour avec sudo, ces caches peuvent appartenir à root.
# Forcer un cache temporaire permet le contrôle syntaxique sans altérer les sources.
SYNTAX_CACHE="$(mktemp -d "${TMPDIR:-/tmp}/classlive-compile.XXXXXXXX")"
if PYTHONPYCACHEPREFIX="$SYNTAX_CACHE" "$PY" -m compileall -q classlive tests; then
  rm -rf -- "$SYNTAX_CACHE"
else
  result=$?
  rm -rf -- "$SYNTAX_CACHE"
  exit "$result"
fi

echo '[2/6] Tests unitaires + API (inclut inventaire des 42 routes HTTP et sécurité)'
"$PY" -m pytest -q -p no:cacheprovider --disable-warnings --cov=classlive --cov-report=term-missing --cov-fail-under=100

echo '[3/6] Scénario curl intégral sur serveur éphémère'
"$PY" tests/test_curl_isole.py

echo '[4/6] Tests WebSocket et concurrence sur serveur éphémère'
"$PY" tests/test_reseau_multiclients.py --students "${CLASSLIVE_TEST_STUDENTS:-30}"

echo '[5/6] Soak test court (stabilité ping/pong + navigation)'
"$PY" tests/test_soak.py --duree "${CLASSLIVE_SOAK_DUREE:-20}" --students "${CLASSLIVE_SOAK_STUDENTS:-5}"

echo '[6/6] Vérification ZIP source et documentation test'
test -f tests/MATRICE_COUVERTURE.md
test -f classlive/GUIDE_CLASSLIVE.md

echo
printf '=== SUCCÈS : suite terminée à %s ===\n' "$(date -Is)"
echo "Journal : $REPORT"
echo 'Aucune modification du workspace de production ; aucune utilisation du port 8080.'
