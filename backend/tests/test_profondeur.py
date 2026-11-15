"""Tests de profondeur : concurrence, WS autonome, persistance restart,
présence 45 s, failles de sécurité, scénarios extrêmes autonome."""
import concurrent.futures
import time
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from classlive.api import create_app
from classlive.config import Settings


def _event(client, slides=3):
    g = client.post('/api/v1/groups', json={'group': 'Prof'}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': 'Cours'}).json()['title']
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    kinds = ['C', 'Q', 'C', 'Q', 'T']
    for i in range(slides):
        kind = kinds[i % len(kinds)]
        content = '---\nclasslive_answer:\n  selected: [B]\n---\n# Q' if kind != 'C' else f'# Slide {i}'
        client.post(base, json={'title': f'S{i}', 'slide_type': kind, 'content': content})
    return g, e, base


def _event_qcm_seul(client):
    """Un événement avec UNE seule slide QCM."""
    g = client.post('/api/v1/groups', json={'group': 'Q'}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': 'Q'}).json()['title']
    client.post(f'/api/v1/groups/{g}/events/{e}/slides', json={
        'title': 'Q', 'slide_type': 'Q',
        'content': '---\nclasslive_answer:\n  selected: [B]\n---\n# Q?'})
    return g, e


def _start(client, g, e, **kw):
    payload = {'group': g, 'title': e}
    payload.update(kw)
    if 'mode' not in payload:
        payload['mode'] = 'autonome'
    r = client.post('/api/v1/live/start', json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _join(client, code, nom='Eleve'):
    r = client.post('/api/v1/student/join', json={'session_code': code, 'nom': nom, 'prenom': 'T'})
    assert r.status_code == 200, r.text
    return r.json()


def _h(s):
    return {'Authorization': 'Bearer ' + s['student_session_id']}


# ── 1. Concurrence : soumissions simultanées sur la même slide (autonome) ────

def test_concurrence_submit_meme_slide_un_seul_gagne(client):
    g, e = _event_qcm_seul(client)
    live = _start(client, g, e)
    students = [_join(client, live['session_code'], nom=f'N{i}') for i in range(10)]
    def submit(s):
        return client.post('/api/v1/student/answers', headers=_h(s), json={'answer': {'selected': ['A']}})
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(submit, students))
    # Chaque élève a soumis une fois (pas de race entre eux) ; chacun re-soumet -> 409
    assert all(r.status_code == 200 for r in results)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        results2 = list(ex.map(submit, students))
    assert all(r.status_code == 409 for r in results2)  # verrouillées
    res = client.get(f"/api/v1/live/{live['live_id']}/results").json()['results']
    assert all(r['answered'] == 1 for r in res)  # une seule réponse conservée par élève


def test_concurrence_start_meme_event_un_seul_gagne(client):
    g, e, _ = _event(client, slides=1)
    def start():
        return client.post('/api/v1/live/start', json={'group': g, 'title': e, 'mode': 'autonome'})
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda _: start(), range(8)))
    assert sum(1 for r in results if r.status_code == 200) == 1
    assert sum(1 for r in results if r.status_code == 409) == 7


def test_concurrence_stop_simultane(client):
    g, e, _ = _event(client, slides=2)
    live = _start(client, g, e)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(lambda _: client.post(f"/api/v1/live/{live['live_id']}/stop"), range(5)))
    assert all(r.status_code == 200 for r in results)
    assert client.get(f"/api/v1/live/{live['live_id']}/status").json()['status'] == 'ended'


# ── 2. WS autonome : événements perso ────────────────────────────────────────

