"""Fonctionnalités v0.8.5 : RGPD, audit, export/import ZIP, multi-comptes, Q&A,
réactions emoji, limite d'élèves, rétention, stats d'usage, duplication de groupe,
historique des versions de slides, compteur d'élèves en ligne.

Ces tests n'écrivent que dans tmp_path et n'ouvrent aucun port réseau.
"""
import contextlib
import io
import json
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient

from classlive.api import create_app
from classlive.config import Settings
from classlive.live import LiveStore
from classlive.slides import SlideStorage
from classlive.storage import EventStorage


@contextlib.contextmanager
def app_client(tmp_path, **kwargs):
    kwargs.setdefault('trainer_password', 'test-password')
    app = create_app(Settings(workdir=tmp_path, **kwargs))
    with TestClient(app) as c:
        token = c.post('/api/v1/auth/login', json={'username': 'formateur', 'password': 'test-password'}).json()['access_token']
        c.headers.update({'Authorization': f'Bearer {token}'})
        yield c


@pytest.fixture
def client(tmp_path):
    with app_client(tmp_path) as c:
        yield c


def make_event(client, group='Cours', event='Chapitre 1', kinds=('C', 'Q')):
    g = client.post('/api/v1/groups', json={'group': group}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': event}).json()['title']
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    slides = []
    for i, kind in enumerate(kinds, 1):
        content = ('---\nclasslive_answer:\n  selected: [B]\n---\n' if kind != 'C' else '') + f'# Slide {i}'
        r = client.post(base, json={'title': f'Page {i}', 'slide_type': kind, 'content': content})
        assert r.status_code == 200, r.text
        slides.append(r.json()['slide'])
    return g, e, base, slides


def start_live(client, g, e, **payload):
    payload.setdefault('group', g)
    payload.setdefault('title', e)
    r = client.post('/api/v1/live/start', json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def join(client, code, nom='Dupont', prenom='Marie'):
    r = client.post('/api/v1/student/join', json={'session_code': code, 'nom': nom, 'prenom': prenom})
    assert r.status_code == 200, r.text
    return r.json()


def student_headers(student):
    return {'Authorization': 'Bearer ' + student['student_session_id']}


# ── Multi-comptes formateur ─────────────────────────────────────────────────

def test_multi_comptes_formateur(tmp_path):
    with app_client(tmp_path, trainer_accounts=(('prof2', 'motdepasse2'), ('prof3', 'autremotdepasse'))) as c:
        ok = c.post('/api/v1/auth/login', json={'username': 'prof2', 'password': 'motdepasse2'})
        assert ok.status_code == 200 and ok.json()['role'] == 'trainer'
        assert c.get('/api/v1/groups', headers={'Authorization': 'Bearer ' + ok.json()['access_token']}).status_code == 200
        assert c.post('/api/v1/auth/login', json={'username': 'prof2', 'password': 'mauvais'}).status_code == 401
        assert c.post('/api/v1/auth/login', json={'username': 'inconnu', 'password': 'motdepasse2'}).status_code == 401
        assert c.post('/api/v1/auth/login', json={'username': 'formateur', 'password': 'test-password'}).status_code == 200
        audit = c.get('/api/v1/audit').json()['entries']
        assert any(e['action'] == 'login_failed' and e['actor'] == 'prof2' for e in audit)
        assert any(e['action'] == 'login' and e['actor'] == 'prof2' for e in audit)


def test_comptes_secondaires_sans_mot_de_passe_principal(tmp_path):
    app = create_app(Settings(workdir=tmp_path, trainer_password=None,
                              trainer_accounts=(('prof2', 'motdepasse2'),)))
    with TestClient(app) as c:
        assert c.post('/api/v1/auth/login', json={'username': 'formateur', 'password': 'x'}).status_code == 401
        ok = c.post('/api/v1/auth/login', json={'username': 'prof2', 'password': 'motdepasse2'})
        assert ok.status_code == 200
        assert c.get('/api/v1/groups').status_code == 401


def test_login_sans_aucun_compte_configure(tmp_path):
    app = create_app(Settings(workdir=tmp_path, trainer_password=None))
    with TestClient(app) as c:
        assert c.post('/api/v1/auth/login', json={'username': 'formateur', 'password': 'x'}).status_code == 503


# ── Audit ───────────────────────────────────────────────────────────────────

def test_audit_db_et_fichier(tmp_path):
    with app_client(tmp_path) as c:
        g, e, _, _ = make_event(c)
        live = start_live(c, g, e)
        c.post(f'/api/v1/live/{live["live_id"]}/stop')
        entries = c.get('/api/v1/audit').json()['entries']
        actions = [e['action'] for e in entries]
        assert 'login' in actions and 'live_start' in actions and 'live_stop' in actions
        assert all(set(e) == {'ts', 'actor', 'action', 'detail'} for e in entries)
        # Limite du paramètre limit.
        assert len(c.get('/api/v1/audit?limit=1').json()['entries']) == 1
        assert c.get('/api/v1/audit?limit=0').status_code == 422
        assert c.get('/api/v1/audit?limit=1001').status_code == 422
        # Fichier d'audit JSON-lines.
        audit_file = tmp_path / 'audit.log'
        lines = [json.loads(l) for l in audit_file.read_text(encoding='utf-8').splitlines()]
        assert any(l['action'] == 'live_start' for l in lines)


def test_audit_desactive_pas_de_fichier_mais_db_ok(tmp_path):
    with app_client(tmp_path, audit_enabled=False) as c:
        assert not (tmp_path / 'audit.log').exists()
        assert any(e['action'] == 'login' for e in c.get('/api/v1/audit').json()['entries'])


def test_audit_fichier_illisible_ne_casse_pas(tmp_path):
    repertoire = tmp_path / 'audit_dir'
    repertoire.mkdir()
    with app_client(tmp_path, audit_file=repertoire) as c:  # open() sur un dossier -> OSError
        c.post('/api/v1/groups', json={'group': 'G'})
        assert any(e['action'] == 'login' for e in c.get('/api/v1/audit').json()['entries'])


# ── Droit à l'oubli (RGPD) ──────────────────────────────────────────────────

def test_forget_student_supprime_toutes_ses_donnees(client):
    g, e, _, slides = make_event(client)
    live = start_live(client, g, e)
    lid = live['live_id']
    a = join(client, live['session_code'], 'Dupont', 'Marie')
    b = join(client, live['session_code'], 'Martin', 'Paul')
    ha = student_headers(a)
    client.post(f'/api/v1/live/{lid}/next')
    assert client.post('/api/v1/student/answers', headers=ha, json={'answer': {'selected': ['B']}}).status_code == 200
    assert client.post('/api/v1/student/questions', headers=ha, json={'text': 'Pourquoi B ?'}).status_code == 200
    assert client.post('/api/v1/student/reaction', headers=ha, json={'emoji': '👍'}).status_code == 200
    assert len(client.get(f'/api/v1/live/{lid}/results').json()['results']) == 2

    r = client.delete(f'/api/v1/groups/{g}/events/{e}/students-data', params={'nom': 'Dupont', 'prenom': 'Marie'})
    assert r.status_code == 200, r.text
    assert r.json()['deleted_participations'] == 1
    results = client.get(f'/api/v1/live/{lid}/results').json()['results']
    assert len(results) == 1 and results[0]['nom'] == 'Martin'
    assert client.get(f'/api/v1/live/{lid}/questions').json()['questions'] == []
    assert client.get(f'/api/v1/live/{lid}/reactions').json()['total'] == 0
    # Le jeton de l'élève supprimé est invalide.
    assert client.get('/api/v1/student/current', headers=ha).status_code == 401
    # Second appel : plus rien à supprimer. Paramètres manquants : 422.
    r = client.delete(f'/api/v1/groups/{g}/events/{e}/students-data', params={'nom': 'Dupont', 'prenom': 'Marie'})
    assert r.json()['deleted_participations'] == 0
    assert client.delete(f'/api/v1/groups/{g}/events/{e}/students-data').status_code == 422
    assert client.delete('/api/v1/groups/inconnu/events/x/students-data',
                         params={'nom': 'A', 'prenom': 'B'}).status_code == 404
    assert any(e['action'] == 'forget_student' for e in client.get('/api/v1/audit').json()['entries'])


# ── Export / import ZIP ─────────────────────────────────────────────────────

def test_export_import_zip_aller_retour(client):
    g, e, base, slides = make_event(client, kinds=('C', 'Q', 'T'))
    r = client.get(f'/api/v1/groups/{g}/events/{e}/export.zip')
    assert r.status_code == 200
    assert r.headers['content-type'] == 'application/zip'
    assert 'attachment' in r.headers['content-disposition']
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
    assert manifest['format'] == 'classlive-event' and manifest['slides'] == slides
    for s in slides:
        assert s in zf.namelist()

    # Import dans un autre groupe (créé au passage).
    r = client.post('/api/v1/groups/Groupe Import/import.zip',
                    content=r.content, headers={'Content-Type': 'application/zip'})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['created'] is True and body['slides'] == slides
    g2 = body['group']
    e2 = body['event']
    assert e2 == e
    for s in slides:
        assert client.get(f'/api/v1/groups/{g2}/events/{e2}/slides/{s}').json()['content'] == \
            client.get(f'{base}/{s}').json()['content']
    # Le contenu privé (classlive_answer) est préservé dans le ZIP.
    assert 'classlive_answer' in zipfile.ZipFile(io.BytesIO(
        client.get(f'/api/v1/groups/{g2}/events/{e2}/export.zip').content)).read(slides[1]).decode('utf-8')
    # Import idempotent : réimporter le même ZIP crée l'événement existant (created=False).
    r = client.post('/api/v1/groups/Groupe Import/import.zip',
                    content=client.get(f'/api/v1/groups/{g}/events/{e}/export.zip').content)
    assert r.json()['created'] is False
    assert any(en['action'] == 'import_zip' for en in client.get('/api/v1/audit').json()['entries'])


def _zip_bytes(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


GOOD_MANIFEST = json.dumps({'format': 'classlive-event', 'version': 1, 'event': 'Cours',
                            'slides': ['S001_C_Intro.md']}).encode()


@pytest.mark.parametrize('files,attendu', [
    ({'manifest.json': GOOD_MANIFEST}, 'absente'),                  # slide listée absente du ZIP
    ({'autre.txt': b'x'}, 'manifest.json manquant'),
    ({'manifest.json': b'\xff\xfe invalide'}, 'illisible'),
    ({'manifest.json': json.dumps({'format': 'autre', 'event': 'X', 'slides': ['S001_C_Intro.md']}).encode(),
      'S001_C_Intro.md': b'# ok'}, 'invalide'),
    ({'manifest.json': json.dumps({'format': 'classlive-event', 'event': 'X', 'slides': ['pas une slide.md']}).encode(),
      'pas une slide.md': b'# ok'}, 'Sxxx'),
    ({'manifest.json': json.dumps({'format': 'classlive-event', 'event': 'X', 'slides': []}).encode()}, 'requise'),
    ({'manifest.json': json.dumps({'format': 'classlive-event', 'event': '', 'slides': ['S001_C_Intro.md']}).encode(),
      'S001_C_Intro.md': b'# ok'}, 'invalide'),
    ({'manifest.json': GOOD_MANIFEST, 'S001_C_Intro.md': b'\xff\xfe'}, 'utf8'),  # contenu slide non UTF-8
])
def test_import_zip_rejete_les_mauvais_fichiers(client, files, attendu):
    client.post('/api/v1/groups', json={'group': 'G'})
    r = client.post('/api/v1/groups/G/import.zip', content=_zip_bytes(files))
    assert r.status_code == 422, (attendu, r.status_code, r.text)
    assert client.get('/api/v1/groups/G/events').json()['events'] == []


def test_import_zip_corps_vide(client):
    client.post('/api/v1/groups', json={'group': 'G'})
    assert client.post('/api/v1/groups/G/import.zip', content=b'').status_code == 422


def test_import_zip_corrompu_et_trop_gros(client, tmp_path):
    assert client.post('/api/v1/groups/G/import.zip', content=b'ceci nest pas un zip').status_code == 422
    with app_client(tmp_path, export_max_zip_mb=0) as c:  # limite 0 -> tout ZIP non vide est trop gros
        r = c.post('/api/v1/groups/G/import.zip', content=b'x')
        assert r.status_code == 413
        # Corps streamé (sans Content-Length) dépassant la limite : 413 aussi.
        r = c.post('/api/v1/groups/G/import.zip', content=iter([b'x', b'y', b'z']))
        assert r.status_code == 413


def test_import_zip_entete_content_length_et_zip_bomb(tmp_path):
    with app_client(tmp_path, export_max_zip_mb=1) as c:
        c.post('/api/v1/groups', json={'group': 'G'})
        # En-tête Content-Length au-delà de la limite : refus 413 avant lecture du corps.
        r = c.post('/api/v1/groups/G/import.zip', content=b'x',
                   headers={'Content-Length': str(5 * 1024 * 1024)})
        assert r.status_code == 413, r.text
        # En-tête Content-Length illisible : 422.
        r = c.post('/api/v1/groups/G/import.zip', content=b'x', headers={'Content-Length': 'abc'})
        assert r.status_code == 422, r.text
        # Zip-bomb : petite archive compressée, mais > 1 Mo décompressé -> 413.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('manifest.json', GOOD_MANIFEST)
            zf.writestr('S001_C_Intro.md', b'#' * (2 * 1024 * 1024))
        r = c.post('/api/v1/groups/G/import.zip', content=buf.getvalue())
        assert r.status_code == 413, r.text
        assert c.get('/api/v1/groups/G/events').json()['events'] == []


# ── Duplication de groupe ───────────────────────────────────────────────────

def test_duplicate_group(client):
    g, e, base, slides = make_event(client, group='Original', event='Cours A')
    _, e2, _, _ = make_event(client, group=g, event='Cours B', kinds=('Q',))
    r = client.post(f'/api/v1/groups/{g}/duplicate')
    assert r.status_code == 200, r.text
    g2 = r.json()['new_name']
    assert g2 != g and g2.endswith('_copie')
    events = client.get(f'/api/v1/groups/{g2}/events').json()['events']
    assert sorted(events) == sorted([e, e2])
    s2 = client.get(f'/api/v1/groups/{g2}/events/{e}/slides').json()['slides']
    assert s2 == slides
    assert client.get(f'/api/v1/groups/{g2}/events/{e}/slides/{slides[1]}').json()['content'] == \
        client.get(f'{base}/{slides[1]}').json()['content']
    # Nom explicite + suffixe automatique en cas de conflit (accents normalisés).
    r = client.post(f'/api/v1/groups/{g}/duplicate', json={'new_title': 'Copie nommée'})
    g3 = r.json()['new_name']
    assert 'Copie_nommee' in g3
    r = client.post(f'/api/v1/groups/{g}/duplicate', json={'new_title': 'Copie nommée'})
    assert r.json()['new_name'] != g3 and 'Copie_nommee_2' in r.json()['new_name']
    assert client.post('/api/v1/groups/inconnu/duplicate').status_code == 404


def test_duplicate_group_suffixe_epuise_et_erreur_copie(tmp_path, monkeypatch):
    import classlive.storage as storage_mod
    from classlive.storage import ResourceConflict, StorageError
    storage = EventStorage(tmp_path, 'Evts')
    storage.init()
    storage.create_group('Original')
    for i in range(1, 101):  # occupe Original_copie, Original_copie_2 ... Original_copie_100
        storage.create_group('Original_copie' if i == 1 else f'Original_copie_{i}')
    with pytest.raises(ResourceConflict, match='nom de copie'):
        storage.duplicate_group('Original')

    def boom(*a, **k):
        raise OSError('disque plein')
    monkeypatch.setattr(storage_mod.shutil, 'copytree', boom)
    with pytest.raises(StorageError, match='disque plein'):
        storage.duplicate_group('Original', 'Autre')


# ── Historique des versions de slides ───────────────────────────────────────

def test_versions_slides_cycle_complet(client):
    g, e, base, slides = make_event(client, kinds=('C',))
    slide = slides[0]
    v = client.get(f'{base}/{slide}/versions').json()
    assert v['versions'] == []  # aucune édition pour l'instant
    for i in range(1, 4):
        assert client.put(f'{base}/{slide}/content', json={'content': f'# v{i}'}).status_code == 200
    versions = client.get(f'{base}/{slide}/versions').json()['versions']
    assert len(versions) == 3  # l'état initial est archivé à chaque PUT
    assert versions[0]['size'] > 0
    # versions triées de la plus récente à la plus ancienne : [v2, v1, initiale]
    vid = versions[1]['id']
    version = client.get(f'{base}/{slide}/versions/{vid}').json()
    assert version['content'] == '# v1'
    assert version['actor'] == 'formateur'
    # Restaure v1 : le contenu courant (v3) est archivé puis remplacé.
    r = client.post(f'{base}/{slide}/versions/{vid}/restore')
    assert r.status_code == 200 and r.json()['restored_version'] == vid
    assert client.get(f'{base}/{slide}').json()['content'] == '# v1'
    assert len(client.get(f'{base}/{slide}/versions').json()['versions']) == 4
    # Restaurer la version déjà courante (v1) n'archive rien de plus.
    client.post(f'{base}/{slide}/versions/{vid}/restore')
    assert len(client.get(f'{base}/{slide}/versions').json()['versions']) == 4
    # Un PUT avec un contenu identique n'archive pas de nouvelle version.
    client.put(f'{base}/{slide}/content', json={'content': '# v1'})
    assert len(client.get(f'{base}/{slide}/versions').json()['versions']) == 4
    assert any(en['action'] == 'slide_restore' for en in client.get('/api/v1/audit').json()['entries'])


def test_versions_slides_plafonne_a_50_et_erreurs(client):
    g, e, base, slides = make_event(client, kinds=('C',))
    slide = slides[0]
    for i in range(60):
        client.put(f'{base}/{slide}/content', json={'content': f'# edit {i}'})
    versions = client.get(f'{base}/{slide}/versions').json()['versions']
    assert len(versions) == 50
    assert client.get(f'{base}/{slide}/versions/999999').status_code == 404
    assert client.get(f'{base}/S999_C_Inconnue/versions').status_code == 404
    assert client.post(f'{base}/S999_C_Inconnue/versions/1/restore').status_code == 404
    assert client.get(f'/api/v1/groups/inconnu/events/x/slides/{slide}/versions').status_code == 404


# ── Limite d'élèves et rétention ────────────────────────────────────────────

def test_max_students_limite_le_join(tmp_path):
    with app_client(tmp_path, max_students=1) as c:
        g, e, _, _ = make_event(c)
        live = start_live(c, g, e)
        join(c, live['session_code'])
        r = c.post('/api/v1/student/join', json={'session_code': live['session_code'], 'nom': 'A', 'prenom': 'B'})
        assert r.status_code == 409 and 'pleine' in r.json()['detail']


def test_max_students_zero_illimite(tmp_path):
    with app_client(tmp_path, max_students=0) as c:
        g, e, _, _ = make_event(c)
        live = start_live(c, g, e)
        for i in range(5):
            join(c, live['session_code'], f'Nom{i}', f'Prenom{i}')
        assert len(c.get(f'/api/v1/live/{live["live_id"]}/students').json()['students']) == 5


def test_join_rate_limit_anti_bruteforce(tmp_path):
    with app_client(tmp_path, join_rate_limit=3) as c:
        g, e, _, _ = make_event(c)
        live = start_live(c, g, e)
        code = live['session_code']
        for i in range(3):
            r = c.post('/api/v1/student/join', json={'session_code': code, 'nom': f'N{i}', 'prenom': 'P'})
            assert r.status_code == 200, r.text
        r = c.post('/api/v1/student/join', json={'session_code': code, 'nom': 'N', 'prenom': 'P'})
        assert r.status_code == 429
        # Le rate limit ne bloque pas les autres routes publiques.
        assert c.get('/health').status_code == 200
    with app_client(tmp_path / 'sans-limite', join_rate_limit=0) as c:  # désactivé
        g, e, _, _ = make_event(c)
        live = start_live(c, g, e)
        for i in range(10):
            assert c.post('/api/v1/student/join', json={
                'session_code': live['session_code'], 'nom': f'N{i}', 'prenom': 'P'}).status_code == 200


def test_purge_retention_manuel_et_au_demarrage(tmp_path):
    with app_client(tmp_path, retention_days=30) as c:
        g, e, _, _ = make_event(c)
        live = start_live(c, g, e)
        c.post(f'/api/v1/live/{live["live_id"]}/stop')
        with sqlite3.connect(tmp_path / 'classlive.db') as con:
            con.execute("UPDATE live_sessions SET ended_at='2000-01-01T00:00:00+00:00'")
        con.close()
        r = c.post('/api/v1/admin/purge')
        assert r.status_code == 200 and r.json()['deleted_sessions'] == 1
        assert c.get(f'/api/v1/groups/{g}/events/{e}/sessions').json()['sessions'] == []
        assert c.post('/api/v1/admin/purge').json()['deleted_sessions'] == 0
        assert any(en['action'] == 'purge' for en in c.get('/api/v1/audit').json()['entries'])
    # Une session récente n'est pas purgée ; une ancienne session est purgée au démarrage.
    with app_client(tmp_path, retention_days=30) as c:
        live = start_live(c, g, e)
        c.post(f'/api/v1/live/{live["live_id"]}/stop')
        with sqlite3.connect(tmp_path / 'classlive.db') as con:
            con.execute("UPDATE live_sessions SET ended_at='2000-01-01T00:00:00+00:00'")
        con.close()
    with app_client(tmp_path, retention_days=30) as c2:  # purge au démarrage de create_app
        assert c2.get(f'/api/v1/groups/{g}/events/{e}/sessions').json()['sessions'] == []
    with app_client(tmp_path, retention_days=0) as c3:  # rétention désactivée : rien n'est purgé
        live = start_live(c3, g, e)
        c3.post(f'/api/v1/live/{live["live_id"]}/stop')
        with sqlite3.connect(tmp_path / 'classlive.db') as con:
            con.execute("UPDATE live_sessions SET ended_at='2000-01-01T00:00:00+00:00'")
        con.close()
        assert c3.post('/api/v1/admin/purge').json()['deleted_sessions'] == 0
        assert len(c3.get(f'/api/v1/groups/{g}/events/{e}/sessions').json()['sessions']) == 1


# ── Stats d'usage ───────────────────────────────────────────────────────────

def test_usage_stats(client):
    g, e, _, _ = make_event(client)
    live = start_live(client, g, e)
    s = join(client, live['session_code'])
    client.post(f'/api/v1/live/{live["live_id"]}/next')
    client.post('/api/v1/student/answers', headers=student_headers(s), json={'answer': {'selected': ['A']}})
    client.post('/api/v1/student/questions', headers=student_headers(s), json={'text': 'Question ?'})
    client.post('/api/v1/student/reaction', headers=student_headers(s), json={'emoji': '🔥'})
    stats = client.get('/api/v1/stats/usage').json()
    assert stats['groups'] == 1 and stats['events'] == 1
    assert stats['sessions'] == {'total': 1, 'running': 1, 'ended': 0}
    assert stats['participations'] == 1 and stats['answers'] == 1
    assert stats['questions'] == 1 and stats['reactions'] == 1
    assert stats['per_event'] == [{'group_name': g, 'event_name': e, 'sessions': 1, 'ended': 0}]


# ── Q&A élève ───────────────────────────────────────────────────────────────

def test_qa_cycle_complet_et_erreurs(client):
    g, e, _, _ = make_event(client)
    live = start_live(client, g, e)
    lid = live['live_id']
    s = join(client, live['session_code'])
    h = student_headers(s)
    r = client.post('/api/v1/student/questions', headers=h, json={'text': '  Pourquoi B ?  '})
    assert r.status_code == 200 and r.json()['success'] is True
    qid = r.json()['question_id']
    mine = client.get('/api/v1/student/questions', headers=h).json()['questions']
    assert len(mine) == 1 and mine[0]['text'] == 'Pourquoi B ?' and mine[0]['answered'] == 0
    all_q = client.get(f'/api/v1/live/{lid}/questions').json()['questions']
    assert all_q[0]['nom'] == 'Dupont' and all_q[0]['id'] == qid
    # Réponse du formateur visible par l'élève.
    r = client.post(f'/api/v1/live/{lid}/questions/{qid}/answer', json={'text': ' Parce que. '})
    assert r.status_code == 200 and r.json()['answer_text'] == 'Parce que.'
    mine = client.get('/api/v1/student/questions', headers=h).json()['questions']
    assert mine[0]['answered'] == 1 and mine[0]['answer_text'] == 'Parce que.'
    # Toggle answered.
    assert client.post(f'/api/v1/live/{lid}/questions/{qid}/toggle').json()['answered'] is False
    assert client.post(f'/api/v1/live/{lid}/questions/{qid}/toggle').json()['answered'] is True
    # Erreurs.
    assert client.post('/api/v1/student/questions', headers=h, json={'text': '   '}).status_code == 422
    assert client.post('/api/v1/student/questions', headers=h, json={'text': 'x' * 1001}).status_code == 422
    assert client.post(f'/api/v1/live/{lid}/questions/{qid}/answer', json={'text': ''}).status_code == 422
    assert client.post(f'/api/v1/live/{lid}/questions/{qid}/answer', json={'text': 'x' * 2001}).status_code == 422
    assert client.post(f'/api/v1/live/{lid}/questions/9999/answer', json={'text': 'x'}).status_code == 404
    assert client.post(f'/api/v1/live/{lid}/questions/9999/toggle').status_code == 404
    assert client.get(f'/api/v1/live/{lid}/questions').status_code == 200
    assert client.get('/api/v1/live/inconnu/questions').status_code == 404
    # Limite de 50 questions par élève.
    for _ in range(49):
        assert client.post('/api/v1/student/questions', headers=h, json={'text': 'q'}).status_code == 200
    r = client.post('/api/v1/student/questions', headers=h, json={'text': 'une de trop'})
    assert r.status_code == 409
    # Session terminée : le jeton étudiant est révoqué (401), plus de question possible.
    client.post(f'/api/v1/live/{lid}/stop')
    assert client.post('/api/v1/student/questions', headers=h, json={'text': 'encore ?'}).status_code == 401


# ── Réactions emoji ─────────────────────────────────────────────────────────

def test_reactions_cycle_complet_et_erreurs(client):
    g, e, _, _ = make_event(client)
    live = start_live(client, g, e)
    lid = live['live_id']
    s1 = join(client, live['session_code'], 'Un', 'Eleve')
    s2 = join(client, live['session_code'], 'Deux', 'Eleve')
    r = client.post('/api/v1/student/reaction', headers=student_headers(s1), json={'emoji': ' 👍 '})
    assert r.status_code == 200 and r.json()['counts'] == {'👍': 1}
    client.post('/api/v1/student/reaction', headers=student_headers(s1), json={'emoji': '👍'})
    client.post('/api/v1/student/reaction', headers=student_headers(s2), json={'emoji': '😀'})
    r = client.get(f'/api/v1/live/{lid}/reactions')
    assert r.json() == {'live_id': lid, 'total': 3, 'counts': {'👍': 2, '😀': 1}}
    assert client.post('/api/v1/student/reaction', headers=student_headers(s1), json={'emoji': '  '}).status_code == 422
    assert client.post('/api/v1/student/reaction', headers=student_headers(s1), json={'emoji': '123456789'}).status_code == 422
    assert client.get('/api/v1/live/inconnu/reactions').status_code == 404
    client.post(f'/api/v1/live/{lid}/stop')
    assert client.post('/api/v1/student/reaction', headers=student_headers(s1), json={'emoji': '👍'}).status_code == 401


# ── Compteur d'élèves en ligne ──────────────────────────────────────────────

def test_online_compte_les_websockets_actifs(client):
    g, e, _, _ = make_event(client)
    live = start_live(client, g, e)
    s = join(client, live['session_code'])
    h = student_headers(s)
    assert client.get('/api/v1/student/current', headers=h).json()['online'] == 0
    with client.websocket_connect('/api/v1/student/ws') as ws:
        ws.send_json({'token': s['student_session_id']})
        greeting = ws.receive_json()
        assert greeting['event'] == 'current' and greeting['current']['online'] == 1
        assert client.get('/api/v1/student/current', headers=h).json()['online'] == 1
        ws.send_json({'event': 'ping'})
        assert ws.receive_json() == {'event': 'pong'}
    assert client.get('/api/v1/student/current', headers=h).json()['online'] == 0


def test_online_repli_sur_last_seen_sans_hub(tmp_path):
    """Sans online_counter installé (Hub), student_state compte les last_seen récents."""
    storage = EventStorage(tmp_path, 'Evts')
    storage.init()
    slides = SlideStorage(storage)
    store = LiveStore(tmp_path / 'classlive.db', slides)
    assert store.online_counter is None
    storage.create_group('G')
    storage.create_event('G', 'E')
    slides.create('G', 'E', 'Intro', 'C', '# Hello')
    live = store.start('G', 'E')
    student = store.join(live['session_code'], 'Nom', 'Prenom')
    assert student['current']['online'] == 1  # join vient de mettre à jour last_seen
    # Branches "session terminée" de Q&A/réactions, atteignables hors HTTP (auth révoque le jeton).
    from classlive.storage import ResourceConflict
    store.stop(live['live_id'])
    with pytest.raises(ResourceConflict):
        store.ask_question(student, 'encore ?')
    with pytest.raises(ResourceConflict):
        store.react(student, '👍')
