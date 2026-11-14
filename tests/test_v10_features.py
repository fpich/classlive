"""Fonctionnalités v0.9.x : nouveaux types de slides (F/P/N/L), médias, frontend statique,
annonce formateur, planification (start_at), exports CSV présence/Q&A/réactions,
résultats élève cross-événements, backup ZIP, duplication de slide.

Ces tests n'écrivent que dans tmp_path et n'ouvrent aucun port réseau.
"""
import io
import csv
import json
import os
import time
import zipfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from classlive.api import create_app
from classlive.config import Settings, load_settings
from classlive.slides import SlideStorage
from classlive.storage import EventStorage, ResourceConflict, StorageError

from test_features import app_client, make_event, start_live, join, student_headers


# ── Nouveaux types de slides F (texte libre), P (sondage), N (nuage), L (échelle) ──

def test_nouveaux_types_creations_et_types_invalides(client):
    g, e, base, _ = make_event(client, kinds=('C',))
    for kind in 'FPNL':
        r = client.post(base, json={'title': f'Slide {kind}', 'slide_type': kind, 'content': '# x'})
        assert r.status_code == 200, r.text
        assert f'_{kind}_' in r.json()['slide']
    assert client.post(base, json={'title': 'Bad', 'slide_type': 'Z', 'content': ''}).status_code == 422
    # renommage de type autorisé vers les nouveaux types
    slides = client.get(base).json()['slides']
    f_slide = next(s for s in slides if '_F_' in s)
    r = client.patch(f'{base}/{f_slide}', json={'new_type': 'L'})
    assert r.status_code == 200 and '_L_' in r.json()['new_name']
    assert client.patch(f'{base}/{f_slide}', json={'new_type': 'Z'}).status_code == 422


def test_nouveaux_types_submit_valide_et_invalide(client):
    g, e, base, _ = make_event(client, kinds=('C', 'F', 'P', 'N', 'L'))
    live = start_live(client, g, e)
    lid = live['live_id']
    s = join(client, live['session_code'])
    h = student_headers(s)

    def goto(number):
        assert client.post(f'/api/v1/live/{lid}/goto', json={'number': number}).status_code == 200

    def answer(payload):
        return client.post('/api/v1/student/answers', headers=h, json={'answer': payload})

    goto(2)  # F texte libre
    assert answer({'text': ''}).status_code == 422
    assert answer({'text': 'x' * 5001}).status_code == 422
    assert answer({'text': '  '}).status_code == 422
    assert answer({'pas_text': 'x'}).status_code == 422
    assert answer({'text': 'Ma réponse libre'}).status_code == 200

    goto(3)  # P sondage
    assert answer({'selected': []}).status_code == 422
    assert answer({'selected': ['A' * 51]}).status_code == 422
    assert answer({'selected': 'A'}).status_code == 422
    assert answer({'selected': ['A']}).status_code == 200

    goto(4)  # N nuage de mots
    assert answer({'words': ['a'] * 6}).status_code == 422
    assert answer({'words': ['w' * 31]}).status_code == 422
    assert answer({'words': []}).status_code == 422
    assert answer({'words': ['lundi', 'mardi']}).status_code == 200

    goto(5)  # L échelle
    for bad in (0, 6, '3', True, 2.5, None):
        assert answer({'value': bad}).status_code == 422, bad
    assert answer({'value': 4}).status_code == 200

    # Les réponses sont bien enregistrées telles quelles.
    results = client.get(f'/api/v1/live/{lid}/results').json()['results'][0]['answers']
    by_slide = {a['slide']: a['answer'] for a in results}
    assert by_slide[[k for k in by_slide if '_F_' in k][0]] == {'text': 'Ma réponse libre'}
    assert by_slide[[k for k in by_slide if '_P_' in k][0]] == {'selected': ['A']}
    assert by_slide[[k for k in by_slide if '_N_' in k][0]] == {'words': ['lundi', 'mardi']}
    assert by_slide[[k for k in by_slide if '_L_' in k][0]] == {'value': 4}
    # Export CSV contient les réponses JSON.
    rows = list(csv.DictReader(io.StringIO(client.get(f'/api/v1/live/{lid}/export.csv').content.decode('utf-8-sig')), delimiter=';'))
    assert len(rows) == 4
    assert json.loads(rows[0]['reponse_json'])['text'] == 'Ma réponse libre'


