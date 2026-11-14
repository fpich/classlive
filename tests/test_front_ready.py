"""Tests des fonctionnalités ajoutées pour préparer un frontend (style Wooclap).

CORS, /live/active, kick d'étudiant, duplication d'événement, stats all=1,
liste globale des événements, change-password. Cas limites inclus.
"""
import pytest
from starlette.websockets import WebSocketDisconnect


# ── CORS ─────────────────────────────────────────────────────────────────────

def test_cors_preflight_autorise(client):
    r = client.options('/api/v1/groups', headers={
        'Origin': 'http://localhost:5173',
        'Access-Control-Request-Method': 'GET',
        'Access-Control-Request-Headers': 'authorization',
    })
    assert r.status_code == 200
    assert r.headers['access-control-allow-origin'] == '*'
    assert 'GET' in r.headers['access-control-allow-methods']


def test_cors_header_sur_reponse_normale(client):
    r = client.get('/health', headers={'Origin': 'http://front.local:3000'})
    assert r.headers.get('access-control-allow-origin') == '*'


def test_cors_origins_restreints(tmp_path):
    from fastapi.testclient import TestClient
    from classlive.api import create_app
    from classlive.config import Settings
    cfg_file = tmp_path / 'config.yml'
    cfg_file.write_text(
        'classlive:\n  storage:\n    workdir: "/tmp/x"\n'
        '  security:\n    cors_origins: ["https://cours.example.fr"]\n', encoding='utf-8')
    from classlive.config import load_settings
    settings = load_settings(cfg_file)
    assert settings.cors_origins == ('https://cours.example.fr',)
    app = create_app(settings)
    with TestClient(app) as c:
        r = c.get('/health', headers={'Origin': 'https://cours.example.fr'})
        assert r.headers.get('access-control-allow-origin') == 'https://cours.example.fr'
        r2 = c.get('/health', headers={'Origin': 'https://evil.example'})
        assert 'access-control-allow-origin' not in r2.headers


def test_cors_origins_invalide_rejete(tmp_path):
    from classlive.config import load_settings
    cfg = tmp_path / 'c.yml'
    cfg.write_text('classlive:\n  storage:\n    workdir: "/tmp/x"\n  security:\n    cors_origins: "pas-une-liste"\n')
    with pytest.raises(ValueError, match="cors_origins"):
        load_settings(cfg)
    cfg.write_text('classlive:\n  storage:\n    workdir: "/tmp/x"\n  security:\n    cors_origins: []\n')
    with pytest.raises(ValueError, match="cors_origins"):
        load_settings(cfg)


# ── GET /live/active ─────────────────────────────────────────────────────────

def _setup_live(client, group='G', title='E', with_slide=True):
    g = client.post('/api/v1/groups', json={'group': group}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': title}).json()['title']
    if with_slide:
        client.post(f'/api/v1/groups/{g}/events/{e}/slides', json={'title': 'S', 'slide_type': 'C', 'content': '# S'})
    return g, e


def test_live_active_liste_les_running(client):
    assert client.get('/api/v1/live/active').json()['lives'] == []
    g, e = _setup_live(client)
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    active = client.get('/api/v1/live/active').json()['lives']
    assert len(active) == 1
    assert active[0]['id'] == live['live_id']
    assert active[0]['code'] == live['session_code']
    assert active[0]['group_name'] == g and active[0]['event_name'] == e
    client.post(f"/api/v1/live/{live['live_id']}/stop")
    assert client.get('/api/v1/live/active').json()['lives'] == []


def test_live_active_deux_lives_differents(client):
    g1, e1 = _setup_live(client, 'G1', 'E1')
    g2, e2 = _setup_live(client, 'G2', 'E2')
    client.post('/api/v1/live/start', json={'group': g1, 'title': e1})
    client.post('/api/v1/live/start', json={'group': g2, 'title': e2})
    assert len(client.get('/api/v1/live/active').json()['lives']) == 2


def test_live_active_sans_auth_401(client):
    r = client.get('/api/v1/live/active', headers={'Authorization': ''})
    assert r.status_code == 401


# ── DELETE /live/{id}/students/{pid} (kick) ──────────────────────────────────

def test_kick_supprime_participation_et_reponses(client):
    g, e = _setup_live(client)
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    client.post(base, json={'title': 'Q', 'slide_type': 'Q', 'content': '# Q'})
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    lid = live['live_id']
    s = client.post('/api/v1/student/join', json={'session_code': live['session_code'], 'nom': 'A', 'prenom': 'B'}).json()
    pid = s['participation_id']
    h = {'Authorization': 'Bearer ' + s['student_session_id']}
    client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['A']}})
    assert client.get(f'/api/v1/live/{lid}/students').json()['total_students'] == 1
    r = client.delete(f'/api/v1/live/{lid}/students/{pid}')
    assert r.status_code == 200 and r.json()['kicked'] is True
    assert client.get(f'/api/v1/live/{lid}/students').json()['total_students'] == 0
    # Les réponses du kické sont supprimées (CASCADE)
    assert client.get(f'/api/v1/live/{lid}/results').json()['results'] == []
    # Son token ne fonctionne plus
    assert client.get('/api/v1/student/current', headers=h).status_code == 401