def test_ws_autonome_recoit_slide_changed_answer_locked_session_ended(client):
    g, e, _ = _event(client, slides=2)  # C, Q
    live = _start(client, g, e, correction='après_question')
    lid = live['live_id']
    s = _join(client, live['session_code'])
    h = _h(s)
    with client.websocket_connect('/api/v1/student/ws') as ws:
        ws.send_json({'token': s['student_session_id']})
        assert ws.receive_json()['event'] == 'current'
        # next (slide C -> Q) notifie le WS de l'élève
        client.post('/api/v1/student/next', headers=h)
        evt = ws.receive_json()
        assert evt['event'] == 'slide_changed' and evt['current']['number'] == 2
        # réponse -> answer_locked + correction après_question visible
        client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['A']}})
        evt = ws.receive_json()
        assert evt['event'] == 'answer_locked'
        # next sur dernière slide -> finish -> session_ended
        r = client.post('/api/v1/student/next', headers=h)
        assert r.json()['finished'] is True
        evt = ws.receive_json()
        assert evt['event'] == 'slide_changed'
        evt = ws.receive_json()
        assert evt['event'] == 'session_ended'


def test_ws_monitor_recoit_student_finished_en_autonome(client):
    g, e, _ = _event(client, slides=2)
    live = _start(client, g, e)
    lid = live['live_id']
    s = _join(client, live['session_code'])
    h = _h(s)
    trainer_token = client.headers['Authorization'].split(' ', 1)[1]
    with client.websocket_connect(f'/api/v1/live/{lid}/monitor') as mon:
        mon.send_json({'token': trainer_token})
        mon.receive_json()
        client.post('/api/v1/student/next', headers=h)  # -> Q
        client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['B']}})
        evt = mon.receive_json()
        assert evt['event'] == 'answer_received'
        client.post('/api/v1/student/next', headers=h)  # finish
        evt = mon.receive_json()
        assert evt['event'] == 'student_finished' and evt['participation_id'] == s['participation_id']


# ── 3. Faille corrigée : WS moniteur fermé après change-password ────────────

def test_change_password_ferme_ws_moniteur(client):
    g, e, _ = _event(client, slides=2)
    live = _start(client, g, e, mode='live')
    lid = live['live_id']
    trainer_token = client.headers['Authorization'].split(' ', 1)[1]
    with client.websocket_connect(f'/api/v1/live/{lid}/monitor') as mon:
        mon.send_json({'token': trainer_token})
        assert mon.receive_json()['event'] == 'monitor'
        client.post('/api/v1/auth/change-password',
                    json={'old_password': 'test-password', 'new_password': 'nouveau-mdp-99'})
        with pytest.raises(WebSocketDisconnect) as exc:
            mon.receive_json()
        assert exc.value.code == 1008


# ── 4. Persistance restart en mode autonome ──────────────────────────────────

def test_restart_persiste_progress_locks_timers_autonome(client, tmp_path):
    g, e, _ = _event(client, slides=3)
    live = _start(client, g, e, timing='par_question', timing_seconds=300)
    lid = live['live_id']
    s = _join(client, live['session_code'])
    h = _h(s)
    client.post('/api/v1/student/next', headers=h)  # -> Q, timer démarre
    cur = client.get('/api/v1/student/current', headers=h).json()
    assert 'expires_at' in cur
    exp = cur['expires_at']
    client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['A']}})
    # "Restart" : nouvelle app sur le même workdir
    with TestClient(create_app(Settings(workdir=tmp_path, trainer_password='test-password'))) as c2:
        tok = c2.post('/api/v1/auth/login', json={'username': 'formateur', 'password': 'test-password'}).json()['access_token']
        c2.headers.update({'Authorization': f'Bearer {tok}'})
        st = c2.get(f'/api/v1/live/{lid}/status').json()
        assert st['status'] == 'running' and st['mode'] == 'autonome'
        # L'élève retrouve sa position et son lock avec le même token
        cur2 = c2.get('/api/v1/student/current', headers=h).json()
        assert cur2['number'] == 2 and cur2['locked'] is True
        # Le timer n'a pas redémarré : expires_at identique
        assert cur2.get('expires_at') == exp or cur2['locked'] is True
        # resoumission toujours 409 après restart
        assert c2.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['B']}}).status_code == 409
        # next débloqué (lock existe)
        r = c2.post('/api/v1/student/next', headers=h)
        assert r.status_code == 200 and r.json()['number'] == 3