def test_nouveaux_types_stats_agregats(client):
    g, e, base, _ = make_event(client, kinds=('C', 'P', 'N', 'L', 'F'))
    live = start_live(client, g, e)
    lid = live['live_id']
    s1 = join(client, live['session_code'], 'Un', 'Eleve')
    s2 = join(client, live['session_code'], 'Deux', 'Eleve')
    h1, h2 = student_headers(s1), student_headers(s2)

    def goto(n):
        client.post(f'/api/v1/live/{lid}/goto', json={'number': n})

    def answer(h, payload):
        assert client.post('/api/v1/student/answers', headers=h, json={'answer': payload}).status_code == 200

    goto(2)  # P
    answer(h1, {'selected': ['A']})
    answer(h2, {'selected': ['B']})
    st = client.get(f'/api/v1/live/{lid}/stats').json()
    assert st['slide_type'] == 'P' and st['options'] == {'A': 1, 'B': 1} and st['answered'] == 2
    goto(3)  # N
    answer(h1, {'words': ['chat', 'chien']})
    answer(h2, {'words': ['chat']})
    st = client.get(f'/api/v1/live/{lid}/stats').json()
    assert st['words'] == {'chat': 2, 'chien': 1} and 'options' not in st
    goto(4)  # L
    answer(h1, {'value': 5})
    answer(h2, {'value': 5})
    st = client.get(f'/api/v1/live/{lid}/stats').json()
    assert st['values'] == {'5': 2}
    goto(5)  # F : jamais de contenu exposé
    answer(h1, {'text': 'secret'})
    st = client.get(f'/api/v1/live/{lid}/stats').json()
    assert st['answered'] == 1 and not any(k in st for k in ('options', 'words', 'values'))
    assert 'secret' not in json.dumps(st)
    # stats?all=1 couvre toutes les slides
    all_st = client.get(f'/api/v1/live/{lid}/stats?all=1').json()
    assert len(all_st['slides']) == 5
    assert all_st['slides'][1]['options'] == {'A': 1, 'B': 1}


def test_nouveau_type_en_mode_autonome_verrouillage(client):
    g, e, base, slides = make_event(client, kinds=('C', 'F'))
    live = start_live(client, g, e, mode='autonome')
    s = join(client, live['session_code'])
    h = student_headers(s)
    # C -> F : avancer est libre sur une slide contenu
    assert client.post('/api/v1/student/next', headers=h).status_code == 200
    # next bloqué tant que l'exercice F n'est pas répondu
    assert client.post('/api/v1/student/next', headers=h).status_code == 409
    assert client.post('/api/v1/student/answers', headers=h, json={'answer': {'text': 'ok'}}).status_code == 200
    r = client.post('/api/v1/student/next', headers=h)
    assert r.status_code == 200 and r.json()['finished'] is True
    # réponse verrouillée : resoumission interdite
    assert client.post('/api/v1/student/answers', headers=h, json={'answer': {'text': 'autre'}}).status_code == 409


# ── Médias par événement ────────────────────────────────────────────────────

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 100


def test_media_upload_list_download_public_delete(client):
    g, e, _, _ = make_event(client)
    base = f'/api/v1/groups/{g}/events/{e}/media'
    assert client.get(base).json()['files'] == []  # pas encore de dossier media
    r = client.post(f'{base}?filename=schema.png', content=PNG, headers={'Content-Type': 'image/png'})
    assert r.status_code == 200, r.text
    assert r.json()['size'] == len(PNG) and r.json()['uploaded'] is True
    assert client.get(base).json()['files'] == ['schema.png']
    # double upload -> 409
    assert client.post(f'{base}?filename=schema.png', content=PNG).status_code == 409
    # téléchargement public (sans jeton), bon type MIME et contenu identique
    r = client.get(f'/media/{g}/{e}/schema.png')
    assert r.status_code == 200 and r.headers['content-type'] == 'image/png' and r.content == PNG
    # suppression puis 404
    assert client.delete(f'{base}/schema.png').status_code == 200
    assert client.get(f'/media/{g}/{e}/schema.png').status_code == 404
    assert client.get(base).json()['files'] == []


