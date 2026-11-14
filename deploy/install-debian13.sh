#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Exécuter avec sudo/root.' >&2; exit 1; fi
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
apt-get update
apt-get install -y python3 python3-venv python3-pip acl
if ! id -u classlive >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/classlive --shell /usr/sbin/nologin classlive
fi
install -d -o root -g root -m 755 /opt/classlive
install -d -o root -g classlive -m 750 /etc/classlive
install -d -o classlive -g classlive -m 750 /var/lib/classlive
cp -a "$SOURCE_DIR/classlive" "$SOURCE_DIR/pyproject.toml" "$SOURCE_DIR/README.md" /opt/classlive/
# Les sources doivent être lisibles par l'utilisateur systemd (cp -a conserve les modes de l'archive).
chmod -R a+rX /opt/classlive/classlive

# Le tilde désigne le dossier personnel de l'utilisateur qui a exécuté sudo,
# pas celui du compte système classlive.
INSTALL_USER="${SUDO_USER:-$(id -un)}"
USER_HOME="$(getent passwd "$INSTALL_USER" | cut -d: -f6)"
if [[ -z "$USER_HOME" || ! -d "$USER_HOME" ]]; then
  echo "Répertoire personnel introuvable pour $INSTALL_USER" >&2
  exit 1
fi
DEFAULT_WORKDIR="$USER_HOME/classlive_workspace"

if [[ ! -e /etc/classlive/config.yml ]]; then
  # Convertir la valeur ~/classlive_workspace en chemin absolu,
  # car le service systemd tourne sous un utilisateur différent.
  CLASSLIVE_DEFAULT_WORKDIR="$DEFAULT_WORKDIR" SOURCE_CONFIG="$SOURCE_DIR/config.example.yml" \
    python3 - <<'PYCODE' > /etc/classlive/config.yml
import json
import os
from pathlib import Path
content = Path(os.environ['SOURCE_CONFIG']).read_text(encoding='utf-8')
content = content.replace('workdir: "~/classlive_workspace"', 'workdir: ' + json.dumps(os.environ['CLASSLIVE_DEFAULT_WORKDIR']))
print(content, end='')
PYCODE
  chown root:classlive /etc/classlive/config.yml
  chmod 640 /etc/classlive/config.yml
fi

# Créer des identifiants formateur au premier déploiement.
if [[ ! -e /etc/classlive/classlive.env ]]; then
  password="$(python3 - <<'PYCODE'
import secrets
print(secrets.token_urlsafe(24))
PYCODE
)"
  printf 'CLASSLIVE_TRAINER_PASSWORD=%s\n' "$password" > /etc/classlive/classlive.env
  chown root:classlive /etc/classlive/classlive.env
  chmod 640 /etc/classlive/classlive.env
fi
python3 -m venv /opt/classlive/.venv
/opt/classlive/.venv/bin/python -m pip install --disable-pip-version-check /opt/classlive

# Respecter les configurations existantes : ne pas écraser le workspace de l'utilisateur.
WORKDIR="$(CLASSLIVE_CONFIG=/etc/classlive/config.yml /opt/classlive/.venv/bin/python - <<'PYCODE'
from classlive.config import load_settings
print(load_settings().workdir)
PYCODE
)"
if [[ ! "$WORKDIR" = /* || "$WORKDIR" == '/' || "$WORKDIR" == *$'\n'* ]]; then
  echo "Répertoire de travail incorrect : $WORKDIR" >&2
  exit 1
fi
# Corriger les droits automatiquement a chaque installation/reinstallation.
case "$WORKDIR/" in
  "$USER_HOME/"*)
    setfacl -m 'u:classlive:--x' "$USER_HOME"
    install -d -m 750 "$WORKDIR"
    chown -R "$INSTALL_USER:$(id -gn "$INSTALL_USER")" "$WORKDIR"
    chmod u+rwx "$WORKDIR"
    ;;
  *)
    install -d -m 750 "$WORKDIR"
    ;;
esac
setfacl -R -m 'u:classlive:rwX' "$WORKDIR"
setfacl -R -d -m 'u:classlive:rwX' "$WORKDIR"
if ! runuser -u classlive -- test -r "$WORKDIR" || ! runuser -u classlive -- test -w "$WORKDIR"; then
  echo "ERREUR : acces impossible au workspace pour l'utilisateur classlive" >&2
  exit 1
fi
# systemd n'autorise en écriture que le workspace déclaré dans config.yml.
# Le chemin est échappé pour le format de directive systemd.
WORKDIR="$WORKDIR" SOURCE_SERVICE="$SOURCE_DIR/deploy/classlive.service" \
  python3 - <<'PYCODE' > /etc/systemd/system/classlive.service
import os
from pathlib import Path
value = os.environ['WORKDIR']
if any(c in value for c in '\n\r\x00'):
    raise ValueError('Chemin de workspace invalide')
# systemd accepte une valeur entre guillemets, avec échappement des backslashes et guillemets.
quoted = '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
print(Path(os.environ['SOURCE_SERVICE']).read_text(encoding='utf-8').replace('__CLASSLIVE_WORKSPACE__', quoted), end='')
PYCODE
chmod 644 /etc/systemd/system/classlive.service
systemctl daemon-reload
systemctl enable classlive
systemctl restart classlive
ready=0
for attempt in $(seq 1 20); do
  if /opt/classlive/.venv/bin/python - <<'PYHEALTH' >/dev/null 2>&1
from urllib.request import urlopen
with urlopen('http://127.0.0.1:8080/health', timeout=1) as response:
    assert response.status == 200
PYHEALTH
  then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" != 1 ]]; then
  echo "ERREUR : API ClassLive inaccessible sur 127.0.0.1:8080" >&2
  systemctl --no-pager -l status classlive || true
  journalctl -u classlive -n 40 --no-pager || true
  exit 1
fi
systemctl --no-pager status classlive
printf '\nWorkspace : %s\nConfiguration : /etc/classlive/config.yml\nMot de passe formateur : /etc/classlive/classlive.env\nLogs : journalctl -u classlive -f\n' "$WORKDIR"