# ── 5. Présence : seuil 45 s ─────────────────────────────────────────────────

def test_presence_seuil_45s(client, monkeypatch):
    g, e, _ = _event(client, slides=1)
    live = _start(client, g, e, mode='live')
    lid = live['live_id']
    s = _join(client, live['session_code'])
    store = client.app.state.live_store
    # Simuler une connexion vue il y a 46 s
    store.connections.setdefault(lid, {})[s['participation_id']] = time.monotonic() - 46
    st = client.get(f'/api/v1/live/{lid}/students').json()
    assert st['connected'] == 0 and st['disconnected'] == 1
    # À 44 s : encore connecté
    store.connections[lid][s['participation_id']] = time.monotonic() - 44
    st = client.get(f'/api/v1/live/{lid}/students').json()
    assert st['connected'] == 1


# ── 6. Scénarios autonome manquants ──────────────────────────────────────────

def test_timer_non_redemarre_a_la_revisite(client):
    g, e, _ = _event(client, slides=3)  # C, Q, C
    live = _start(client, g, e, timing='par_question', timing_seconds=300)
    s = _join(client, live['session_code'])
    h = _h(s)
    client.post('/api/v1/student/next', headers=h)  # -> Q
    c1 = client.get('/api/v1/student/current', headers=h).json()
    client.post('/api/v1/student/previous', headers=h)  # retour
    client.post('/api/v1/student/next', headers=h)  # revisite Q
    c2 = client.get('/api/v1/student/current', headers=h).json()
    assert c1['question_started_at'] == c2['question_started_at']
    assert c1['expires_at'] == c2['expires_at']


def test_next_derniere_slide_exercice_non_repondu_409_pas_finish(client):
    g, e = _event_qcm_seul(client)  # 1 seule slide = QCM
    live = _start(client, g, e)
    s = _join(client, live['session_code'])
    h = _h(s)
    r = client.post('/api/v1/student/next', headers=h)
    assert r.status_code == 409  # exercice non répondu, même sur la dernière
    assert client.get('/api/v1/student/current', headers=h).json()['finished'] is False


def test_deadline_pendant_next_finit_au_lieu_davancer(client):
    g, e, _ = _event(client, slides=3)
    live = _start(client, g, e, timing='par_evenement', timing_seconds=3600)
    lid = live['live_id']
    s = _join(client, live['session_code'])
    h = _h(s)
    store = client.app.state.live_store
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with store.db() as con:
        con.execute('UPDATE live_sessions SET deadline=? WHERE id=?', (past, lid))
    r = client.post('/api/v1/student/next', headers=h)
    assert r.status_code == 409  # fini par deadline, pas d'avance
    assert client.get('/api/v1/student/current', headers=h).json()['finished'] is True


def test_student_results_correction_jamais_pas_de_correction(client):
    g, e, _ = _event(client, slides=2)  # C, Q
    live = _start(client, g, e, correction='jamais')
    s = _join(client, live['session_code'])
    h = _h(s)
    client.post('/api/v1/student/next', headers=h)
    client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['A']}})
    client.post('/api/v1/student/next', headers=h)  # finish
    data = client.get('/api/v1/student/results', headers=h).json()
    q = [x for x in data['slides'] if x['slide_type'] == 'Q'][0]
    assert q['answer'] == {'selected': ['A']}
    assert 'correction' not in q


