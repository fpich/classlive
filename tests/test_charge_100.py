#!/usr/bin/env python3
"""Test de charge : 100 étudiants simultanés sur un serveur éphémère isolé.

Réutilise le scénario réseau de test_reseau_multiclients.py avec 100 étudiants.
Ne contacte jamais le port 8080 ni les données de production.
Usage : python tests/test_charge_100.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_reseau_multiclients import Server, network_scenario


def main():
    students = 100
    with tempfile.TemporaryDirectory(prefix='classlive-charge100-') as temp:
        srv = Server(Path(temp))
        srv.start()
        try:
            checks = asyncio.run(network_scenario(srv, students))
        except Exception:
            print('\n--- Journaux du serveur éphémère ---\n' + srv.log_tail(), file=sys.stderr)
            raise
        finally:
            srv.stop()
    print(f'\nSUCCÈS : charge {students} étudiants sur instance temporaire')
    for entry in checks:
        print('  [OK] ' + entry)


if __name__ == '__main__':
    main()
