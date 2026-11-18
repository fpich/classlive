"""Navigation par session dans les slides d'un événement.

Chaque client reçoit un identifiant de session indépendant. L'état est volontairement
volatile : un redémarrage du service invalide les sessions, jamais les slides.
"""
from __future__ import annotations

import threading
import time
from threading import RLock
from uuid import uuid4

from classlive.slides import SLIDE_RE, SlideStorage
from classlive.storage import ResourceNotFound, StorageError


class SlideNavigator:
    # TTL des sessions en secondes (30 minutes d'inactivité)
    SESSION_TTL = 1800
    
    def __init__(self, slides: SlideStorage):
        self.slides = slides
        self._sessions: dict[str, tuple[str, str, int, float]] = {}  # (group, event, number, last_used)
        self._lock = RLock()
        self._cleanup_thread: threading.Thread | None = None
        self._running = False
        
        # Démarrer le thread de nettoyage
        self._start_cleanup_thread()
    
    def _start_cleanup_thread(self):
        """Lance un thread daemon pour nettoyer les sessions expirées."""
        self._running = True
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()
    
    def _cleanup_loop(self):
        """Boucle de nettoyage des sessions expirées."""
        while self._running:
            time.sleep(60)  # Nettoyage toutes les minutes
            self._cleanup_expired()
    
    def _cleanup_expired(self):
        """Supprime les sessions expirées (TTL dépassé)."""
        with self._lock:
            now = time.monotonic()
            expired_sessions = [
                session_id for session_id, (_, _, _, last_used) in self._sessions.items()
                if now - last_used > self.SESSION_TTL
            ]
            for session_id in expired_sessions:
                del self._sessions[session_id]
    
    def _update_session_timestamp(self, session: str):
        """Met à jour le timestamp de dernière utilisation de la session."""
        with self._lock:
            if session in self._sessions:
                g, e, n, _ = self._sessions[session]
                self._sessions[session] = (g, e, n, time.monotonic())
    
    def shutdown(self):
        """Arrête le thread de nettoyage."""
        self._running = False
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=1)
            self._cleanup_thread = None

    def _ordered(self, group: str, event: str):
        # La même validation des chemins et liens symboliques que le stockage est appliquée.
        g, parent = self.slides._parent(group, event)
        files = self.slides._slides(parent)
        return g.name, parent.name, [(int(SLIDE_RE.fullmatch(p.name).group(1)), p) for p in files]

    def _response(self, session: str, group: str, event: str, number: int,
                  ordered: list[tuple[int, object]]) -> dict:
        indices = [n for n, _ in ordered]
        if number not in indices:
            raise ResourceNotFound('La slide courante n’existe plus. Sélectionnez à nouveau l’événement.')
        index = indices.index(number)
        path = ordered[index][1]
        try:
            content = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError) as exc:
            raise StorageError(f'Impossible de lire la slide : {exc}') from exc
        match = SLIDE_RE.fullmatch(path.name)
        return {
            'session_id': session,
            'group': group,
            'event': event,
            'slide': path.name,
            'number': number,
            'slide_type': match.group(2),
            'title': match.group(3),
            'content': content,
            'position': index + 1,
            'total': len(ordered),
            'has_previous': index > 0,
            'has_next': index < len(ordered) - 1,
        }

    def select(self, group: str, event: str) -> dict:
        with self._lock, self.slides.events._lock:
            g, e, ordered = self._ordered(group, event)
            if not ordered:
                raise ResourceNotFound('Cet événement ne contient aucune slide.')
            if len(self._sessions) >= 10000:
                raise StorageError('Nombre maximal de sessions de lecture atteint.')
            session = str(uuid4())
            number = ordered[0][0]
            response = self._response(session, g, e, number, ordered)
            self._sessions[session] = (g, e, number, time.monotonic())
            return response

    def navigate(self, session: str, direction: str) -> dict:
        with self._lock, self.slides.events._lock:
            if session not in self._sessions:
                raise ResourceNotFound('Session de lecture introuvable ou expirée.')
            g, e, current, _ = self._sessions[session]
            group, event, ordered = self._ordered(g, e)
            if not ordered:
                raise ResourceNotFound('Cet événement ne contient plus aucune slide.')
            numbers = [n for n, _ in ordered]
            if direction == 'next':
                number = next((n for n in numbers if n > current), numbers[-1] if current in numbers else None)
            elif direction == 'previous':
                number = next((n for n in reversed(numbers) if n < current), numbers[0] if current in numbers else None)
            elif direction == 'current':
                number = current
            else:
                raise ValueError('Direction de navigation invalide.')
            if number is None:
                raise ResourceNotFound('Aucune slide disponible dans cette direction.')
            response = self._response(session, group, event, number, ordered)
            self._sessions[session] = (group, event, number, time.monotonic())
            self._update_session_timestamp(session)
            return response

    def close(self, session: str) -> dict:
        with self._lock:
            if session not in self._sessions:
                raise ResourceNotFound('Session de lecture introuvable ou expirée.')
            del self._sessions[session]
            return {'success': True, 'session_id': session, 'closed': True}
    
    def purge_expired(self) -> int:
        """Supprime manuellement les sessions expirées.
        
        Returns:
            int: Nombre de sessions supprimées
        """
        with self._lock:
            now = time.monotonic()
            expired_sessions = [
                session_id for session_id, (_, _, _, last_used) in self._sessions.items()
                if now - last_used > self.SESSION_TTL
            ]
            for session_id in expired_sessions:
                del self._sessions[session_id]
            return len(expired_sessions)