def test_media_erreurs(client, tmp_path):
    g, e, _, _ = make_event(client)
    base = f'/api/v1/groups/{g}/events/{e}/media'
    assert client.post(f'{base}?filename=../evil.png', content=PNG).status_code == 422
    assert client.post(f'{base}?filename=image.txt', content=PNG).status_code == 422
    assert client.post(f'{base}?filename=image.png', content=b'').status_code == 422
    assert client.post(f'{base}?filename=image.png', content=PNG,
                       headers={'Content-Length': '999999999'}).status_code == 413
    assert client.post(f'{base}?filename=image.png', content=PNG,
                       headers={'Content-Length': 'abc'}).status_code == 422
    # corps streamé (sans Content-Length) trop gros -> 413 aussi
    with app_client(tmp_path / 'stream', media_max_mb=1) as c:
        g2, e2, _, _ = make_event(c)
        r = c.post(f'/api/v1/groups/{g2}/events/{e2}/media?filename=big.png',
                   content=iter([b'x' * (1024 * 1024 + 1)]))
        assert r.status_code == 413
    assert client.get(f'/media/{g}/{e}/inconnu.png').status_code == 404
    assert client.get(f'/media/{g}/{e}/bad.txt').status_code == 422
    assert client.get(f'/media/{g}/inconnu/x.png').status_code == 404
    assert client.delete(f'{base}/inconnu.png').status_code == 404
    assert client.delete(f'{base}/bad name!.png').status_code == 422
    # Limite de taille sur le corps (media_max_mb=1 -> 1 Mo max)
    with app_client(tmp_path / 'media', media_max_mb=1) as c:
        g2, e2, _, _ = make_event(c)
        r = c.post(f'/api/v1/groups/{g2}/events/{e2}/media?filename=big.png',
                   content=b'x' * (1024 * 1024 + 1))
        assert r.status_code == 413
        # la limite store (InvalidName -> 422) est atteinte via un appel direct
        storage = EventStorage(tmp_path / 'media', 'Evts')
        slides = SlideStorage(storage, media_max_bytes=10)
        storage.init()
        storage.create_group('G')
        storage.create_event('G', 'E')
        from classlive.storage import InvalidName
        with pytest.raises(InvalidName):
            slides.upload_media('G', 'E', 'x.png', b'x' * 11)
        with pytest.raises(InvalidName):
            slides.upload_media('G', 'E', 'x.png', b'')


def test_media_symlink_et_oserror(client, tmp_path, monkeypatch):
    g, e, _, _ = make_event(client)
    base = f'/api/v1/groups/{g}/events/{e}/media'
    client.post(f'{base}?filename=a.png', content=PNG)
    # lien symbolique dans media/ : upload refusé (500), download 404
    gpath = tmp_path / 'Evts'
    event_dir = next(p for p in gpath.rglob('E*') if p.is_dir() and p.name.endswith(e.split('_', 1)[1].replace(' ', '_')) or p.name == e)
    media_dir = event_dir / 'media'
    os.symlink('/etc/hostname', media_dir / 'lien.png')
    assert client.post(f'{base}?filename=lien.png', content=PNG).status_code == 500
    assert client.get(f'/media/{g}/{e}/lien.png').status_code == 404
    assert client.delete(f'{base}/lien.png').status_code == 404
    assert 'lien.png' not in client.get(base).json()['files']  # symlink exclu de la liste
    # OSError à l'écriture -> 500
    import pathlib
    real_open = pathlib.Path.open

    def fake_open(self, mode='r', *a, **k):
        if 'x' in mode and 'b' in mode:
            raise OSError('disque plein')
        return real_open(self, mode, *a, **k)
    monkeypatch.setattr(pathlib.Path, 'open', fake_open)
    assert client.post(f'{base}?filename=b.png', content=PNG).status_code == 500
    monkeypatch.undo()
    # OSError à la suppression -> 500
    real_unlink = pathlib.Path.unlink

    def fake_unlink(self, *a, **k):
        if self.name == 'a.png':
            raise OSError('io error')
        return real_unlink(self, *a, **k)
    monkeypatch.setattr(pathlib.Path, 'unlink', fake_unlink)
    assert client.delete(f'{base}/a.png').status_code == 500


