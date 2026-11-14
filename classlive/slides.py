"""Slides Markdown: SNNN_TYPE_Titre.md, uniques par numéro dans un événement.

Types : C contenu, A association, O ordre, R catégories, Q QCM, T texte à trous,
F texte libre, P sondage, N nuage de mots, L échelle (Likert 1-5).
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from classlive.storage import EventStorage, InvalidName, ResourceConflict, ResourceNotFound, StorageError, normalize_name

SLIDE_TYPES = frozenset({'C', 'A', 'O', 'R', 'Q', 'T', 'F', 'P', 'N', 'L'})
SLIDE_RE = re.compile(r'^S([0-9]{3,})_([CAORQTFNPL])_([A-Za-z0-9]+(?:_[A-Za-z0-9]+)*)\.md$')
# Médias servis publiquement depuis le sous-dossier media/ de l'événement.
MEDIA_RE = re.compile(r'^[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*\.(png|jpe?g|gif|svg|webp|pdf)$', re.IGNORECASE)
MEDIA_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
               '.gif': 'image/gif', '.svg': 'image/svg+xml', '.webp': 'image/webp',
               '.pdf': 'application/pdf'}


class SlideStorage:
    def __init__(self, events: EventStorage, media_max_bytes: int = 10 * 1024 * 1024):
        self.events = events
        self.media_max_bytes = media_max_bytes

    @staticmethod
    def _type(value: str) -> str:
        if not isinstance(value, str) or value not in SLIDE_TYPES:
            raise InvalidName('Type de slide invalide : C, A, O, R, Q, T, F, P, N ou L uniquement.')
        return value

    @staticmethod
    def _content(value: str) -> str:
        if not isinstance(value, str):
            raise InvalidName('Le contenu Markdown doit être une chaîne.')
        if len(value.encode('utf-8')) > 2_000_000:
            raise InvalidName('Contenu Markdown limité à 2 Mo.')
        return value

    @staticmethod
    def _slides(parent: Path) -> list[Path]:
        result = []
        for p in parent.iterdir():
            if p.is_symlink():
                raise StorageError(f'Lien symbolique interdit dans un événement : {p}')
            if p.is_file() and SLIDE_RE.fullmatch(p.name):
                result.append(p)
        return sorted(result, key=lambda p: (int(SLIDE_RE.fullmatch(p.name).group(1)), p.name))

    def _parent(self, group: str, event: str) -> tuple[Path, Path]:
        group_path = self.events._group(group)
        return group_path, self.events._event(group_path, event)

    @staticmethod
    def _check_unique(peers: list[Path], number: int, title: str, source: Path | None = None):
        for p in peers:
            if p == source:
                continue
            match = SLIDE_RE.fullmatch(p.name)
            if int(match.group(1)) == number:
                raise ResourceConflict(f'Le numéro S{number:03d} est déjà utilisé dans cet événement.')
            if match.group(3).casefold() == title.casefold():
                raise ResourceConflict('Une slide porte déjà ce titre normalisé dans cet événement.')

    def _resolve(self, parent: Path, slide: str) -> Path:
        if not isinstance(slide, str) or '/' in slide or '\\' in slide:
            raise InvalidName('Identifiant de slide invalide.')
        peers = self._slides(parent)
        for p in peers:
            if slide in (p.name, p.stem):
                return p
        normalized = normalize_name(slide)
        matching = [p for p in peers if SLIDE_RE.fullmatch(p.name).group(3).casefold() == normalized.casefold()]
        if not matching:
            raise ResourceNotFound('Slide introuvable.')
        if len(matching) > 1:
            raise ResourceConflict('Slide ambiguë : utiliser son nom complet.')
        return matching[0]

    @staticmethod
    def _write_exclusive(path: Path, content: str) -> None:
        try:
            with path.open('x', encoding='utf-8') as f:
                f.write(content)
        except FileExistsError as exc:
            raise ResourceConflict('Fichier de slide déjà présent.') from exc
        except OSError as exc:
            raise StorageError(f'Impossible de créer la slide : {exc}') from exc

    @staticmethod
    def _write_atomic(path: Path, content: str) -> None:
        tmp = None
        try:
            fd, name = tempfile.mkstemp(prefix='.classlive-slide-', suffix='.tmp', dir=path.parent)
            tmp = Path(name)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except OSError as exc:
            raise StorageError(f'Impossible de modifier la slide : {exc}') from exc
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    def create(self, group: str, event: str, title: str, slide_type: str, content: str = '', number: int | None = None) -> dict:
        with self.events._lock:
            normalized = normalize_name(title)
            kind = self._type(slide_type)
            body = self._content(content)
            g, parent = self._parent(group, event)
            peers = self._slides(parent)
            # Sans numéro demandé, une création répétée conserve la slide existante.
            by_title = [p for p in peers if SLIDE_RE.fullmatch(p.name).group(3).casefold() == normalized.casefold()]
            if by_title and number is None and SLIDE_RE.fullmatch(by_title[0].name).group(2) == kind:
                p = by_title[0]
                return {'group': g.name, 'event': parent.name, 'slide': p.name, 'created': False, 'path': str(p)}
            num = self.events._number(number) if number is not None else max(
                (int(SLIDE_RE.fullmatch(p.name).group(1)) for p in peers), default=0
            ) + 1
            self.events._number(num)
            self._check_unique(peers, num, normalized)
            path = parent / f'S{num:03d}_{kind}_{normalized}.md'
            self._write_exclusive(path, body)
            return {'group': g.name, 'event': parent.name, 'slide': path.name, 'created': True, 'path': str(path)}

    def list(self, group: str, event: str) -> dict:
        with self.events._lock:
            g, parent = self._parent(group, event)
            return {'group': g.name, 'event': parent.name, 'slides': [p.name for p in self._slides(parent)]}

    def read(self, group: str, event: str, slide: str) -> dict:
        with self.events._lock:
            g, parent = self._parent(group, event)
            path = self._resolve(parent, slide)
            try:
                content = path.read_text(encoding='utf-8')
            except (OSError, UnicodeError) as exc:
                raise StorageError(f'Impossible de lire la slide : {exc}') from exc
            return {'group': g.name, 'event': parent.name, 'slide': path.name, 'content': content, 'path': str(path)}

    def rename(self, group: str, event: str, slide: str, new_name: str | None = None,
               new_number: int | None = None, new_type: str | None = None) -> dict:
        with self.events._lock:
            if new_name is None and new_number is None and new_type is None:
                raise InvalidName('Indiquer new_name, new_number et/ou new_type.')
            g, parent = self._parent(group, event)
            source = self._resolve(parent, slide)
            current = SLIDE_RE.fullmatch(source.name)
            normalized = normalize_name(new_name) if new_name is not None else current.group(3)
            number = self.events._number(new_number) if new_number is not None else int(current.group(1))
            kind = self._type(new_type) if new_type is not None else current.group(2)
            target = parent / f'S{number:03d}_{kind}_{normalized}.md'
            if target == source:
                return {'group': g.name, 'event': parent.name, 'slide': source.name, 'new_name': source.name, 'renamed': False, 'path': str(source)}
            self._check_unique(self._slides(parent), number, normalized, source)
            if os.path.lexists(target):
                raise ResourceConflict('Le fichier cible existe déjà.')
            try:
                source.rename(target)
            except OSError as exc:
                raise StorageError(f'Impossible de renommer la slide : {exc}') from exc
            return {'group': g.name, 'event': parent.name, 'slide': source.name, 'new_name': target.name, 'renamed': True, 'path': str(target)}

    def update_content(self, group: str, event: str, slide: str, content: str) -> dict:
        with self.events._lock:
            body = self._content(content)
            g, parent = self._parent(group, event)
            path = self._resolve(parent, slide)
            self._write_atomic(path, body)
            return {'group': g.name, 'event': parent.name, 'slide': path.name, 'updated': True, 'path': str(path)}

    def delete(self, group: str, event: str, slide: str) -> dict:
        with self.events._lock:
            g, parent = self._parent(group, event)
            path = self._resolve(parent, slide)
            try:
                path.unlink()
            except OSError as exc:
                raise StorageError(f'Impossible de supprimer la slide : {exc}') from exc
            return {'group': g.name, 'event': parent.name, 'slide': path.name, 'deleted': True}

    def duplicate(self, group: str, event: str, slide: str, new_name: str | None = None) -> dict:
        """Copie une slide vers un nouveau numéro (max+1), même type, titre `_copie` par défaut."""
        with self.events._lock:
            g, parent = self._parent(group, event)
            source = self._resolve(parent, slide)
            current = SLIDE_RE.fullmatch(source.name)
            peers = self._slides(parent)
            num = max((int(SLIDE_RE.fullmatch(p.name).group(1)) for p in peers), default=0) + 1
            self.events._number(num)
            base = normalize_name(new_name) if new_name is not None else current.group(3) + '_copie'
            normalized = base
            suffix = 1
            while any(SLIDE_RE.fullmatch(p.name).group(3).casefold() == normalized.casefold() for p in peers):
                suffix += 1
                if suffix > 100:
                    raise ResourceConflict('Impossible de trouver un nom de copie disponible.')
                normalized = f'{base}_{suffix}'
            target = parent / f'S{num:03d}_{current.group(2)}_{normalized}.md'
            self.events._check_no_symlinks(source)
            try:
                shutil.copyfile(source, target)
            except OSError as exc:
                raise StorageError(f'Impossible de dupliquer la slide : {exc}') from exc
            return {'group': g.name, 'event': parent.name, 'slide': source.name, 'new_slide': target.name,
                    'duplicated': True, 'path': str(target)}

    # ── Médias de l'événement (sous-dossier media/, servis publiquement) ────

    def _media_path(self, parent: Path, filename: str) -> Path:
        if not isinstance(filename, str) or not MEDIA_RE.fullmatch(filename):
            raise InvalidName('Nom de média invalide (lettres/chiffres/underscore, extension png, jpg, jpeg, gif, svg, webp ou pdf).')
        return parent / 'media' / filename

    def upload_media(self, group: str, event: str, filename: str, data: bytes) -> dict:
        with self.events._lock:
            g, parent = self._parent(group, event)
            target = self._media_path(parent, filename)
            if not isinstance(data, (bytes, bytearray)) or not data:
                raise InvalidName('Fichier vide.')
            if len(data) > self.media_max_bytes:
                raise InvalidName(f'Média trop volumineux (max {self.media_max_bytes // 1048576} Mo).')
            target.parent.mkdir(exist_ok=True)
            if target.is_symlink():
                raise StorageError(f'Lien symbolique interdit : {target}')
            try:
                with target.open(mode='xb') as f:
                    f.write(bytes(data))
            except FileExistsError as exc:
                raise ResourceConflict('Un média porte déjà ce nom.') from exc
            except OSError as exc:
                raise StorageError(f'Impossible d’écrire le média : {exc}') from exc
            return {'group': g.name, 'event': parent.name, 'file': filename, 'size': len(data),
                    'uploaded': True, 'path': str(target)}

    def list_media(self, group: str, event: str) -> dict:
        with self.events._lock:
            g, parent = self._parent(group, event)
            d = parent / 'media'
            if not d.is_dir():
                files = []
            else:
                files = sorted(p.name for p in d.iterdir()
                               if p.is_file() and not p.is_symlink() and MEDIA_RE.fullmatch(p.name))
            return {'group': g.name, 'event': parent.name, 'files': files}

    def delete_media(self, group: str, event: str, filename: str) -> dict:
        with self.events._lock:
            g, parent = self._parent(group, event)
            target = self._media_path(parent, filename)
            if not target.is_file() or target.is_symlink():
                raise ResourceNotFound('Média introuvable.')
            try:
                target.unlink()
            except OSError as exc:
                raise StorageError(f'Impossible de supprimer le média : {exc}') from exc
            return {'group': g.name, 'event': parent.name, 'file': filename, 'deleted': True}

    def media_file(self, group: str, event: str, filename: str) -> Path:
        """Chemin d'un média existant (pour FileResponse), sans traversal possible."""
        g, parent = self._parent(group, event)
        target = self._media_path(parent, filename)
        if not target.is_file() or target.is_symlink():
            raise ResourceNotFound('Média introuvable.')
        return target
