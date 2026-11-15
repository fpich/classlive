"""Tests ciblés pour atteindre 100 % de couverture des lignes.

Beaucoup de branches d'erreur (OSError disque, symlinks, races) sont
inatteignables via l'API seule à cause de la validation Pydantic en amont ;
elles sont testées ici par appels directs ou monkeypatch.
"""
import os
import runpy
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from classlive.api import create_app
from classlive.config import Settings
from classlive.live import LiveStore
from classlive.live_api import Hub
from classlive.navigation import SlideNavigator
from classlive.slides import SlideStorage, SLIDE_RE
from classlive.storage import (
    EventStorage, GROUP_RE, EVENT_RE, InvalidName, ResourceConflict,
    ResourceNotFound, StorageError,
)


# ═══════════════════ storage.py ═══════════════════

def test_storage_events_dir_invalide(tmp_path):
    with pytest.raises(ValueError, match="Evts"):
        EventStorage(tmp_path, "Autre")


def test_directory_symlink_interdit(tmp_path):
    storage = EventStorage(tmp_path)
    (tmp_path / "lien").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(StorageError, match="Lien symbolique"):
        storage._directory(tmp_path / "lien" / "sous", create=True)


def test_directory_pas_un_dossier(tmp_path):
    storage = EventStorage(tmp_path)
    f = tmp_path / "fichier"
    f.write_text("x")
    with pytest.raises(StorageError, match="pas un dossier"):
        storage._directory(f / "sous", create=True)


def test_directory_fileexists_race(tmp_path, monkeypatch):
    storage = EventStorage(tmp_path)
    real_mkdir = Path.mkdir
    def fake_mkdir(self, *a, **kw):
        raise FileExistsError
    monkeypatch.setattr(Path, "mkdir", fake_mkdir)
    with pytest.raises(StorageError, match="Chemin invalide"):
        storage._directory(tmp_path / "nouveau", create=True)


def test_directory_oserror(tmp_path, monkeypatch):
    storage = EventStorage(tmp_path)
    def fake_mkdir(self, *a, **kw):
        raise OSError("disque plein")
    monkeypatch.setattr(Path, "mkdir", fake_mkdir)
    with pytest.raises(StorageError, match="Impossible de créer"):
        storage._directory(tmp_path / "nouveau", create=True)


def test_directory_inexistant_sans_create(tmp_path):
    storage = EventStorage(tmp_path)
    assert storage._directory(tmp_path / "absent") is False


def test_compteur_symlink_interdit(tmp_path):
    storage = EventStorage(tmp_path)
    storage.init()
    cible = tmp_path / "cible.json"
    cible.write_text("{}")
    storage._counters.symlink_to(cible)
    with pytest.raises(StorageError, match="symbolique"):
        storage._read_sequences()


def test_compteurs_event_by_group_invalide(tmp_path):
    storage = EventStorage(tmp_path)
    storage.init()
    storage._counters.write_text('{"group": 0, "event": 0, "event_by_group": {"G001": "x"}}')
    with pytest.raises(StorageError, match="Compteurs"):
        storage.create_group("Nouveau")


def test_write_sequences_oserror(tmp_path, monkeypatch):
    storage = EventStorage(tmp_path)
    storage.init()
    monkeypatch.setattr(os, "replace", MagicMock(side_effect=OSError("io error")))
    with pytest.raises(StorageError, match="enregistrer les compteurs"):
        storage._write_sequences({"group": 1, "event": 0, "event_by_group": {}})


def test_number_invalide(tmp_path):
    with pytest.raises(InvalidName, match="numéro"):
        EventStorage._number(0)
    with pytest.raises(InvalidName, match="numéro"):
        EventStorage._number("5")


def test_reserve_id_event_sans_parent(tmp_path):
    storage = EventStorage(tmp_path)
    storage.init()
    with pytest.raises(ValueError, match="Parent requis"):
        storage._reserve_id("event")


def test_advance_counter_group_direct(tmp_path):
    storage = EventStorage(tmp_path)
    storage.init()
    storage._advance_counter("group", 42)
    data = storage._read_sequences()
    assert data["group"] == 42


def test_advance_counter_sans_parent(tmp_path):
    storage = EventStorage(tmp_path)
    storage.init()
    with pytest.raises(ValueError, match="Parent requis"):
        storage._advance_counter("event", 5)