def test_media_copie_avec_evenement_duplique(client):
    g, e, base, _ = make_event(client)
    client.post(f'/api/v1/groups/{g}/events/{e}/media?filename=img.png', content=PNG)
    r = client.post(f'/api/v1/groups/{g}/events/{e}/duplicate', json={'new_title': 'Copie'})
    e2 = r.json()['new_title']
    assert client.get(f'/api/v1/groups/{g}/events/{e2}/media').json()['files'] == ['img.png']
    assert client.get(f'/media/{g}/{e2}/img.png').content == PNG


# ── Frontend statique servi sur /app ────────────────────────────────────────

def test_frontend_statique_servi_sur_app(tmp_path):
    dist = tmp_path / 'dist'
    dist.mkdir()
    (dist / 'index.html').write_text('<html>ClassLive APP</html>', encoding='utf-8')
    (dist / 'style.css').write_text('body{}', encoding='utf-8')
    with app_client(tmp_path, frontend_dir='dist') as c:
        r = c.get('/app/')
        assert r.status_code == 200 and 'ClassLive APP' in r.text
        # fallback SPA sur les routes client inconnues
        r = c.get('/app/live/123456')
        assert r.status_code == 200 and 'ClassLive APP' in r.text
        # vrai fichier statique servi tel quel
        r = c.get('/app/style.css')
        assert r.status_code == 200 and r.text == 'body{}'
        # l'API reste prioritaire et intacte
        assert c.get('/health').status_code == 200
        assert c.get('/api/v1/groups').status_code == 200
        # join_url pointe vers /app/join quand le frontend est configuré
        g, e, _, _ = make_event(c)
        live = start_live(c, g, e)
        assert live['join_url'] == f"/app/join?code={live['session_code']}"


def test_frontend_non_configure_ou_dossier_absent(tmp_path):
    with app_client(tmp_path) as c:  # pas de frontend_dir
        assert c.get('/app/').status_code == 404
        g, e, _, _ = make_event(c)
        live = start_live(c, g, e)
        assert live['join_url'] == f"/join?code={live['session_code']}"
    with app_client(tmp_path / 'x', frontend_dir='dist-inexistant') as c2:  # dossier absent : pas de mount
        assert c2.get('/app/').status_code == 404
    # chemin absolu accepté
    dist = tmp_path / 'build'
    dist.mkdir()
    (dist / 'index.html').write_text('<html>ABS</html>', encoding='utf-8')
    with app_client(tmp_path / 'y', frontend_dir=str(dist)) as c3:
        assert c3.get('/app/').status_code == 200 and 'ABS' in c3.get('/app/').text


def test_config_frontend_dir_et_media_invalides(tmp_path):
    base = 'classlive:\n  storage:\n    workdir: "/tmp/x"\n'
    for bad in ('  server:\n    frontend_dir: ""\n', '  server:\n    frontend_dir: 42\n'):
        cfg = tmp_path / 'c.yml'
        cfg.write_text(base + bad, encoding='utf-8')
        with pytest.raises(ValueError, match='frontend_dir'):
            load_settings(cfg)
    for bad in ('  media: "x"\n', '  media:\n    max_file_mb: 0\n', '  media:\n    max_file_mb: 101\n', '  media:\n    max_file_mb: "5"\n'):
        cfg = tmp_path / 'c.yml'
        cfg.write_text(base + bad, encoding='utf-8')
        with pytest.raises(ValueError, match='media'):
            load_settings(cfg)
    cfg = tmp_path / 'c.yml'
    cfg.write_text(base + '  server:\n    frontend_dir: "dist"\n  media:\n    max_file_mb: 25\n', encoding='utf-8')
    s = load_settings(cfg)
    assert s.frontend_dir == 'dist' and s.media_max_mb == 25


# ── Annonce du formateur ────────────────────────────────────────────────────

