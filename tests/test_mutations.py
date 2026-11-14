
def create(client, group, title):
    r = client.post('/api/events', json={'group':group, 'title':title})
    assert r.status_code == 200
    return r.json()['group'], r.json()['title']


def test_rename_group_stable_id_and_contents(client, tmp_path):
    group, title = create(client, 'Groupe A', 'Leçon')
    p = tmp_path/'Evts'/group/title/'sub'
    p.mkdir()
    (p/'data.txt').write_text('important')
    r = client.patch(f'/api/groups/{group}', json={'new_name': "Groupe d'été"})
    assert r.status_code == 200
    new_group = r.json()['new_name']
    assert new_group == 'G001_Groupe_dete'
    assert (tmp_path/'Evts'/new_group/title/'sub'/'data.txt').read_text() == 'important'
    assert client.patch(f'/api/groups/{new_group}', json={'new_name': "Groupe d'été"}).json()['renamed'] is False


def test_rename_event_stable_id_and_contents(client, tmp_path):
    group, title = create(client, 'Groupe', 'Ancien titre')
    p = tmp_path/'Evts'/group/title/'nested'
    p.mkdir()
    (p/'doc.txt').write_text('preserve')
    r = client.patch(f'/api/groups/{group}/events/{title}', json={'new_name': "L'événement été"})
    assert r.status_code == 200
    new_title = r.json()['new_name']
    assert new_title == 'E001_Levenement_ete'
    assert (tmp_path/'Evts'/group/new_title/'nested'/'doc.txt').read_text() == 'preserve'


def test_normalized_conflicts(client, tmp_path):
    group, e1 = create(client, 'G', "L'été")
    _, e2 = create(client, group, 'Autre')
    assert client.patch(f'/api/groups/{group}/events/{e2}', json={'new_name': 'Lete'}).status_code == 409
    assert (tmp_path/'Evts'/group/e2).is_dir()
    other = client.post('/api/groups', json={'group': 'Autre Groupe'}).json()['group']
    assert client.patch(f'/api/groups/{other}', json={'new_name': 'G'}).status_code == 409
    assert (tmp_path/'Evts'/other).exists()
    assert e1 == 'E001_Lete'


def test_recursive_deletion_and_references(client, tmp_path):
    group, title = create(client, 'Formation', 'Event')
    _, title2 = create(client, group, 'Deuxieme')
    path = tmp_path/'Evts'/group/title
    nested = path/'a'/'b'
    nested.mkdir(parents=True)
    (nested/'f.txt').write_text('hello')
    assert client.delete(f'/api/groups/{group}/events/{title}').json()['deleted']
    assert not path.exists()
    assert (tmp_path/'Evts'/group/title2).is_dir()
    assert client.delete(f'/api/groups/{group}').json()['deleted']
    assert not (tmp_path/'Evts'/group).exists()
    assert client.delete(f'/api/groups/{group}').status_code == 404


def test_internal_symlink_not_followed(client, tmp_path):
    group, title = create(client, 'G', 'E')
    outside = tmp_path/'outside'
    outside.mkdir()
    (outside/'file.txt').write_text('keep')
    (tmp_path/'Evts'/group/title/'link').symlink_to(outside, target_is_directory=True)
    assert client.delete(f'/api/groups/{group}/events/{title}').status_code == 200
    assert (outside/'file.txt').read_text() == 'keep'


def test_missing(client):
    assert client.patch('/api/groups/Absent', json={'new_name': 'New'}).status_code == 404
    assert client.delete('/api/groups/Absent').status_code == 404
    group = client.post('/api/groups', json={'group': 'G'}).json()['group']
    assert client.delete(f'/api/groups/{group}/events/Absent').status_code == 404


def test_auth_destructive(tmp_path):
    from fastapi.testclient import TestClient
    from classlive.api import create_app
    from classlive.config import Settings
    with TestClient(create_app(Settings(workdir=tmp_path, api_key='secret'))) as c:
        headers = {'X-API-Key': 'secret'}
        r = c.post('/api/events', json={'group':'G','title':'E'}, headers=headers).json()
        group, title = r['group'], r['title']
        assert c.delete(f'/api/groups/{group}').status_code == 401
        assert c.delete(f'/api/groups/{group}/events/{title}').status_code == 401
        assert c.patch(f'/api/groups/{group}', json={'new_name': 'G2'}).status_code == 401
        assert (tmp_path/'Evts'/group/title).is_dir()


def test_delete_does_not_recycle_event_number(client):
    group, title = create(client, 'Alpha', 'Un')
    assert client.delete(f'/api/groups/{group}/events/{title}').status_code == 200
    assert client.post('/api/events', json={'group': group, 'title': 'Deux'}).json()['title'] == 'E002_Deux'


def test_normalized_create_is_idempotent_across_accents_case(client):
    first = client.post('/api/groups', json={'group': 'École d’été'}).json()
    second = client.post('/api/groups', json={'group': 'ecole dete'}).json()
    assert first['created'] is True
    assert second['created'] is False
    assert first['group'] == second['group']