def test_resolve_parent_inexistant(tmp_path):
    storage = EventStorage(tmp_path)
    with pytest.raises(ResourceNotFound, match="introuvable"):
        storage._resolve(tmp_path / "absent", "x", GROUP_RE, "Groupe")


def test_resolve_ambigu(tmp_path):
    storage = EventStorage(tmp_path)
    storage.init()
    (storage.root / "G001_Test").mkdir()
    (storage.root / "G002_test").mkdir()
    with pytest.raises(ResourceConflict, match="ambigu"):
        storage._resolve(storage.root, "test", GROUP_RE, "Groupe")


def test_create_group_identifiant_inexistant_404(client):
    r = client.post("/api/v1/groups", json={"group": "G999_Inconnu"})
    assert r.status_code == 404


def test_create_event_identifiant_inexistant_404(client):
    g = client.post("/api/v1/groups", json={"group": "G"}).json()["group"]
    r = client.post("/api/v1/events", json={"group": g, "title": "E999_Inconnu"})
    assert r.status_code == 404


def test_unused_cible_symlink(tmp_path):
    storage = EventStorage(tmp_path)
    storage.init()
    g1 = storage.create_group("A")["group"]
    g2 = storage.create_group("B")["group"]
    path_g1 = storage.root / g1
    path_g2 = storage.root / g2
    cible = storage.root / "G001_Cible"
    cible.symlink_to(path_g1, target_is_directory=True)
    with pytest.raises(StorageError, match="Lien symbolique"):
        storage._unused(cible, [path_g1, path_g2], "Cible")


def test_unused_cible_existe_deja(tmp_path):
    storage = EventStorage(tmp_path)
    storage.init()
    g1 = storage.create_group("A")["group"]
    path_g1 = storage.root / g1
    cible = storage.root / "G001_Autre"
    cible.mkdir()
    with pytest.raises(ResourceConflict, match="existe déjà"):
        storage._unused(cible, [path_g1], "Autre")


def test_rename_group_sans_args_direct(tmp_path):
    storage = EventStorage(tmp_path)
    storage.init()
    g = storage.create_group("G")["group"]
    with pytest.raises(InvalidName, match="new_name"):
        storage.rename_group(g)


def test_rename_group_oserror(tmp_path, monkeypatch):
    storage = EventStorage(tmp_path)
    g = storage.create_group("G")["group"]
    monkeypatch.setattr(Path, "rename", MagicMock(side_effect=OSError("io")))
    with pytest.raises(StorageError, match="renommer le groupe"):
        storage.rename_group(g, new_name="Nouveau")


def test_rename_event_sans_args_direct(tmp_path):
    storage = EventStorage(tmp_path)
    g = storage.create_group("G")["group"]
    e = storage.create_event(g, "E")["title"]
    with pytest.raises(InvalidName, match="new_name"):
        storage.rename_event(g, e)


def test_rename_event_identique_renamed_false(client):
    g = client.post("/api/v1/groups", json={"group": "G"}).json()["group"]
    e = client.post("/api/v1/events", json={"group": g, "title": "MonEvent"}).json()["title"]
    r = client.patch(f"/api/v1/groups/{g}/events/{e}", json={"new_name": "MonEvent"})
    assert r.status_code == 200
    assert r.json()["renamed"] is False


def test_rename_event_oserror(tmp_path, monkeypatch):
    storage = EventStorage(tmp_path)
    g = storage.create_group("G")["group"]
    e = storage.create_event(g, "E")["title"]
    monkeypatch.setattr(Path, "rename", MagicMock(side_effect=OSError("io")))
    with pytest.raises(StorageError, match="renommer l’événement"):
        storage.rename_event(g, e, new_name="Nouveau")


def test_delete_event_oserror(tmp_path, monkeypatch):
    storage = EventStorage(tmp_path)
    g = storage.create_group("G")["group"]
    e = storage.create_event(g, "E")["title"]
    monkeypatch.setattr(shutil, "rmtree", MagicMock(side_effect=OSError("io")))
    with pytest.raises(StorageError, match="supprimer l’événement"):
        storage.delete_event(g, e)