def test_annonce_persistee_et_vue_par_eleve(client):
    g, e, _, _ = make_event(client)
    live = start_live(client, g, e)
    lid = live['live_id']
    s = join(client, live['session_code'])
    assert client.get('/api/v1/student/current', headers=student_headers(s)).json()['announcement'] is None
    r = client.post(f'/api/v1/live/{lid}/announce', json={'text': '  Pause 5 min !  '})
    assert r.status_code == 200 and r.json()['text'] == 'Pause 5 min !'
    cur = client.get('/api/v1/student/current', headers=student_headers(s)).json()
    assert cur['announcement'] == 'Pause 5 min !'
    assert client.get(f'/api/v1/live/{lid}/status').json()['announcement'] == 'Pause 5 min !'
    assert client.post(f'/api/v1/live/{lid}/announce', json={'text': '   '}).status_code == 422
    assert client.post(f'/api/v1/live/{lid}/announce', json={'text': 'x' * 501}).status_code == 422
    assert client.post('/api/v1/live/inconnu/announce', json={'text': 'x'}).status_code == 404
    assert any(en['action'] == 'announce' for en in client.get('/api/v1/audit').json()['entries'])


# ── Planification (start_at) ───────────────────────────────────────────────

def test_start_planifie_activation_automatique(client):
    g, e, _, _ = make_event(client)
    # start_at invalide ou passé -> 422
    assert client.post('/api/v1/live/start', json={'group': g, 'title': e, 'start_at': 'pas-une-date'}).status_code == 422
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    assert client.post('/api/v1/live/start', json={'group': g, 'title': e, 'start_at': past}).status_code == 422
    # planification dans ~1.2 s (fuseau omitted -> UTC)
    future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=1.2)
    r = client.post('/api/v1/live/start', json={'group': g, 'title': e, 'start_at': future.isoformat()})
    assert r.status_code == 200, r.text
    live = r.json()
    assert live['status'] == 'scheduled' and live['join_url'].endswith(live['session_code'])
    assert any(s['id'] == live['live_id'] for s in client.get('/api/v1/live/scheduled').json()['scheduled'])
    assert client.get('/api/v1/live/active').json()['lives'] == []
    # join impossible tant que planifiée
    assert client.post('/api/v1/student/join', json={'session_code': live['session_code'], 'nom': 'A', 'prenom': 'B'}).status_code == 404
    # deuxième start sur le même événement -> 409 (scheduled comprise)
    assert client.post('/api/v1/live/start', json={'group': g, 'title': e}).status_code == 409
    time.sleep(1.8)
    assert client.get(f'/api/v1/live/{live["live_id"]}/status').json()['status'] == 'running'
    s = join(client, live['session_code'])
    assert client.get('/api/v1/student/current', headers=student_headers(s)).json()['status'] == 'running'
    assert client.get('/api/v1/live/scheduled').json()['scheduled'] == []


def test_annulation_et_rearmement_planification(tmp_path):
    with app_client(tmp_path) as c:
        g, e, _, _ = make_event(c)
        future = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
        live = c.post('/api/v1/live/start', json={'group': g, 'title': e, 'start_at': future}).json()
        # stop annule une session planifiée
        assert c.post(f'/api/v1/live/{live["live_id"]}/stop').status_code == 200
        assert c.get(f'/api/v1/live/{live["live_id"]}/status').json()['status'] == 'ended'
        assert c.get('/api/v1/live/scheduled').json()['scheduled'] == []
    # rearmement au redémarrage : session planifiée encore en attente, puis activée
    with app_client(tmp_path) as c:
        future = (datetime.now(timezone.utc) + timedelta(seconds=1.2)).isoformat()
        live = c.post('/api/v1/live/start', json={'group': g, 'title': e, 'start_at': future}).json()
    with app_client(tmp_path) as c2:  # "redémarrage" : réarmement via install_live_api
        assert any(s['id'] == live['live_id'] for s in c2.get('/api/v1/live/scheduled').json()['scheduled'])
        time.sleep(1.8)
        assert c2.get(f'/api/v1/live/{live["live_id"]}/status').json()['status'] == 'running'
        c2.post(f'/api/v1/live/{live["live_id"]}/stop')
    # activate() sans effet sur une session non planifiée
    with app_client(tmp_path) as c3:
        live2 = start_live(c3, g, e)
        store = c3.app.state.live_store
        assert store.activate(live2['live_id']) == {'activated': False, 'live_id': live2['live_id'], 'status': 'running'}
        # arm_scheduled : date illisible ou passée -> activation immédiate
        from classlive.live_api import arm_scheduled
        future = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
        e2 = c3.post('/api/v1/events', json={'group': g, 'title': 'Second'}).json()['title']
        c3.post(f'/api/v1/groups/{g}/events/{e2}/slides', json={'title': 'C', 'slide_type': 'C', 'content': '# c'})
        live4 = c3.post('/api/v1/live/start', json={'group': g, 'title': e2, 'start_at': future}).json()
        arm_scheduled(store, live4['live_id'], 'date-invalide')
        assert store.state(live4['live_id'])['status'] == 'running'
        e3 = c3.post('/api/v1/events', json={'group': g, 'title': 'Troisieme'}).json()['title']
        c3.post(f'/api/v1/groups/{g}/events/{e3}/slides', json={'title': 'C', 'slide_type': 'C', 'content': '# c'})
        past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        live5 = c3.post('/api/v1/live/start', json={'group': g, 'title': e3, 'start_at': future}).json()
        arm_scheduled(store, live5['live_id'], past)
        assert store.state(live5['live_id'])['status'] == 'running'


