import csv
import io
import json
from fastapi.testclient import TestClient
from classlive.api import create_app
from classlive.config import Settings


def prepare(c):
    g=c.post('/api/v1/groups',json={'group':'Cours'}).json()['group']
    e=c.post('/api/v1/events',json={'group':g,'title':'Bases'}).json()['title']
    path=f'/api/v1/groups/{g}/events/{e}/slides'
    assert c.post(path,json={'title':'Accueil','slide_type':'C','content':'# Bonjour'}).status_code==200
    assert c.post(path,json={'title':'Question','slide_type':'Q','content':'---\nclasslive_answer:\n  selected: [B, D]\n---\n# Choisissez B et D'}).status_code==200
    assert c.post(path,json={'title':'Texte','slide_type':'T','content':'---\nclasslive_answer:\n  blanks: [Paris]\n---\n# Capitale ?'}).status_code==200
    return g,e


def student(c, code, nom='Dupont'):
    result=c.post('/api/v1/student/join',json={'session_code':code,'nom':nom,'prenom':'Marie'})
    assert result.status_code==200, result.text
    return result.json()


def student_request(c,token,method,path,**kwargs):
    return getattr(c,method)(path,headers={'Authorization':'Bearer '+token},**kwargs)


def test_full_lifecycle(client,tmp_path):
    g,e=prepare(client)
    lid_data=client.post('/api/v1/live/start',json={'group':g,'title':e})
    assert lid_data.status_code==200,lid_data.text
    lid,code=lid_data.json()['live_id'],lid_data.json()['session_code']
    assert client.post('/api/v1/live/start',json={'group':g,'title':e}).status_code==409
    s=student(client,code)
    tok=s['student_session_id']
    assert s['current']['slide']=='S001_C_Accueil.md'
    assert student_request(client,tok,'get','/api/v1/groups').status_code==401
    assert client.get('/api/v1/live/'+lid+'/students').json()['disconnected']==1
    assert student_request(client,tok,'post','/api/v1/student/answers',json={'answer':{'selected':['B','D']}}).status_code==409
    n=client.post(f'/api/v1/live/{lid}/next')
    assert n.status_code==200
    assert 'classlive_answer' not in json.dumps(n.json())
    current=student_request(client,tok,'get','/api/v1/student/current').json()
    assert current['slide']=='S002_Q_Question.md' and 'classlive_answer' not in str(current)
    assert student_request(client,tok,'post','/api/v1/student/answers',json={'answer':{'selected':['A']}}).status_code==200
    # En mode live, une réponse est verrouillée : une seconde soumission est refusée (même après refresh).
    assert student_request(client,tok,'post','/api/v1/student/answers',json={'answer':{'selected':['D','B']}}).status_code==409
    assert student_request(client,tok,'get','/api/v1/student/current').json()['locked'] is True
    assert student_request(client,tok,'post','/api/v1/student/resume').json()['nom']=='Dupont'
    assert client.post(f'/api/v1/live/{lid}/next').status_code==200
    assert student_request(client,tok,'post','/api/v1/student/answers',json={'answer':{'blanks':['Paris']}}).status_code==200
    result=client.get(f'/api/v1/live/{lid}/results').json()['results'][0]
    assert result['answered']==2 and len(result['answers'])==2 and 'points' not in result
    assert client.delete(f'/api/v1/live/{lid}').status_code==409
    assert client.patch(f'/api/v1/groups/{g}/events/{e}',json={'new_name':'Nouvelle'}).status_code==409
    assert client.post(f'/api/v1/live/{lid}/stop').status_code==200
    assert student_request(client,tok,'get','/api/v1/student/current').status_code==401
    csvresp=client.get(f'/api/v1/live/{lid}/export.csv')
    assert csvresp.status_code==200
    lines=list(csv.DictReader(io.StringIO(csvresp.content.decode('utf-8-sig')),delimiter=';'))
    assert len(lines)==2 and 'points' not in lines[0] and lines[0]['reponse_json']
    sessions=client.get(f'/api/v1/groups/{g}/events/{e}/sessions').json()['sessions']
    assert len(sessions)==1 and sessions[0]['status']=='ended'
    assert client.delete(f'/api/v1/live/{lid}').status_code==200
    assert client.get(f'/api/v1/groups/{g}/events/{e}/sessions').json()['sessions']==[]
    assert client.post('/api/v1/live/start',json={'group':g,'title':e}).status_code==200


def test_export_reset_and_restart(client,tmp_path):
    g,e=prepare(client)
    lid=client.post('/api/v1/live/start',json={'group':g,'title':e}).json()
    student(client,lid['session_code'])
    assert client.post(f"/api/v1/live/{lid['live_id']}/stop").status_code==200
    with TestClient(create_app(Settings(workdir=tmp_path,trainer_password='test-password'))) as restarted:
        token=restarted.post('/api/v1/auth/login',json={'username':'formateur','password':'test-password'}).json()['access_token']
        restarted.headers.update({'Authorization':f'Bearer {token}'})
        assert len(restarted.get(f'/api/v1/groups/{g}/events/{e}/sessions').json()['sessions'])==1
        assert restarted.get(f'/api/v1/groups/{g}/events/{e}/export.csv').status_code==200
        assert restarted.delete(f'/api/v1/groups/{g}/events/{e}/sessions').json()['deleted_sessions']==1
        assert restarted.get(f'/api/v1/groups/{g}/events/{e}/sessions').json()['sessions']==[]


def test_ws_sync_and_monitor(client):
    g,e=prepare(client)
    live=client.post('/api/v1/live/start',json={'group':g,'title':e}).json()
    student_data=student(client,live['session_code'])
    token=student_data['student_session_id']
    lid=live['live_id']
    # Need an auth token even if TestClient defaults headers already include it.
    trainer_token=client.headers['Authorization'].split(' ',1)[1]
    with client.websocket_connect(f'/api/v1/live/{lid}/monitor') as monitor:
        monitor.send_json({'token':trainer_token})
        assert monitor.receive_json()['event']=='monitor'
        with client.websocket_connect('/api/v1/student/ws') as ws:
            ws.send_json({'token':token})
            assert ws.receive_json()['event']=='current'
            assert monitor.receive_json()['event']=='student_connected'
            assert client.get(f'/api/v1/live/{lid}/students').json()['connected']==1
            client.post(f'/api/v1/live/{lid}/next')
            assert ws.receive_json()['current']['slide']=='S002_Q_Question.md'
            assert monitor.receive_json()['event']=='slide_changed'
            ws.send_json({'event':'ping'})
            assert ws.receive_json()['event']=='pong'
        assert monitor.receive_json()['event']=='student_disconnected'
    assert client.get(f'/api/v1/live/{lid}/students').json()['disconnected']==1


def test_missing_solution_and_access(client):
    g=client.post('/api/v1/groups',json={'group':'G'}).json()['group']
    e=client.post('/api/v1/events',json={'group':g,'title':'E'}).json()['title']
    p=f'/api/v1/groups/{g}/events/{e}/slides'
    client.post(p,json={'title':'Q','slide_type':'Q','content':'# Question'})
    assert client.post('/api/v1/live/start',json={'group':g,'title':e}).status_code==200
    assert client.post('/api/v1/student/join',json={'session_code':'000000','nom':'A','prenom':'B'}).status_code==404
    assert client.post('/api/v1/auth/login',json={'username':'formateur','password':'wrong'}).status_code==401
