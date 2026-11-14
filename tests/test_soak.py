#!/usr/bin/env python3
"""Soak test court : stabilité d'un Live avec ping/pong continu et navigations.

Démarre un serveur éphémère, connecte 5 étudiants en WebSocket, envoie des
ping toutes les 2 secondes pendant la durée indiquée (défaut 20 s), navigue
entre les slides, et vérifie qu'aucune connexion n'est perdue.
Ne contacte jamais le port 8080.
Usage : python tests/test_soak.py --duree 20 --students 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_reseau_multiclients import Server, PASSWORD, auth, req, ws_packet


async def soak(srv: Server, duree: int, students: int):
    with httpx.Client(base_url=srv.base, timeout=30) as client:
        async with httpx.AsyncClient(base_url=srv.base, timeout=30) as aclient:
            trainer = auth(client)
            t_headers = {'Authorization': f'Bearer {trainer}'}
            g = req(client, 'POST', '/api/v1/groups', token=trainer, json={'group': 'Soak'}).json()['group']
            e = req(client, 'POST', '/api/v1/events', token=trainer, json={'group': g, 'title': 'Stabilité'}).json()['title']
            base = f'/api/v1/groups/{g}/events/{e}/slides'
            for i in range(1, 6):
                req(client, 'POST', base, token=trainer, json={
                    'title': f'Slide {i}', 'slide_type': 'Q' if i % 2 else 'C',
                    'content': f'# Slide {i}'})
            live = req(client, 'POST', '/api/v1/live/start', token=trainer, json={'group': g, 'title': e}).json()
            lid, code = live['live_id'], live['session_code']

            async def join(i):
                r = await aclient.post('/api/v1/student/join', json={
                    'session_code': code, 'nom': f'Soak{i:02d}', 'prenom': f'Test{i:02d}'})
                assert r.status_code == 200, r.text
                return r.json()

            regs = await asyncio.gather(*(join(i) for i in range(students)))
            tokens = [r['student_session_id'] for r in regs]

            ws_streams = []
            for tok in tokens:
                ws = await connect(f'{srv.wsbase}/api/v1/student/ws', open_timeout=10)
                await ws.send(json.dumps({'token': tok}))
                await ws_packet(ws, 'current')
                ws_streams.append(ws)

            # Boucle de ping continuelle + navigation périodique
            deadline = time.monotonic() + duree
            nav_count = 0
            pings = 0
            while time.monotonic() < deadline:
                await asyncio.gather(*(ws.send(json.dumps({'event': 'ping'})) for ws in ws_streams))
                await asyncio.gather(*(ws_packet(ws, 'pong') for ws in ws_streams))
                pings += 1
                if pings % 5 == 0 and nav_count < 4:
                    req(client, 'POST', f'/api/v1/live/{lid}/next', token=trainer)
                    await asyncio.gather(*(ws_packet(ws, 'slide_changed') for ws in ws_streams))
                    nav_count += 1
                await asyncio.sleep(2)

            # Vérifier que tous sont toujours connectés
            status = req(client, 'GET', f'/api/v1/live/{lid}/students', token=trainer).json()
            assert status['connected'] == students, f"Perdus: {status}"

            await asyncio.gather(*(ws.close() for ws in ws_streams))
            req(client, 'POST', f'/api/v1/live/{lid}/stop', token=trainer)
            req(client, 'DELETE', f'/api/v1/groups/{g}/events/{e}/sessions', token=trainer)
            req(client, 'DELETE', f'/api/v1/groups/{g}/events/{e}', token=trainer)
            req(client, 'DELETE', f'/api/v1/groups/{g}', token=trainer)
            return pings, nav_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duree', type=int, default=20, help='Durée du soak en secondes (défaut 20)')
    parser.add_argument('--students', type=int, default=5, help='Nombre d\'étudiants (défaut 5)')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='classlive-soak-') as temp:
        srv = Server(Path(temp))
        srv.start()
        try:
            pings, navs = asyncio.run(soak(srv, args.duree, args.students))
        finally:
            srv.stop()
    print(f'\nSUCCÈS soak : {args.duree}s, {args.students} étudiants, {pings} cycles ping/pong, {navs} navigations, aucune déconnexion.')


if __name__ == '__main__':
    main()