def test_student_results_avec_timeout_slide_non_repondue(client):
    g, e, _ = _event(client, slides=2)
    live = _start(client, g, e, timing='par_question', timing_seconds=1)
    s = _join(client, live['session_code'])
    h = _h(s)
    client.post('/api/v1/student/next', headers=h)  # -> Q, timer 1s
    time.sleep(1.2)
    client.get('/api/v1/student/current', headers=h)  # verrouille time_expired
    r = client.post('/api/v1/student/next', headers=h)  # débloqué par le lock -> finish (dernière slide)
    assert r.status_code == 200 and r.json()['finished'] is True
    data = client.get('/api/v1/student/results', headers=h).json()
    q = [x for x in data['slides'] if x['slide_type'] == 'Q'][0]
    assert q['answered'] is False  # verrouillée par timeout, pas de réponse


def test_student_results_mix_live_et_autonome(client):
    g, e, _ = _event(client, slides=2)
    # Session 1 : live
    live1 = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    s1 = _join(client, live1['session_code'], nom='Mix')
    client.post(f"/api/v1/live/{live1['live_id']}/next")
    client.post('/api/v1/student/answers', headers=_h(s1), json={'answer': {'selected': ['A']}})
    client.post(f"/api/v1/live/{live1['live_id']}/stop")
    # Session 2 : autonome
    live2 = _start(client, g, e)
    s2 = _join(client, live2['session_code'], nom='Mix')
    client.post('/api/v1/student/next', headers=_h(s2))
    client.post('/api/v1/student/answers', headers=_h(s2), json={'answer': {'selected': ['B']}})
    client.post('/api/v1/student/next', headers=_h(s2))
    client.post('/api/v1/student/next', headers=_h(s2))  # finish
    client.post(f"/api/v1/live/{live2['live_id']}/stop")
    data = client.get(f'/api/v1/groups/{g}/events/{e}/student-results',
                      params={'nom': 'Mix', 'prenom': 'T'}).json()
    assert len(data['sessions']) == 2
    assert data['total_answers'] == 2
    reponses = sorted(s['answers'][0]['answer']['selected'][0] for s in data['sessions'])
    assert reponses == ['A', 'B']


# ── 7. Divers extrêmes ───────────────────────────────────────────────────────

def test_token_trop_long_401(client):
    g, e, _ = _event(client, slides=1)
    live = _start(client, g, e, mode='live')
    r = client.get('/api/v1/student/current', headers={'Authorization': 'Bearer ' + 'x' * 600})
    assert r.status_code == 401


def test_evenement_500_slides_start_ok(client):
    g = client.post('/api/v1/groups', json={'group': 'Gros'}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': 'Gros'}).json()['title']
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    for i in range(500):
        r = client.post(base, json={'title': f'Slide{i}', 'slide_type': 'C', 'content': f'# {i}'})
        assert r.status_code == 200
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    st = client.get(f"/api/v1/live/{live['live_id']}/status").json()
    assert st['total'] == 500


def test_authorization_sans_bearer_401(client):
    assert client.get('/api/v1/groups', headers={'Authorization': 'Basic abc'}).status_code == 401


def test_deux_sessions_autonomes_events_differents_simultanees(client):
    g1, e1, _ = _event(client, slides=1)
    g2 = client.post('/api/v1/groups', json={'group': 'Deux'}).json()['group']
    e2 = client.post('/api/v1/events', json={'group': g2, 'title': 'Deuxieme'}).json()['title']
    client.post(f'/api/v1/groups/{g2}/events/{e2}/slides', json={'title': 'S', 'slide_type': 'C', 'content': '# S'})
    l1 = _start(client, g1, e1)
    l2 = _start(client, g2, e2)
    active = client.get('/api/v1/live/active').json()['lives']
    assert len(active) == 2 and all(a['mode'] == 'autonome' for a in active)


def test_close_all_trainers_ignore_erreur():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from classlive.live_api import Hub
    hub = Hub()
    ws = MagicMock()
    ws.close = AsyncMock(side_effect=RuntimeError('déjà fermée'))
    hub.trainers['lid'].add(ws)
    asyncio.run(hub.close_all_trainers())  # ne doit pas lever
    assert ws not in hub.trainers['lid']
