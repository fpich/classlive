"""Changement de numéros et unicité à chaque niveau."""
from fastapi.testclient import TestClient
from classlive.api import create_app
from classlive.config import Settings


def group(c, name):
    r = c.post('/api/v1/groups', json={'group': name})
    assert r.status_code == 200
    return r.json()['group']


def event(c, g, name):
    r = c.post('/api/v1/events', json={'group': g, 'title': name})
    assert r.status_code == 200
    return r.json()['title']


def test_group_number_change_and_global_collision(client, tmp_path):
    first, second = group(client, 'Premier'), group(client, 'Deuxieme')
    e = event(client, first, 'Chapitre')
    nested = tmp_path / 'Evts' / first / e / 'sous' / 'f.txt'
    nested.parent.mkdir()
    nested.write_text('conserve')
    conflict = client.patch(f'/api/v1/groups/{first}', json={'new_number': 2})
    assert conflict.status_code == 409
    assert (tmp_path/'Evts'/first).exists()
    r = client.patch(f'/api/v1/groups/{first}', json={'new_number': 17})
    assert r.status_code == 200
    assert r.json()['new_name'] == 'G017_Premier'
    assert (tmp_path/'Evts'/'G017_Premier'/e/'sous'/'f.txt').read_text() == 'conserve'
    assert group(client, 'Troisieme') == 'G018_Troisieme'
    r = client.patch('/api/v1/groups/G017_Premier', json={'new_number': 21, 'new_name': 'Séminaire d’été'})
    assert r.status_code == 200
    assert r.json()['new_name'] == 'G021_Seminaire_dete'


def test_event_number_uniqueness_only_within_group(client, tmp_path):
    a, b = group(client, 'A'), group(client, 'B')
    a1, a2, b1 = event(client, a, 'Un'), event(client, a, 'Deux'), event(client, b, 'Autre')
    assert (a1, a2, b1) == ('E001_Un', 'E002_Deux', 'E001_Autre')
    assert client.patch(f'/api/v1/groups/{a}/events/{a2}', json={'new_number': 1}).status_code == 409
    r = client.patch(f'/api/v1/groups/{b}/events/{b1}', json={'new_number': 2})
    assert r.status_code == 200 and r.json()['new_name'] == 'E002_Autre'
    r = client.patch(f'/api/v1/groups/{a}/events/{a2}', json={'new_number': 12, 'new_name': "L'été"})
    assert r.status_code == 200 and r.json()['new_name'] == 'E012_Lete'
    assert event(client, a, 'Trois') == 'E013_Trois'
    assert event(client, b, 'Encore') == 'E003_Encore'


def test_same_name_different_number_still_conflict(client):
    g = group(client, 'G')
    x, y = event(client, g, 'Un'), event(client, g, 'Deux')
    assert client.patch(f'/api/v1/groups/{g}/events/{y}', json={'new_number': 8, 'new_name': 'Un'}).status_code == 409
    assert client.get(f'/api/v1/groups/{g}/events').json()['events'] == [x, y]


def test_number_validation(client):
    g = group(client, 'G')
    e = event(client, g, 'E')
    for bad in [0, -1, 1000000, 'abc', 3.5, True]:
        assert client.patch(f'/api/v1/groups/{g}', json={'new_number': bad}).status_code == 422
        assert client.patch(f'/api/v1/groups/{g}/events/{e}', json={'new_number': bad}).status_code == 422
    assert client.patch(f'/api/v1/groups/{g}', json={}).status_code == 422
    assert client.patch(f'/api/v1/groups/{g}/events/{e}', json={}).status_code == 422


def test_numbered_event_persists_after_group_renumber_and_restart(client, tmp_path):
    g = group(client, 'Formation')
    e = event(client, g, 'Intro')
    assert e == 'E001_Intro'
    g2 = client.patch(f'/api/v1/groups/{g}', json={'new_number': 42}).json()['new_name']
    with TestClient(create_app(Settings(workdir=tmp_path, trainer_password="test-password"))) as again:
        token=again.post("/api/v1/auth/login", json={"username":"formateur","password":"test-password"}).json()["access_token"]
        again.headers.update({"Authorization":f"Bearer {token}"})
        assert event(again, g2, 'Suite') == 'E002_Suite'
        assert group(again, 'Nouveau') == 'G043_Nouveau'


def test_manual_reuse_of_vacated_number(client):
    g = group(client, 'Un')
    new_g = client.patch(f'/api/v1/groups/{g}', json={'new_number': 9}).json()['new_name']
    g2 = group(client, 'Deux')
    assert client.patch(f'/api/v1/groups/{g2}', json={'new_number': 1}).status_code == 200
    assert client.get('/api/v1/groups').json()['groups'] == ['G001_Deux', new_g]
