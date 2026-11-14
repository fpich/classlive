"""Scénarios extrêmes et cas limites supplémentaires (revue de cohérence).

CSV avec caractères spéciaux, champs aux limites exactes, Unicode/emoji,
concurrence de stop, WS double connexion, navigation après renommage,
frontmatter limite, etc.
"""
import csv
import io
import json

import pytest
from starlette.websockets import WebSocketDisconnect


def _groupe_event(client, group='G', title='E'):
    g = client.post('/api/v1/groups', json={'group': group}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': title}).json()['title']
    return g, e


def _live_avec_qcm(client, g, e):
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    client.post(base, json={'title': 'Q', 'slide_type': 'Q', 'content': '# Q\n- A\n- B'})
    return client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()


# ── CSV : caractères spéciaux, échappement ───────────────────────────────────

def test_csv_echappement_pointvirgule_guillemets_emoji(client):
    g, e = _groupe_event(client)
    live = _live_avec_qcm(client, g, e)
    s = client.post('/api/v1/student/join', json={
        'session_code': live['session_code'], 'nom': 'Dupon;t', 'prenom': 'Mar"ie🎉'}).json()
    h = {'Authorization': 'Bearer ' + s['student_session_id']}
    reponse = {'selected': ['A;B', 'C"D', 'x\ny', '🎯']}
    assert client.post('/api/v1/student/answers', headers=h, json={'answer': reponse}).status_code == 200
    client.post(f"/api/v1/live/{live['live_id']}/stop")
    r = client.get(f'/api/v1/live/{live["live_id"]}/export.csv')
    assert r.status_code == 200
    assert r.content.startswith(b'\xef\xbb\xbf')  # BOM UTF-8
    rows = list(csv.DictReader(io.StringIO(r.content.decode('utf-8-sig')), delimiter=';'))
    assert len(rows) == 1
    assert rows[0]['nom'] == 'Dupon;t'
    assert rows[0]['prenom'] == 'Mar"ie🎉'
    assert json.loads(rows[0]['reponse_json']) == reponse


def test_join_nom_avec_newline_rejete_422(client):
    g, e = _groupe_event(client)
    live = _live_avec_qcm(client, g, e)
    r = client.post('/api/v1/student/join', json={
        'session_code': live['session_code'], 'nom': 'A', 'prenom': 'Mar\nie'})
    assert r.status_code == 422


def test_csv_evenement_sans_sessions_juste_entete(client):
    g, e = _groupe_event(client)
    r = client.get(f'/api/v1/groups/{g}/events/{e}/export.csv')
    assert r.status_code == 200
    text = r.content.decode('utf-8-sig')
    assert text.strip() == 'live_id;nom;prenom;date_session;slide;reponse_json;date_reponse'


# ── Stats : options exotiques ────────────────────────────────────────────────

def test_stats_options_avec_emoji_et_texte_long(client):
    g, e = _groupe_event(client)
    live = _live_avec_qcm(client, g, e)
    lid = live['live_id']
    opts = ['🎉', 'A' * 500, 'opt;with;semicolons', '']
    for i, opt in enumerate(opts):
        s = client.post('/api/v1/student/join', json={
            'session_code': live['session_code'], 'nom': f'N{i}', 'prenom': 'P'}).json()
        h = {'Authorization': 'Bearer ' + s['student_session_id']}
        client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': [opt]}})
    st = client.get(f'/api/v1/live/{lid}/stats').json()
    assert st['answered'] == 4
    assert st['options']['🎉'] == 1
    assert st['options']['A' * 500] == 1
    assert st['options']['opt;with;semicolons'] == 1
    assert st['options'][''] == 1


# ── Champs aux limites exactes ───────────────────────────────────────────────

def test_group_limite_brute_150_mais_normalise_120(client):
    # Champ accepte 150, mais la normalisation impose 120 max -> 120 OK, 121 rejeté
    r = client.post('/api/v1/groups', json={'group': 'A' * 120})
    assert r.status_code == 200
    r2 = client.post('/api/v1/groups', json={'group': 'B' * 121})
    assert r2.status_code == 422
    # 150 caractères brut mais normalisés à 1 -> accepté (limite brute 150 respectée)
    r3 = client.post('/api/v1/groups', json={'group': 'a' + ' ' * 149})
    assert r3.status_code == 200
    assert r3.json()['group'].endswith('_a')
    # 151 brut -> rejeté même si normalisé serait court
    r4 = client.post('/api/v1/groups', json={'group': 'a' + ' ' * 150})
    assert r4.status_code == 422


def test_nom_normalise_trop_long_rejete(client):
    # 130 caractères alphabétiques -> normalisé > 120 -> 422
    r = client.post('/api/v1/groups', json={'group': 'x' * 130})
    assert r.status_code == 422


def test_nom_etudiant_100_ok_101_rejete(client):
    g, e = _groupe_event(client)
    live = _live_avec_qcm(client, g, e)
    r = client.post('/api/v1/student/join', json={
        'session_code': live['session_code'], 'nom': 'N' * 100, 'prenom': 'P' * 100})
    assert r.status_code == 200
    r2 = client.post('/api/v1/student/join', json={
        'session_code': live['session_code'], 'nom': 'N' * 101, 'prenom': 'P'})
    assert r2.status_code == 422


def test_nom_groupe_emoji_rejete(client):
    assert client.post('/api/v1/groups', json={'group': '🎉🎉'}).status_code == 422


def test_nom_groupe_unicode_normalise(client):
    r = client.post('/api/v1/groups', json={'group': 'Cœur œuvre ß'})
    assert r.status_code == 200
    assert r.json()['group'] == 'G001_Coeur_oeuvre_ss'


# ── Comportements live ───────────────────────────────────────────────────────

def test_join_code_live_termine_404(client):
    g, e = _groupe_event(client)
    live = _live_avec_qcm(client, g, e)
    code = live['session_code']
    client.post(f"/api/v1/live/{live['live_id']}/stop")
    r = client.post('/api/v1/student/join', json={'session_code': code, 'nom': 'A', 'prenom': 'B'})
    assert r.status_code == 404


def test_stop_deux_fois_idempotent(client):
    g, e = _groupe_event(client)
    live = _live_avec_qcm(client, g, e)
    lid = live['live_id']
    assert client.post(f'/api/v1/live/{lid}/stop').status_code == 200
    r = client.post(f'/api/v1/live/{lid}/stop')
    assert r.status_code == 200 and r.json()['status'] == 'ended'


def test_stats_sur_live_termine(client):
    g, e = _groupe_event(client)
    live = _live_avec_qcm(client, g, e)
    lid = live['live_id']
    s = client.post('/api/v1/student/join', json={
        'session_code': live['session_code'], 'nom': 'A', 'prenom': 'B'}).json()
    h = {'Authorization': 'Bearer ' + s['student_session_id']}
    client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['A']}})
    client.post(f'/api/v1/live/{lid}/stop')
    st = client.get(f'/api/v1/live/{lid}/stats').json()
    assert st['answered'] == 1 and st['options'] == {'A': 1}


