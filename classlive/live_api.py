"""Protected trainer routes and restricted student routes; no HTML frontend."""
from __future__ import annotations

import asyncio
import hmac
import secrets
import time
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field

from classlive.config import Settings
from classlive.live import LiveStore
from classlive.storage import ResourceNotFound


class Login(BaseModel):
    username: str
    password: str


class Begin(BaseModel):
    group: str
    title: str
    mode: str = 'live'
    timing: str = 'none'
    timing_seconds: int | None = None
    correction: str | None = None


class Jump(BaseModel):
    number: int = Field(ge=1, le=999999, strict=True)


class Join(BaseModel):
    session_code: str = Field(min_length=6,max_length=6,pattern=r'^\d{6}$')
    nom: str = Field(min_length=1,max_length=100)
    prenom: str = Field(min_length=1,max_length=100)


class Submit(BaseModel):
    answer: dict[str, Any]


class QuestionText(BaseModel):
    text: str


class AnswerText(BaseModel):
    text: str


class Reaction(BaseModel):
    emoji: str


class ChangePassword(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=200)


class Auth:
    _LOGIN_WINDOW = 60          # fenêtre de rate limiting (secondes)
    _LOGIN_MAX = 5              # tentatives max par fenêtre et par IP

    def __init__(self, cfg: Settings, store: LiveStore):
        self.cfg = cfg
        self.store = store
        self.trainers: dict[str, float] = {}
        self._login_attempts: dict[str, list[float]] = {}
        self._password = cfg.trainer_password

    def _check_rate_limit(self, client_ip: str):
        now = time.monotonic()
        attempts = [t for t in self._login_attempts.get(client_ip, []) if now - t < self._LOGIN_WINDOW]
        if len(attempts) >= self._LOGIN_MAX:
            raise HTTPException(status_code=429, detail='Trop de tentatives de connexion. Réessayez dans une minute.')
        attempts.append(now)
        self._login_attempts[client_ip] = attempts

    def _check_credentials(self, username: str, password: str) -> bool:
        if self._password and hmac.compare_digest(username, self.cfg.trainer_username) \
                and hmac.compare_digest(password, self._password):
            return True
        return any(hmac.compare_digest(username, u) and hmac.compare_digest(password, p)
                   for u, p in self.cfg.trainer_accounts)

    def login(self, payload: Login, client_ip: str = 'unknown'):
        self._check_rate_limit(client_ip)
        if not self._password and not self.cfg.trainer_accounts:
            raise HTTPException(status_code=503,detail='Configurer CLASSLIVE_TRAINER_PASSWORD ou security.trainer_accounts avant de se connecter.')
        if not self._check_credentials(payload.username, payload.password):
            self.store.audit(payload.username, 'login_failed', f'ip={client_ip}')
            raise HTTPException(status_code=401,detail='Identifiants invalides.')
        token=secrets.token_urlsafe(32)
        self.trainers[token]=time.monotonic()+8*3600
        self.store.audit(payload.username, 'login', f'ip={client_ip}')
        return {'access_token':token,'token_type':'bearer','expires_in':28800,'role':'trainer'}

    def change_password(self, old: str, new: str, client_ip: str = 'unknown', username: str = 'formateur'):
        """Change le mot de passe du compte principal en mémoire (jusqu'au redémarrage) et invalide tous les jetons."""
        self._check_rate_limit(client_ip)
        if not self._password:
            raise HTTPException(status_code=503,detail='Aucun mot de passe formateur configuré.')
        if not hmac.compare_digest(old,self._password):
            raise HTTPException(status_code=401,detail='Ancien mot de passe invalide.')
        if len(new) < 8:
            raise HTTPException(status_code=422,detail='Le nouveau mot de passe doit faire au moins 8 caractères.')
        self._password=new
        self.trainers.clear()
        self.store.audit(username, 'change_password', f'ip={client_ip}')
        return {'changed':True}

    def valid_trainer(self, token: str) -> bool:
        expiry=self.trainers.get(token,0)
        if expiry<=time.monotonic():
            self.trainers.pop(token,None)
            return False
        return True

    def trainer(self, authorization: str | None=Header(default=None), x_api_key: str | None=Header(default=None)):
        if self.cfg.api_key and x_api_key and hmac.compare_digest(x_api_key,self.cfg.api_key):
            return {'role':'trainer'}
        token=authorization.partition(' ')[2] if authorization and authorization.lower().startswith('bearer ') else ''
        if not self.valid_trainer(token):
            raise HTTPException(status_code=401, detail='Authentification formateur requise.')
        return {'role':'trainer'}

    def student(self, authorization: str | None=Header(default=None)):
        token=authorization.partition(' ')[2] if authorization and authorization.lower().startswith('bearer ') else ''
        participant=self.store.authenticate_student(token)
        if participant is None:
            raise HTTPException(status_code=401,detail='Jeton étudiant invalide ou Live terminé.')
        return participant