def test_delete_group_oserror(tmp_path, monkeypatch):
    storage = EventStorage(tmp_path)
    g = storage.create_group("G")["group"]
    monkeypatch.setattr(shutil, "rmtree", MagicMock(side_effect=OSError("io")))
    with pytest.raises(StorageError, match="supprimer le groupe"):
        storage.delete_group(g)


# ═══════════════════ slides.py ═══════════════════

def _slides_store(tmp_path):
    storage = EventStorage(tmp_path)
    storage.init()
    g = storage.create_group("G")["group"]
    e = storage.create_event(g, "E")["title"]
    return SlideStorage(storage), g, e


def test_slide_type_invalide_direct():
    with pytest.raises(InvalidName, match="Type de slide"):
        SlideStorage._type("X")
    with pytest.raises(InvalidName, match="Type de slide"):
        SlideStorage._type(123)


def test_slide_content_non_string_direct():
    with pytest.raises(InvalidName, match="chaîne"):
        SlideStorage._content(123)


def test_slide_resolve_identifiant_invalide(tmp_path):
    slides, g, e = _slides_store(tmp_path)
    _, parent = slides._parent(g, e)
    with pytest.raises(InvalidName, match="Identifiant de slide"):
        slides._resolve(parent, "a/b")
    with pytest.raises(InvalidName, match="Identifiant de slide"):
        slides._resolve(parent, "a\\b")


def test_slide_resolve_par_nom_normalise(client):
    g = client.post("/api/v1/groups", json={"group": "G"}).json()["group"]
    e = client.post("/api/v1/events", json={"group": g, "title": "E"}).json()["title"]
    base = f"/api/v1/groups/{g}/events/{e}/slides"
    r = client.post(base, json={"title": "Ma Belle Slide", "slide_type": "C", "content": "# x"})
    slide = r.json()["slide"]  # S001_C_Ma_Belle_Slide.md
    # Résolution par nom normalisé sans match exact (casse différente)
    r2 = client.get(f"{base}/ma belle slide")
    assert r2.status_code == 200 and r2.json()["slide"] == slide


def test_slide_ambigue(tmp_path):
    slides, g, e = _slides_store(tmp_path)
    _, parent = slides._parent(g, e)
    (parent / "S001_C_Test.md").write_text("a")
    (parent / "S002_C_test.md").write_text("b")
    with pytest.raises(ResourceConflict, match="ambiguë"):
        slides.read(g, e, "test")


def test_write_exclusive_fileexists(tmp_path, monkeypatch):
    slides, g, e = _slides_store(tmp_path)
    _, parent = slides._parent(g, e)
    def fake_open(self, mode='r', *a, **kw):
        raise FileExistsError
    monkeypatch.setattr(Path, "open", fake_open)
    with pytest.raises(ResourceConflict, match="déjà présent"):
        slides._write_exclusive(parent / "S001_C_X.md", "contenu")


def test_write_exclusive_oserror(tmp_path, monkeypatch):
    slides, g, e = _slides_store(tmp_path)
    _, parent = slides._parent(g, e)
    def fake_open(self, mode='r', *a, **kw):
        raise OSError("io")
    monkeypatch.setattr(Path, "open", fake_open)
    with pytest.raises(StorageError, match="créer la slide"):
        slides._write_exclusive(parent / "S001_C_X.md", "contenu")


def test_write_atomic_oserror(tmp_path, monkeypatch):
    slides, g, e = _slides_store(tmp_path)
    _, parent = slides._parent(g, e)
    p = parent / "S001_C_X.md"
    p.write_text("old")
    monkeypatch.setattr(os, "replace", MagicMock(side_effect=OSError("io")))
    with pytest.raises(StorageError, match="modifier la slide"):
        slides._write_atomic(p, "new")


def test_slide_read_oserror(tmp_path, monkeypatch):
    slides, g, e = _slides_store(tmp_path)
    s = slides.create(g, e, "MaSlide", "C", "contenu")["slide"]
    monkeypatch.setattr(Path, "read_text", MagicMock(side_effect=OSError("io")))
    with pytest.raises(StorageError, match="lire la slide"):
        slides.read(g, e, s)


def test_slide_rename_sans_args_direct(tmp_path):
    slides, g, e = _slides_store(tmp_path)
    s = slides.create(g, e, "S", "C")["slide"]
    with pytest.raises(InvalidName, match="new_name"):
        slides.rename(g, e, s)