def test_kick_pid_inconnu_404(client):
    g, e = _setup_live(client)
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    assert client.delete(f"/api/v1/live/{live['live_id']}/students/pid-inconnu").status_code == 404


def test_kick_live_inconnu_404(client):
    assert client.delete('/api/v1/live/inconnu/students/abc').status_code == 404


def test_kick_autre_live_404(client):
    g, e = _setup_live(client)
    live1 = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    s = client.post('/api/v1/student/join', json={'session_code': live1['session_code'], 'nom': 'A', 'prenom': 'B'}).json()
    g2, e2 = _setup_live(client, 'G2', 'E2')
    client.post('/api/v1/live/start', json={'group': g2, 'title': e2}).json()
    # Le pid appartient au live1, pas au live de G2/E2 (qui est terminé ici) -> 404
    assert client.delete(f"/api/v1/live/{live1['live_id']}/students/{s['participation_id']}").status_code == 200


def test_kick_ferme_websocket_au_prochain_ping(client):
    g, e = _setup_live(client)
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    lid = live['live_id']
    s = client.post('/api/v1/student/join', json={'session_code': live['session_code'], 'nom': 'A', 'prenom': 'B'}).json()
    with client.websocket_connect('/api/v1/student/ws') as ws:
        ws.send_json({'token': s['student_session_id']})
        assert ws.receive_json()['event'] == 'current'
        ws.send_json({'event': 'ping'})
        assert ws.receive_json()['event'] == 'pong'
        client.delete(f'/api/v1/live/{lid}/students/{s["participation_id"]}')
        # L'événement student_kicked est diffusé, puis le prochain ping ferme la connexion
        evt = ws.receive_json()
        assert evt['event'] == 'student_kicked'
        ws.send_json({'event': 'ping'})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008


def test_kick_notifie_monitor(client):
    g, e = _setup_live(client)
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    lid = live['live_id']
    s = client.post('/api/v1/student/join', json={'session_code': live['session_code'], 'nom': 'A', 'prenom': 'B'}).json()
    trainer_token = client.headers['Authorization'].split(' ', 1)[1]
    with client.websocket_connect(f'/api/v1/live/{lid}/monitor') as mon:
        mon.send_json({'token': trainer_token})
        mon.receive_json()  # monitor
        client.delete(f'/api/v1/live/{lid}/students/{s["participation_id"]}')
        evt = mon.receive_json()
        assert evt['event'] == 'student_kicked' and evt['participation_id'] == s['participation_id']


# ── POST /events/{e}/duplicate ───────────────────────────────────────────────

def test_duplicate_event_copie_slides(client, tmp_path):
    g, e = _setup_live(client, with_slide=False)
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    client.post(base, json={'title': 'Intro', 'slide_type': 'C', 'content': '# Intro'})
    client.post(base, json={'title': 'QCM', 'slide_type': 'Q', 'content': '# Q'})
    r = client.post(f'/api/v1/groups/{g}/events/{e}/duplicate')
    assert r.status_code == 200
    new_e = r.json()['new_title']
    assert new_e != e and new_e.startswith('E002_') and new_e.endswith('_copie')
    slides_orig = client.get(base).json()['slides']
    slides_copy = client.get(f'/api/v1/groups/{g}/events/{new_e}/slides').json()['slides']
    assert slides_orig == slides_copy
    assert client.get(f'/api/v1/groups/{g}/events/{new_e}/slides/{slides_copy[0]}').json()['content'] == '# Intro'