class Hub:
    def __init__(self):
        self.students: dict[str,set[WebSocket]] = defaultdict(set)
        self.trainers: dict[str,set[WebSocket]] = defaultdict(set)
        self.by_pid: dict[str,dict[str,WebSocket]] = defaultdict(dict)

    async def publish(self, lid, message, trainer_only=False):
        targets=list(self.trainers.get(lid,set()))
        if not trainer_only:
            targets+=list(self.students.get(lid,set()))
        for ws in targets:
            try:
                await ws.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                self.trainers[lid].discard(ws)
                self.students[lid].discard(ws)
                for pid, w in list(self.by_pid.get(lid, {}).items()):
                    if w is ws:
                        del self.by_pid[lid][pid]

    async def publish_to_student(self, lid, pid, message):
        ws = self.by_pid.get(lid, {}).get(pid)
        if ws is not None:
            try:
                await ws.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                self.by_pid[lid].pop(pid, None)
                self.students[lid].discard(ws)

    async def close_all_trainers(self):
        """Ferme toutes les connexions moniteur (invalidation des jetons formateur)."""
        for lid, sockets in list(self.trainers.items()):
            for ws in list(sockets):
                try:
                    await ws.close(code=1008)
                except Exception:
                    pass
                sockets.discard(ws)


def install_live_api(app, cfg: Settings, store: LiveStore):
    auth=Auth(cfg,store)
    hub=Hub()
    # Nombre d'élèves réellement connectés en WebSocket (visible dans student_state).
    store.online_counter=lambda lid: len(hub.by_pid.get(lid,{}))
    app.state.live_store=store
    app.state.live_auth=auth
    app.state.live_hub=hub
    trainer_routes=APIRouter(prefix='/api/v1', dependencies=[Depends(auth.trainer)])
    student_routes=APIRouter(prefix='/api/v1')

    @student_routes.post('/auth/login', tags=['Authentification'])
    def login(payload: Login, request: Request):
        client_ip = request.client.host if request.client else 'unknown'
        return auth.login(payload, client_ip)

    @student_routes.post('/auth/change-password', tags=['Authentification'])
    async def change_password(payload: ChangePassword, request: Request):
        client_ip = request.client.host if request.client else 'unknown'
        result = auth.change_password(payload.old_password, payload.new_password, client_ip,
                                      username=cfg.trainer_username)
        await hub.close_all_trainers()  # invalide aussi les WS moniteur ouverts
        return result

    @trainer_routes.post('/live/start', tags=['Live formateur'])
    def start(payload: Begin):
        correction = payload.correction or ('show' if payload.mode == 'live' else 'à_la_fin')
        try:
            result = store.start(payload.group, payload.title, mode=payload.mode, timing=payload.timing,
                                 timing_seconds=payload.timing_seconds, correction_mode=correction)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        store.audit(cfg.trainer_username, 'live_start',
                    f"{result['group']}/{result['event']} mode={payload.mode} code={result['session_code']}")
        return result

    async def movement(lid,direction,number=None):
        result=store.move(lid,direction,number)
        await hub.publish(lid,{'event':'slide_changed','current':result})
        return result

    @trainer_routes.post('/live/{live_id}/next',tags=['Live formateur'])
    async def next_(live_id: str):
        return await movement(live_id,'next')

    @trainer_routes.post('/live/{live_id}/previous',tags=['Live formateur'])
    async def previous(live_id: str):
        return await movement(live_id,'previous')

    @trainer_routes.post('/live/{live_id}/goto',tags=['Live formateur'])
    async def goto(live_id: str, payload: Jump):
        return await movement(live_id,'goto',payload.number)

    @trainer_routes.get('/live/{live_id}/status',tags=['Live formateur'])
    def live_status(live_id: str):
        return store.state(live_id,include_content=True)

    async def set_correction(live_id: str, visible: bool):
        result = store.correction(live_id, visible)
        await hub.publish(live_id, {'event': 'correction_shown' if visible else 'correction_hidden', 'current': result})
        return result

    @trainer_routes.post('/live/{live_id}/correction/show',tags=['Live formateur'])
    async def show_correction(live_id: str):
        return await set_correction(live_id, True)

    @trainer_routes.post('/live/{live_id}/correction/hide',tags=['Live formateur'])
    async def hide_correction(live_id: str):
        return await set_correction(live_id, False)

    @trainer_routes.post('/live/{live_id}/stop',tags=['Live formateur'])
    async def stop(live_id: str):
        result=store.stop(live_id)
        store.audit(cfg.trainer_username, 'live_stop', f"{result['group']}/{result['event']} live_id={live_id}")
        await hub.publish(live_id,{'event':'live_ended','live_id':live_id})
        return result

    @trainer_routes.get('/live/{live_id}/students',tags=['Live formateur'])
    def students(live_id: str):
        return store.students(live_id)

    @trainer_routes.get('/live/{live_id}/results',tags=['Résultats'])
    def results(live_id: str):
        return store.results(live_id)

    @trainer_routes.get('/live/{live_id}/stats',tags=['Résultats'])
    def live_stats(live_id: str, all: bool = False):
        return store.stats(live_id, all_slides=all)

    @trainer_routes.get('/live/active',tags=['Live formateur'])
    def active_lives():
        return store.active()

    @trainer_routes.delete('/live/{live_id}/students/{participation_id}',tags=['Live formateur'])
    async def kick_student(live_id: str, participation_id: str):
        result=store.kick(live_id,participation_id)
        store.audit(cfg.trainer_username, 'student_kick', f'live_id={live_id} participation_id={participation_id}')
        await hub.publish(live_id,{'event':'student_kicked','participation_id':participation_id})
        return result

    @trainer_routes.get('/live/{live_id}/export.csv',tags=['Résultats'])
    def export_live(live_id: str):
        return Response(store.csv([live_id]),media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition':f'attachment; filename="classlive_{live_id}.csv"'})

    @trainer_routes.get('/groups/{group}/events/{event}/sessions',tags=['Résultats'])
    def list_sessions(group: str,event: str):
        return store.sessions(group,event)

    @trainer_routes.get('/groups/{group}/events/{event}/export.csv',tags=['Résultats'])
    def export_event(group: str,event: str):
        return Response(store.event_csv(group,event),media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition':'attachment; filename="classlive_evenement.csv"'})

    @trainer_routes.get('/groups/{group}/events/{event}/student-results',tags=['Résultats'])
    def student_results(group: str, event: str, nom: str | None = None, prenom: str | None = None):
        if not nom or not prenom:
            raise HTTPException(status_code=422, detail='Paramètres nom et prenom obligatoires.')
        return store.student_results(group, event, nom.strip(), prenom.strip())

    @trainer_routes.delete('/live/{live_id}',tags=['Résultats'])
    def delete_session(live_id: str):
        return store.delete(live_id)

    @trainer_routes.delete('/groups/{group}/events/{event}/sessions',tags=['Résultats'])
    def reset(group: str,event: str):
        return store.reset(group,event)

    @student_routes.post('/student/join',tags=['Étudiants'])
    async def join(payload: Join):
        nom,prenom=payload.nom.strip(),payload.prenom.strip()
        if not nom or not prenom or any(ord(x)<32 for x in nom+prenom):
            raise HTTPException(status_code=422,detail='Nom et prénom obligatoires et valides.')
        result=store.join(payload.session_code,nom,prenom)
        await hub.publish(result['live_id'],{'event':'student_joined','participation_id':result['participation_id']},trainer_only=True)
        return result

    @student_routes.post('/student/resume',tags=['Étudiants'])
    def resume(student=Depends(auth.student)):
        return store.resume(student)

    @student_routes.get('/student/current',tags=['Étudiants'])
    def current(student=Depends(auth.student)):
        store.touch(student['id'])
        return store.student_state(student)

    @student_routes.post('/student/next',tags=['Étudiants'])
    async def student_next(student=Depends(auth.student)):
        result=store.student_move(student,'next')
        lid=student['live_id']
        await hub.publish_to_student(lid,student['id'],{'event':'slide_changed','current':result})
        if result.get('finished'):
            await hub.publish(lid,{'event':'student_finished','participation_id':student['id']},trainer_only=True)
            await hub.publish_to_student(lid,student['id'],{'event':'session_ended','live_id':lid})
        return result

    @student_routes.post('/student/previous',tags=['Étudiants'])
    async def student_previous(student=Depends(auth.student)):
        result=store.student_move(student,'previous')
        await hub.publish_to_student(student['live_id'],student['id'],{'event':'slide_changed','current':result})
        return result

    @student_routes.get('/student/results',tags=['Étudiants'])
    def student_results(student=Depends(auth.student)):
        return store.student_own_results(student)

    @student_routes.post('/student/answers',tags=['Étudiants'])
    async def answer(payload: Submit,student=Depends(auth.student)):
        try:
            result=store.submit(student,payload.answer)
        except ValueError as exc:
            raise HTTPException(status_code=422,detail=str(exc)) from exc
        await hub.publish(student['live_id'],{'event':'answer_received','participation_id':student['id']},trainer_only=True)
        if result.get('locked'):
            await hub.publish_to_student(student['live_id'],student['id'],
                                         {'event':'answer_locked','slide':result['slide']})
        return result

    # ── Q&A élève pendant le live ───────────────────────────────────────────

    @student_routes.post('/student/questions',tags=['Étudiants'])
    async def ask(payload: QuestionText,student=Depends(auth.student)):
        try:
            result=store.ask_question(student,payload.text)
        except ValueError as exc:
            raise HTTPException(status_code=422,detail=str(exc)) from exc
        lid=student['live_id']
        await hub.publish(lid,{'event':'question_asked','participation_id':student['id'],
                               'question_id':result['question_id'],'nom':student['nom'],'prenom':student['prenom']},
                          trainer_only=True)
        return {'success':True,**result}

    @student_routes.get('/student/questions',tags=['Étudiants'])
    def my_questions(student=Depends(auth.student)):
        return store.my_questions(student)

    @trainer_routes.get('/live/{live_id}/questions',tags=['Live formateur'])
    def list_questions(live_id: str):
        return store.list_questions(live_id)

    @trainer_routes.post('/live/{live_id}/questions/{qid}/answer',tags=['Live formateur'])
    async def answer_question(live_id: str, qid: int, payload: AnswerText):
        try:
            result=store.answer_question(live_id,qid,payload.text)
        except ValueError as exc:
            raise HTTPException(status_code=422,detail=str(exc)) from exc
        await hub.publish_to_student(live_id,result['participation_id'],
                                     {'event':'question_answered','question_id':qid,
                                      'answer_text':result['answer_text'],'answered_at':result['answered_at']})
        await hub.publish(live_id,{'event':'question_updated','question_id':qid,'answered':True},trainer_only=True)
        return {'success':True,**result}

    @trainer_routes.post('/live/{live_id}/questions/{qid}/toggle',tags=['Live formateur'])
    async def toggle_question(live_id: str, qid: int):
        result=store.toggle_question(live_id,qid)
        await hub.publish(live_id,{'event':'question_updated','question_id':qid,'answered':result['answered']},trainer_only=True)
        return {'success':True,**result}

    # ── Réactions emoji en live ─────────────────────────────────────────────

    @student_routes.post('/student/reaction',tags=['Étudiants'])
    async def reaction(payload: Reaction,student=Depends(auth.student)):
        try:
            result=store.react(student,payload.emoji)
        except ValueError as exc:
            raise HTTPException(status_code=422,detail=str(exc)) from exc
        await hub.publish(student['live_id'],{'event':'reaction','participation_id':student['id'],
                                              'emoji':result['emoji'],'counts':result['counts']})
        return {'success':True,**result}

    @trainer_routes.get('/live/{live_id}/reactions',tags=['Live formateur'])
    def list_reactions(live_id: str):
        return store.reactions(live_id)

    async def authorize_ws(ws: WebSocket, trainer: bool):
        await ws.accept()
        try:
            packet=await asyncio.wait_for(ws.receive_json(),timeout=10)
        except (ValueError,asyncio.TimeoutError,WebSocketDisconnect):
            await ws.close(code=1008)
            return None
        token=packet.get('token') if isinstance(packet,dict) else None
        if not isinstance(token,str):
            await ws.close(code=1008)
            return None
        if trainer:
            if not auth.valid_trainer(token):
                await ws.close(code=1008)
                return None
            return {'role':'trainer'}
        participant=store.authenticate_student(token)
        if participant is None:
            await ws.close(code=1008)
            return None
        return participant

    @app.websocket('/api/v1/student/ws')
    async def student_ws(ws: WebSocket):
        student=await authorize_ws(ws,False)
        if student is None:
            return
        lid,pid=student['live_id'],student['id']
        hub.students[lid].add(ws)
        hub.by_pid[lid][pid]=ws
        store.connected(lid,pid)
        await ws.send_json({'event':'current','current':store.student_state(student)})
        await hub.publish(lid,{'event':'student_connected','participation_id':pid},trainer_only=True)
        try:
            while True:
                data=await ws.receive_json()
                if isinstance(data,dict) and data.get('event')=='ping':
                    if store.state(lid)['status'] != 'running' or not store.participation_exists(pid):
                        await ws.close(code=1008)
                        break
                    store.ping(lid,pid)
                    await ws.send_json({'event':'pong'})
                else:
                    await ws.send_json({'event':'error','detail':'Seul ping est autorisé.'})
        except WebSocketDisconnect:
            pass
        finally:
            hub.students[lid].discard(ws)
            hub.by_pid[lid].pop(pid,None)
            store.disconnected(lid,pid)
            await hub.publish(lid,{'event':'student_disconnected','participation_id':pid},trainer_only=True)

    @app.websocket('/api/v1/live/{live_id}/monitor')
    async def trainer_ws(ws: WebSocket,live_id: str):
        trainer=await authorize_ws(ws,True)
        if trainer is None:
            return
        try:
            store.state(live_id)
        except ResourceNotFound:
            await ws.close(code=1008)
            return
        hub.trainers[live_id].add(ws)
        await ws.send_json({'event':'monitor','students':store.students(live_id),'current':store.state(live_id)})
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hub.trainers[live_id].discard(ws)

    app.include_router(student_routes)
    app.include_router(trainer_routes)
    return auth
