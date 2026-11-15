"""Tests du mode session autonome (self-paced) : verrouillage, progression,
timing, corrections, récap final, archivage."""
import json
from datetime import datetime, timezone, timedelta

import pytest


def _event_3_slides(client):
    """C -> Q -> C ; retourne (g, e, base)."""
    g = client.post('/api/v1/groups', json={'group': 'Auto'}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': 'Cours'}).json()['title']
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    client.post(base, json={'title': 'Intro', 'slide_type': 'C', 'content': '# Intro'})
    client.post(base, json={'title': 'QCM', 'slide_type': 'Q',
                            'content': '---\nclasslive_answer:\n  selected: [B]\n---\n# Question?\n- A\n- B'})
    client.post(base, json={'title': 'Fin', 'slide_type': 'C', 'content': '# Fin'})
    return g, e, base


def _start_autonome(client, g, e, **kw):
    payload = {'group': g, 'title': e, 'mode': 'autonome'}
    payload.update(kw)
    r = client.post('/api/v1/live/start', json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _join(client, code, nom='Eleve'):
    r = client.post('/api/v1/student/join', json={'session_code': code, 'nom': nom, 'prenom': 'Test'})
    assert r.status_code == 200, r.text
    return r.json()


def _h(student):
    return {'Authorization': 'Bearer ' + student['student_session_id']}


# ── Démarrage et validation des paramètres ──────────────────────────────────

def test_start_autonome_retourne_config(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e, timing='par_question', timing_seconds=60, correction='après_question')
    assert live['mode'] == 'autonome'
    assert live['timing'] == 'par_question' and live['timing_seconds'] == 60
    assert live['correction_mode'] == 'après_question'
    st = client.get(f"/api/v1/live/{live['live_id']}/status").json()
    assert st['mode'] == 'autonome'


def test_start_mode_invalide_422(client):
    g, e, _ = _event_3_slides(client)
    r = client.post('/api/v1/live/start', json={'group': g, 'title': e, 'mode': 'bancal'})
    assert r.status_code == 422


def test_start_autonome_timing_sans_duree_422(client):
    g, e, _ = _event_3_slides(client)
    r = client.post('/api/v1/live/start', json={'group': g, 'title': e, 'mode': 'autonome', 'timing': 'par_question'})
    assert r.status_code == 422


def test_start_autonome_correction_invalide_422(client):
    g, e, _ = _event_3_slides(client)
    r = client.post('/api/v1/live/start', json={'group': g, 'title': e, 'mode': 'autonome', 'correction': 'tout_de_suite'})
    assert r.status_code == 422


def test_start_live_par_defaut_comportement_identique(client):
    g, e, _ = _event_3_slides(client)
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    assert live['mode'] == 'live'


def test_une_seule_session_active_par_eventement_quelque_soit_le_mode(client):
    g, e, _ = _event_3_slides(client)
    _start_autonome(client, g, e)
    assert client.post('/api/v1/live/start', json={'group': g, 'title': e}).status_code == 409
    assert client.post('/api/v1/live/start', json={'group': g, 'title': e, 'mode': 'autonome'}).status_code == 409


# ── Progression : règle B (next bloqué sur exercice non répondu) ─────────────

def test_next_libre_sur_contenu_bloque_sur_exercice_non_repondu(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e)
    s = _join(client, live['session_code'])
    h = _h(s)
    # Slide 1 = contenu -> next OK
    r = client.post('/api/v1/student/next', headers=h)
    assert r.status_code == 200 and r.json()['number'] == 2
    # Slide 2 = QCM -> next bloqué sans réponse
    r = client.post('/api/v1/student/next', headers=h)
    assert r.status_code == 409 and 'Validez' in r.json()['detail']
    # previous toujours OK (lecture seule)
    r = client.post('/api/v1/student/previous', headers=h)
    assert r.status_code == 200 and r.json()['number'] == 1


def test_apres_reponse_next_debloque_et_verrouille(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e)
    s = _join(client, live['session_code'])
    h = _h(s)
    client.post('/api/v1/student/next', headers=h)  # -> QCM
    r = client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['A']}})
    assert r.status_code == 200 and r.json()['locked'] is True
    # Re-soumettre -> 409 verrouillée
    r2 = client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['B']}})
    assert r2.status_code == 409
    # next maintenant OK
    r3 = client.post('/api/v1/student/next', headers=h)
    assert r3.status_code == 200 and r3.json()['number'] == 3
    # Retour arrière : la réponse reste verrouillée
    client.post('/api/v1/student/previous', headers=h)
    cur = client.get('/api/v1/student/current', headers=h).json()
    assert cur['number'] == 2 and cur['locked'] is True
    assert client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['B']}}).status_code == 409


