"""Tests des cas limites : validation config, tailles, expiration, limites internes.

Ces tests n'ouvrent aucun port réseau et n'écrivent que dans tmp_path.
Objectif : porter la couverture au-delà de 90 % et verrouiller les comportements
de sécurité (rate limiting viendra en Phase 3, expiration des jetons, etc.).
"""
import sqlite3
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from classlive.api import create_app
from classlive.config import Settings, load_settings
from classlive.navigation import SlideNavigator
from classlive.slides import SlideStorage
from classlive.storage import EventStorage


# ── Configuration : tous les cas d'erreur YAML ──────────────────────────────

def _write_cfg(tmp_path, body: str):
    cfg = tmp_path / "config.yml"
    cfg.write_text(body, encoding="utf-8")
    return cfg


def test_config_manquante(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "inexistant.yml")


def test_config_racine_non_dict(tmp_path):
    cfg = _write_cfg(tmp_path, "- item\n- autre\n")
    with pytest.raises(ValueError, match="objet YAML"):
        load_settings(cfg)


def test_config_section_non_dict(tmp_path):
    cfg = _write_cfg(tmp_path, 'classlive: "pas un dict"\n')
    with pytest.raises(ValueError, match="objet YAML"):
        load_settings(cfg)


def test_config_workdir_absent(tmp_path):
    cfg = _write_cfg(tmp_path, 'classlive:\n  storage:\n    events_dir: "Evts"\n')
    with pytest.raises(ValueError, match="workdir"):
        load_settings(cfg)


def test_config_workdir_vide(tmp_path):
    cfg = _write_cfg(tmp_path, 'classlive:\n  storage:\n    workdir: "  "\n')
    with pytest.raises(ValueError, match="workdir"):
        load_settings(cfg)


def test_config_workdir_non_absolu(tmp_path):
    cfg = _write_cfg(tmp_path, 'classlive:\n  storage:\n    workdir: "relatif/chemin"\n')
    with pytest.raises(ValueError, match="absolu"):
        load_settings(cfg)


def test_config_events_dir_ancien_nom(tmp_path):
    cfg = _write_cfg(tmp_path, 'classlive:\n  storage:\n    workdir: "/tmp/x"\n    events_dir: "événements"\n')
    assert load_settings(cfg).events_root.name == "Evts"


def test_config_events_dir_interdit(tmp_path):
    cfg = _write_cfg(tmp_path, 'classlive:\n  storage:\n    workdir: "/tmp/x"\n    events_dir: "Autre"\n')
    with pytest.raises(ValueError, match="Evts"):
        load_settings(cfg)


def test_config_host_invalide(tmp_path):
    cfg = _write_cfg(tmp_path, 'classlive:\n  server:\n    host: ""\n  storage:\n    workdir: "/tmp/x"\n')
    with pytest.raises(ValueError, match="host"):
        load_settings(cfg)


def test_config_port_hors_range(tmp_path):
    for yaml_port in ('0', '65536', '"8080"', '3.14', 'true'):
        cfg = _write_cfg(tmp_path, f'classlive:\n  server:\n    port: {yaml_port}\n  storage:\n    workdir: "/tmp/x"\n')
        with pytest.raises(ValueError, match="port"):
            load_settings(cfg)


def test_config_log_level_invalide(tmp_path):
    cfg = _write_cfg(tmp_path, 'classlive:\n  logging:\n    level: "TRACE"\n  storage:\n    workdir: "/tmp/x"\n')
    with pytest.raises(ValueError, match="level"):
        load_settings(cfg)


def test_config_api_key_vide_rejete(tmp_path):
    cfg = _write_cfg(tmp_path, 'classlive:\n  security:\n    api_key: "  "\n  storage:\n    workdir: "/tmp/x"\n')
    with pytest.raises(ValueError, match="api_key"):
        load_settings(cfg)


def test_config_trainer_username_vide_rejete(tmp_path):
    cfg = _write_cfg(tmp_path, 'classlive:\n  security:\n    trainer_username: ""\n  storage:\n    workdir: "/tmp/x"\n')
    with pytest.raises(ValueError, match="trainer_username"):
        load_settings(cfg)


