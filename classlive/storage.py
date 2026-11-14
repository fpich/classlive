"""Stockage ClassLive : arborescence stricte Evts/GNNN_nom/ENNN_nom."""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import tempfile
import unicodedata
from pathlib import Path


class StorageError(Exception):
    """Erreur de stockage."""


class ResourceNotFound(Exception):
    """Ressource absente."""


class ResourceConflict(Exception):
    """Nom normalisé déjà attribué à une autre ressource."""


class InvalidName(ValueError):
    """Nom utilisateur invalide."""


GROUP_RE = re.compile(r"^G([0-9]{3,})_([A-Za-z0-9]+(?:_[A-Za-z0-9]+)*)$")
EVENT_RE = re.compile(r"^E([0-9]{3,})_([A-Za-z0-9]+(?:_[A-Za-z0-9]+)*)$")


def normalize_name(value: str) -> str:
    """Accents supprimés, apostrophes supprimées, séparateurs convertis en _."""
    if not isinstance(value, str) or not value.strip():
        raise InvalidName("Le nom doit être une chaîne non vide.")
    if len(value) > 150 or any(c in value for c in ('/', '\\')) or any(unicodedata.category(c).startswith('C') for c in value):
        raise InvalidName("Nom trop long, séparateur de chemin ou caractère de contrôle interdit.")
    if value.strip() in ('.', '..'):
        raise InvalidName("Nom de chemin interdit.")
    ascii_text = unicodedata.normalize('NFKD', value)
    ascii_text = ''.join(c for c in ascii_text if not unicodedata.combining(c))
    ascii_text = ascii_text.replace('œ', 'oe').replace('Œ', 'OE').replace('æ', 'ae').replace('Æ', 'AE').replace('ß', 'ss')
    ascii_text = re.sub(r"['’‘`´]", '', ascii_text)
    ascii_text = re.sub(r'[^A-Za-z0-9]+', '_', ascii_text).strip('_')
    if not ascii_text or len(ascii_text) > 120:
        raise InvalidName("Le nom normalisé doit contenir 1 à 120 caractères alphanumériques/underscores.")
    return ascii_text


# Compatibilité avec l'ancien nom exporté.
validate_name = normalize_name


