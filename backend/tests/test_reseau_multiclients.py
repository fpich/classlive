#!/usr/bin/env python3
"""Test de bout en bout sur une vraie instance HTTP/WebSocket ISOLÉE.

Ne contacte JAMAIS le ClassLive installé sur :8080. Démarre une instance éphémère
sur 127.0.0.1 avec un workspace SQLite temporaire puis la redémarre.
Usage : python tests/test_reseau_multiclients.py --students 30
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import AsyncExitStack
from pathlib import Path

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'test-reseau-isole-aucun-secret-production'


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class Server:
    def __init__(self, temporary: Path):
        self.tmp = temporary
        self.port = free_port()
        self.base = f'http://127.0.0.1:{self.port}'
        self.wsbase = f'ws://127.0.0.1:{self.port}'
        self.config = self.tmp / 'config.yml'
        self.workspace = self.tmp / 'workspace'
        self.logpath = self.tmp / 'serveur.log'
        self.config.write_text(
            'classlive:\n'
            f'  server:\n    host: "127.0.0.1"\n    port: {self.port}\n'
            f'  storage:\n    workdir: "{self.workspace}"\n    events_dir: "Evts"\n'
            '  logging:\n    level: "INFO"\n'
            '  security:\n    trainer_username: "formateur"\n    api_key: null\n',
            encoding='utf-8',
        )
        self.process = None

    def start(self):
        env = dict(os.environ)
        env['CLASSLIVE_CONFIG'] = str(self.config)
        env['CLASSLIVE_TRAINER_PASSWORD'] = PASSWORD
        env['PYTHONPATH'] = str(ROOT) + os.pathsep + env.get('PYTHONPATH', '')
        with self.logpath.open('ab') as log:
            self.process = subprocess.Popen(
                [sys.executable, '-m', 'classlive'], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError('Serveur isolé arrêté au démarrage :\n' + self.log_tail())
            try:
                with httpx.Client(timeout=1) as client:
                    response = client.get(self.base + '/health')
                if response.status_code == 200 and response.json().get('service') == 'classlive':
                    return
            except httpx.HTTPError:
                pass
            time.sleep(.1)
        raise AssertionError('Serveur isolé inaccessible :\n' + self.log_tail())

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def restart(self):
        self.stop()
        self.start()

    def log_tail(self):
        try:
            return '\n'.join(self.logpath.read_text(errors='replace').splitlines()[-80:])
        except OSError:
            return '(aucun journal)'


def req(client, method, path, expected=200, token=None, **kwargs):
    headers = kwargs.pop('headers', {})
    if token is not None:
        headers = {**headers, 'Authorization': 'Bearer ' + token}
    response = client.request(method, path, headers=headers, **kwargs)
    check(response.status_code == expected,
          f'{method} {path}: HTTP {response.status_code} attendu {expected}; {response.text[:800]}')
    return response


def auth(client):
    return req(client, 'POST', '/api/v1/auth/login', json={'username': 'formateur', 'password': PASSWORD}).json()['access_token']


async def ws_packet(ws, expected, timeout=15):
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    data = json.loads(raw)
    check(data.get('event') == expected, f'WS: attendu {expected}, reçu {data}')
    return data


async def wait_connected(client, lid, token, target, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = (client.get(f'/api/v1/live/{lid}/students', headers={'Authorization': f'Bearer {token}'})).json()
        if result.get('connected') == target:
            return result
        await asyncio.sleep(.1)
    raise AssertionError(f'Présence WS: {target} attendus, dernière réponse {result}')


async def network_scenario(srv: Server, students: int):
    checks = []
    with httpx.Client(base_url=srv.base, timeout=30) as client:
        async with httpx.AsyncClient(base_url=srv.base, timeout=30) as async_client:
            trainer = auth(client)
            t_headers = {'Authorization': f'Bearer {trainer}'}
            check((client.get('/openapi.json')).status_code == 200, 'OpenAPI')
            check((client.get('/api/v1/help')).status_code == 200, 'Aide')
            checks.append('HTTP /health /openapi.json /help')
            g = req(client, 'POST', '/api/v1/groups', token=trainer, json={'group': 'Test Réseau'}).json()['group']
            e = req(client, 'POST', '/api/v1/events', token=trainer, json={'group': g, 'title': 'Test Concurrence'}).json()['title']
            base = f'/api/v1/groups/{g}/events/{e}/slides'
            s1 = req(client, 'POST', base, token=trainer,
                     json={'title': 'QCM initial', 'slide_type': 'Q',
                           'content': '---\nclasslive_answer:\n  selected: [B]\n---\n# QUESTION_UNIQUE_SENSITIVE\n- A\n- B'}).json()['slide']
            req(client, 'POST', base, token=trainer,
                json={'title': 'Contenu', 'slide_type': 'C', 'content': '# Fin'} )
            live = req(client, 'POST', '/api/v1/live/start', token=trainer,
                       json={'group': g, 'title': e}).json()
            lid, code = live['live_id'], live['session_code']
            checks.append('Création groupes / événement / slides / Live')

            async def join(i):
                response = await async_client.post('/api/v1/student/join', json={
                    'session_code': code, 'nom': f'Nom{i:02d}', 'prenom': f'Prenom{i:02d}'})
                check(response.status_code == 200, f'Inscription étudiant {i}: {response.text}')
                return response.json()

            registrations = await asyncio.gather(*(join(i) for i in range(students)))
            tokens = [r['student_session_id'] for r in registrations]
            ids = [r['participation_id'] for r in registrations]
            check(len(set(tokens)) == students and len(set(ids)) == students,
                  'Les identifiants et jetons ne sont pas uniques')
            check(all(r['current']['number'] == 1 for r in registrations), 'Slide initiale incorrecte')
            checks.append(f'{students} inscriptions concurrentes, jetons uniques et noms enregistrés')

            # Un étudiant ne peut pas appeler les routes formateur, même avec un jeton valide.
            denied = client.get('/api/v1/groups', headers={'Authorization': f'Bearer {tokens[0]}'})
            check(denied.status_code == 401, 'Escalade de privilèges étudiant')
            checks.append('Séparation formateur / étudiant')

            # Connexions WebSocket réelles, simultanées, avec un moniteur formateur.
            async with AsyncExitStack() as stack:
                monitor = await stack.enter_async_context(connect(
                    f'{srv.wsbase}/api/v1/live/{lid}/monitor', open_timeout=10))
                await monitor.send(json.dumps({'token': trainer}))
                await ws_packet(monitor, 'monitor')

                async def connect_student(tok):
                    ws = await stack.enter_async_context(connect(f'{srv.wsbase}/api/v1/student/ws', open_timeout=15))
                    await ws.send(json.dumps({'token': tok}))
                    packet = await ws_packet(ws, 'current')
                    check('classlive_answer' not in json.dumps(packet) and 'correction' not in packet['current'],
                          'Fuite du corrigé avant affichage')
                    return ws

                streams = await asyncio.gather(*(connect_student(tok) for tok in tokens))
                status = await wait_connected(client, lid, trainer, students)
                check(status['total_students'] == students, f'Comptage étudiants incorrect: {status}')
                for _ in range(students):
                    await ws_packet(monitor, 'student_connected')
                checks.append(f'{students} WebSockets + surveillance de présence réelle')

                await asyncio.gather(*(ws.send(json.dumps({'event': 'ping'})) for ws in streams))
                await asyncio.gather(*(ws_packet(ws, 'pong') for ws in streams))
                checks.append(f'{students} heartbeats ping / pong')

                # 30 étudiants envoient simultanément une réponse; SQLite doit tout conserver.
                async def send_answer(i):
                    response = await async_client.post('/api/v1/student/answers',
                         headers={'Authorization': 'Bearer ' + tokens[i]},
                         json={'answer': {'selected': ['B'], 'index': i}})
                    check(response.status_code == 200, f'Réponse étudiant {i}: {response.status_code} {response.text}')

                await asyncio.gather(*(send_answer(i) for i in range(students)))
                for _ in range(students):
                    await ws_packet(monitor, 'answer_received')
                result = req(client, 'GET', f'/api/v1/live/{lid}/results', token=trainer).json()
                check(len(result['results']) == students, 'Nombre de résultats incorrect')
                check(all(r['answered'] == 1 and len(r['answers']) == 1 for r in result['results']),
                      'Réponses perdues ou dupliquées')
                expected = {f'Nom{i:02d}': i for i in range(students)}
                for r in result['results']:
                    check(r['answers'][0]['answer']['index'] == expected[r['nom']], 'Réponses attribuées au mauvais étudiant')
                check('points' not in json.dumps(result), 'Notation présente malgré la demande de suppression')
                checks.append(f'{students} réponses HTTP concurrentes, stockage SQLite et attribution correcte')

                req(client, 'POST', f'/api/v1/live/{lid}/correction/show', token=trainer)
                packets = await asyncio.gather(*(ws_packet(ws, 'correction_shown') for ws in streams))
                check(all(p['current'].get('correction') == {'selected': ['B']} for p in packets),
                      'Correction non diffusée')
                await ws_packet(monitor, 'correction_shown')
                check((await async_client.post('/api/v1/student/answers', headers={
                    'Authorization': f'Bearer {tokens[0]}'}, json={'answer': {'selected': ['A']}})).status_code == 409,
                    'Réponse acceptée pendant correction')
                req(client, 'POST', f'/api/v1/live/{lid}/correction/hide', token=trainer)
                hidden = await asyncio.gather(*(ws_packet(ws, 'correction_hidden') for ws in streams))
                check(all('correction' not in p['current'] for p in hidden), 'Corrigé exposé après hide')
                await ws_packet(monitor, 'correction_hidden')
                req(client, 'POST', f'/api/v1/live/{lid}/next', token=trainer)
                moved = await asyncio.gather(*(ws_packet(ws, 'slide_changed') for ws in streams))
                check(all(p['current']['number'] == 2 for p in moved), 'Les étudiants ne sont pas synchronisés')
                await ws_packet(monitor, 'slide_changed')
                checks.append(f'Diffusion simultanée show/hide et navigation à {students} étudiants')

                # Déconnexion partielle puis présence exacte. Les autres restent connectés.
                cut = max(1, students // 3)
                await asyncio.gather(*(ws.close() for ws in streams[:cut]))
                await wait_connected(client, lid, trainer, students-cut)
                for _ in range(cut):
                    await ws_packet(monitor, 'student_disconnected')
                checks.append(f'Déconnexion de {cut} étudiants, {students-cut} restent en ligne')

                # Fermer proprement les connexions restantes AVANT le redémarrage.
                # Le test de reconnexion vérifie ensuite la persistance à travers un vrai processus.
                await asyncio.gather(*(ws.close() for ws in streams[cut:]))
                for _ in range(students-cut):
                    await ws_packet(monitor, 'student_disconnected')
                await wait_connected(client, lid, trainer, 0)

            # Vérification des CSV (aucun score, bonnes colonnes, identité préservée).
            csv_resp = req(client, 'GET', f'/api/v1/live/{lid}/export.csv', token=trainer)
            rows = list(csv.DictReader(io.StringIO(csv_resp.content.decode('utf-8-sig')), delimiter=';'))
            check(len(rows) == students, f'CSV: {len(rows)} lignes, {students} attendues')
            check({r['nom'] for r in rows} == set(expected), 'Export CSV ne contient pas les étudiants attendus')
            check('points' not in rows[0] and 'reponse_json' in rows[0], 'CSV contient une notation')
            checks.append('Export CSV vérifié : lignes, colonnes et identité des étudiants')

            # Un vrai redémarrage du serveur conserve le Live, les snapshots et les réponses.
            srv.restart()
            trainer = auth(client)
            req(client, 'GET', f'/api/v1/live/{lid}/status', token=trainer)
            state = req(client, 'GET', f'/api/v1/live/{lid}/status', token=trainer).json()
            check(state['status'] == 'running' and state['number'] == 2, 'Live actif non conservé après redémarrage')
            resume = req(client, 'POST', '/api/v1/student/resume', token=tokens[0]).json()
            check(resume['nom'] == 'Nom00' and resume['current']['number'] == 2, 'Reconnexion étudiant après redémarrage')
            check('correction' not in resume['current'], 'Correction cachée devenue visible après redémarrage')
            results = req(client, 'GET', f'/api/v1/live/{lid}/results', token=trainer).json()
            check(len(results['results']) == students, 'Réponses perdues après redémarrage')
            check(req(client, 'GET', f'/api/v1/live/{lid}/students', token=trainer).json()['connected'] == 0,
                  'Présence WebSocket fantôme après redémarrage')
            checks.append('Redémarrage vrai processus : Live actif + données + reconnexion + présence')

            # Vie complète: arrêt, accès révoqué, archivage, nouveau Live, nettoyage.
            req(client, 'POST', f'/api/v1/live/{lid}/stop', token=trainer)
            check((client.get('/api/v1/student/current', headers={
                'Authorization': 'Bearer ' + tokens[0]})).status_code == 401,
                'L’étudiant peut encore voir le Live terminé')
            check(req(client, 'GET', f'/api/v1/live/{lid}/results', token=trainer).json()['status'] == 'ended',
                  'Historique non conservé')
            check(req(client, 'DELETE', f'/api/v1/live/{lid}', token=trainer).json()['deleted'],
                  'Session terminée non supprimée')
            live2 = req(client, 'POST', '/api/v1/live/start', token=trainer,
                        json={'group': g, 'title': e}).json()
            req(client, 'POST', f'/api/v1/live/{live2["live_id"]}/stop', token=trainer)
            req(client, 'DELETE', f'/api/v1/groups/{g}/events/{e}/sessions', token=trainer)
            check(req(client, 'GET', f'/api/v1/groups/{g}/events/{e}/sessions', token=trainer).json()['sessions'] == [],
                  'Réinitialisation événement incomplète')
            req(client, 'DELETE', f'{base}/{s1}', token=trainer)
            req(client, 'DELETE', f'/api/v1/groups/{g}/events/{e}', token=trainer)
            req(client, 'DELETE', f'/api/v1/groups/{g}', token=trainer)
            checks.append('Arrêt, archive, suppression, réutilisation et réinitialisation')

    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--students', type=int, default=30, help='Connexions et réponses concurrentes (défaut 30)')
    args = parser.parse_args()
    if not 1 <= args.students <= 300:
        parser.error('--students doit être entre 1 et 300')
    with tempfile.TemporaryDirectory(prefix='classlive-reseau-isole-') as temp:
        srv = Server(Path(temp))
        srv.start()
        try:
            checks = asyncio.run(network_scenario(srv, args.students))
        except Exception:
            print('\n--- Journaux du serveur éphémère ---\n' + srv.log_tail(), file=sys.stderr)
            raise
        finally:
            srv.stop()
    print('\nSUCCÈS : tests réseau réels sur instance temporaire')
    for entry in checks:
        print('  [OK] ' + entry)
    print('Aucune donnée de production utilisée, aucune requête sur le port 8080.')


if __name__ == '__main__':
    main()