def test_slide_rename_cible_existe(tmp_path):
    slides, g, e = _slides_store(tmp_path)
    s1 = slides.create(g, e, "Un", "C")["slide"]
    slides.create(g, e, "Deux", "C")
    _, parent = slides._parent(g, e)
    # Un dossier portant le nom cible : pas listé par _slides (is_file false),
    # donc _check_unique passe et os.path.lexists(target) atteint
    (parent / "S005_C_Un.md").mkdir()
    with pytest.raises(ResourceConflict, match="fichier cible existe"):
        slides.rename(g, e, s1, new_number=5)


def test_slide_rename_oserror(tmp_path, monkeypatch):
    slides, g, e = _slides_store(tmp_path)
    s = slides.create(g, e, "S", "C")["slide"]
    monkeypatch.setattr(Path, "rename", MagicMock(side_effect=OSError("io")))
    with pytest.raises(StorageError, match="renommer la slide"):
        slides.rename(g, e, s, new_name="Nouveau")


def test_slide_delete_oserror(tmp_path, monkeypatch):
    slides, g, e = _slides_store(tmp_path)
    s = slides.create(g, e, "S", "C")["slide"]
    monkeypatch.setattr(Path, "unlink", MagicMock(side_effect=OSError("io")))
    with pytest.raises(StorageError, match="supprimer la slide"):
        slides.delete(g, e, s)


# ═══════════════════ navigation.py ═══════════════════

def _nav_setup(tmp_path):
    storage = EventStorage(tmp_path)
    storage.init()
    slides = SlideStorage(storage)
    nav = SlideNavigator(slides)
    g = storage.create_group("G")["group"]
    e = storage.create_event(g, "E")["title"]
    slides.create(g, e, "Un", "C", "# 1", number=1)
    slides.create(g, e, "Deux", "C", "# 2", number=2)
    return nav, slides, g, e


def test_nav_slide_courante_supprimee(tmp_path):
    nav, slides, g, e = _nav_setup(tmp_path)
    sess = nav.select(g, e)["session_id"]
    _, parent = slides._parent(g, e)
    (parent / "S001_C_Un.md").unlink()
    with pytest.raises(ResourceNotFound, match="n’existe plus"):
        nav.navigate(sess, "current")


def test_nav_lecture_slide_oserror(tmp_path, monkeypatch):
    nav, slides, g, e = _nav_setup(tmp_path)
    sess = nav.select(g, e)["session_id"]
    monkeypatch.setattr(Path, "read_text", MagicMock(side_effect=OSError("io")))
    with pytest.raises(StorageError, match="lire la slide"):
        nav.navigate(sess, "next")


def test_nav_evenement_vide_pendant_nav(tmp_path):
    nav, slides, g, e = _nav_setup(tmp_path)
    sess = nav.select(g, e)["session_id"]
    _, parent = slides._parent(g, e)
    for p in parent.iterdir():
        if p.suffix == ".md":
            p.unlink()
    with pytest.raises(ResourceNotFound, match="plus aucune slide"):
        nav.navigate(sess, "next")


def test_nav_direction_invalide_direct(tmp_path):
    nav, slides, g, e = _nav_setup(tmp_path)
    sess = nav.select(g, e)["session_id"]
    with pytest.raises(ValueError, match="Direction"):
        nav.navigate(sess, "bidon")


def test_nav_aucune_slide_dans_direction(tmp_path):
    nav, slides, g, e = _nav_setup(tmp_path)
    sess = nav.select(g, e)["session_id"]
    nav._sessions[sess] = (g, e, 999)  # numéro inexistant
    with pytest.raises(ResourceNotFound, match="Aucune slide"):
        nav.navigate(sess, "next")


def test_nav_close_session_inexistente(client):
    assert client.delete("/api/v1/player/session-inconnue").status_code == 404


# ═══════════════════ live.py ═══════════════════

def _live_store(tmp_path):
    storage = EventStorage(tmp_path)
    storage.init()
    slides = SlideStorage(storage)
    g = storage.create_group("G")["group"]
    e = storage.create_event(g, "E")["title"]
    slides.create(g, e, "C", "C", "# C")
    slides.create(g, e, "Q", "Q", "# Q")
    return LiveStore(tmp_path / "classlive.db", slides), slides, g, e


