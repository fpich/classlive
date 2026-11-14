from fastapi.testclient import TestClient
from classlive.api import create_app
from classlive.config import Settings


def test_health(client):
    assert client.get('/health').json()['status'] == 'ok'


def test_create_and_idempotence(client, tmp_path):
    req = {'group': "L'école d'été", 'title': "Événement d'ouverture 2026 !"}
    result = client.post('/api/events', json=req)
    assert result.status_code == 200
    data = result.json()
    assert data['group'] == 'G001_Lecole_dete'
    assert data['title'] == 'E001_Evenement_douverture_2026'
    assert (tmp_path/'Evts'/data['group']/data['title']).is_dir()
    again = client.post('/api/v1/events', json={'group': 'Lecole_dete', 'title': "Evenement d'ouverture 2026"})
    assert again.status_code == 200 and not again.json()['created']
    assert again.json()['title'] == data['title']


def test_sequences_across_groups_and_restart(client, tmp_path):
    a = client.post('/api/groups', json={'group': 'A'}).json()['group']
    b = client.post('/api/groups', json={'group': 'B'}).json()['group']
    assert (a, b) == ('G001_A', 'G002_B')
    e1 = client.post('/api/events', json={'group': a, 'title': 'Premier'}).json()['title']
    e2 = client.post('/api/events', json={'group': b, 'title': 'Second'}).json()['title']
    assert (e1, e2) == ('E001_Premier', 'E001_Second')
    assert client.get('/api/groups').json()['groups'] == [a, b]
    assert client.get(f'/api/groups/{a}/events').json()['events'] == [e1]
    client.delete(f'/api/groups/{b}')
    with TestClient(create_app(Settings(workdir=tmp_path, trainer_password="test-password"))) as restarted:
        token = restarted.post("/api/v1/auth/login", json={"username":"formateur","password":"test-password"}).json()["access_token"]
        restarted.headers.update({"Authorization": f"Bearer {token}"})
        assert restarted.post('/api/groups', json={'group': 'C'}).json()['group'] == 'G003_C'
        assert restarted.post('/api/events', json={'group': a, 'title': 'Troisieme'}).json()['title'] == 'E002_Troisieme'


def test_invalid_names(client):
    for bad in ('../secret', '..', 'x/y', 'x\\y', '\n', '!!!', 'a\n'):
        assert client.post('/api/events', json={'group': bad, 'title': 'Normal'}).status_code == 422
        assert client.post('/api/events', json={'group': 'Normal', 'title': bad}).status_code == 422


def test_symlink_group_rejected(client, tmp_path):
    (tmp_path/'Evts'/'G001_evil').symlink_to(tmp_path, target_is_directory=True)
    assert client.post('/api/events', json={'group':'evil','title':'t'}).status_code == 500


def test_list_events_group_not_found(client):
    assert client.get('/api/v1/groups/G999_Inconnu/events').status_code == 404


def test_auth(tmp_path):
    with TestClient(create_app(Settings(workdir=tmp_path, api_key='secret'))) as c:
        assert c.get('/api/groups').status_code == 401
        assert c.get('/api/groups', headers={'X-API-Key':'secret'}).status_code == 200
        assert c.get('/health').status_code == 200