def test_planification_mode_autonome_deadline_a_activation(client):
    g, e, _, _ = make_event(client, kinds=('C', 'Q'))
    future = (datetime.now(timezone.utc) + timedelta(seconds=1.2)).isoformat()
    r = client.post('/api/v1/live/start', json={'group': g, 'title': e, 'mode': 'autonome',
                                                'timing': 'par_evenement', 'timing_seconds': 60,
                                                'correction': 'à_la_fin', 'start_at': future})
    assert r.status_code == 200
    lid = r.json()['live_id']
    assert client.get(f'/api/v1/live/{lid}/status').json()['deadline'] is None
    time.sleep(1.8)
    st = client.get(f'/api/v1/live/{lid}/status').json()
    assert st['status'] == 'running' and st['deadline'] is not None


# ── Exports CSV présence / questions / réactions ────────────────────────────

def test_exports_csv_complementaires(client):
    g, e, _, _ = make_event(client)
    live = start_live(client, g, e)
    lid = live['live_id']
    s = join(client, live['session_code'])
    h = student_headers(s)
    client.post(f'/api/v1/live/{lid}/next')
    client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['A']}})
    client.post('/api/v1/student/questions', headers=h, json={'text': 'Q ?'})
    client.post(f'/api/v1/live/{lid}/questions/1/answer', json={'text': 'R !'})
    client.post('/api/v1/student/reaction', headers=h, json={'emoji': '👍'})

    rows = list(csv.DictReader(io.StringIO(client.get(f'/api/v1/live/{lid}/presence.csv').content.decode('utf-8-sig')), delimiter=';'))
    assert rows[0]['nom'] == 'Dupont' and rows[0]['statut'] in ('connected', 'disconnected') and rows[0]['reponses'] == '1'
    assert client.get(f'/api/v1/live/{lid}/presence.csv').headers['content-disposition'].endswith('classlive_presence.csv"')

    rows = list(csv.DictReader(io.StringIO(client.get(f'/api/v1/live/{lid}/questions.csv').content.decode('utf-8-sig')), delimiter=';'))
    assert len(rows) == 1 and rows[0]['question'] == 'Q ?' and rows[0]['reponse'] == 'R !' and rows[0]['repondu'] == '1'

    rows = list(csv.DictReader(io.StringIO(client.get(f'/api/v1/live/{lid}/reactions.csv').content.decode('utf-8-sig')), delimiter=';'))
    assert rows == [{'live_id': lid, 'emoji': '👍', 'nombre': '1'}]

    for path in ('presence.csv', 'questions.csv', 'reactions.csv'):
        assert client.get(f'/api/v1/live/inconnu/{path}').status_code == 404


# ── Résultats élève sur tout un groupe (cross-événements) ───────────────────

