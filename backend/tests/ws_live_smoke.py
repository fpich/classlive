#!/usr/bin/env python3
"""Test réseau WebSocket réel pour ClassLive; dépendance runtime `websockets`."""
import json
import os
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from websockets.sync.client import connect

base = os.environ['CLASSLIVE_URL'].rstrip('/')
trainer = os.environ['CLASSLIVE_TRAINER_TOKEN']
student = os.environ['CLASSLIVE_STUDENT_TOKEN']
live = os.environ['CLASSLIVE_LIVE_ID']
parts = urlsplit(base)
ws_url = ('wss' if parts.scheme == 'https' else 'ws') + '://' + parts.netloc


def request(method, path):
    r = Request(base + path, method=method, headers={'Authorization': 'Bearer ' + trainer})
    with urlopen(r, timeout=10) as response:
        assert response.status == 200
        return json.load(response)


def received(ws, expected):
    packet = json.loads(ws.recv(timeout=8))
    assert packet.get('event') == expected, f"Événement WebSocket attendu {expected!r}, reçu: {packet!r}"
    return packet


with connect(f'{ws_url}/api/v1/live/{live}/monitor', open_timeout=8, close_timeout=2) as monitor:
    monitor.send(json.dumps({'token': trainer}))
    received(monitor, 'monitor')
    with connect(f'{ws_url}/api/v1/student/ws', open_timeout=8, close_timeout=2) as stream:
        stream.send(json.dumps({'token': student}))
        start = received(stream, 'current')
        assert start['current']['number'] == 1
        received(monitor, 'student_connected')
        connected = request('GET', f'/api/v1/live/{live}/students')
        assert connected['connected'] >= 1, connected
        stream.send(json.dumps({'event': 'ping'}))
        received(stream, 'pong')
        request('POST', f'/api/v1/live/{live}/next')
        move = received(stream, 'slide_changed')
        assert move['current']['number'] == 2, move
        received(monitor, 'slide_changed')
        request('POST', f'/api/v1/live/{live}/previous')
        restored = received(stream, 'slide_changed')
        assert restored['current']['number'] == 1, restored
        received(monitor, 'slide_changed')
    received(monitor, 'student_disconnected')
    disconnected = request('GET', f'/api/v1/live/{live}/students')
    assert disconnected['connected'] == 0, disconnected
print('OK WebSocket réel : monitor, présence, ping/pong, slide_changed, déconnexion.')