class EventStorage:
    def __init__(self, workdir: Path, events_dir: str = 'Evts') -> None:
        if events_dir != 'Evts':
            raise ValueError("La nomenclature impose events_dir='Evts'.")
        self.workdir = Path(workdir)
        self.root = self.workdir / 'Evts'
        self._lock = threading.RLock()
        self._counters = self.root / '.classlive-sequences.json'

    @staticmethod
    def _directory(path: Path, *, create: bool = False) -> bool:
        parts = list(reversed((path, *path.parents)))
        created = False
        for item in parts:
            if item.is_symlink():
                raise StorageError(f"Lien symbolique interdit : {item}")
            if item.exists():
                if not item.is_dir():
                    raise StorageError(f"Le chemin n'est pas un dossier : {item}")
            elif create:
                try:
                    item.mkdir()
                    if item == path:
                        created = True
                except FileExistsError:
                    if item.is_symlink() or not item.is_dir():
                        raise StorageError(f"Chemin invalide : {item}") from None
                except OSError as exc:
                    raise StorageError(f"Impossible de créer {item} : {exc}") from exc
            else:
                return False
        return created if create else True

    def init(self) -> None:
        self._directory(self.root, create=True)

    def _read_sequences(self) -> dict:
        if self._counters.is_symlink():
            raise StorageError("Compteur symbolique interdit.")
        if not self._counters.exists():
            return {'group': 0, 'event': 0, 'event_by_group': {}}
        try:
            data = json.loads(self._counters.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or any(type(data.get(k)) is not int or data[k] < 0 for k in ('group', 'event')):
                raise ValueError('Compteurs incorrects')
            by_group = data.setdefault('event_by_group', {})
            if not isinstance(by_group, dict) or any(not isinstance(k, str) or type(v) is not int or v < 0 for k,v in by_group.items()):
                raise ValueError('Compteurs événement par groupe incorrects')
            return data
        except (OSError, ValueError, TypeError) as exc:
            raise StorageError(f'Compteurs illisibles : {exc}') from exc

    def _write_sequences(self, data: dict) -> None:
        temporary = None
        try:
            fd, temp_name = tempfile.mkstemp(prefix='.classlive-sequences-', suffix='.tmp', dir=self.root)
            temporary = Path(temp_name)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(data, stream, indent=2, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._counters)
        except OSError as exc:
            raise StorageError(f'Impossible d\'enregistrer les compteurs : {exc}') from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _number(value: int) -> int:
        if type(value) is not int or not 1 <= value <= 999999:
            raise InvalidName('Le numéro doit être un entier entre 1 et 999999.')
        return value

    @staticmethod
    def _identifier(path: Path, regex: re.Pattern) -> int:
        return int(regex.fullmatch(path.name).group(1))

    def _reserve_id(self, kind: str, parent: Path | None = None) -> int:
        """Les groupes sont globaux ; les événements sont numérotés par groupe.

        Ne réutilise pas les numéros attribués par la séquence locale, même supprimés.
        """
        data = self._read_sequences()
        if kind == 'group':
            highest = max([data['group'], *[self._identifier(p, GROUP_RE) for p in self._items(self.root, GROUP_RE)]])
            number = highest + 1
            self._number(number)
            data['group'] = number
        else:
            if parent is None:
                raise ValueError('Parent requis pour les numéros événements')
            key = f'G{self._identifier(parent, GROUP_RE):03d}'
            highest = max([data['event_by_group'].get(key, 0), *[self._identifier(p, EVENT_RE) for p in self._items(parent, EVENT_RE)]])
            number = highest + 1
            self._number(number)
            data['event_by_group'][key] = number
        self._write_sequences(data)
        return number

    def _advance_counter(self, kind: str, number: int, parent: Path | None = None) -> None:
        """Une réattribution manuelle haute avance la prochaine séquence automatique."""
        data = self._read_sequences()
        if kind == 'group':
            data['group'] = max(data['group'], number)
        else:
            if parent is None:
                raise ValueError('Parent requis')
            key = f'G{self._identifier(parent, GROUP_RE):03d}'
            data['event_by_group'][key] = max(data['event_by_group'].get(key, 0), number)
        self._write_sequences(data)

    @staticmethod
    def _items(parent: Path, regex: re.Pattern) -> list[Path]:
        results = []
        for item in parent.iterdir():
            if item.is_symlink():
                raise StorageError(f'Lien symbolique interdit : {item}')
            if item.is_dir() and regex.fullmatch(item.name):
                results.append(item)
        return sorted(results, key=lambda p: int(regex.fullmatch(p.name).group(1)))

    def _resolve(self, parent: Path, supplied: str, regex: re.Pattern, kind: str) -> Path:
        if not self._directory(parent):
            raise ResourceNotFound(f'{kind} introuvable.')
        # Référence exacte G001_Nom ou E001_Nom, sinon recherche par nom humain normalisé.
        normalized = normalize_name(supplied)
        matches = self._items(parent, regex)
        for item in matches:
            if item.name == supplied:
                return item
        by_name = [item for item in matches if regex.fullmatch(item.name).group(2).casefold() == normalized.casefold()]
        if not by_name:
            raise ResourceNotFound(f'{kind} introuvable.')
        if len(by_name) > 1:
            raise ResourceConflict(f'{kind} ambigu : utiliser son identifiant complet.')
        return by_name[0]

    def _group(self, group: str) -> Path:
        return self._resolve(self.root, group, GROUP_RE, 'Groupe')

    def _event(self, group_path: Path, title: str) -> Path:
        return self._resolve(group_path, title, EVENT_RE, 'Événement')

    def _create_group_locked(self, group: str) -> tuple[Path, bool]:
        normalized = normalize_name(group)
        self.init()
        try:
            existing = self._group(group)
            return existing, False
        except ResourceNotFound:
            pass
        # Si l'appel utilise un identifiant inexistant, ne pas injecter G001_ dans le nouveau libellé.
        if GROUP_RE.fullmatch(group):
            raise ResourceNotFound('Identifiant de groupe introuvable.')
        identifier = self._reserve_id('group')
        path = self.root / f'G{identifier:03d}_{normalized}'
        self._directory(path, create=True)
        return path, True

    def create_group(self, group: str) -> dict:
        with self._lock:
            path, created = self._create_group_locked(group)
            return {'group': path.name, 'created': created, 'path': str(path)}

    def create_event(self, group: str, title: str) -> dict:
        with self._lock:
            normalized = normalize_name(title)
            group_path, _ = self._create_group_locked(group)
            try:
                existing = self._event(group_path, title)
                return {'group': group_path.name, 'title': existing.name, 'created': False, 'path': str(existing)}
            except ResourceNotFound:
                pass
            if EVENT_RE.fullmatch(title):
                raise ResourceNotFound('Identifiant d’événement introuvable.')
            identifier = self._reserve_id('event', group_path)
            path = group_path / f'E{identifier:03d}_{normalized}'
            self._directory(path, create=True)
            return {'group': group_path.name, 'title': path.name, 'created': True, 'path': str(path)}

    def list_groups(self) -> list[str]:
        with self._lock:
            self.init()
            return [p.name for p in self._items(self.root, GROUP_RE)]

    def list_events(self, group: str) -> list[str] | None:
        with self._lock:
            self.init()
            try:
                path = self._group(group)
            except ResourceNotFound:
                return None
            return [p.name for p in self._items(path, EVENT_RE)]

    @staticmethod
    def _unused(path: Path, peers: list[Path], normalized: str, source: Path | None = None) -> None:
        if any(p != path and p != source and p.name.split('_', 1)[1].casefold() == normalized.casefold() for p in peers):
            raise ResourceConflict('Un autre dossier porte déjà ce nom normalisé.')
        if os.path.lexists(path):
            if path.is_symlink():
                raise StorageError(f'Lien symbolique interdit : {path}')
            raise ResourceConflict('Le dossier cible existe déjà.')

    @staticmethod
    def _check_number_available(peers: list[Path], source: Path, number: int, regex: re.Pattern) -> None:
        for peer in peers:
            if peer != source and int(regex.fullmatch(peer.name).group(1)) == number:
                raise ResourceConflict(f'Le numéro {number:03d} est déjà utilisé.')

    def rename_group(self, group: str, new_name: str | None = None, new_number: int | None = None) -> dict:
        with self._lock:
            if new_name is None and new_number is None:
                raise InvalidName('Indiquer new_name et/ou new_number.')
            source = self._group(group)
            match = GROUP_RE.fullmatch(source.name)
            normalized = normalize_name(new_name) if new_name is not None else match.group(2)
            number = self._number(new_number) if new_number is not None else int(match.group(1))
            target = self.root / f'G{number:03d}_{normalized}'
            if source == target:
                return {'group': source.name, 'new_name': source.name, 'renamed': False, 'path': str(source)}
            peers = self._items(self.root, GROUP_RE)
            self._check_number_available(peers, source, number, GROUP_RE)
            self._unused(target, peers, normalized, source)
            try:
                source.rename(target)
            except OSError as exc:
                raise StorageError(f'Impossible de renommer le groupe : {exc}') from exc
            # Le compteur d'événements est attaché à l'identifiant Gnnn, pas au libellé.
            if number != int(match.group(1)):
                data = self._read_sequences()
                old_key, new_key = f'G{int(match.group(1)):03d}', f'G{number:03d}'
                previous = data['event_by_group'].pop(old_key, 0)
                data['event_by_group'][new_key] = max(data['event_by_group'].get(new_key, 0), previous)
                data['group'] = max(data['group'], number)
                self._write_sequences(data)
            return {'group': source.name, 'new_name': target.name, 'renamed': True, 'path': str(target)}

    def rename_event(self, group: str, title: str, new_name: str | None = None, new_number: int | None = None) -> dict:
        with self._lock:
            if new_name is None and new_number is None:
                raise InvalidName('Indiquer new_name et/ou new_number.')
            parent = self._group(group)
            source = self._event(parent, title)
            match = EVENT_RE.fullmatch(source.name)
            normalized = normalize_name(new_name) if new_name is not None else match.group(2)
            number = self._number(new_number) if new_number is not None else int(match.group(1))
            target = parent / f'E{number:03d}_{normalized}'
            if source == target:
                return {'group': parent.name, 'title': source.name, 'new_name': source.name, 'renamed': False, 'path': str(source)}
            peers = self._items(parent, EVENT_RE)
            self._check_number_available(peers, source, number, EVENT_RE)
            self._unused(target, peers, normalized, source)
            try:
                source.rename(target)
            except OSError as exc:
                raise StorageError(f'Impossible de renommer l’événement : {exc}') from exc
            if number != int(match.group(1)):
                self._advance_counter('event', number, parent)
            return {'group': parent.name, 'title': source.name, 'new_name': target.name, 'renamed': True, 'path': str(target)}

    def delete_event(self, group: str, title: str) -> dict:
        with self._lock:
            parent = self._group(group)
            path = self._event(parent, title)
            try:
                shutil.rmtree(path)
            except OSError as exc:
                raise StorageError(f'Impossible de supprimer l’événement : {exc}') from exc
            return {'group': parent.name, 'title': path.name, 'deleted': True}

    def delete_group(self, group: str) -> dict:
        with self._lock:
            path = self._group(group)
            try:
                shutil.rmtree(path)
            except OSError as exc:
                raise StorageError(f'Impossible de supprimer le groupe : {exc}') from exc
            return {'group': path.name, 'deleted': True}