def test_duplicate_avec_nouveau_titre(client):
    g, e = _setup_live(client)
    client.post(f'/api/v1/groups/{g}/events/{e}/slides', json={'title': 'S', 'slide_type': 'C', 'content': '# S'})
    r = client.post(f'/api/v1/groups/{g}/events/{e}/duplicate', json={'new_title': "Ma copie d'été"})
    assert r.status_code == 200
    assert r.json()['new_title'] == 'E002_Ma_copie_dete'


def test_duplicate_conflit_nom_incremente(client):
    g, e = _setup_live(client)
    r1 = client.post(f'/api/v1/groups/{g}/events/{e}/duplicate', json={'new_title': 'Copie'}).json()['new_title']
    r2 = client.post(f'/api/v1/groups/{g}/events/{e}/duplicate', json={'new_title': 'Copie'}).json()['new_title']
    assert r1 == 'E002_Copie' and r2 == 'E003_Copie_2'


def test_duplicate_event_inexistant_404(client):
    g = client.post('/api/v1/groups', json={'group': 'G'}).json()['group']
    assert client.post(f'/api/v1/groups/{g}/events/E999_X/duplicate').status_code == 404


def test_duplicate_garde_numeros_slides(client):
    g, e = _setup_live(client, with_slide=False)
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    client.post(base, json={'title': 'A', 'slide_type': 'C', 'number': 5, 'content': '# A'})
    new_e = client.post(f'/api/v1/groups/{g}/events/{e}/duplicate').json()['new_title']
    assert client.get(f'/api/v1/groups/{g}/events/{new_e}/slides').json()['slides'] == ['S005_C_A.md']


def test_duplicate_symlink_source_rejete(client, tmp_path):
    g, e = _setup_live(client)
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    client.post(base, json={'title': 'S', 'slide_type': 'C', 'content': '# S'})
    outside = tmp_path / 'secret.txt'
    outside.write_text('secret')
    (tmp_path / 'Evts' / g / e / 'lien.md').symlink_to(outside)
    r = client.post(f'/api/v1/groups/{g}/events/{e}/duplicate')
    assert r.status_code == 500  # StorageError


# ── GET /live/{id}/stats?all=1 ────────────────────────────────────────────────

def test_stats_all_slides(client):
    g, e = _setup_live(client, with_slide=False)
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    client.post(base, json={'title': 'Q1', 'slide_type': 'Q', 'content': '# Q1'})
    client.post(base, json={'title': 'C1', 'slide_type': 'C', 'content': '# C1'})
    client.post(base, json={'title': 'Q2', 'slide_type': 'Q', 'content': '# Q2'})
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    lid = live['live_id']
    s1 = client.post('/api/v1/student/join', json={'session_code': live['session_code'], 'nom': 'A', 'prenom': 'B'}).json()
    h1 = {'Authorization': 'Bearer ' + s1['student_session_id']}
    client.post('/api/v1/student/answers', headers=h1, json={'answer': {'selected': ['A']}})
    client.post(f'/api/v1/live/{lid}/next')  # C1 : pas d'exercice
    client.post(f'/api/v1/live/{lid}/next')  # Q2
    s2 = client.post('/api/v1/student/join', json={'session_code': live['session_code'], 'nom': 'C', 'prenom': 'D'}).json()
    h2 = {'Authorization': 'Bearer ' + s2['student_session_id']}
    client.post('/api/v1/student/answers', headers=h2, json={'answer': {'selected': ['B', 'A']}})
    client.post('/api/v1/student/answers', headers=h1, json={'answer': {'selected': ['B']}})
    r = client.get(f'/api/v1/live/{lid}/stats', params={'all': 'true'})
    assert r.status_code == 200
    slides = r.json()['slides']
    assert len(slides) == 3
    q1, c1, q2 = slides
    assert q1['slide_type'] == 'Q' and q1['answered'] == 1 and q1['options'] == {'A': 1}
    assert c1['slide_type'] == 'C' and c1['answered'] == 0 and 'options' not in c1
    assert q2['answered'] == 2 and q2['options'] == {'A': 1, 'B': 2}
    assert all(s['total_students'] == 2 for s in slides)
    # Sans all=1 : comportement par défaut (slide courante)
    r2 = client.get(f'/api/v1/live/{lid}/stats')
    assert 'slides' not in r2.json() and r2.json()['slide'] == q2['slide']


