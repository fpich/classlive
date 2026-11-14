import sqlite3
import csv
import io
from fastapi.testclient import TestClient
from classlive.api import create_app
from classlive.config import Settings


def setup_event(client):
    g = client.post('/api/v1/groups',json={'group':'Formation'}).json()['group']
    e = client.post('/api/v1/events',json={'group':g,'title':'Exercices'}).json()['title']
    path = f'/api/v1/groups/{g}/events/{e}/slides'
    client.post(path,json={'title':'Intro','slide_type':'C','content':'# Intro'})
    client.post(path,json={'title':'Question','slide_type':'Q','content':'---\nclasslive_answer:\n  selected: [B]\n---\n# Choisissez B'})
    client.post(path,json={'title':'Association','slide_type':'A','content':'# Exercice sans corrigé'})
    return g,e


def test_help_workspace_markdown(client,tmp_path):
    guide=tmp_path/'GUIDE_CLASSLIVE.md'
    assert guide.exists()
    assert 'correction/show' in guide.read_text()
    r=client.get('/api/v1/help')
    assert r.status_code==200
    assert 'text/markdown' in r.headers['content-type']
    assert r.text==guide.read_text()
    guide.write_text('# Guide personnalisé',encoding='utf-8')
    assert client.get('/api/v1/help').text=='# Guide personnalisé'
    with TestClient(create_app(Settings(workdir=tmp_path,trainer_password='test-password'))) as c:
        assert c.get('/api/v1/help').text=='# Guide personnalisé'


def test_correction_visibility_and_scores_removed(client):
    g,e=setup_event(client)
    live=client.post('/api/v1/live/start',json={'group':g,'title':e}).json()
    lid=live['live_id']
    joined=client.post('/api/v1/student/join',json={'session_code':live['session_code'],'nom':'Dupont','prenom':'Marie'}).json()
    headers={'Authorization':'Bearer '+joined['student_session_id']}
    assert client.post(f'/api/v1/live/{lid}/correction/show').status_code==409  # Intro
    client.post(f'/api/v1/live/{lid}/next')
    assert 'correction' not in client.get('/api/v1/student/current',headers=headers).json()
    r=client.post('/api/v1/student/answers',headers=headers,json={'answer':{'selected':['A']}})
    assert r.status_code==200 and 'points' not in r.json()
    show=client.post(f'/api/v1/live/{lid}/correction/show')
    assert show.status_code==200 and show.json()['correction']=={'selected':['B']}
    current=client.get('/api/v1/student/current',headers=headers).json()
    assert current['correction_visible'] and current['correction']=={'selected':['B']}
    assert client.post('/api/v1/student/answers',headers=headers,json={'answer':{'selected':['B']}}).status_code==409
    assert client.post(f'/api/v1/live/{lid}/correction/hide').status_code==200
    assert 'correction' not in client.get('/api/v1/student/current',headers=headers).json()
    assert client.post('/api/v1/student/answers',headers=headers,json={'answer':{'selected':['B']}}).status_code==200
    client.post(f'/api/v1/live/{lid}/next')
    assert client.post(f'/api/v1/live/{lid}/correction/show').status_code==409  # Pas de corrigé
    assert not client.get('/api/v1/student/current',headers=headers).json()['correction_visible']
    result=client.get(f'/api/v1/live/{lid}/results').json()['results'][0]
    assert result['answered']==1 and result['answers'][0]['answer']=={'selected':['B']}
    assert 'points' not in str(result) and 'note' not in str(result)
    out=client.get(f'/api/v1/live/{lid}/export.csv')
    rows=list(csv.DictReader(io.StringIO(out.content.decode('utf-8-sig')),delimiter=';'))
    assert len(rows)==1 and 'points' not in rows[0] and 'reponse_json' in rows[0]


def test_websocket_correction(client):
    g,e=setup_event(client)
    live=client.post('/api/v1/live/start',json={'group':g,'title':e}).json()
    lid=live['live_id']
    s=client.post('/api/v1/student/join',json={'session_code':live['session_code'],'nom':'Roux','prenom':'Alex'}).json()
    client.post(f'/api/v1/live/{lid}/next')
    with client.websocket_connect('/api/v1/student/ws') as ws:
        ws.send_json({'token':s['student_session_id']})
        assert 'correction' not in ws.receive_json()['current']
        assert client.post(f'/api/v1/live/{lid}/correction/show').status_code==200
        shown=ws.receive_json()
        assert shown['event']=='correction_shown' and shown['current']['correction']=={'selected':['B']}
        client.post(f'/api/v1/live/{lid}/correction/hide')
        hidden=ws.receive_json()
        assert hidden['event']=='correction_hidden' and 'correction' not in hidden['current']


def test_migrate_previous_sqlite(client,tmp_path):
    db=tmp_path/'classlive.db'
    with sqlite3.connect(db) as con:
        con.execute('ALTER TABLE submissions ADD COLUMN points INTEGER NOT NULL DEFAULT 0')
    con.close()
    with TestClient(create_app(Settings(workdir=tmp_path,trainer_password='test-password'))) as c:
        assert c.get('/health').status_code==200
    with sqlite3.connect(db) as con:
        cols=[r[1] for r in con.execute('PRAGMA table_info(submissions)')]
    con.close()
    assert 'points' not in cols