def test_participation_fail_if_missing(tmp_path):
    store, slides, g, e = _live_store(tmp_path)
    with store.db() as con:
        with pytest.raises(ResourceNotFound, match="Participation"):
            store._participation(con, "inconnu")


def test_aucun_code_live_disponible(tmp_path, monkeypatch):
    import secrets
    store, slides, g, e = _live_store(tmp_path)
    # Un seul code possible, déjà pris
    with store.db() as con:
        con.execute("INSERT INTO live_sessions(id,code,group_name,event_name,started_at,status,current_number) VALUES ('x','000000','a','b','t','ended',1)")
    monkeypatch.setattr(secrets, "randbelow", lambda n: 0)
    with pytest.raises(ResourceConflict, match="Aucun code Live"):
        store.start(g, e)


def test_move_previous_au_debut(client):
    g = client.post("/api/v1/groups", json={"group": "G"}).json()["group"]
    e = client.post("/api/v1/events", json={"group": g, "title": "E"}).json()["title"]
    client.post(f"/api/v1/groups/{g}/events/{e}/slides", json={"title": "S", "slide_type": "C", "content": "# S"})
    live = client.post("/api/v1/live/start", json={"group": g, "title": e}).json()
    r = client.post(f"/api/v1/live/{live['live_id']}/previous")
    assert r.status_code == 200 and r.json()["number"] == 1


def test_move_goto_via_api(client):
    g = client.post("/api/v1/groups", json={"group": "G"}).json()["group"]
    e = client.post("/api/v1/events", json={"group": g, "title": "E"}).json()["title"]
    base = f"/api/v1/groups/{g}/events/{e}/slides"
    client.post(base, json={"title": "S1", "slide_type": "C", "content": "# 1", "number": 1})
    client.post(base, json={"title": "S5", "slide_type": "C", "content": "# 5", "number": 5})
    live = client.post("/api/v1/live/start", json={"group": g, "title": e}).json()
    r = client.post(f"/api/v1/live/{live['live_id']}/goto", json={"number": 5})
    assert r.status_code == 200 and r.json()["number"] == 5


def test_move_direction_invalide_direct(tmp_path):
    store, slides, g, e = _live_store(tmp_path)
    live = store.start(g, e)
    with pytest.raises(ValueError, match="Direction invalide"):
        store.move(live["live_id"], "bidon")


def test_submit_reponse_non_dict_direct(tmp_path):
    store, slides, g, e = _live_store(tmp_path)
    live = store.start(g, e)
    student = store.join(live["session_code"], "Nom", "Prenom")
    auth = store.authenticate_student(student["student_session_id"])
    with pytest.raises(ValueError, match="objet JSON"):
        store.submit(auth, "pas un dict")


def test_submit_session_terminee_direct(tmp_path):
    store, slides, g, e = _live_store(tmp_path)
    live = store.start(g, e)
    student = store.join(live["session_code"], "Nom", "Prenom")
    auth = store.authenticate_student(student["student_session_id"])
    store.stop(live["live_id"])
    with pytest.raises(ResourceConflict, match="terminée"):
        store.submit(auth, {"selected": ["A"]})


def test_reset_avec_live_actif_409(client):
    g = client.post("/api/v1/groups", json={"group": "G"}).json()["group"]
    e = client.post("/api/v1/events", json={"group": g, "title": "E"}).json()["title"]
    client.post(f"/api/v1/groups/{g}/events/{e}/slides", json={"title": "S", "slide_type": "C", "content": "# S"})
    client.post("/api/v1/live/start", json={"group": g, "title": e})
    r = client.delete(f"/api/v1/groups/{g}/events/{e}/sessions")
    assert r.status_code == 409


# ═══════════════════ live_api.py ═══════════════════

def test_hub_publish_websocket_fermee(tmp_path):
    hub = Hub()
    ws = MagicMock()
    ws.send_json = AsyncMock(side_effect=WebSocketDisconnect(code=1008))
    hub.students["lid"].add(ws)
    import asyncio
    asyncio.run(hub.publish("lid", {"event": "test"}))
    assert ws not in hub.students["lid"]


