#!/usr/bin/env python3
"""Lance la totalité des tests curl existants sur un serveur TEMPORAIRE.

Évite toute modification du ClassLive en production et n'utilise aucun mot de
passe formateur réel. Le workspace et les exports sont détruits à la fin.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_reseau_multiclients import Server, PASSWORD

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='classlive-curl-isole-') as tmp:
        server = Server(Path(tmp))
        server.start()
        try:
            env = dict(os.environ)
            env.update(
                CLASSLIVE_URL=server.base,
                CLASSLIVE_PASSWORD=PASSWORD,
                CLASSLIVE_PYTHON=sys.executable,
                CLASSLIVE_SKIP_WEBSOCKET='0',
            )
            result = subprocess.run(
                ['bash', str(ROOT / 'test_classlive_curl.sh')],
                cwd=tmp, env=env, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=150,
            )
            print(result.stdout)
            if result.returncode != 0:
                print('JOURNAL SERVEUR ISOLÉ :\n' + server.log_tail(), file=sys.stderr)
                raise SystemExit('ÉCHEC du scénario curl intégral sur instance isolée')
            if 'SUCCÈS : tous les tests REST ont réussi.' not in result.stdout:
                raise SystemExit('ÉCHEC : marqueur de succès absent')
        finally:
            server.stop()
    print('SUCCÈS : parcours curl complet, sans toucher au port 8080 ni aux données réelles.')


if __name__ == '__main__':
    main()