def test_goto_zero_422(client):
    g, e = _groupe_event(client)
    live = _live_avec_qcm(client, g, e)
    assert client.post(f"/api/v1/live/{live['live_id']}/goto", json={'number': 0}).status_code == 422


def test_reponse_dict_vide_acceptee(client):
    g, e = _groupe_event(client)
    live = _live_avec_qcm(client, g, e)
    s = client.post('/api/v1/student/join', json={
        'session_code': live['session_code'], 'nom': 'A', 'prenom': 'B'}).json()
    h = {'Authorization': 'Bearer ' + s['student_session_id']}
    r = client.post('/api/v1/student/answers', headers=h, json={'answer': {}})
    assert r.status_code == 200


def test_health_pendant_live_actif(client):
    g, e = _groupe_event(client)
    _live_avec_qcm(client, g, e)
    h = client.get('/health').json()
    assert h['status'] == 'ok' and h['database'] is True


# ── Frontmatter cas limites ──────────────────────────────────────────────────

def test_frontmatter_trois_tirets_au_milieu_est_contenu(client):
    g, e = _groupe_event(client)
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    # "---" pas en première ligne = contenu normal, pas du frontmatter
    r = client.post(base, json={'title': 'Doc', 'slide_type': 'C', 'content': '# Titre\n---\ntexte\n---\nfin'})
    assert r.status_code == 200
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    cur = client.get(f"/api/v1/live/{live['live_id']}/status").json()
    assert '---' in cur['content']


def test_frontmatter_answer_null_correction_show_409(client):
    g, e = _groupe_event(client)
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    client.post(base, json={'title': 'Q', 'slide_type': 'Q',
                            'content': '---\nclasslive_answer: null\n---\n# Q'})
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    r = client.post(f"/api/v1/live/{live['live_id']}/correction/show")
    assert r.status_code == 409  # pas de corrigé défini


# ── WebSocket cas extrêmes ──────────────────────────────────────────────────

def test_deux_connexions_ws_meme_token(client):
    g, e = _groupe_event(client)
    live = _live_avec_qcm(client, g, e)
    lid = live['live_id']
    s = client.post('/api/v1/student/join', json={
        'session_code': live['session_code'], 'nom': 'A', 'prenom': 'B'}).json()
    tok = s['student_session_id']
    with client.websocket_connect('/api/v1/student/ws') as ws1:
        ws1.send_json({'token': tok})
        assert ws1.receive_json()['event'] == 'current'
        with client.websocket_connect('/api/v1/student/ws') as ws2:
            ws2.send_json({'token': tok})
            assert ws2.receive_json()['event'] == 'current'
            client.post(f'/api/v1/live/{lid}/next')
            assert ws1.receive_json()['current']['number'] == 1  # une seule slide, next reste
            assert ws2.receive_json()['current']['number'] == 1


