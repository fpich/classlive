#!/usr/bin/env bash
# ClassLive — build le frontend et lance le backend (port 8080, sert /app).
#
#   ./start.sh
#
# L'URL d'exposition LAN se règle dans expose.conf (une ligne, ex: http://192.168.10.26:8080).
# Si expose.conf est introuvable, détecte automatiquement l'IP LAN.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
CONFIG_YML="$BACKEND_DIR/config.yml"
DIST_DIR="$FRONTEND_DIR/dist"
PID_FILE="$BACKEND_DIR/classlive.pid"
BACKEND_PID=""

# ── Arrêt propre ────────────────────────────────────────────────────────────

cleanup() {
  echo "→ Arrêt."
  if [ -n "$BACKEND_PID" ] && [ -f /proc/$BACKEND_PID/status ] 2>/dev/null; then
    echo "  Arrêt du processus $BACKEND_PID..."
    kill "$BACKEND_PID" 2>/dev/null || true
    for i in $(seq 1 10); do
      [ ! -f /proc/$BACKEND_PID/status ] 2>/dev/null && break
      sleep 0.5
    done
    [ -f /proc/$BACKEND_PID/status ] 2>/dev/null && kill -9 "$BACKEND_PID" 2>/dev/null || true
  fi
  # Supprimer d'anciens fichiers PID
  rm -f "$PID_FILE" 2>/dev/null || true
  exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# ── Détection de l'IP LAN ───────────────────────────────────────────────────

get_lan_ip() {
  # Essayer hostname -I
  local ip
  ip=$(hostname -I 2>/dev/null | awk '{print $1}') 2>/dev/null || true
  [ -n "$ip" ] && echo "$ip" && return
  
  # Essayer ip route
  ip=$(ip route get 1 2>/dev/null | awk '{print $NF; exit}') 2>/dev/null || true
  [ -n "$ip" ] && echo "$ip" && return
  
  # Essayer ifconfig
  ip=$(ifconfig 2>/dev/null | awk '/inet / {print $2}' | grep -v '127.0.0.1' | head -1) 2>/dev/null || true
  [ -n "$ip" ] && echo "$ip" && return
  
  # Essayer ip addr
  ip=$(ip addr 2>/dev/null | awk '/inet / {print $2}' | grep -v '127.0.0.1' | head -1 | cut -d/ -f1) 2>/dev/null || true
  [ -n "$ip" ] && echo "$ip" && return
  
  echo "127.0.0.1"
}

get_public_url() {
  # Lire depuis expose.conf
  if [ -f "$ROOT/expose.conf" ]; then
    local url
    url=$(grep -v '^#' "$ROOT/expose.conf" | grep -v '^$' | head -1 | tr -d '[:space:]')
    [ -n "$url" ] && echo "$url" && return
  fi
  
  # Détection automatique
  local ip
  ip=$(get_lan_ip)
  echo "http://${ip}:8080"
}

PUBLIC_URL=$(get_public_url)

# ── Vérifications ──────────────────────────────────────────────────────────

for cmd in python3 node npm; do
  command -v "$cmd" &>/dev/null || { echo "ERREUR : $cmd introuvable." >&2; exit 1; }
done

port_in_use() {
  python3 -c "import socket; s=socket.socket(); s.settimeout(0.5); s.connect(('127.0.0.1', $1)); s.close()" 2>/dev/null && return 0 || return 1
}

get_classlive_pid() {
  # Trouver le PID du processus classlive
  local pid
  # Méthode 1 : rechercher python -m classlive
  pid=$(ps aux 2>/dev/null | grep -E "python.*-m classlive|classlive.__main__" | grep -v grep | awk '{print $2}' | head -1) || true
  [ -n "$pid" ] && echo "$pid" && return
  
  # Méthode 2 : rechercher classlive (script)
  pid=$(ps aux 2>/dev/null | grep "classlive" | grep -v grep | awk '{print $2}' | head -1) || true
  [ -n "$pid" ] && echo "$pid" && return
  
  echo ""
}

# ── Arrêter une ancienne instance ────────────────────────────────────────────

if port_in_use 8080; then
  echo "→ Port 8080 déjà utilisé, arrêt de l'ancienne instance..."
  OLD_PID=$(get_classlive_pid)
  if [ -n "$OLD_PID" ]; then
    echo "  Processus trouvé : $OLD_PID"
    kill "$OLD_PID" 2>/dev/null || sudo kill "$OLD_PID" 2>/dev/null || true
    for i in $(seq 1 10); do
      ! port_in_use 8080 && break
      sleep 0.5
    done
    port_in_use 8080 && echo "  ⚠ Impossible d'arrêter, vérifiez manuellement." || echo "  ✓ Arrêté."
  else
    echo "  ⚠ Processus inconnu sur le port 8080, vérifiez manuellement."
  fi
  sleep 1
fi

# ── Backend : venv + dépendances + config ──────────────────────────────────

cd "$BACKEND_DIR"

# Créer venv si nécessaire
if [ ! -d .venv ]; then
  echo "→ Création du venv Python..."
  python3 -m venv .venv
fi

# Activer venv
source .venv/bin/activate

# Installer les dépendances uniquement si nécessaire
if [ ! -f .venv_installed ]; then
  echo "→ Installation des dépendances backend..."
  pip install -q -e .
  touch .venv_installed
fi

# Installer les préparation de test uniquement si explicitement demandé
# (évite de réinstaller à chaque démarrage)
if [ "${INSTALL_TESTS:-}" = "true" ]; then
  echo "→ Installation des dépendances de test..."
  pip install -q -e '.[test]'
else
  # Vérifier si les dépendances tests sont déjà installées
  if [ -f .venv_test_installed ]; then
    echo "→ Dépendances de test déjà installées"
  else
    # Installe uniquement les dépendances principales
    echo "→ Vérification des dépendances principales..."
    pip install -q -e .
    touch .venv_installed
  fi
fi

if [ ! -f "$CONFIG_YML" ]; then
  cp config.local.example.yml "$CONFIG_YML" 2>/dev/null || cp config.example.yml "$CONFIG_YML"
fi

[ -z "${CLASSLIVE_TRAINER_PASSWORD:-}" ] && echo "⚠  CLASSLIVE_TRAINER_PASSWORD non défini."

# ── Frontend : build ───────────────────────────────────────────────────────

echo "→ Build du frontend..."
cd "$FRONTEND_DIR"

# Installer node_modules si nécessaire
if [ ! -d node_modules ]; then
  echo "  Installation des dépendances npm..."
  npm install
fi

# Build seulement si nécessaire
if [ ! -d "$DIST_DIR" ] || [ "$FRONTEND_DIR/src" -nt "$DIST_DIR/index.html" ] 2>/dev/null || [ "$FRONTEND_DIR/package.json" -nt "$DIST_DIR/index.html" ] 2>/dev/null; then
  echo "  Build en cours..."
  npm run build
else
  echo "  Frontend déjà à jour."
fi

# ── Configuration du backend pour servir le frontend ─────────────────────

cd "$BACKEND_DIR"

# Configurer frontend_dir dans config.yml
if grep -q "frontend_dir:" "$CONFIG_YML"; then
  sed -i "s|frontend_dir:.*|frontend_dir: \"$DIST_DIR\"|" "$CONFIG_YML"
elif grep -q "^  server:" "$CONFIG_YML"; then
  sed -i "/^  server:/a\\    frontend_dir: \"$DIST_DIR\"" "$CONFIG_YML"
else
  sed -i "s|^classlive:|classlive:\n  server:\n    frontend_dir: \"$DIST_DIR\"|" "$CONFIG_YML"
fi

# ── Lancement ──────────────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════"
echo "  ClassLive — $PUBLIC_URL/app/"
echo "  Élèves    : $PUBLIC_URL/app/join?code=XXXXXX"
echo "  Swagger   : $PUBLIC_URL/docs"
echo "═══════════════════════════════════════════"
echo "  expose.conf = $PUBLIC_URL   |   Ctrl+C pour arrêter"
echo ""

cd "$BACKEND_DIR"
source .venv/bin/activate

# Écrire le PID dans un fichier
python3 -c "import os, sys; sys.stdout.write(str(os.getpid()))" > "$PID_FILE"

# Démarrer le backend
python -m classlive &
BACKEND_PID=$!

# Attendre que le serveur soit prêt
for i in $(seq 1 60); do
  if port_in_use 8080; then
    echo "→ prêt sur 0.0.0.0:8080 (PID: $BACKEND_PID)"
    # Mettre à jour le PID file avec le bon PID
    echo "$BACKEND_PID" > "$PID_FILE"
    break
  fi
  sleep 0.5
done

# Attendre indéfiniment
while [ -f /proc/$BACKEND_PID/status ] 2>/dev/null; do
  sleep 1
done

cleanup
