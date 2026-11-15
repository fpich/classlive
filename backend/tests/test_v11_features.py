"""v0.9.2 : pin sur image (type I), compte à rebours par slide en mode live,
mode résultats anonymes. Tests stricts : nominaux + cas limites.

Ces tests n'écrivent que dans tmp_path et n'ouvrent aucun port réseau.
"""
import csv
import io
import json
import time
from datetime import datetime, timedelta, timezone

from test_features import app_client, make_event, start_live, join, student_headers


# ── Type I : pin sur image ──────────────────────────────────────────────────

def test_type_I_creation_et_reponses(client):
    g, e, base, _ = make_event(client, kinds=('C', 'I'))
    r = client.post(base, json={'title': 'Plan', 'slide_type': 'I',
                                'content': '# Où est le projecteur ?\n![plan](/media/x/plan.png)'})
    assert r.status_code == 200 and '_I_' in r.json()['slide']
    live = start_live(client, g, e)
    lid = live['live_id']
    s1 = join(client, live['session_code'], 'Un', 'Eleve')
    s2 = join(client, live['session_code'], 'Deux', 'Eleve')
    client.post(f'/api/v1/live/{lid}/next')  # -> slide I
    h1, h2 = student_headers(s1), student_headers(s2)
    for h, payload in ((h1, {'x': 0.25, 'y': 0.5}), (h2, {'x': 0.75, 'y': 0.5})):
        assert client.post('/api/v1/student/answers', headers=h, json={'answer': payload}).status_code == 200
    # formes invalides -> 422
    for bad in ({}, {'x': 0.5}, {'y': 0.5}, {'x': -0.1, 'y': 0.5}, {'x': 1.5, 'y': 0.5},
                    {'x': 'a', 'y': 0.5}, {'x': True, 'y': 0.5}, {'x': 0.5, 'y': None}):
        assert client.post('/api/v1/student/answers', headers=h1, json={'answer': bad}).status_code == 422, bad
    # stats : pins + centre de gravité
    st = client.get(f'/api/v1/live/{lid}/stats').json()
    assert st['slide_type'] == 'I' and st['answered'] == 2
    assert st['pins'] == [[0.25, 0.5], [0.75, 0.5]]
    assert st['center'] == {'x': 0.5, 'y': 0.5}
    all_st = client.get(f'/api/v1/live/{lid}/stats?all=1').json()
    assert all_st['slides'][1]['pins'] == [[0.25, 0.5], [0.75, 0.5]]
    # results + CSV contiennent les coordonnées
    res = client.get(f'/api/v1/live/{lid}/results').json()['results']
    answers = sorted(json.dumps(a['answer'], sort_keys=True) for r in res for a in r['answers'])
    assert answers == [json.dumps({'x': 0.25, 'y': 0.5}), json.dumps({'x': 0.75, 'y': 0.5})]
    rows = list(csv.DictReader(io.StringIO(client.get(f'/api/v1/live/{lid}/export.csv').content.decode('utf-8-sig')), delimiter=';'))
    assert len(rows) == 2 and json.loads(rows[0]['reponse_json'])['x'] in (0.25, 0.75)


def test_type_I_sans_reponse_stats_vide_et_autonome(client):
    g, e, base, slides = make_event(client, kinds=('C', 'I'))
    live = start_live(client, g, e)
    lid = live['live_id']
    client.post(f'/api/v1/live/{lid}/next')
    st = client.get(f'/api/v1/live/{lid}/stats').json()
    assert st['answered'] == 0 and st['pins'] == [] and 'center' not in st
    # autonome : next bloqué sur I non répondu, puis verrouillé après réponse
    live2 = start_live(client, g, e + ' copie') if False else None
    client.post(f'/api/v1/live/{lid}/stop')
    live3 = start_live(client, g, e, mode='autonome')
    s = join(client, live3['session_code'])
    h = student_headers(s)
    assert client.post('/api/v1/student/next', headers=h).status_code == 200  # C -> I
    assert client.post('/api/v1/student/next', headers=h).status_code == 409  # I non répondu
    assert client.post('/api/v1/student/answers', headers=h, json={'answer': {'x': 0.1, 'y': 0.9}}).status_code == 200
    assert client.post('/api/v1/student/answers', headers=h, json={'answer': {'x': 0.2, 'y': 0.2}}).status_code == 409
    assert client.post('/api/v1/student/next', headers=h).json()['finished'] is True


# ── Compte à rebours par slide en mode live ─────────────────────────────────

