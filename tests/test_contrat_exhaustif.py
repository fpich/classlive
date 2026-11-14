"""Complément v0.8.4 : contrats de routes, sécurité, erreurs et persistance.

Ces tests n'écrivent que dans tmp_path et n'ouvrent aucun port réseau.
Le test de charge et le redémarrage d'un VRAI serveur sont dans test_reseau_multiclients.py.
"""
import csv
import io
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from classlive.api import create_app
from classlive.config import Settings


# 48 combinaisons HTTP publiques, contractuellement attendues dans OpenAPI.
# Chaque route dispose en plus d'un scénario fonctionnel dans les tests historiques,
# dans les nouveaux tests de ce fichier, ou dans test_reseau_multiclients.py.
PUBLIC_ROUTES = {
    ('POST', '/api/v1/auth/login'),
    ('POST', '/api/v1/auth/change-password'),
    ('POST', '/api/v1/student/join'),
    ('POST', '/api/v1/student/resume'),
    ('GET', '/api/v1/student/current'),
    ('POST', '/api/v1/student/answers'),
    ('POST', '/api/v1/live/start'),
    ('POST', '/api/v1/live/{live_id}/next'),
    ('POST', '/api/v1/live/{live_id}/previous'),
    ('POST', '/api/v1/live/{live_id}/goto'),
    ('GET', '/api/v1/live/{live_id}/status'),
    ('POST', '/api/v1/live/{live_id}/correction/show'),
    ('POST', '/api/v1/live/{live_id}/correction/hide'),
    ('POST', '/api/v1/live/{live_id}/stop'),
    ('GET', '/api/v1/live/{live_id}/students'),
    ('GET', '/api/v1/live/{live_id}/results'),
    ('GET', '/api/v1/live/{live_id}/stats'),
    ('GET', '/api/v1/live/active'),
    ('DELETE', '/api/v1/live/{live_id}/students/{participation_id}'),
    ('GET', '/api/v1/live/{live_id}/export.csv'),
    ('GET', '/api/v1/groups/{group}/events/{event}/sessions'),
    ('DELETE', '/api/v1/groups/{group}/events/{event}/sessions'),
    ('GET', '/api/v1/groups/{group}/events/{event}/export.csv'),
    ('GET', '/api/v1/groups/{group}/events/{event}/student-results'),
    ('DELETE', '/api/v1/live/{live_id}'),
    ('GET', '/api/v1/help'),
    ('GET', '/health'),
    ('POST', '/api/v1/groups'),
    ('GET', '/api/v1/groups'),
    ('GET', '/api/v1/groups/{group}/events'),
    ('POST', '/api/v1/events'),
    ('GET', '/api/v1/events'),
    ('POST', '/api/v1/groups/{group}/events/{event}/duplicate'),
    ('PATCH', '/api/v1/groups/{group}'),
    ('DELETE', '/api/v1/groups/{group}'),
    ('PATCH', '/api/v1/groups/{group}/events/{title}'),
    ('DELETE', '/api/v1/groups/{group}/events/{title}'),
    ('POST', '/api/v1/groups/{group}/events/{event}/slides'),
    ('GET', '/api/v1/groups/{group}/events/{event}/slides'),
    ('GET', '/api/v1/groups/{group}/events/{event}/slides/{slide}'),
    ('PATCH', '/api/v1/groups/{group}/events/{event}/slides/{slide}'),
    ('DELETE', '/api/v1/groups/{group}/events/{event}/slides/{slide}'),
    ('PUT', '/api/v1/groups/{group}/events/{event}/slides/{slide}/content'),
    ('POST', '/api/v1/player/select'),
    ('POST', '/api/v1/player/{session_id}/next'),
    ('POST', '/api/v1/player/{session_id}/previous'),
    ('GET', '/api/v1/player/{session_id}'),
    ('DELETE', '/api/v1/player/{session_id}'),
}