def test_config_ok_avec_tous_champs(tmp_path):
    cfg = _write_cfg(tmp_path, (
        'classlive:\n'
        '  server:\n    host: "127.0.0.1"\n    port: 9090\n'
        '  storage:\n    workdir: "/tmp/classlive-test-ok"\n'
        '  logging:\n    level: "debug"\n'
        '  security:\n    trainer_username: "prof"\n    api_key: "cle"\n'
    ))
    s = load_settings(cfg)
    assert s.host == "127.0.0.1"
    assert s.port == 9090
    assert s.log_level == "DEBUG"
    assert s.trainer_username == "prof"
    assert s.api_key == "cle"


# ── Limites de taille ────────────────────────────────────────────────────────

def test_slide_content_trop_grande_rejetee(client):
    g = client.post('/api/v1/groups', json={'group': 'G'}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': 'E'}).json()['title']
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    big = 'A' * (2_000_001)
    r = client.post(base, json={'title': 'TropGros', 'slide_type': 'C', 'content': big})
    assert r.status_code == 422


def test_slide_content_limite_exacte_acceptee(client):
    g = client.post('/api/v1/groups', json={'group': 'G'}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': 'E'}).json()['title']
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    # 2 Mo exactement en UTF-8 (ASCII = 1 octet/car)
    ok = 'A' * 2_000_000
    r = client.post(base, json={'title': 'Limite', 'slide_type': 'C', 'content': ok})
    assert r.status_code == 200


def test_reponse_64kio_limite(client):
    g = client.post('/api/v1/groups', json={'group': 'G'}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': 'E'}).json()['title']
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    client.post(base, json={'title': 'Q', 'slide_type': 'Q', 'content': '# Q'})
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    s = client.post('/api/v1/student/join', json={
        'session_code': live['session_code'], 'nom': 'A', 'prenom': 'B'}).json()
    h = {'Authorization': 'Bearer ' + s['student_session_id']}
    # 64 Ko pile : accepté ; 64 Ko + 1 : rejeté
    ok = {'answer': {'text': 'x' * 65500}}
    r_ok = client.post('/api/v1/student/answers', headers=h, json=ok)
    assert r_ok.status_code == 200
    too_big = {'answer': {'text': 'x' * 66000}}
    r_ko = client.post('/api/v1/student/answers', headers=h, json=too_big)
    assert r_ko.status_code == 422


# ── Limite interne : 10 000 sessions /player ─────────────────────────────────

def test_player_session_limit(tmp_path):
    storage = EventStorage(tmp_path)
    storage.init()
    slides = SlideStorage(storage)
    nav = SlideNavigator(slides)
    g = storage.create_group('G')['group']
    e = storage.create_event(g, 'E')['title']
    slides.create(g, e, 'S1', 'C', '# contenu')
    # Remplir artificiellement jusqu'à la limite
    nav._sessions = {f's{i}': (g, e, 1) for i in range(10000)}
    with pytest.raises(Exception, match="maximal"):
        nav.select(g, e)


# ── Expiration du jeton formateur (8 h) ──────────────────────────────────────

def test_trainer_token_expire_apres_8h(client):
    from classlive.live_api import Auth
    auth = client.app.state.live_auth
    # Simuler un jeton créé il y a plus de 8h
    auth.trainers['vieux-jeton'] = time.monotonic() - 8 * 3600 - 1
    assert auth.valid_trainer('vieux-jeton') is False
    assert 'vieux-jeton' not in auth.trainers
    # Un jeton récent reste valide
    r = client.post('/api/v1/auth/login', json={'username': 'formateur', 'password': 'test-password'})
    token = r.json()['access_token']
    assert auth.valid_trainer(token) is True


def test_trainer_token_invalide_requete_rejetee(client):
    r = client.get('/api/v1/groups', headers={'Authorization': 'Bearer jeton-faux'})
    assert r.status_code == 401


# ── Plusieurs moniteurs formateur simultanés ─────────────────────────────────

def test_plusieurs_moniteurs_ws_recoivent_les_memes_events(client):
    g = client.post('/api/v1/groups', json={'group': 'G'}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': 'E'}).json()['title']
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    client.post(base, json={'title': 'Q', 'slide_type': 'Q', 'content': '# Q1'})
    client.post(base, json={'title': 'C', 'slide_type': 'C', 'content': '# C2'})
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    lid = live['live_id']
    trainer_token = client.headers['Authorization'].split(' ', 1)[1]
    with client.websocket_connect(f'/api/v1/live/{lid}/monitor') as m1:
        m1.send_json({'token': trainer_token})
        assert m1.receive_json()['event'] == 'monitor'
        with client.websocket_connect(f'/api/v1/live/{lid}/monitor') as m2:
            m2.send_json({'token': trainer_token})
            assert m2.receive_json()['event'] == 'monitor'
            client.post(f'/api/v1/live/{lid}/next')
            e1 = m1.receive_json()
            e2 = m2.receive_json()
            assert e1['event'] == 'slide_changed' == e2['event']
            assert e1['current']['number'] == e2['current']['number'] == 2


# ── Caractères de contrôle dans nom/prénom étudiant ─────────────────────────

@pytest.mark.parametrize('bad', ['\x00', 'a\x00b', 'x\x00y\x00z'])
def test_nom_prenom_avec_controle_rejetes(client, bad):
    g = client.post('/api/v1/groups', json={'group': 'G'}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': 'E'}).json()['title']
    client.post(f'/api/v1/groups/{g}/events/{e}/slides', json={'title': 'S', 'slide_type': 'C', 'content': '# S'})
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    r = client.post('/api/v1/student/join', json={
        'session_code': live['session_code'], 'nom': bad, 'prenom': 'Marie'})
    assert r.status_code == 422
    r2 = client.post('/api/v1/student/join', json={
        'session_code': live['session_code'], 'nom': 'Marie', 'prenom': bad})
    assert r2.status_code == 422


# ── Goto sur slide inexistante / Live terminé ────────────────────────────────

def test_goto_slide_inexistante_pendant_live(client):
    g = client.post('/api/v1/groups', json={'group': 'G'}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': 'E'}).json()['title']
    client.post(f'/api/v1/groups/{g}/events/{e}/slides', json={'title': 'S', 'slide_type': 'C', 'content': '# S'})
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    r = client.post(f"/api/v1/live/{live['live_id']}/goto", json={'number': 999})
    assert r.status_code == 404


def test_goto_apres_stop_live(client):
    g = client.post('/api/v1/groups', json={'group': 'G'}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': 'E'}).json()['title']
    client.post(f'/api/v1/groups/{g}/events/{e}/slides', json={'title': 'S', 'slide_type': 'C', 'content': '# S'})
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    lid = live['live_id']
    client.post(f'/api/v1/live/{lid}/stop')
    r = client.post(f'/api/v1/live/{lid}/goto', json={'number': 1})
    assert r.status_code == 409
    r2 = client.post(f'/api/v1/live/{lid}/next')
    assert r2.status_code == 409
    r3 = client.post(f'/api/v1/live/{lid}/correction/show')
    assert r3.status_code == 409


# ── __main__.py : démarrage avec config invalide ─────────────────────────────

def test_main_config_invalide_quitte_proprement(tmp_path, monkeypatch):
    from classlive.__main__ import main
    cfg = tmp_path / "config.yml"
    cfg.write_text('classlive:\n  storage:\n    workdir: "relatif"\n', encoding="utf-8")
    monkeypatch.setenv('CLASSLIVE_CONFIG', str(cfg))
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_config_absente_quitte_proprement(tmp_path, monkeypatch):
    from classlive.__main__ import main
    monkeypatch.setenv('CLASSLIVE_CONFIG', str(tmp_path / "absent.yml"))
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


# ── Compteurs corrompus ──────────────────────────────────────────────────────

def test_compteurs_corrompus_rejetes(tmp_path):
    storage = EventStorage(tmp_path)
    storage.init()
    storage._counters.write_text('{"group": "pas un int", "event": 0}', encoding='utf-8')
    with pytest.raises(Exception, match="Compteurs"):
        storage.create_group('Nouveau')


def test_compteurs_json_invalide_rejetes(tmp_path):
    storage = EventStorage(tmp_path)
    storage.init()
    storage._counters.write_text('pas du json{{{', encoding='utf-8')
    with pytest.raises(Exception, match="Compteurs"):
        storage.create_group('Nouveau')


# ── Stockage : événement sans slides ne peut pas démarrer de Live ────────────

def test_live_sans_slides_refuse(client):
    g = client.post('/api/v1/groups', json={'group': 'Vide'}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': 'SansSlides'}).json()['title']
    r = client.post('/api/v1/live/start', json={'group': g, 'title': e})
    assert r.status_code == 409


# ── Rate limiting sur /auth/login ────────────────────────────────────────────

def test_rate_limiting_login_apres_5_tentatives(client):
    auth = client.app.state.live_auth
    auth._login_attempts.clear()  # ignorer le login du fixture
    for i in range(5):
        r = client.post('/api/v1/auth/login', json={'username': 'formateur', 'password': 'mauvais'})
        assert r.status_code == 401, f'tentative {i+1}: {r.status_code}'
    r = client.post('/api/v1/auth/login', json={'username': 'formateur', 'password': 'mauvais'})
    assert r.status_code == 429
    assert 'Trop de tentatives' in r.json()['detail']


def test_rate_limiting_reset_apres_fenetre(client):
    from classlive.live_api import Auth
    auth = client.app.state.live_auth
    # Simuler 5 tentatives il y a plus de 60s
    auth._login_attempts['testclient'] = [time.monotonic() - 61] * 5
    r = client.post('/api/v1/auth/login', json={'username': 'formateur', 'password': 'test-password'})
    assert r.status_code == 200


def test_login_ok_compte_pas_dans_rate_limit(client):
    # Une connexion réussie ne doit pas être bloquée ensuite
    for _ in range(3):
        r = client.post('/api/v1/auth/login', json={'username': 'formateur', 'password': 'test-password'})
        assert r.status_code == 200


# ── Health check avec base de données ────────────────────────────────────────

def test_health_avec_database_ok(client):
    h = client.get('/health').json()
    assert h['status'] == 'ok'
    assert h['database'] is True


# ── Stats agrégées (style Wooclap, sans identité) ────────────────────────────

def test_stats_qcm_agrege_par_option(client):
    g = client.post('/api/v1/groups', json={'group': 'Stats'}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': 'QCM'}).json()['title']
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    client.post(base, json={'title': 'Intro', 'slide_type': 'C', 'content': '# Intro'})
    client.post(base, json={'title': 'Question', 'slide_type': 'Q',
                            'content': '# Q\n- A\n- B\n- C'})
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    lid = live['live_id']
    # Sur slide C (intro) : pas d'agrégation, juste le total
    s = client.get(f'/api/v1/live/{lid}/stats').json()
    assert s['answered'] == 0 and s['total_students'] == 0 and 'options' not in s
    client.post(f'/api/v1/live/{lid}/next')  # aller au QCM
    tokens = []
    for i, reponse in enumerate([['A'], ['B'], ['B'], ['A', 'B']]):
        st = client.post('/api/v1/student/join', json={
            'session_code': live['session_code'], 'nom': f'N{i}', 'prenom': f'P{i}'}).json()
        h = {'Authorization': 'Bearer ' + st['student_session_id']}
        assert client.post('/api/v1/student/answers', headers=h,
                           json={'answer': {'selected': reponse}}).status_code == 200
        tokens.append(st)
    s = client.get(f'/api/v1/live/{lid}/stats').json()
    assert s['slide_type'] == 'Q'
    assert s['answered'] == 4
    assert s['total_students'] == 4
    assert s['options'] == {'A': 2, 'B': 3}
    # Aucune identité dans les stats
    assert 'nom' not in str(s) and 'participation_id' not in str(s)


def test_stats_non_qcm_total_seul(client):
    g = client.post('/api/v1/groups', json={'group': 'StatsT'}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': 'Texte'}).json()['title']
    client.post(f'/api/v1/groups/{g}/events/{e}/slides', json={
        'title': 'Trou', 'slide_type': 'T', 'content': '# Complétez'})
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    lid = live['live_id']
    for i in range(3):
        st = client.post('/api/v1/student/join', json={
            'session_code': live['session_code'], 'nom': f'N{i}', 'prenom': 'P'}).json()
        h = {'Authorization': 'Bearer ' + st['student_session_id']}
        client.post('/api/v1/student/answers', headers=h, json={'answer': {'blanks': ['Paris']}})
    s = client.get(f'/api/v1/live/{lid}/stats').json()
    assert s['slide_type'] == 'T'
    assert s['answered'] == 3 and s['total_students'] == 3
    assert 'options' not in s


def test_stats_requiert_auth_formateur(client):
    g = client.post('/api/v1/groups', json={'group': 'G'}).json()['group']
    e = client.post('/api/v1/events', json={'group': g, 'title': 'E'}).json()['title']
    client.post(f'/api/v1/groups/{g}/events/{e}/slides', json={'title': 'S', 'slide_type': 'C', 'content': '# S'})
    live = client.post('/api/v1/live/start', json={'group': g, 'title': e}).json()
    assert client.get(f'/api/v1/live/{live["live_id"]}/stats').status_code == 200  # fixture a le token
    # Sans token
    import httpx
    r = client.get(f'/api/v1/live/{live["live_id"]}/stats', headers={'Authorization': ''})
    assert r.status_code == 401


def test_stats_live_inexistant(client):
    assert client.get('/api/v1/live/inconnu/stats').status_code == 404


# ── Health check avec base cassée ────────────────────────────────────────────

def test_health_database_cassee(tmp_path):
    from fastapi.testclient import TestClient
    from classlive.api import create_app
    from classlive.config import Settings
    # Créer l'app avec une DB valide, puis corrompre le fichier ensuite
    app = create_app(Settings(workdir=tmp_path, trainer_password='x'))
    db = tmp_path / 'classlive.db'
    db.write_bytes(b'pas du sqlite valide!!!')
    with TestClient(app) as c:
        h = c.get('/health').json()
        assert h['database'] is False
        assert h['status'] == 'degraded'


# ── Migration colonne correction_visible (base v0.7.0) ──────────────────────

def test_migration_correction_visible(tmp_path):
    import sqlite3
    from fastapi.testclient import TestClient
    from classlive.api import create_app
    from classlive.config import Settings
    db = tmp_path / 'classlive.db'
    # Simuler une vieille base sans correction_visible
    with sqlite3.connect(db) as con:
        con.executescript('''
        CREATE TABLE live_sessions (
          id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE, group_name TEXT NOT NULL,
          event_name TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
          status TEXT NOT NULL, current_number INTEGER NOT NULL, revision INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE participations (
          id TEXT PRIMARY KEY, live_id TEXT NOT NULL, nom TEXT NOT NULL, prenom TEXT NOT NULL,
          token_hash TEXT NOT NULL UNIQUE, joined_at TEXT NOT NULL, last_seen TEXT NOT NULL
        );
        CREATE TABLE snapshots (
          live_id TEXT NOT NULL, number INTEGER NOT NULL, filename TEXT NOT NULL, kind TEXT NOT NULL,
          public_content TEXT NOT NULL, answer_key TEXT, PRIMARY KEY(live_id,number)
        );
        CREATE TABLE submissions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, participation_id TEXT NOT NULL,
          slide_number INTEGER NOT NULL, answer_json TEXT NOT NULL, submitted_at TEXT NOT NULL
        );
        ''')
    with TestClient(create_app(Settings(workdir=tmp_path, trainer_password='x'))) as c:
        assert c.get('/health').json()['status'] == 'ok'
    with sqlite3.connect(db) as con:
        cols = [r[1] for r in con.execute('PRAGMA table_info(live_sessions)')]
    assert 'correction_visible' in cols


# ── __main__ sans mot de passe : warning logué mais démarrage OK ─────────────

def test_main_sans_mot_de_passe_logue_warning(tmp_path, monkeypatch, caplog):
    from classlive.__main__ import main
    cfg = tmp_path / "config.yml"
    cfg.write_text('classlive:\n  storage:\n    workdir: "/tmp/classlive-main-test"\n', encoding="utf-8")
    monkeypatch.setenv('CLASSLIVE_CONFIG', str(cfg))
    monkeypatch.delenv('CLASSLIVE_TRAINER_PASSWORD', raising=False)
    # Ne pas lancer uvicorn : intercepter l'appel
    import classlive.__main__ as main_mod
    called = {}
    def fake_run(app, **kwargs):
        called['ran'] = True
    monkeypatch.setattr(main_mod.uvicorn, 'run', fake_run)
    with caplog.at_level('WARNING', logger='classlive'):
        main()
    assert called.get('ran') is True
    assert any('CLASSLIVE_TRAINER_PASSWORD' in r.message for r in caplog.records)


# ── Redirection / vers /docs ─────────────────────────────────────────────────

def test_root_redirect_vers_docs(client):
    r = client.get('/', follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers['location'] == '/docs'


# ── Divers ───────────────────────────────────────────────────────────────────

def test_health_contient_version(client):
    h = client.get('/health').json()
    assert h['status'] == 'ok'
    assert h['service'] == 'classlive'
    assert 'version' in h


def test_openapi_routes_complet(client):
    paths = client.get('/openapi.json').json()['paths']
    assert '/api/v1/live/start' in paths
    assert '/api/v1/student/ws' not in paths  # WS pas dans OpenAPI
    assert '/health' in paths