def test_navigation_eleve_refusee_en_mode_live(client):
    g, e, _ = _event_3_slides(client)
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    s = _join(client, live['session_code'])
    h = _h(s)
    assert client.post('/api/v1/student/next', headers=h).status_code == 409
    assert client.post('/api/v1/student/previous', headers=h).status_code == 409


def test_terminer_la_derniere_slide_finit_la_session(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e)
    s = _join(client, live['session_code'])
    h = _h(s)
    client.post('/api/v1/student/next', headers=h)          # -> Q2 (exercice)
    client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['B']}})
    r = client.post('/api/v1/student/next', headers=h)       # -> slide 3 (fin)
    assert r.status_code == 200 and r.json()['number'] == 3 and r.json()['finished'] is False
    r2 = client.post('/api/v1/student/next', headers=h)      # past last -> finish
    assert r2.status_code == 200 and r2.json()['finished'] is True
    # next après fin -> 409
    assert client.post('/api/v1/student/next', headers=h).status_code == 409


# ── Corrections selon le mode ────────────────────────────────────────────────

def test_correction_apres_question(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e, correction='après_question')
    s = _join(client, live['session_code'])
    h = _h(s)
    client.post('/api/v1/student/next', headers=h)
    cur = client.get('/api/v1/student/current', headers=h).json()
    assert 'correction' not in cur  # pas encore répondu
    client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['A']}})
    cur = client.get('/api/v1/student/current', headers=h).json()
    assert cur['correction'] == {'selected': ['B']}


def test_correction_a_la_fin(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e, correction='à_la_fin')
    s = _join(client, live['session_code'])
    h = _h(s)
    client.post('/api/v1/student/next', headers=h)
    client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['A']}})
    cur = client.get('/api/v1/student/current', headers=h).json()
    assert 'correction' not in cur  # pas encore fini
    client.post('/api/v1/student/next', headers=h)
    r = client.post('/api/v1/student/next', headers=h)  # finish
    assert r.json()['finished'] is True
    client.post('/api/v1/student/previous', headers=h)
    cur = client.get('/api/v1/student/current', headers=h).json()
    assert cur['finished'] is True and cur['correction'] == {'selected': ['B']}


def test_correction_jamais(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e, correction='jamais')
    s = _join(client, live['session_code'])
    h = _h(s)
    client.post('/api/v1/student/next', headers=h)
    client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['A']}})
    client.post('/api/v1/student/next', headers=h)
    client.post('/api/v1/student/next', headers=h)  # finish
    client.post('/api/v1/student/previous', headers=h)
    cur = client.get('/api/v1/student/current', headers=h).json()
    assert 'correction' not in cur


# ── Récap final étudiant ─────────────────────────────────────────────────────

def test_student_results_dispo_apres_fin(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e, correction='à_la_fin')
    s = _join(client, live['session_code'])
    h = _h(s)
    # Avant la fin -> 409
    assert client.get('/api/v1/student/results', headers=h).status_code == 409
    client.post('/api/v1/student/next', headers=h)
    client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['A']}})
    client.post('/api/v1/student/next', headers=h)
    client.post('/api/v1/student/next', headers=h)  # finish
    r = client.get('/api/v1/student/results', headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data['total_slides'] == 3 and data['answered'] == 1 and data['finished_at']
    q = [x for x in data['slides'] if x['slide_type'] == 'Q'][0]
    assert q['answer'] == {'selected': ['A']} and q['correction'] == {'selected': ['B']}
    c = [x for x in data['slides'] if x['slide_type'] == 'C'][0]
    assert c['answered'] is False and 'correction' not in c


def test_student_results_refuse_en_mode_live(client):
    g, e, _ = _event_3_slides(client)
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    s = _join(client, live['session_code'])
    assert client.get('/api/v1/student/results', headers=_h(s)).status_code == 409


# ── Timing ───────────────────────────────────────────────────────────────────

def test_timing_par_question_expiration_verrouille(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e, timing='par_question', timing_seconds=1)
    s = _join(client, live['session_code'])
    h = _h(s)
    client.post('/api/v1/student/next', headers=h)  # -> QCM, timer démarre
    cur = client.get('/api/v1/student/current', headers=h).json()
    assert 'expires_at' in cur and 'question_started_at' in cur
    assert cur['locked'] is False
    import time as _t
    _t.sleep(1.2)
    r = client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['A']}})
    assert r.status_code == 409 and 'Temps écoulé' in r.json()['detail']
    # La slide est verrouillée (vide) -> next débloqué
    cur = client.get('/api/v1/student/current', headers=h).json()
    assert cur['locked'] is True
    r = client.post('/api/v1/student/next', headers=h)
    assert r.status_code == 200 and r.json()['number'] == 3