def test_ws_fermeture_propre_sans_ping_notifie_deconnexion(client):
    g, e = _groupe_event(client)
    live = _live_avec_qcm(client, g, e)
    lid = live['live_id']
    s = client.post('/api/v1/student/join', json={
        'session_code': live['session_code'], 'nom': 'A', 'prenom': 'B'}).json()
    trainer_token = client.headers['Authorization'].split(' ', 1)[1]
    with client.websocket_connect(f'/api/v1/live/{lid}/monitor') as mon:
        mon.send_json({'token': trainer_token})
        mon.receive_json()
        with client.websocket_connect('/api/v1/student/ws') as ws:
            ws.send_json({'token': s['student_session_id']})
            ws.receive_json()
            assert mon.receive_json()['event'] == 'student_connected'
        # fermeture du ws étudiant -> student_disconnected
        assert mon.receive_json()['event'] == 'student_disconnected'
    assert client.get(f'/api/v1/live/{lid}/students').json()['connected'] == 0


def test_ws_monitor_ignore_messages_texte(client):
    g, e = _groupe_event(client)
    live = _live_avec_qcm(client, g, e)
    trainer_token = client.headers['Authorization'].split(' ', 1)[1]
    with client.websocket_connect(f"/api/v1/live/{live['live_id']}/monitor") as mon:
        mon.send_json({'token': trainer_token})
        assert mon.receive_json()['event'] == 'monitor'
        mon.send_text('hello')  # ignoré, la connexion reste ouverte
        client.post(f"/api/v1/live/{live['live_id']}/stop")
        evt = mon.receive_json()
        assert evt['event'] == 'live_ended'


# ── Navigation après modifications de structure ──────────────────────────────

def test_nav_apres_rename_event_404(client):
    g, e = _groupe_event(client)
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    client.post(base, json={'title': 'S1', 'slide_type': 'C', 'content': '# 1'})
    sess = client.post('/api/v1/player/select', json={'group': g, 'title': e}).json()['session_id']
    new_e = client.patch(f'/api/v1/groups/{g}/events/{e}', json={'new_name': 'Nouveau'}).json()['new_name']
    assert client.post(f'/api/v1/player/{sess}/next').status_code == 404


def test_nav_apres_suppression_groupe_404(client):
    g, e = _groupe_event(client)
    client.post(f'/api/v1/groups/{g}/events/{e}/slides', json={'title': 'S', 'slide_type': 'C', 'content': '# S'})
    sess = client.post('/api/v1/player/select', json={'group': g, 'title': e}).json()['session_id']
    client.delete(f'/api/v1/groups/{g}')
    assert client.post(f'/api/v1/player/{sess}/next').status_code == 404


# ── Auth cas limites ─────────────────────────────────────────────────────────

def test_login_username_vide_401(client):
    r = client.post('/api/v1/auth/login', json={'username': '', 'password': 'test-password'})
    assert r.status_code == 401


def test_change_password_8_chars_exact_ok(client):
    r = client.post('/api/v1/auth/change-password', json={'old_password': 'test-password', 'new_password': '12345678'})
    assert r.status_code == 200


def test_change_password_ancien_egal_nouveau_ok(client):
    r = client.post('/api/v1/auth/change-password', json={'old_password': 'test-password', 'new_password': 'test-password'})
    assert r.status_code == 200


# ── student-results cas limites ──────────────────────────────────────────────

def test_student_results_sans_sessions(client):
    g, e = _groupe_event(client)
    r = client.get(f'/api/v1/groups/{g}/events/{e}/student-results', params={'nom': 'A', 'prenom': 'B'})
    assert r.status_code == 200
    assert r.json()['sessions'] == [] and r.json()['total_answers'] == 0


def test_student_results_espaces_strip(client):
    g, e = _groupe_event(client)
    live = _live_avec_qcm(client, g, e)
    s = client.post('/api/v1/student/join', json={
        'session_code': live['session_code'], 'nom': 'Dupont', 'prenom': 'Marie'}).json()
    h = {'Authorization': 'Bearer ' + s['student_session_id']}
    client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['A']}})
    client.post(f"/api/v1/live/{live['live_id']}/stop")
    r = client.get(f'/api/v1/groups/{g}/events/{e}/student-results',
                   params={'nom': '  Dupont  ', 'prenom': ' Marie '})
    assert r.status_code == 200
    assert r.json()['total_answers'] == 1


# ── Duplicate avec sous-dossiers ─────────────────────────────────────────────

def test_duplicate_copie_sous_dossiers(client, tmp_path):
    g, e = _groupe_event(client)
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    client.post(base, json={'title': 'S', 'slide_type': 'C', 'content': '# S'})
    sub = tmp_path / 'Evts' / g / e / 'assets'
    sub.mkdir()
    (sub / 'img.png').write_bytes(b'\x89PNG')
    new_e = client.post(f'/api/v1/groups/{g}/events/{e}/duplicate').json()['new_title']
    assert (tmp_path / 'Evts' / g / new_e / 'assets' / 'img.png').read_bytes() == b'\x89PNG'