def test_live_timer_par_question(client):
    g, e, _, _ = make_event(client, kinds=('C', 'Q', 'Q'))
    # validations au start
    assert client.post('/api/v1/live/start', json={'group': g, 'title': e, 'timing': 'par_evenement',
                                                   'timing_seconds': 60}).status_code == 422
    assert client.post('/api/v1/live/start', json={'group': g, 'title': e, 'timing': 'par_question'}).status_code == 422
    assert client.post('/api/v1/live/start', json={'group': g, 'title': e, 'timing': 'par_question',
                                                   'timing_seconds': 0}).status_code == 422
    live = start_live(client, g, e, timing='par_question', timing_seconds=2)
    lid = live['live_id']
    assert live['timing'] == 'par_question' and live['timing_seconds'] == 2
    st = client.get(f'/api/v1/live/{lid}/status').json()
    assert st['deadline'] is not None and st['timing'] == 'par_question'
    # slide C (contenu) : pas d'expiry exposé côté élève
    s = join(client, live['session_code'])
    h = student_headers(s)
    cur = client.get('/api/v1/student/current', headers=h).json()
    assert 'expires_at' not in cur
    # slide Q : expires_at exposé (deadline de la slide courante)
    client.post(f'/api/v1/live/{lid}/next')
    st_q1 = client.get(f'/api/v1/live/{lid}/status').json()
    cur = client.get('/api/v1/student/current', headers=h).json()
    assert cur['expires_at'] == st_q1['deadline'] and cur['time_expired'] is False
    # la deadline est renouvelée à chaque navigation
    client.post(f'/api/v1/live/{lid}/next')
    st_q2 = client.get(f'/api/v1/live/{lid}/status').json()
    assert st_q2['deadline'] > st_q1['deadline']
    cur = client.get('/api/v1/student/current', headers=h).json()
    assert cur['expires_at'] == st_q2['deadline']
    # réponse OK avant expiry, puis 409 après expiry
    assert client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['A']}}).status_code == 200
    time.sleep(2.2)
    cur = client.get('/api/v1/student/current', headers=h).json()
    assert cur['time_expired'] is True
    assert client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['B']}}).status_code == 409
    # sans timer : pas de deadline
    client.post(f'/api/v1/live/{lid}/stop')
    live2 = start_live(client, g, e)
    st3 = client.get(f'/api/v1/live/{live2["live_id"]}/status').json()
    assert st3['deadline'] is None and st3['timing'] == 'none'


def test_live_timer_avec_planification(client):
    g, e, _, _ = make_event(client, kinds=('C', 'Q'))
    future = (datetime.now(timezone.utc) + timedelta(seconds=1.2)).isoformat()
    r = client.post('/api/v1/live/start', json={'group': g, 'title': e, 'timing': 'par_question',
                                                'timing_seconds': 30, 'start_at': future})
    assert r.status_code == 200
    lid = r.json()['live_id']
    assert client.get(f'/api/v1/live/{lid}/status').json()['deadline'] is None  # calculée à l'activation
    time.sleep(1.8)
    st = client.get(f'/api/v1/live/{lid}/status').json()
    assert st['status'] == 'running' and st['deadline'] is not None


# ── Mode anonyme ────────────────────────────────────────────────────────────

def test_mode_anonyme_masque_identites_mais_pas_les_donnees(client):
    g, e, _, _ = make_event(client)
    live = start_live(client, g, e, anonymous=True)
    lid = live['live_id']
    assert live['anonymous'] is True
    assert client.get(f'/api/v1/live/{lid}/status').json()['anonymous'] is True
    s = join(client, live['session_code'], 'Dupont', 'Marie')
    h = student_headers(s)
    client.post(f'/api/v1/live/{lid}/next')
    assert client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['A']}}).status_code == 200
    # results : identités masquées, réponses conservées, flag exposé
    res = client.get(f'/api/v1/live/{lid}/results').json()
    assert res['anonymous'] is True
    assert res['results'][0]['nom'] == 'anonyme' and res['results'][0]['prenom'] == ''
    assert res['results'][0]['answers'][0]['answer'] == {'selected': ['A']}
    # export CSV aussi masqué
    rows = list(csv.DictReader(io.StringIO(client.get(f'/api/v1/live/{lid}/export.csv').content.decode('utf-8-sig')), delimiter=';'))
    assert rows[0]['nom'] == 'anonyme' and rows[0]['prenom'] == ''
    assert json.loads(rows[0]['reponse_json']) == {'selected': ['A']}
    # l'élève garde son identité côté client ; student-results par nom fonctionne toujours
    assert client.post('/api/v1/student/resume', headers=h).json()['nom'] == 'Dupont'
    sr = client.get(f'/api/v1/groups/{g}/events/{e}/student-results', params={'nom': 'Dupont', 'prenom': 'Marie'})
    assert sr.json()['total_answers'] == 1
    # RGPD : le droit à l'oubli fonctionne toujours par nom réel en base
    r = client.delete(f'/api/v1/groups/{g}/events/{e}/students-data', params={'nom': 'Dupont', 'prenom': 'Marie'})
    assert r.json()['deleted_participations'] == 1


def test_mode_non_anonyme_par_defaut(client):
    g, e, _, _ = make_event(client)
    live = start_live(client, g, e)
    assert live['anonymous'] is False
    s = join(client, live['session_code'], 'Dupont', 'Marie')
    client.post(f'/api/v1/live/{live["live_id"]}/next')
    client.post('/api/v1/student/answers', headers=student_headers(s), json={'answer': {'selected': ['B']}})
    res = client.get(f'/api/v1/live/{live["live_id"]}/results').json()
    assert res['anonymous'] is False and res['results'][0]['nom'] == 'Dupont'
    # autonome + anonyme : idem côté formateur, le récap perso élève reste identifié
    client.post(f'/api/v1/live/{live["live_id"]}/stop')
    live2 = start_live(client, g, e, mode='autonome', anonymous=True)
    s2 = join(client, live2['session_code'], 'Martin', 'Paul')
    h2 = student_headers(s2)
    client.post('/api/v1/student/next', headers=h2)
    client.post('/api/v1/student/answers', headers=h2, json={'answer': {'selected': ['A']}})
    client.post('/api/v1/student/next', headers=h2)
    own = client.get('/api/v1/student/results', headers=h2).json()
    assert own['nom'] == 'Martin' and own['answered'] == 1  # récap perso intact et identifié
    res2 = client.get(f'/api/v1/live/{live2["live_id"]}/results').json()
    assert res2['anonymous'] is True and res2['results'][0]['nom'] == 'anonyme'
