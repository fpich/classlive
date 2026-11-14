"""Lecture séquentielle : isolation des clients, ordre, bornes et erreurs."""
from test_slides import setup


def test_navigation_forward_backward_and_bounds(client):
    group, event, base = setup(client)
    for num, kind in [(1, 'C'), (3, 'Q'), (9, 'T')]:
        r = client.post(base, json={'title': f'Slide {num}', 'slide_type': kind, 'number': num,
                                    'content': f'# Contenu {num}'})
        assert r.status_code == 200
    r = client.post('/api/v1/player/select', json={'group': group, 'title': event})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data['slide'] == 'S001_C_Slide_1.md'
    assert data['content'] == '# Contenu 1'
    assert (data['position'], data['total'], data['has_previous'], data['has_next']) == (1, 3, False, True)
    sess = data['session_id']
    prefix = f'/api/v1/player/{sess}'
    assert client.post(prefix + '/next').json()['slide'] == 'S003_Q_Slide_3.md'
    assert client.post(prefix + '/next').json()['slide'] == 'S009_T_Slide_9.md'
    last = client.post(prefix + '/next').json()
    assert last['slide'] == 'S009_T_Slide_9.md'
    assert last['has_next'] is False
    assert client.post(prefix + '/previous').json()['slide'] == 'S003_Q_Slide_3.md'
    assert client.get(prefix).json()['slide'] == 'S003_Q_Slide_3.md'
    assert client.post(prefix + '/previous').json()['slide'] == 'S001_C_Slide_1.md'
    assert client.post(prefix + '/previous').json()['slide'] == 'S001_C_Slide_1.md'
    assert client.delete(prefix).json()['closed'] is True
    assert client.get(prefix).status_code == 404


def test_independent_sessions_and_dynamic_content(client):
    group, event, base = setup(client)
    first = client.post(base, json={'title': 'Intro', 'slide_type': 'C', 'content': 'v1'}).json()['slide']
    client.post(base, json={'title': 'Suite', 'slide_type': 'C'})
    ids = [client.post('/api/v1/player/select', json={'group': group, 'title': event}).json()['session_id'] for _ in range(2)]
    assert client.post(f'/api/v1/player/{ids[0]}/next').json()['number'] == 2
    assert client.get(f'/api/v1/player/{ids[1]}').json()['number'] == 1
    client.put(f'{base}/{first}/content', json={'content': 'v2'})
    assert client.get(f'/api/v1/player/{ids[1]}').json()['content'] == 'v2'


def test_empty_and_missing_event(client):
    group, event, base = setup(client)
    assert client.post('/api/v1/player/select', json={'group': group, 'title': event}).status_code == 404
    assert client.post('/api/v1/player/select', json={'group': group, 'title': 'absent'}).status_code == 404
    assert client.post('/api/v1/player/bad-session/next').status_code == 404


def test_slide_renumber_during_navigation(client):
    group, event, base = setup(client)
    client.post(base, json={'title': 'Premier', 'slide_type': 'C', 'number': 1})
    second = client.post(base, json={'title': 'Second', 'slide_type': 'C', 'number': 2}).json()['slide']
    client.post(base, json={'title': 'Troisieme', 'slide_type': 'C', 'number': 3})
    session = client.post('/api/v1/player/select', json={'group': group, 'title': event}).json()['session_id']
    client.patch(f'{base}/{second}', json={'new_number': 8})
    assert client.post(f'/api/v1/player/{session}/next').json()['number'] == 3
    assert client.post(f'/api/v1/player/{session}/next').json()['number'] == 8