PUBLIC_ENDPOINTS = {
    ('POST', '/api/v1/auth/login'), ('POST', '/api/v1/auth/change-password'),
    ('POST', '/api/v1/student/join'),
    ('GET', '/api/v1/help'), ('GET', '/health'),
}
STUDENT_ENDPOINTS = {
    ('POST', '/api/v1/student/resume'), ('GET', '/api/v1/student/current'),
    ('POST', '/api/v1/student/answers'),
}


def sample(client):
    group = client.post('/api/v1/groups', json={'group': 'Vérification'}).json()['group']
    event = client.post('/api/v1/events', json={'group': group, 'title': 'Validation'}).json()['title']
    base = f'/api/v1/groups/{group}/events/{event}/slides'
    slides = []
    for kind in 'CAORQT':
        content = ('---\nclasslive_answer:\n  selected: [B]\n---\n' if kind != 'C' else '') + '# Exercice'
        resp = client.post(base, json={'title': f'Page {kind}', 'slide_type': kind, 'content': content})
        assert resp.status_code == 200, resp.text
        slides.append(resp.json()['slide'])
    return group, event, base, slides


def start_student(client, group, event):
    r = client.post('/api/v1/live/start', json={'group': group, 'title': event})
    assert r.status_code == 200, r.text
    live = r.json()
    student = client.post('/api/v1/student/join', json={
        'session_code': live['session_code'], 'nom': 'Dupont', 'prenom': 'Marie'})
    assert student.status_code == 200, student.text
    return live, student.json()


def test_inventaire_openapi_et_websockets(client):
    paths = client.get('/openapi.json').json()['paths']
    actual = {(method.upper(), path) for path, verbs in paths.items() for method in verbs}
    assert actual == PUBLIC_ROUTES, f'Nouvelles routes non testées : {actual - PUBLIC_ROUTES}; manquantes : {PUBLIC_ROUTES - actual}'
    ws_paths = {r.path for r in client.app.routes if r.__class__.__name__ == 'APIWebSocketRoute'}
    assert ws_paths == {'/api/v1/student/ws', '/api/v1/live/{live_id}/monitor'}


@pytest.mark.parametrize('method,path', sorted(PUBLIC_ROUTES - PUBLIC_ENDPOINTS - STUDENT_ENDPOINTS))
def test_toutes_routes_formateur_refusent_absence_jeton_et_jeton_etudiant(client, method, path):
    group, event, base, slides = sample(client)
    live, student = start_student(client, group, event)
    concrete = path.format(
        group=group, event=event, title=event, live_id=live['live_id'],
        slide=slides[0], session_id='session_inexistante',
        participation_id=student['participation_id'])
    for header in ('', f'Bearer {student["student_session_id"]}'):
        r = client.request(method, concrete, headers={'Authorization': header})
        assert r.status_code == 401, (method, concrete, r.status_code, r.text)


@pytest.mark.parametrize('method,path', sorted(STUDENT_ENDPOINTS))
def test_toutes_routes_etudiant_refusent_anonyme_et_jeton_formateur(client, method, path):
    trainer = client.headers['Authorization']
    for header in ('', trainer):
        r = client.request(method, path, headers={'Authorization': header})
        assert r.status_code == 401, (method, path, r.status_code)


@pytest.mark.parametrize('kind,answer', [
    ('A', {'pairs': {'chat': 'animal'}}),
    ('O', {'order': ['C', 'A', 'B']}),
    ('R', {'categories': {'chat': 'animaux'}}),
    ('Q', {'selected': ['B', 'D']}),
    ('T', {'blanks': ['Paris']}),
])
def test_chacun_des_5_exercices_enregistre_sans_points(client, kind, answer):
    group = client.post('/api/v1/groups', json={'group': 'Cours'}).json()['group']
    event = client.post('/api/v1/events', json={'group': group, 'title': 'Un type'}).json()['title']
    slide = client.post(f'/api/v1/groups/{group}/events/{event}/slides', json={
        'title': 'Test', 'slide_type': kind, 'content': '# Exercice sans correction'}).json()['slide']
    live, student = start_student(client, group, event)
    token = student['student_session_id']
    headers = {'Authorization': 'Bearer ' + token}
    response = client.post('/api/v1/student/answers', headers=headers, json={'answer': answer})
    assert response.status_code == 200, response.text
    assert response.json()['slide'] == slide
    result = client.get(f'/api/v1/live/{live["live_id"]}/results').json()
    assert result['results'][0]['answers'][0]['answer'] == answer
    assert result['results'][0]['answered'] == 1
    assert 'points' not in json.dumps(result)
    csv_r = client.get(f'/api/v1/live/{live["live_id"]}/export.csv')
    assert csv_r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(csv_r.content.decode('utf-8-sig')), delimiter=';'))
    assert json.loads(rows[0]['reponse_json']) == answer
    assert 'points' not in rows[0]