def test_student_results_groupe_cross_evenements(client):
    g = client.post('/api/v1/groups', json={'group': 'Classe'}).json()['group']
    answers = []
    for i in (1, 2):
        e = client.post('/api/v1/events', json={'group': g, 'title': f'Cours {i}'}).json()['title']
        client.post(f'/api/v1/groups/{g}/events/{e}/slides', json={'title': 'Q', 'slide_type': 'Q', 'content': '# Q'})
        live = start_live(client, g, e)
        s = join(client, live['session_code'], 'Dupont', 'Marie')
        client.post(f'/api/v1/live/{live["live_id"]}/next')
        client.post('/api/v1/student/answers', headers=student_headers(s),
                    json={'answer': {'selected': [str(i)]}})
        answers.append({'selected': [str(i)]})
        client.post(f'/api/v1/live/{live["live_id"]}/stop')
    r = client.get(f'/api/v1/groups/{g}/student-results', params={'nom': 'Dupont', 'prenom': 'Marie'})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['total_answers'] == 2 and len(body['events']) == 2
    got = sorted(json.dumps(a['answers'][0]['answer'], sort_keys=True)
                 for ev in body['events'] for a in ev['sessions'])
    assert got == sorted(json.dumps(a, sort_keys=True) for a in answers)
    assert client.get(f'/api/v1/groups/{g}/student-results').status_code == 422
    assert client.get('/api/v1/groups/inconnu/student-results', params={'nom': 'A', 'prenom': 'B'}).status_code == 404


# ── Backup ZIP du workspace ─────────────────────────────────────────────────

def test_backup_zip_workspace(client, tmp_path):
    g, e, base, slides = make_event(client)
    os.symlink('/etc/hostname', tmp_path / 'lien.txt')  # symlink exclu de l'archive
    r = client.get('/api/v1/admin/backup.zip')
    assert r.status_code == 200 and r.headers['content-type'] == 'application/zip'
    assert 'classlive_backup_' in r.headers['content-disposition']
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert 'classlive.db' in names and any(n.startswith('Evts/') for n in names)
    assert 'lien.txt' not in names
    assert any(n.endswith(slides[0]) for n in names)
    assert any(en['action'] == 'backup' for en in client.get('/api/v1/audit').json()['entries'])


# ── Duplication de slide ────────────────────────────────────────────────────

def test_duplicate_slide(client, tmp_path):
    g, e, base, slides = make_event(client, kinds=('C', 'Q'))
    src = slides[1]
    r = client.post(f'{base}/{src}/duplicate')
    assert r.status_code == 200, r.text
    new = r.json()['new_slide']
    assert '_Q_' in new and new.endswith('_copie.md')
    assert client.get(f'{base}/{new}').json()['content'] == client.get(f'{base}/{src}').json()['content']
    # nom explicite + suffixe auto en cas de conflit
    r = client.post(f'{base}/{src}/duplicate', json={'new_title': 'Ma copie'})
    assert r.json()['new_slide'].endswith('_Ma_copie.md')
    r = client.post(f'{base}/{src}/duplicate', json={'new_title': 'Ma copie'})
    assert r.json()['new_slide'].endswith('_Ma_copie_2.md')
    assert client.post(f'{base}/S999_Q_Inconnue/duplicate').status_code == 404

    # branche suffixe > 100 via le store directement
    storage = EventStorage(tmp_path / 'slides', 'Evts')
    storage.init()
    storage.create_group('G')
    storage.create_event('G', 'E')
    sl = SlideStorage(storage)
    sl.create('G', 'E', 'T', 'C', '# t')
    for i in range(1, 101):
        sl.create('G', 'E', 'T_copie' if i == 1 else f'T_copie_{i}', 'C', '# c')
    with pytest.raises(ResourceConflict, match='nom de copie'):
        sl.duplicate('G', 'E', sl.list('G', 'E')['slides'][0])
    # OSError de copie -> StorageError
    import classlive.slides as slides_mod
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(slides_mod.shutil, 'copyfile', lambda *a, **k: (_ for _ in ()).throw(OSError('disk')))
    with pytest.raises(StorageError, match='disk'):
        sl.duplicate('G', 'E', sl.list('G', 'E')['slides'][0], 'Autre')
    monkeypatch.undo()
