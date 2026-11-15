"""Navigation par session dans les slides d'un événement.

Chaque client reçoit un identifiant de session indépendant. L'état est volontairement
volatile : un redémarrage du service invalide les sessions, jamais les slides.
"""
from __future__ import annotations

from threading import RLock
from uuid import uuid4

from classlive.slides import SLIDE_RE, SlideStorage
from classlive.storage import ResourceNotFound, StorageError


class SlideNavigator:
    def __init__(self, slides: SlideStorage):
        self.slides = slides
        self._sessions: dict[str, tuple[str, str, int]] = {}
        self._lock = RLock()

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
            self._sessions[session] = (g, e, number)
            return response

    def navigate(self, session: str, direction: str) -> dict:
        with self._lock, self.slides.events._lock:
            if session not in self._sessions:
                raise ResourceNotFound('Session de lecture introuvable ou expirée.')
            g, e, current = self._sessions[session]
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
            self._sessions[session] = (group, event, number)
            return response

    def close(self, session: str) -> dict:
        with self._lock:
            if session not in self._sessions:
                raise ResourceNotFound('Session de lecture introuvable ou expirée.')
            del self._sessions[session]
            return {'success': True, 'session_id': session, 'closed': True}