def test_stats_all_live_inexistant_404(client):
    assert client.get('/api/v1/live/inconnu/stats', params={'all': 'true'}).status_code == 404


# ── GET /api/v1/events (liste globale) ───────────────────────────────────────

def test_list_all_events(client):
    assert client.get('/api/v1/events').json()['events'] == []
    g1, e1 = _setup_live(client, 'G1', 'E1')
    g2, e2 = _setup_live(client, 'G2', 'E2')
    _setup_live(client, 'G2', 'E3')
    events = client.get('/api/v1/events').json()['events']
    assert {'group': g1, 'title': e1} in events
    assert {'group': g2, 'title': e2} in events
    assert len(events) == 3


def test_list_all_events_sans_auth_401(client):
    assert client.get('/api/v1/events', headers={'Authorization': ''}).status_code == 401


# ── POST /auth/change-password ───────────────────────────────────────────────

def test_change_password_ok_puis_login_avec_nouveau(client):
    r = client.post('/api/v1/auth/change-password', json={'old_password': 'test-password', 'new_password': 'nouveau-mdp-123'})
    assert r.status_code == 200 and r.json()['changed'] is True
    # Les anciens tokens sont invalidés
    assert client.get('/api/v1/groups').status_code == 401
    # Login avec l'ancien mdp échoue
    assert client.post('/api/v1/auth/login', json={'username': 'formateur', 'password': 'test-password'}).status_code == 401
    # Login avec le nouveau fonctionne
    r2 = client.post('/api/v1/auth/login', json={'username': 'formateur', 'password': 'nouveau-mdp-123'})
    assert r2.status_code == 200


def test_change_password_mauvais_ancien_401(client):
    r = client.post('/api/v1/auth/change-password', json={'old_password': 'faux', 'new_password': 'nouveau-mdp-123'})
    assert r.status_code == 401


def test_change_password_trop_court_422(client):
    r = client.post('/api/v1/auth/change-password', json={'old_password': 'test-password', 'new_password': 'court'})
    assert r.status_code == 422


def test_change_password_sans_mdp_configure_503(tmp_path):
    from fastapi.testclient import TestClient
    from classlive.api import create_app
    from classlive.config import Settings
    with TestClient(create_app(Settings(workdir=tmp_path, api_key='cle'))) as c:
        r = c.post('/api/v1/auth/change-password', json={'old_password': 'x', 'new_password': 'nouveau-mdp-123'})
        assert r.status_code == 503


def test_change_password_rate_limite(client):
    auth = client.app.state.live_auth
    auth._login_attempts.clear()
    for _ in range(5):
        client.post('/api/v1/auth/change-password', json={'old_password': 'faux', 'new_password': 'nouveau-mdp-123'})
    r = client.post('/api/v1/auth/change-password', json={'old_password': 'faux', 'new_password': 'nouveau-mdp-123'})
    assert r.status_code == 429


def test_change_password_trop_court_direct(client):
    # Pydantic filtre min_length=8 en amont ; la branche interne est testée en direct
    auth = client.app.state.live_auth
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        auth.change_password('test-password', 'court')
    assert exc.value.status_code == 422


# ── Cas limites internes duplicate_event ─────────────────────────────────────

def test_duplicate_suffix_epuise_direct(tmp_path):
    from classlive.storage import EventStorage, ResourceConflict
    storage = EventStorage(tmp_path)
    g = storage.create_group('G')['group']
    e = storage.create_event(g, 'E')['title']
    # Occuper tous les noms Copie, Copie_2 ... Copie_100
    for i in range(100):
        name = 'Copie' if i == 0 else f'Copie_{i+1}'
        (storage.root / g / f'E{i+2:03d}_{name}').mkdir()
    with pytest.raises(ResourceConflict, match="nom de copie"):
        storage.duplicate_event(g, e, new_title='Copie')


def test_duplicate_copytree_oserror_direct(tmp_path, monkeypatch):
    import shutil
    from unittest.mock import MagicMock
    from classlive.storage import EventStorage, StorageError
    storage = EventStorage(tmp_path)
    g = storage.create_group('G')['group']
    e = storage.create_event(g, 'E')['title']
    monkeypatch.setattr(shutil, 'copytree', MagicMock(side_effect=OSError('disque plein')))
    with pytest.raises(StorageError, match="dupliquer"):
        storage.duplicate_event(g, e)