def test_timing_par_evenement_deadline_finit_tout(client, monkeypatch):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e, timing='par_evenement', timing_seconds=3600)
    lid = live['live_id']
    assert client.get(f'/api/v1/live/{lid}/status').json()['deadline'] is not None
    s = _join(client, live['session_code'])
    h = _h(s)
    # Simuler une deadline passée
    import sqlite3, pathlib
    from classlive.config import Settings
    # modifier la deadline directement en base via le store de l'app
    store = client.app.state.live_store
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with store.db() as con:
        con.execute('UPDATE live_sessions SET deadline=? WHERE id=?', (past, lid))
    cur = client.get('/api/v1/student/current', headers=h).json()
    assert cur['finished'] is True
    assert client.get('/api/v1/student/results', headers=h).status_code == 200
    assert client.post('/api/v1/student/next', headers=h).status_code == 409


# ── Archivage et formateur ───────────────────────────────────────────────────

def test_session_autonome_archivee_comme_live(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e)
    lid = live['live_id']
    s = _join(client, live['session_code'])
    h = _h(s)
    client.post('/api/v1/student/next', headers=h)
    client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['B']}})
    client.post(f'/api/v1/live/{lid}/stop')
    sessions = client.get(f'/api/v1/groups/{g}/events/{e}/sessions').json()['sessions']
    assert len(sessions) == 1 and sessions[0]['status'] == 'ended' and sessions[0]['mode'] == 'autonome'
    results = client.get(f'/api/v1/live/{lid}/results').json()['results']
    assert results[0]['answers'][0]['answer'] == {'selected': ['B']}
    csv_r = client.get(f'/api/v1/live/{lid}/export.csv')
    assert csv_r.status_code == 200 and 'selected' in csv_r.text
    sr = client.get(f'/api/v1/groups/{g}/events/{e}/student-results', params={'nom': 'Eleve', 'prenom': 'Test'}).json()
    assert sr['total_answers'] == 1


def test_stop_verrouille_les_sessions_perso_en_cours(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e)
    lid = live['live_id']
    s = _join(client, live['session_code'])
    h = _h(s)
    client.post(f'/api/v1/live/{lid}/stop')
    # Le token étudiant ne marche plus (session terminée)
    assert client.get('/api/v1/student/current', headers=h).status_code == 401


def test_live_active_indique_le_mode(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e)
    active = client.get('/api/v1/live/active').json()['lives']
    assert active[0]['mode'] == 'autonome'


def test_deux_eleves_positions_independantes(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e)
    s1 = _join(client, live['session_code'], nom='Un')
    s2 = _join(client, live['session_code'], nom='Deux')
    h1, h2 = _h(s1), _h(s2)
    client.post('/api/v1/student/next', headers=h1)
    c1 = client.get('/api/v1/student/current', headers=h1).json()
    c2 = client.get('/api/v1/student/current', headers=h2).json()
    assert c1['number'] == 2 and c2['number'] == 1


# ── Cas limites internes (couverture) ────────────────────────────────────────

def test_start_autonome_timing_invalide_422(client):
    g, e, _ = _event_3_slides(client)
    r = client.post('/api/v1/live/start', json={'group': g, 'title': e, 'mode': 'autonome', 'timing': 'bancal'})
    assert r.status_code == 422