@pytest.mark.parametrize('bad', [[], 42, 'réponse', None])
def test_reponse_non_objet_rejetee(client, bad):
    group, event, _, _ = sample(client)
    live, student = start_student(client, group, event)
    client.post(f'/api/v1/live/{live["live_id"]}/next')
    response = client.post('/api/v1/student/answers',
        headers={'Authorization': 'Bearer '+student['student_session_id']},
        json={'answer': bad})
    assert response.status_code == 422, response.text


def test_reponse_trop_volumineuse_et_historique_modifications(client, tmp_path):
    group, event, _, slides = sample(client)
    live, student = start_student(client, group, event)
    lid = live['live_id']
    client.post(f'/api/v1/live/{lid}/next')
    h = {'Authorization': 'Bearer ' + student['student_session_id']}
    assert client.post('/api/v1/student/answers', headers=h,
        json={'answer': {'text': 'A'*70000}}).status_code == 422
    assert client.post('/api/v1/student/answers', headers=h,
        json={'answer': {'selected': ['A']}}).status_code == 200
    assert client.post('/api/v1/student/answers', headers=h,
        json={'answer': {'selected': ['B']}}).status_code == 200
    result = client.get(f'/api/v1/live/{lid}/results').json()['results'][0]
    assert result['answered'] == 1
    assert result['answers'][0]['answer'] == {'selected': ['B']}
    with sqlite3.connect(tmp_path/'classlive.db') as con:
        assert con.execute('SELECT COUNT(*) FROM submissions').fetchone()[0] == 2


@pytest.mark.parametrize('markdown', [
    '---\nclasslive_answer:\n  selected: [B]\n',
    '---\n- un\n- deux\n---\n# Exercice',
    '---\nclasslive_answer: [pas fini\n---\n# Exercice',
])
def test_frontmatter_invalide_bloque_demarrage_sans_creer_session(client, markdown):
    group = client.post('/api/v1/groups', json={'group': 'Cours'}).json()['group']
    event = client.post('/api/v1/events', json={'group': group, 'title': 'Échec sûr'}).json()['title']
    base = f'/api/v1/groups/{group}/events/{event}/slides'
    assert client.post(base, json={'title':'QCM','slide_type':'Q','content': markdown}).status_code == 200
    resp = client.post('/api/v1/live/start', json={'group':group,'title':event})
    assert resp.status_code == 422, resp.text
    assert client.get(f'/api/v1/groups/{group}/events/{event}/sessions').json()['sessions'] == []


