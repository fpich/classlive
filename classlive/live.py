"""SQLite-backed live sessions, registrations and exercise submissions."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path

import yaml

from classlive.slides import SLIDE_RE, SlideStorage
from classlive.storage import ResourceConflict, ResourceNotFound

EXERCISES = set('AORQT')


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def prepare_markdown(markdown: str) -> tuple[str, object | None]:
    """Remove private answer key before sending slide to students.

    Expected front matter: ---\nclasslive_answer: {selected: [B]}\n---\n# Question
    The entire frontmatter is excluded from student output (no leaking other keys).
    """
    if not markdown.startswith('---\n'):
        return markdown, None
    header, sep, content = markdown[4:].partition('\n---\n')
    if not sep:
        raise ValueError('Frontmatter YAML incomplet.')
    try:
        data = yaml.safe_load(header) or {}
    except yaml.YAMLError as exc:
        raise ValueError("Frontmatter YAML invalide.") from exc
    if not isinstance(data, dict):
        raise ValueError('Frontmatter YAML invalide.')
    return content, data.get('classlive_answer')




class LiveStore:
    def __init__(self, db_path: Path, slides: SlideStorage):
        self.path = db_path
        self.slides = slides
        self.lock = threading.RLock()
        self.connections: dict[str, dict[str, float]] = {}
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as con:
            con.executescript('''
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS live_sessions (
              id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE, group_name TEXT NOT NULL,
              event_name TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
              status TEXT NOT NULL, current_number INTEGER NOT NULL, revision INTEGER NOT NULL DEFAULT 0, correction_visible INTEGER NOT NULL DEFAULT 0
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_running_live ON live_sessions(group_name, event_name) WHERE status='running';
            CREATE TABLE IF NOT EXISTS participations (
              id TEXT PRIMARY KEY, live_id TEXT NOT NULL REFERENCES live_sessions(id) ON DELETE CASCADE,
              nom TEXT NOT NULL, prenom TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
              joined_at TEXT NOT NULL, last_seen TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snapshots (
              live_id TEXT NOT NULL REFERENCES live_sessions(id) ON DELETE CASCADE,
              number INTEGER NOT NULL, filename TEXT NOT NULL, kind TEXT NOT NULL,
              public_content TEXT NOT NULL, answer_key TEXT,
              PRIMARY KEY(live_id,number)
            );
            CREATE TABLE IF NOT EXISTS submissions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              participation_id TEXT NOT NULL REFERENCES participations(id) ON DELETE CASCADE,
              slide_number INTEGER NOT NULL, answer_json TEXT NOT NULL,
              submitted_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS submission_lookup ON submissions(participation_id,slide_number,id);
            CREATE TABLE IF NOT EXISTS autonomous_progress (
              participation_id TEXT PRIMARY KEY REFERENCES participations(id) ON DELETE CASCADE,
              current_number INTEGER NOT NULL, finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS slide_locks (
              participation_id TEXT NOT NULL REFERENCES participations(id) ON DELETE CASCADE,
              slide_number INTEGER NOT NULL, locked_at TEXT NOT NULL, reason TEXT NOT NULL,
              PRIMARY KEY(participation_id, slide_number)
            );
            CREATE TABLE IF NOT EXISTS question_timers (
              participation_id TEXT NOT NULL REFERENCES participations(id) ON DELETE CASCADE,
              slide_number INTEGER NOT NULL, started_at TEXT NOT NULL,
              PRIMARY KEY(participation_id, slide_number)
            );
            ''')
            # Migration non destructive des bases créées avec la v0.7.0.
            columns = {row['name'] for row in con.execute('PRAGMA table_info(live_sessions)')}
            if 'correction_visible' not in columns:
                con.execute('ALTER TABLE live_sessions ADD COLUMN correction_visible INTEGER NOT NULL DEFAULT 0')
            # Migration v0.8.4 rev.4 : mode autonome.
            for col, ddl in (
                ('mode', "TEXT NOT NULL DEFAULT 'live'"),
                ('timing', "TEXT NOT NULL DEFAULT 'none'"),
                ('timing_seconds', "INTEGER"),
                ('correction_mode', "TEXT NOT NULL DEFAULT 'show'"),
                ('deadline', "TEXT"),
            ):
                if col not in columns:
                    con.execute(f'ALTER TABLE live_sessions ADD COLUMN {col} {ddl}')
            old_submissions = {row['name'] for row in con.execute('PRAGMA table_info(submissions)')}
            if 'points' in old_submissions:
                con.execute('CREATE TABLE submissions_new (id INTEGER PRIMARY KEY AUTOINCREMENT, participation_id TEXT NOT NULL REFERENCES participations(id) ON DELETE CASCADE, slide_number INTEGER NOT NULL, answer_json TEXT NOT NULL, submitted_at TEXT NOT NULL)')
                con.execute('INSERT INTO submissions_new(id,participation_id,slide_number,answer_json,submitted_at) SELECT id,participation_id,slide_number,answer_json,submitted_at FROM submissions')
                con.execute('DROP TABLE submissions')
                con.execute('ALTER TABLE submissions_new RENAME TO submissions')
                con.execute('CREATE INDEX submission_lookup ON submissions(participation_id,slide_number,id)')

    @contextmanager
    def db(self):
        con = sqlite3.connect(self.path, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        try:
            with con:
                yield con
        finally:
            con.close()

    @staticmethod
    def fail_if_missing(row, label):
        if row is None:
            raise ResourceNotFound(f'{label} introuvable.')
        return row

    def _live(self, con, lid):
        return self.fail_if_missing(con.execute('SELECT * FROM live_sessions WHERE id=?', (lid,)).fetchone(), 'Session Live')

    def _participation(self, con, pid):
        return self.fail_if_missing(con.execute('SELECT * FROM participations WHERE id=?', (pid,)).fetchone(), 'Participation')

    def start(self, group: str, event: str, mode: str = 'live', timing: str = 'none',
              timing_seconds: int | None = None, correction_mode: str = 'show') -> dict:
        """Démarre une session. mode='live' (formateur pilote) ou 'autonome' (élèves à leur rythme)."""
        if mode not in ('live', 'autonome'):
            raise ValueError("mode doit être 'live' ou 'autonome'.")
        if mode == 'autonome':
            if timing not in ('none', 'par_question', 'par_evenement'):
                raise ValueError("timing doit être 'none', 'par_question' ou 'par_evenement'.")
            if timing != 'none':
                if type(timing_seconds) is not int or not 1 <= timing_seconds <= 86400:
                    raise ValueError('timing_seconds requis (1 à 86400) quand timing est actif.')
            else:
                timing_seconds = None
            if correction_mode not in ('jamais', 'après_question', 'à_la_fin'):
                raise ValueError("correction_mode doit être 'jamais', 'après_question' ou 'à_la_fin'.")
        else:
            timing, timing_seconds, correction_mode = 'none', None, 'show'
        # Freeze both public slide and private correct answers for historical integrity.
        with self.lock, self.slides.events._lock:
            g, parent = self.slides._parent(group, event)
            files = self.slides._slides(parent)
            if not files:
                raise ResourceConflict('Impossible de démarrer un événement sans slides.')
            prepared = []
            for path in files:
                match = SLIDE_RE.fullmatch(path.name)
                number, kind = int(match.group(1)), match.group(2)
                content, key = prepare_markdown(path.read_text(encoding='utf-8'))
                prepared.append((number, path.name, kind, content, json.dumps(key, ensure_ascii=False) if key is not None else None))
            lid = str(uuid.uuid4())
            with self.db() as con:
                if con.execute("SELECT 1 FROM live_sessions WHERE group_name=? AND event_name=? AND status='running'", (g.name, parent.name)).fetchone():
                    raise ResourceConflict('Une session est déjà active sur cet événement.')
                for _ in range(30):
                    code = f'{secrets.randbelow(1000000):06d}'
                    if not con.execute('SELECT 1 FROM live_sessions WHERE code=?', (code,)).fetchone():
                        break
                else:
                    raise ResourceConflict('Aucun code Live disponible.')
                deadline = None
                if mode == 'autonome' and timing == 'par_evenement':
                    deadline = datetime.fromtimestamp(time.time() + timing_seconds, timezone.utc).isoformat()
                con.execute('INSERT INTO live_sessions(id,code,group_name,event_name,started_at,status,current_number,mode,timing,timing_seconds,correction_mode,deadline) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                            (lid, code, g.name, parent.name, now(), 'running', prepared[0][0], mode, timing, timing_seconds, correction_mode, deadline))
                con.executemany('INSERT INTO snapshots(live_id,number,filename,kind,public_content,answer_key) VALUES (?,?,?,?,?,?)',
                                [(lid, *row) for row in prepared])
            return {'live_id': lid, 'session_code': code, 'group': g.name, 'event': parent.name, 'current_slide': prepared[0][1],
                    'status': 'running', 'mode': mode, 'timing': timing, 'timing_seconds': timing_seconds, 'correction_mode': correction_mode}

    def state(self, lid: str, include_content: bool = False):
        with self.db() as con:
            session = self._live(con, lid)
            slides = con.execute('SELECT number,filename,kind,public_content FROM snapshots WHERE live_id=? ORDER BY number', (lid,)).fetchall()
            current = next(s for s in slides if s['number'] == session['current_number'])
            result = {'live_id': lid, 'status': session['status'], 'mode': session['mode'], 'group': session['group_name'], 'event': session['event_name'],
                      'slide': current['filename'], 'slide_type': current['kind'], 'number': current['number'],
                      'position': next(i+1 for i,s in enumerate(slides) if s['number'] == current['number']),
                      'total': len(slides), 'revision': session['revision'],
                      'timing': session['timing'], 'timing_seconds': session['timing_seconds'],
                      'correction_mode': session['correction_mode'], 'deadline': session['deadline'],
                      'correction_visible': bool(session['correction_visible']) if current['kind'] in EXERCISES else False}
            if include_content:
                result['content'] = current['public_content']
                if result['correction_visible']:
                    private = con.execute('SELECT answer_key FROM snapshots WHERE live_id=? AND number=?',
                                          (lid, current['number'])).fetchone()['answer_key']
                    result['correction'] = json.loads(private) if private is not None else None
            return result

    def move(self, lid: str, direction: str, number: int | None = None):
        with self.lock, self.db() as con:
            session = self._live(con, lid)
            if session['status'] != 'running':
                raise ResourceConflict('Session Live terminée.')
            numbers = [r['number'] for r in con.execute('SELECT number FROM snapshots WHERE live_id=? ORDER BY number', (lid,))]
            i = numbers.index(session['current_number'])
            if direction == 'next':
                target = numbers[min(i + 1, len(numbers)-1)]
            elif direction == 'previous':
                target = numbers[max(i - 1, 0)]
            elif direction == 'goto':
                if number not in numbers:
                    raise ResourceNotFound('Numéro de slide absent de la session.')
                target = number
            else:
                raise ValueError('Direction invalide.')
            con.execute('UPDATE live_sessions SET current_number=?,correction_visible=0,revision=revision+1 WHERE id=?', (target,lid))
        return self.state(lid, include_content=True)

    def correction(self, lid: str, show: bool):
        """Seul le formateur active l'affichage du corrigé de la slide courante."""
        with self.lock, self.db() as con:
            session = self._live(con, lid)
            if session['status'] != 'running':
                raise ResourceConflict('Session Live terminée.')
            snapshot = con.execute('SELECT kind,answer_key FROM snapshots WHERE live_id=? AND number=?',
                                   (lid, session['current_number'])).fetchone()
            if snapshot['kind'] not in EXERCISES:
                raise ResourceConflict('La slide courante n’est pas un exercice.')
            if show and snapshot['answer_key'] is None:
                raise ResourceConflict('Aucun corrigé classlive_answer défini pour cette slide.')
            con.execute('UPDATE live_sessions SET correction_visible=?,revision=revision+1 WHERE id=?', (int(show), lid))
        return self.state(lid, include_content=True)

    def stop(self, lid: str):
        with self.lock, self.db() as con:
            session = self._live(con, lid)
            if session['status'] == 'running':
                con.execute("UPDATE live_sessions SET status='ended',ended_at=?,revision=revision+1 WHERE id=?", (now(),lid))
                if session['mode'] == 'autonome':
                    # Verrouille la position de chaque élève non terminé.
                    parts = con.execute('SELECT id FROM participations WHERE live_id=?', (lid,)).fetchall()
                    snaps = con.execute('SELECT number FROM snapshots WHERE live_id=?', (lid,)).fetchall()
                    for p in parts:
                        prog = con.execute('SELECT current_number,finished_at FROM autonomous_progress WHERE participation_id=?', (p['id'],)).fetchone()
                        if prog is None or prog['finished_at']:
                            continue
                        for s in snaps:
                            con.execute('INSERT OR IGNORE INTO slide_locks(participation_id,slide_number,locked_at,reason) VALUES (?,?,?,?)',
                                        (p['id'], s['number'], now(), 'session_ended'))
                        con.execute('UPDATE autonomous_progress SET finished_at=? WHERE participation_id=?', (now(), p['id']))
        return self.state(lid)

    def join(self, code: str, nom: str, prenom: str):
        with self.lock, self.db() as con:
            session = con.execute("SELECT * FROM live_sessions WHERE code=? AND status='running'", (code,)).fetchone()
            self.fail_if_missing(session, 'Code de session active')
            pid = str(uuid.uuid4())
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode()).hexdigest()
            con.execute('INSERT INTO participations(id,live_id,nom,prenom,token_hash,joined_at,last_seen) VALUES(?,?,?,?,?,?,?)',
                        (pid, session['id'],nom,prenom,digest,now(),now()))
            if session['mode'] == 'autonome':
                first = con.execute('SELECT MIN(number) AS n FROM snapshots WHERE live_id=?', (session['id'],)).fetchone()['n']
                con.execute('INSERT INTO autonomous_progress(participation_id,current_number) VALUES (?,?)', (pid, first))
        student = {'id': pid, 'live_id': session['id'], 'nom': nom, 'prenom': prenom}
        return {'student_session_id': token, 'participation_id': pid, 'live_id': session['id'], 'nom': nom, 'prenom': prenom,
                'mode': session['mode'], 'current': self.student_state(student)}

    def authenticate_student(self, token: str, require_running: bool = True):
        if not token or len(token) > 512:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.db() as con:
            row = con.execute('SELECT p.*,l.status FROM participations p JOIN live_sessions l ON l.id=p.live_id WHERE token_hash=?', (digest,)).fetchone()
            if row is None or (require_running and row['status'] != 'running'):
                return None
            return dict(row)

    def touch(self, pid):
        with self.db() as con:
            con.execute('UPDATE participations SET last_seen=? WHERE id=?', (now(),pid))

    def resume(self, student):
        self.touch(student['id'])
        with self.db() as con:
            live = self._live(con, student['live_id'])
        current = self.student_state(student) if live['mode'] == 'autonome' else self.state(student['live_id'], include_content=True)
        return {'participation_id': student['id'], 'live_id': student['live_id'], 'nom': student['nom'], 'prenom': student['prenom'],
                'mode': live['mode'], 'current': current}

    # ── Mode autonome ────────────────────────────────────────────────────────

    def _ensure_progress(self, con, pid, lid):
        prog = con.execute('SELECT * FROM autonomous_progress WHERE participation_id=?', (pid,)).fetchone()
        if prog is None:
            first = con.execute('SELECT MIN(number) AS n FROM snapshots WHERE live_id=?', (lid,)).fetchone()['n']
            con.execute('INSERT INTO autonomous_progress(participation_id,current_number) VALUES (?,?)', (pid, first))
            prog = con.execute('SELECT * FROM autonomous_progress WHERE participation_id=?', (pid,)).fetchone()
        return prog

    @staticmethod
    def _slide_locked(con, pid, number):
        return con.execute('SELECT 1 FROM slide_locks WHERE participation_id=? AND slide_number=?', (pid, number)).fetchone() is not None

    def _check_deadline(self, con, pid, live):
        """En timing par_evenement, termine la session perso à la deadline."""
        if live['mode'] == 'autonome' and live['timing'] == 'par_evenement' and live['deadline']:
            prog = con.execute('SELECT finished_at FROM autonomous_progress WHERE participation_id=?', (pid,)).fetchone()
            if prog and not prog['finished_at'] and datetime.now(timezone.utc).isoformat() > live['deadline']:
                snaps = con.execute('SELECT number FROM snapshots WHERE live_id=?', (live['id'],)).fetchall()
                for s in snaps:
                    con.execute('INSERT OR IGNORE INTO slide_locks(participation_id,slide_number,locked_at,reason) VALUES (?,?,?,?)',
                                (pid, s['number'], now(), 'deadline'))
                con.execute('UPDATE autonomous_progress SET finished_at=? WHERE participation_id=?', (now(), pid))

    def _student_current_number(self, con, student, live):
        if live['mode'] == 'autonome':
            self._ensure_progress(con, student['id'], live['id'])
            self._check_deadline(con, student['id'], live)
            prog = con.execute('SELECT current_number,finished_at FROM autonomous_progress WHERE participation_id=?',
                               (student['id'],)).fetchone()
            return prog['current_number'], prog['finished_at']
        return live['current_number'], None

    def student_state(self, student):
        """Vue de la slide courante pour un élève (position perso en autonome)."""
        with self.db() as con:
            live = self._live(con, student['live_id'])
            number, finished = self._student_current_number(con, student, live)
            snap = con.execute('SELECT * FROM snapshots WHERE live_id=? AND number=?', (live['id'], number)).fetchone()
            if snap is None:
                raise ResourceNotFound('Slide introuvable dans la session.')
            slides = con.execute('SELECT number FROM snapshots WHERE live_id=? ORDER BY number', (live['id'],)).fetchall()
            numbers = [s['number'] for s in slides]
            i = numbers.index(number)
            locked = self._slide_locked(con, student['id'], number) if live['mode'] == 'autonome' else False
            result = {'live_id': live['id'], 'status': live['status'], 'mode': live['mode'],
                      'group': live['group_name'], 'event': live['event_name'],
                      'slide': snap['filename'], 'slide_type': snap['kind'], 'number': number,
                      'position': i + 1, 'total': len(numbers), 'revision': live['revision'],
                      'content': snap['public_content'], 'finished': bool(finished)}
            if live['mode'] == 'autonome':
                result['locked'] = locked
                # Timer par question : démarre au premier affichage de la slide.
                if live['timing'] == 'par_question' and snap['kind'] in EXERCISES and not finished:
                    timer = con.execute('SELECT started_at FROM question_timers WHERE participation_id=? AND slide_number=?',
                                        (student['id'], number)).fetchone()
                    if timer is None:
                        started = now()
                        con.execute('INSERT INTO question_timers(participation_id,slide_number,started_at) VALUES (?,?,?)',
                                    (student['id'], number, started))
                    else:
                        started = timer['started_at']
                    expires_ts = datetime.fromisoformat(started).timestamp() + live['timing_seconds']
                    if not locked and time.time() > expires_ts:
                        con.execute('INSERT OR IGNORE INTO slide_locks(participation_id,slide_number,locked_at,reason) VALUES (?,?,?,?)',
                                    (student['id'], number, now(), 'time_expired'))
                        locked = True
                        result['locked'] = True
                    if not locked:
                        result['question_started_at'] = started
                        result['expires_at'] = datetime.fromtimestamp(expires_ts, timezone.utc).isoformat()
                # Correction selon le mode.
                show_correction = False
                if live['correction_mode'] == 'après_question' and locked and snap['kind'] in EXERCISES:
                    show_correction = True
                if live['correction_mode'] == 'à_la_fin' and finished:
                    show_correction = True
                if show_correction and snap['answer_key'] is not None:
                    result['correction'] = json.loads(snap['answer_key'])
                elif show_correction:
                    result['correction'] = None
            else:
                result['correction_visible'] = bool(live['correction_visible']) if snap['kind'] in EXERCISES else False
                if result['correction_visible'] and live['correction_visible']:
                    private = con.execute('SELECT answer_key FROM snapshots WHERE live_id=? AND number=?',
                                          (live['id'], number)).fetchone()['answer_key']
                    result['correction'] = json.loads(private) if private is not None else None
            return result

    def student_move(self, student, direction: str):
        """next/previous en mode autonome. next bloqué sur un exercice non répondu."""
        with self.lock, self.db() as con:
            live = self._live(con, student['live_id'])
            if live['status'] != 'running':
                raise ResourceConflict('La session est terminée.')
            if live['mode'] != 'autonome':
                raise ResourceConflict('La navigation élève n’est disponible qu’en session autonome.')
            prog = self._ensure_progress(con, student['id'], live['id'])
            self._check_deadline(con, student['id'], live)
            prog = con.execute('SELECT * FROM autonomous_progress WHERE participation_id=?', (student['id'],)).fetchone()
            if direction == 'next' and prog['finished_at']:
                raise ResourceConflict('Votre session autonome est terminée.')
            numbers = [r['number'] for r in con.execute('SELECT number FROM snapshots WHERE live_id=? ORDER BY number', (live['id'],))]
            i = numbers.index(prog['current_number'])
            current_snap = con.execute('SELECT kind FROM snapshots WHERE live_id=? AND number=?', (live['id'], prog['current_number'])).fetchone()
            if direction == 'next':
                if current_snap['kind'] in EXERCISES and not self._slide_locked(con, student['id'], prog['current_number']):
                    raise ResourceConflict('Validez votre réponse avant de passer à la suivante.')
                target = numbers[min(i + 1, len(numbers) - 1)]
                if i + 1 >= len(numbers):
                    self._finish_locked(con, student['id'], live['id'], 'completed')
            elif direction == 'previous':
                target = numbers[max(i - 1, 0)]
            else:
                raise ValueError('Direction invalide.')
            con.execute('UPDATE autonomous_progress SET current_number=? WHERE participation_id=?', (target, student['id']))
        return self.student_state(student)

    def _finish_locked(self, con, pid, lid, reason):
        snaps = con.execute('SELECT number FROM snapshots WHERE live_id=?', (lid,)).fetchall()
        for s in snaps:
            con.execute('INSERT OR IGNORE INTO slide_locks(participation_id,slide_number,locked_at,reason) VALUES (?,?,?,?)',
                        (pid, s['number'], now(), reason))
        con.execute('UPDATE autonomous_progress SET finished_at=? WHERE participation_id=?', (now(), pid))

    def student_own_results(self, student):
        """Récap personnel de l'élève en autonome, disponible une fois sa session terminée."""
        with self.db() as con:
            live = self._live(con, student['live_id'])
            if live['mode'] != 'autonome':
                raise ResourceConflict('Le récapitulatif personnel n’est disponible qu’en session autonome.')
            prog = self._ensure_progress(con, student['id'], live['id'])
            if not prog['finished_at']:
                raise ResourceConflict('Terminez toutes les slides pour voir votre récapitulatif.')
            snaps = con.execute('SELECT number,filename,kind,answer_key FROM snapshots WHERE live_id=? ORDER BY number', (live['id'],)).fetchall()
            subs = con.execute('SELECT slide_number,answer_json,submitted_at FROM submissions WHERE participation_id=? ORDER BY slide_number,id',
                               (student['id'],)).fetchall()
            by_slide = {}
            for s in subs:
                by_slide[s['slide_number']] = s  # dernière réponse (une seule en autonome)
            slides_out = []
            for snap in snaps:
                entry = {'slide': snap['filename'], 'slide_type': snap['kind'], 'number': snap['number'],
                         'answered': snap['number'] in by_slide}
                if entry['answered']:
                    entry['answer'] = json.loads(by_slide[snap['number']]['answer_json'])
                    entry['submitted_at'] = by_slide[snap['number']]['submitted_at']
                if live['correction_mode'] != 'jamais' and snap['answer_key'] is not None:
                    entry['correction'] = json.loads(snap['answer_key'])
                slides_out.append(entry)
            return {'live_id': live['id'], 'participation_id': student['id'], 'nom': student['nom'], 'prenom': student['prenom'],
                    'finished_at': prog['finished_at'], 'total_slides': len(snaps), 'answered': sum(1 for e in slides_out if e['answered']),
                    'slides': slides_out}

    def submit(self, student, answer: object):
        if not isinstance(answer, dict):
            raise ValueError('La réponse doit être un objet JSON.')
        with self.lock, self.db() as con:
            live = self._live(con, student['live_id'])
            if live['status'] != 'running':
                raise ResourceConflict('La session est terminée.')
            if live['mode'] == 'autonome':
                number, finished = self._student_current_number(con, student, live)
                if finished:
                    raise ResourceConflict('Votre session autonome est terminée.')
                snap = con.execute('SELECT * FROM snapshots WHERE live_id=? AND number=?', (live['id'], number)).fetchone()
            else:
                snap = con.execute('SELECT * FROM snapshots WHERE live_id=? AND number=?', (live['id'],live['current_number'])).fetchone()
            if snap['kind'] not in EXERCISES:
                raise ResourceConflict('La slide en cours n’est pas un exercice.')
            if live['correction_visible']:
                raise ResourceConflict('Les réponses sont fermées pendant l’affichage de la correction.')
            if live['mode'] == 'autonome':
                if self._slide_locked(con, student['id'], snap['number']):
                    raise ResourceConflict('Réponse déjà verrouillée pour cette slide.')
                if live['timing'] == 'par_question':
                    timer = con.execute('SELECT started_at FROM question_timers WHERE participation_id=? AND slide_number=?',
                                        (student['id'], snap['number'])).fetchone()
                    if timer is not None:
                        expires = datetime.fromisoformat(timer['started_at']).timestamp() + live['timing_seconds']
                        if time.time() > expires:
                            raise ResourceConflict('Temps écoulé pour cette question : réponse verrouillée.')
            # Limit answer size for a local deployment.
            data = json.dumps(answer, ensure_ascii=False, separators=(',',':'))
            if len(data.encode('utf-8')) > 65536:
                raise ValueError('Réponse trop volumineuse (64 Ko maximum).')
            stamp = now()
            con.execute('INSERT INTO submissions(participation_id,slide_number,answer_json,submitted_at) VALUES (?,?,?,?)',
                        (student['id'],snap['number'],data,stamp))
            if live['mode'] == 'autonome':
                con.execute('INSERT INTO slide_locks(participation_id,slide_number,locked_at,reason) VALUES (?,?,?,?) '
                            'ON CONFLICT(participation_id,slide_number) DO UPDATE SET reason=excluded.reason, locked_at=excluded.locked_at',
                            (student['id'], snap['number'], stamp, 'answered'))
            con.execute('UPDATE participations SET last_seen=? WHERE id=?', (stamp,student['id']))
            return {'success': True, 'slide': snap['filename'], 'submitted_at': stamp, 'saved': True, 'locked': live['mode'] == 'autonome'}

    def connected(self, lid, pid):
        with self.lock:
            self.connections.setdefault(lid,{})[pid] = time.monotonic()

    def ping(self, lid, pid):
        self.connected(lid, pid)
        self.touch(pid)

    def disconnected(self, lid, pid):
        with self.lock:
            self.connections.get(lid, {}).pop(pid, None)

    def students(self, lid):
        with self.db() as con:
            self._live(con, lid)
            students = con.execute('SELECT id,nom,prenom,joined_at,last_seen FROM participations WHERE live_id=? ORDER BY joined_at,id', (lid,)).fetchall()
            responses = con.execute('''SELECT p.id as pid, COUNT(DISTINCT s.slide_number) n FROM participations p
                LEFT JOIN submissions s ON s.participation_id=p.id WHERE p.live_id=? GROUP BY p.id''', (lid,)).fetchall()
        counts = {r['pid']:r['n'] for r in responses}
        with self.lock:
            active = {pid for pid,seen in self.connections.get(lid,{}).items() if time.monotonic()-seen < 45}
        data = [{'participation_id': s['id'], 'nom': s['nom'], 'prenom': s['prenom'],
                 'status': 'connected' if s['id'] in active else 'disconnected',
                 'joined_at': s['joined_at'], 'last_seen': s['last_seen'], 'answered': counts.get(s['id'],0)} for s in students]
        return {'live_id': lid, 'total_students': len(data), 'connected': len(active & {s['id'] for s in students}),
                'disconnected': len(data)-len(active & {s['id'] for s in students}), 'students': data}

    def sessions(self, group: str, event: str):
        g,parent = self.slides._parent(group,event)
        with self.db() as con:
            rows = con.execute('SELECT id,started_at,ended_at,status,mode FROM live_sessions WHERE group_name=? AND event_name=? ORDER BY started_at', (g.name,parent.name)).fetchall()
        return {'group': g.name,'event': parent.name, 'sessions': [dict(r) for r in rows]}

    def results(self, lid):
        """Données brutes et nombre de réponses, sans points ni notation."""
        with self.db() as con:
            live = self._live(con, lid)
            students = con.execute('SELECT * FROM participations WHERE live_id=? ORDER BY joined_at,id', (lid,)).fetchall()
            data = []
            for student in students:
                rows = con.execute("SELECT s.id,s.slide_number,s.answer_json,s.submitted_at,snap.filename "
                    "FROM submissions s JOIN snapshots snap ON snap.live_id=? AND snap.number=s.slide_number "
                    "WHERE s.participation_id=? ORDER BY s.id",(lid,student['id'])).fetchall()
                latest = {}
                for row in rows:
                    latest[row['slide_number']] = row
                data.append({'participation_id':student['id'],'nom':student['nom'],
                             'prenom':student['prenom'],'answered':len(latest),
                             'answers':[{'slide':row['filename'],'answer':json.loads(row['answer_json']),
                                         'submitted_at':row['submitted_at']} for row in latest.values()]})
        return {'live_id':lid,'group':live['group_name'],'event':live['event_name'],
                'status':live['status'],'started_at':live['started_at'],
                'ended_at':live['ended_at'],'results':data}

    def stats(self, lid, all_slides: bool = False):
        """Agrégats sans identité : décompte des réponses.

        Par défaut, slide courante uniquement. Avec all_slides=True, toutes
        les slides de la session. Pour un QCM (selected), chaque option est
        décomptée ; pour les autres types, seul le nombre de réponses.
        """
        with self.db() as con:
            live = self._live(con, lid)
            total_students = con.execute('SELECT COUNT(*) AS n FROM participations WHERE live_id=?',
                                         (lid,)).fetchone()['n']
            snapshots = con.execute('SELECT number,filename,kind FROM snapshots WHERE live_id=? ORDER BY number',
                                    (lid,)).fetchall()
            if not all_slides:
                snapshots = [s for s in snapshots if s['number'] == live['current_number']]
            slides_stats = []
            for snap in snapshots:
                rows = con.execute(
                    'SELECT s.answer_json FROM submissions s JOIN participations p ON p.id=s.participation_id '
                    'WHERE p.live_id=? AND s.slide_number=?', (lid, snap['number'])).fetchall()
                entry = {'number': snap['number'], 'slide': snap['filename'], 'slide_type': snap['kind'],
                         'answered': len(rows), 'total_students': total_students}
                if snap['kind'] == 'Q':
                    options: dict[str, int] = {}
                    for row in rows:
                        answer = json.loads(row['answer_json'])
                        if isinstance(answer, dict):
                            for opt in answer.get('selected', []):
                                options[opt] = options.get(opt, 0) + 1
                    entry['options'] = options
                slides_stats.append(entry)
        if all_slides:
            return {'live_id': lid, 'slides': slides_stats}
        s = slides_stats[0]
        result = {'live_id': lid, 'slide': s['slide'], 'slide_type': s['slide_type'],
                  'answered': s['answered'], 'total_students': s['total_students']}
        if 'options' in s:
            result['options'] = s['options']
        return result

    def student_results(self, group, event, nom, prenom):
        """Toutes les réponses d'un élève (nom+prénom) sur toutes les sessions d'un événement."""
        g, parent = self.slides._parent(group, event)
        with self.db() as con:
            sessions = con.execute(
                'SELECT id,started_at,ended_at,status FROM live_sessions WHERE group_name=? AND event_name=? ORDER BY started_at',
                (g.name, parent.name)).fetchall()
            result_sessions = []
            total = 0
            for sess in sessions:
                parts = con.execute('SELECT id FROM participations WHERE live_id=? AND nom=? AND prenom=?',
                                    (sess['id'], nom, prenom)).fetchall()
                for p in parts:
                    rows = con.execute(
                        "SELECT s.slide_number,s.answer_json,s.submitted_at,snap.filename FROM submissions s "
                        "JOIN snapshots snap ON snap.live_id=? AND snap.number=s.slide_number "
                        "WHERE s.participation_id=? ORDER BY s.id", (sess['id'], p['id'])).fetchall()
                    latest = {}
                    for row in rows:
                        latest[row['slide_number']] = row
                    answers = [{'slide': r['filename'], 'answer': json.loads(r['answer_json']),
                                'submitted_at': r['submitted_at']} for r in latest.values()]
                    total += len(answers)
                    result_sessions.append({'live_id': sess['id'], 'started_at': sess['started_at'],
                                            'status': sess['status'], 'participation_id': p['id'],
                                            'answers': answers})
        return {'group': g.name, 'event': parent.name, 'nom': nom, 'prenom': prenom,
                'sessions': result_sessions, 'total_answers': total}

    def active(self):
        """Tous les Lives en cours (un par événement au plus)."""
        with self.db() as con:
            rows = con.execute(
                "SELECT id,code,group_name,event_name,started_at,current_number,mode,timing,timing_seconds,correction_mode "
                "FROM live_sessions WHERE status='running' ORDER BY started_at").fetchall()
        return {'lives': [dict(r) for r in rows]}

    def participation_exists(self, pid):
        with self.db() as con:
            return con.execute('SELECT 1 FROM participations WHERE id=?', (pid,)).fetchone() is not None

    def kick(self, lid, pid):
        """Retire un participant : ses réponses sont supprimées (CASCADE)."""
        with self.lock, self.db() as con:
            self._live(con, lid)
            row = con.execute('SELECT id FROM participations WHERE id=? AND live_id=?', (pid, lid)).fetchone()
            if row is None:
                raise ResourceNotFound('Participation introuvable dans ce Live.')
            con.execute('DELETE FROM participations WHERE id=?', (pid,))
            self.connections.get(lid, {}).pop(pid, None)
        return {'kicked': True, 'participation_id': pid, 'live_id': lid}

    def csv(self, ids):
        output = io.StringIO(newline='')
        writer = csv.writer(output, delimiter=';')
        writer.writerow(['live_id','nom','prenom','date_session','slide','reponse_json','date_reponse'])
        for lid in ids:
            result = self.results(lid)
            for student in result['results']:
                for answer in student['answers']:
                    writer.writerow([lid,student['nom'],student['prenom'],result['started_at'],
                                     answer['slide'],json.dumps(answer['answer'],ensure_ascii=False),answer['submitted_at']])
        return '\ufeff' + output.getvalue()

    def event_csv(self, group,event):
        found=self.sessions(group,event)
        return self.csv([s['id'] for s in found['sessions']])

    def delete(self,lid):
        with self.lock,self.db() as con:
            live=self._live(con,lid)
            if live['status']=='running':
                raise ResourceConflict('Arrêter le Live avant sa suppression.')
            con.execute('DELETE FROM live_sessions WHERE id=?',(lid,))
            self.connections.pop(lid,None)
        return {'deleted':True,'live_id':lid}

    def reset(self,group,event):
        with self.lock,self.db() as con:
            found=self.sessions(group,event)
            if any(s['status']=='running' for s in found['sessions']):
                raise ResourceConflict('Arrêter toutes les sessions avant la réinitialisation.')
            ids=[s['id'] for s in found['sessions']]
            for lid in ids:
                con.execute('DELETE FROM live_sessions WHERE id=?',(lid,))
                self.connections.pop(lid,None)
        return {'deleted_sessions':len(ids),'group':found['group'],'event':found['event']}
