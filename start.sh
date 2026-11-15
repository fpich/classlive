#!/usr/bin/env bash
# ClassLive — build le frontend et lance le backend (port 8080, sert /app).
#
#   ./start.sh
#
# L'URL d'exposition LAN se règle dans expose.conf (une ligne, ex: http://192.168.10.26:8080).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
CONFIG_YML="$BACKEND_DIR/config.yml"
DIST_DIR="$FRONTEND_DIR/dist"
BACKEND_PID=""

# ── URL d'exposition (expose.conf) ─────────────────────────────────────────

PUBLIC_URL=""
if [ -f "$ROOT/expose.conf" ]; then
  PUBLIC_URL=$(grep -v '^#' "$ROOT/expose.conf" | grep -v '^$' | head -1 | tr -d '[:space:]')
fi
[ -z "$PUBLIC_URL" ] && PUBLIC_URL="http://$(hostname -I 2>/dev/null | awk '{print $1}'):8080"

# ── Vérifications ──────────────────────────────────────────────────────────

for cmd in python3 node npm; do
  command -v "$cmd" &>/dev/null || { echo "ERREUR : $cmd introuvable." >&2; exit 1; }
done

port_in_use() {
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3>&- 3<&-; return 0; } || return 1
}

# ── Backend : venv + dépendances + config ──────────────────────────────────

cd "$BACKEND_DIR"
[ ! -d .venv ] && { echo "→ venv Python..."; python3 -m venv .venv; }
. .venv/bin/activate
echo "→ dépendances backend..."
pip install -q -e '.[test]'

if [ ! -f "$CONFIG_YML" ]; then
  cp config.local.example.yml "$CONFIG_YML" 2>/dev/null || cp config.example.yml "$CONFIG_YML"
fi

[ -z "${CLASSLIVE_TRAINER_PASSWORD:-}" ] && echo "⚠  CLASSLIVE_TRAINER_PASSWORD non défini."

# ── Frontend : build ───────────────────────────────────────────────────────

echo "→ build frontend..."
cd "$FRONTEND_DIR"
[ ! -d node_modules ] && npm install
npm run build

cd "$BACKEND_DIR"
if grep -q "frontend_dir:" "$CONFIG_YML"; then
  sed -i "s|frontend_dir:.*|frontend_dir: \"$DIST_DIR\"|" "$CONFIG_YML"
elif grep -q "^  server:" "$CONFIG_YML"; then
  sed -i "/^  server:/a\\    frontend_dir: \"$DIST_DIR\"" "$CONFIG_YML"
else
  sed -i "s|^classlive:|classlive:\n  server:\n    frontend_dir: \"$DIST_DIR\"|" "$CONFIG_YML"
fi

# ── Lancement ──────────────────────────────────────────────────────────────

cleanup() {
  echo "→ Arrêt."
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null
  wait 2>/dev/null
  exit 0
}
trap cleanup SIGINT SIGTERM

echo ""
echo "═══════════════════════════════════════════"
echo "  ClassLive — $PUBLIC_URL/app/"
echo "  Élèves    : $PUBLIC_URL/app/join?code=XXXXXX"
echo "  Swagger   : $PUBLIC_URL/docs"
echo "═══════════════════════════════════════════"
echo "  expose.conf = $PUBLIC_URL   |   Ctrl+C pour arrêter"
echo ""

# Tuer une ancienne instance sur 8080 si présente
if port_in_use 8080; then
  OLD=$(ss -tlnp 2>/dev/null | grep ':8080' | grep -oP 'pid=\K[0-9]+' | head -1)
  [ -n "$OLD" ] && sudo kill "$OLD" 2>/dev/null
  sleep 2
fi

cd "$BACKEND_DIR"
. .venv/bin/activate
python -m classlive &
BACKEND_PID=$!

for i in $(seq 1 30); do
  port_in_use 8080 && { echo "→ prêt sur 0.0.0.0:8080"; break; }
  sleep 0.5
done

wait "$BACKEND_PID" 2>/dev/null || wait
cleanup