def test_double_identite_separee_et_sessions_isolees(client):
    g1 = client.post('/api/v1/groups', json={'group':'Groupe Un'}).json()['group']
    g2 = client.post('/api/v1/groups', json={'group':'Groupe Deux'}).json()['group']
    sessions = []
    for group in [g1, g2]:
        e = client.post('/api/v1/events', json={'group':group,'title':'Événement'}).json()['title']
        client.post(f'/api/v1/groups/{group}/events/{e}/slides', json={
            'title':'Exercice', 'slide_type':'Q', 'content':'# Public '+group})
        live, first = start_student(client, group, e)
        second = client.post('/api/v1/student/join', json={
            'session_code':live['session_code'], 'nom':'Dupont', 'prenom':'Marie'}).json()
        sessions.append((live,first,second))
        assert first['participation_id'] != second['participation_id']
    assert sessions[0][1]['student_session_id'] != sessions[1][1]['student_session_id']
    assert sessions[0][0]['live_id'] != sessions[1][0]['live_id']
    t1 = sessions[0][1]['student_session_id']
    t2 = sessions[1][1]['student_session_id']
    assert g1 in client.get('/api/v1/student/current',headers={'Authorization':'Bearer '+t1}).json()['group']
    assert g2 in client.get('/api/v1/student/current',headers={'Authorization':'Bearer '+t2}).json()['group']
    client.post(f'/api/v1/live/{sessions[0][0]["live_id"]}/stop')
    assert client.get('/api/v1/student/current', headers={'Authorization':'Bearer '+t1}).status_code==401
    assert client.get('/api/v1/student/current', headers={'Authorization':'Bearer '+t2}).status_code==200


def test_session_vide_export_et_conservation_slides_apres_reset(client):
    g,e,base,slides = sample(client)
    live = client.post('/api/v1/live/start',json={'group':g,'title':e}).json()
    lid = live['live_id']
    assert client.get(f'/api/v1/live/{lid}/export.csv').status_code == 200
    assert client.delete(f'/api/v1/groups/{g}/events/{e}').status_code == 409
    assert client.delete(f'/api/v1/groups/{g}').status_code == 409
    assert client.post(f'/api/v1/live/{lid}/stop').status_code == 200
    assert client.patch(f'/api/v1/groups/{g}', json={'new_name':'Bloque'}).status_code == 409
    assert client.delete(f'/api/v1/groups/{g}/events/{e}/sessions').status_code == 200
    assert client.get(base).json()['slides'] == slides
    assert client.post('/api/v1/live/start',json={'group':g,'title':e}).status_code == 200


def test_ws_jetons_invalides_rejetes(client):
    g,e,_,_ = sample(client)
    live,_ = start_student(client,g,e)
    for uri in (f'/api/v1/live/{live["live_id"]}/monitor', '/api/v1/student/ws'):
        with client.websocket_connect(uri) as ws:
            ws.send_json({'token':'mauvais-jeton'})
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 1008


def test_export_et_guide_accessibles_sans_fuite_des_corriges(client, tmp_path):
    g,e,base,slides = sample(client)
    live,student = start_student(client,g,e)
    lid = live['live_id']
    client.post(f'/api/v1/live/{lid}/next')
    headers = {'Authorization':'Bearer '+student['student_session_id']}
    data = client.get('/api/v1/student/current',headers=headers).json()
    assert 'classlive_answer' not in json.dumps(data)
    assert 'correction' not in data
    assert client.get(f'{base}/{slides[1]}',headers=headers).status_code == 401
    assert client.get(f'/api/v1/live/{lid}/results',headers=headers).status_code == 401
    guide = tmp_path/'GUIDE_CLASSLIVE.md'
    before = client.get('/api/v1/help')
    assert before.status_code == 200 and 'markdown' in before.headers['content-type']
    guide.write_text('# Guide utilisateur personnalisé',encoding='utf-8')
    assert client.get('/api/v1/help').text == '# Guide utilisateur personnalisé'


def test_authentification_api_key_compatibilite_et_portee(tmp_path):
    with TestClient(create_app(Settings(workdir=tmp_path, api_key='cle-api'))) as c:
        assert c.get('/api/v1/groups').status_code == 401
        assert c.get('/api/v1/groups',headers={'X-API-Key':'mauvaise'}).status_code == 401
        assert c.get('/api/v1/groups',headers={'X-API-Key':'cle-api'}).status_code == 200
        assert c.get('/api/groups',headers={'X-API-Key':'cle-api'}).status_code == 200
        assert c.post('/api/v1/auth/login',json={'username':'formateur','password':'x'}).status_code == 503
        assert c.get('/api/v1/help').status_code == 200