def test_start_autonome_timing_seconds_hors_range_422(client):
    g, e, _ = _event_3_slides(client)
    r = client.post('/api/v1/live/start', json={'group': g, 'title': e, 'mode': 'autonome',
                                                'timing': 'par_question', 'timing_seconds': 90000})
    assert r.status_code == 422


def test_value_error_handler_direct(client):
    import asyncio
    handler = client.app.exception_handlers[ValueError]
    resp = asyncio.run(handler(None, ValueError('boom')))
    assert resp.status_code == 422 and b'boom' in resp.body


def test_stop_autonome_avec_eleve_deja_fini(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e)
    lid = live['live_id']
    s = _join(client, live['session_code'])
    h = _h(s)
    client.post('/api/v1/student/next', headers=h)
    client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['B']}})
    client.post('/api/v1/student/next', headers=h)
    client.post('/api/v1/student/next', headers=h)  # finish
    # stop avec un élève déjà fini -> branche continue
    assert client.post(f'/api/v1/live/{lid}/stop').status_code == 200


def test_ensure_progress_recree_si_supprime(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e)
    s = _join(client, live['session_code'])
    store = client.app.state.live_store
    with store.db() as con:
        con.execute('DELETE FROM autonomous_progress WHERE participation_id=?', (s['participation_id'],))
    cur = client.get('/api/v1/student/current', headers=_h(s)).json()
    assert cur['number'] == 1  # recréé à la première slide


def test_student_state_slide_inexistante_404(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e)
    s = _join(client, live['session_code'])
    store = client.app.state.live_store
    with store.db() as con:
        con.execute('UPDATE autonomous_progress SET current_number=999 WHERE participation_id=?', (s['participation_id'],))
    assert client.get('/api/v1/student/current', headers=_h(s)).status_code == 404


def test_student_move_session_terminee_direct(client):
    from classlive.storage import ResourceConflict
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e)
    s = _join(client, live['session_code'])
    client.post(f"/api/v1/live/{live['live_id']}/stop")
    store = client.app.state.live_store
    with pytest.raises(ResourceConflict, match='terminée'):
        store.student_move({'id': s['participation_id'], 'live_id': live['live_id']}, 'next')


def test_student_move_direction_invalide_direct(client):
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e)
    s = _join(client, live['session_code'])
    store = client.app.state.live_store
    with pytest.raises(ValueError, match='Direction invalide'):
        store.student_move({'id': s['participation_id'], 'live_id': live['live_id']}, 'bidon')


def test_submit_autonome_fini_direct(client):
    from classlive.storage import ResourceConflict
    g, e, _ = _event_3_slides(client)
    live = _start_autonome(client, g, e, timing='par_evenement', timing_seconds=3600)
    s = _join(client, live['session_code'])
    store = client.app.state.live_store
    student = store.authenticate_student(s['student_session_id'])
    # Marquer comme fini directement
    with store.db() as con:
        con.execute('UPDATE autonomous_progress SET finished_at=? WHERE participation_id=?',
                    ('2026-01-01T00:00:00+00:00', s['participation_id']))
    with pytest.raises(ResourceConflict, match='terminée'):
        store.submit(student, {'selected': ['A']})


def test_hub_publish_nettoie_by_pid(client):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from starlette.websockets import WebSocketDisconnect
    from classlive.live_api import Hub
    hub = Hub()
    ws = MagicMock()
    ws.send_json = AsyncMock(side_effect=WebSocketDisconnect(code=1008))
    hub.students['lid'].add(ws)
    hub.by_pid['lid']['pid1'] = ws
    asyncio.run(hub.publish('lid', {'event': 'x'}))
    assert ws not in hub.students['lid']
    assert 'pid1' not in hub.by_pid['lid']


def test_hub_publish_to_student_ferme(client):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from starlette.websockets import WebSocketDisconnect
    from classlive.live_api import Hub
    hub = Hub()
    ws = MagicMock()
    ws.send_json = AsyncMock(side_effect=RuntimeError('fermée'))
    hub.by_pid['lid']['pid1'] = ws
    hub.students['lid'].add(ws)
    asyncio.run(hub.publish_to_student('lid', 'pid1', {'event': 'x'}))
    assert 'pid1' not in hub.by_pid['lid']
    assert ws not in hub.students['lid']
    # Appel sur pid sans ws : no-op
    asyncio.run(hub.publish_to_student('lid', 'inconnu', {'event': 'x'}))
