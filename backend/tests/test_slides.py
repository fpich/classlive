"""Tests intégration du contrat slides Markdown."""
from pathlib import Path


def setup(client):
    group = client.post('/api/v1/groups', json={'group': 'Français débutant'}).json()['group']
    event = client.post('/api/v1/events', json={'group': group, 'title': "L'été à l'école"}).json()['title']
    return group, event, f'/api/v1/groups/{group}/events/{event}/slides'


def test_create_slide_types_and_content(client, tmp_path):
    group, event, base = setup(client)
    for index, kind in enumerate('CAORQT', 1):
        r = client.post(base, json={'title': f"Présentation numéro {index}", 'slide_type': kind, 'content': '# Bonjour\nTexte'})
        assert r.status_code == 200, r.text
        assert r.json()['slide'] == f'S{index:03d}_{kind}_Presentation_numero_{index}.md'
        p = tmp_path / 'Evts' / group / event / r.json()['slide']
        assert p.read_text() == '# Bonjour\nTexte'
    assert len(client.get(base).json()['slides']) == 6
    assert client.post(base, json={'title': 'Présentation numéro 1', 'slide_type': 'C', 'content': 'modifié ?'}).json()['created'] is False
    assert (tmp_path / 'Evts' / group / event / 'S001_C_Presentation_numero_1.md').read_text() == '# Bonjour\nTexte'


def test_number_unique_across_types_and_titles(client):
    _, _, base = setup(client)
    assert client.post(base, json={'title': 'Un', 'slide_type': 'C', 'number': 8}).status_code == 200
    assert client.post(base, json={'title': 'Deux', 'slide_type': 'A', 'number': 8}).status_code == 409
    assert client.post(base, json={'title': 'Un', 'slide_type': 'Q', 'number': 9}).status_code == 409
    assert client.post(base, json={'title': 'Trois', 'slide_type': 'Q'}).json()['slide'] == 'S009_Q_Trois.md'


def test_rename_number_type_title_preserves_markdown(client, tmp_path):
    g, e, base = setup(client)
    old = client.post(base, json={'title': "L'introduction à l'été", 'slide_type': 'C', 'content': '## texte'}).json()['slide']
    assert old == 'S001_C_Lintroduction_a_lete.md'
    r = client.patch(f'{base}/{old}', json={'new_number': 23, 'new_name': 'Question générale', 'new_type': 'Q'})
    assert r.status_code == 200, r.text
    new = 'S023_Q_Question_generale.md'
    assert r.json()['new_name'] == new
    assert (tmp_path/'Evts'/g/e/new).read_text() == '## texte'
    assert client.get(f'{base}/{new}').json()['content'] == '## texte'
    assert client.get(f'{base}/{old}').status_code == 404
    assert client.patch(f'{base}/{new}', json={'new_number': 23}).json()['renamed'] is False


def test_number_uniqueness_scoped_event(client):
    g, e, base = setup(client)
    s = client.post(base, json={'title': 'Un', 'slide_type': 'C'}).json()['slide']
    e2 = client.post('/api/v1/events', json={'group': g, 'title': 'Deuxième événement'}).json()['title']
    base2 = f'/api/v1/groups/{g}/events/{e2}/slides'
    assert client.post(base2, json={'title': 'Autre', 'slide_type': 'A'}).json()['slide'] == 'S001_A_Autre.md'
    s2 = client.post(base, json={'title': 'Deux', 'slide_type': 'T'}).json()['slide']
    assert client.patch(f'{base}/{s2}', json={'new_number': 1}).status_code == 409
    assert client.patch(f'{base}/{s2}', json={'new_number': 10}).status_code == 200


def test_markdown_update_and_delete(client):
    _, _, base = setup(client)
    s = client.post(base, json={'title': 'Ma slide', 'slide_type': 'T'}).json()['slide']
    assert client.put(f'{base}/{s}/content', json={'content': '# Trous\n{{mot}}'}).status_code == 200
    assert client.get(f'{base}/{s}').json()['content'] == '# Trous\n{{mot}}'
    assert client.delete(f'{base}/{s}').json()['deleted'] is True
    assert client.get(f'{base}/{s}').status_code == 404
    assert client.delete(f'{base}/{s}').status_code == 404


def test_validation_and_missing(client):
    _, _, base = setup(client)
    for kind in ('X', 'c', 'AA', ''):
        assert client.post(base, json={'title': 'Bad', 'slide_type': kind}).status_code == 422
    for num in (0, -1, True, 1.3, 1000000):
        assert client.post(base, json={'title': 'Bad', 'slide_type': 'C', 'number': num}).status_code == 422
    for title in ('../escape', '...', '!!!', 'a/b'):
        assert client.post(base, json={'title': title, 'slide_type': 'C'}).status_code == 422
    assert client.get(f'{base}/missing').status_code == 404
    slide = client.post(base, json={'title': 'OK', 'slide_type': 'C'}).json()['slide']
    assert client.patch(f'{base}/{slide}', json={}).status_code == 422
    assert client.patch(f'{base}/{slide}', json={'new_type': 'Z'}).status_code == 422


def test_no_symlink_inside_event(client, tmp_path):
    g, e, base = setup(client)
    outside = tmp_path/'secret.md'
    outside.write_text('secret')
    (tmp_path/'Evts'/g/e/'S999_C_Secret.md').symlink_to(outside)
    assert client.get(base).status_code == 500
    assert client.post(base, json={'title': 'Autre', 'slide_type': 'C'}).status_code == 500
    assert outside.read_text() == 'secret'


def test_event_rename_keeps_slides(client):
    g, e, base = setup(client)
    s = client.post(base, json={'title': 'Intro', 'slide_type': 'C', 'content': 'salut'}).json()['slide']
    changed = client.patch(f'/api/v1/groups/{g}/events/{e}', json={'new_number': 20}).json()['new_name']
    new_base = f'/api/v1/groups/{g}/events/{changed}/slides'
    assert client.get(f'{new_base}/{s}').json()['content'] == 'salut'