def test_route_previous_via_api(client):
    g = client.post("/api/v1/groups", json={"group": "G"}).json()["group"]
    e = client.post("/api/v1/events", json={"group": g, "title": "E"}).json()["title"]
    base = f"/api/v1/groups/{g}/events/{e}/slides"
    client.post(base, json={"title": "S1", "slide_type": "C", "content": "# 1"})
    client.post(base, json={"title": "S2", "slide_type": "C", "content": "# 2"})
    live = client.post("/api/v1/live/start", json={"group": g, "title": e}).json()
    client.post(f"/api/v1/live/{live['live_id']}/next")
    r = client.post(f"/api/v1/live/{live['live_id']}/previous")
    assert r.status_code == 200 and r.json()["number"] == 1


def test_route_status_via_api(client):
    g = client.post("/api/v1/groups", json={"group": "G"}).json()["group"]
    e = client.post("/api/v1/events", json={"group": g, "title": "E"}).json()["title"]
    client.post(f"/api/v1/groups/{g}/events/{e}/slides", json={"title": "S", "slide_type": "C", "content": "# S"})
    live = client.post("/api/v1/live/start", json={"group": g, "title": e}).json()
    r = client.get(f"/api/v1/live/{live['live_id']}/status")
    assert r.status_code == 200 and r.json()["status"] == "running"


def test_ws_json_invalide_rejete(client):
    with client.websocket_connect("/api/v1/student/ws") as ws:
        ws.send_text("pas du json{{{")
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008


def test_ws_token_non_string_rejete(client):
    with client.websocket_connect("/api/v1/student/ws") as ws:
        ws.send_json({"token": 123})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008


def test_ws_ping_apres_stop_ferme(client):
    g = client.post("/api/v1/groups", json={"group": "G"}).json()["group"]
    e = client.post("/api/v1/events", json={"group": g, "title": "E"}).json()["title"]
    client.post(f"/api/v1/groups/{g}/events/{e}/slides", json={"title": "S", "slide_type": "C", "content": "# S"})
    live = client.post("/api/v1/live/start", json={"group": g, "title": e}).json()
    s = client.post("/api/v1/student/join", json={"session_code": live["session_code"], "nom": "A", "prenom": "B"}).json()
    with client.websocket_connect("/api/v1/student/ws") as ws:
        ws.send_json({"token": s["student_session_id"]})
        assert ws.receive_json()["event"] == "current"
        client.post(f"/api/v1/live/{live['live_id']}/stop")
        assert ws.receive_json()["event"] == "live_ended"  # notification de stop
        ws.send_json({"event": "ping"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008


def test_ws_event_non_ping_recoit_erreur(client):
    g = client.post("/api/v1/groups", json={"group": "G"}).json()["group"]
    e = client.post("/api/v1/events", json={"group": g, "title": "E"}).json()["title"]
    client.post(f"/api/v1/groups/{g}/events/{e}/slides", json={"title": "S", "slide_type": "C", "content": "# S"})
    live = client.post("/api/v1/live/start", json={"group": g, "title": e}).json()
    s = client.post("/api/v1/student/join", json={"session_code": live["session_code"], "nom": "A", "prenom": "B"}).json()
    with client.websocket_connect("/api/v1/student/ws") as ws:
        ws.send_json({"token": s["student_session_id"]})
        ws.receive_json()  # current
        ws.send_json({"event": "bidon"})
        rep = ws.receive_json()
        assert rep["event"] == "error" and "ping" in rep["detail"]


def test_ws_monitor_live_inexistant(client):
    trainer_token = client.headers["Authorization"].split(" ", 1)[1]
    with client.websocket_connect("/api/v1/live/live-inconnu/monitor") as ws:
        ws.send_json({"token": trainer_token})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008


# ═══════════════════ __main__.py:27 ═══════════════════

def test_main_module_runpy(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yml"
    cfg.write_text('classlive:\n  storage:\n    workdir: "/tmp/classlive-runpy"\n', encoding="utf-8")
    monkeypatch.setenv("CLASSLIVE_CONFIG", str(cfg))
    monkeypatch.delenv("CLASSLIVE_TRAINER_PASSWORD", raising=False)
    called = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: called.setdefault("ran", True))
    runpy.run_module("classlive.__main__", run_name="__main__")
    assert called.get("ran") is True
