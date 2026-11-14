"""Chargement et vérification de la configuration ClassLive."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Settings:
    workdir: Path
    events_dir: str = "Evts"
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"
    api_key: str | None = None
    trainer_username: str = "formateur"
    trainer_password: str | None = None
    cors_origins: tuple[str, ...] = ("*",)

    @property
    def events_root(self) -> Path:
        return self.workdir / self.events_dir


def _mapping(value: Any, label: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"La section '{label}' doit être un objet YAML.")
    return value


def load_settings(config_path: str | Path | None = None) -> Settings:
    path = Path(config_path or os.getenv("CLASSLIVE_CONFIG", "config.yml")).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Fichier de configuration introuvable : {path}")
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    root = _mapping(data, "racine")
    config = _mapping(root.get("classlive"), "classlive")
    server = _mapping(config.get("server"), "server")
    storage = _mapping(config.get("storage"), "storage")
    logging = _mapping(config.get("logging"), "logging")
    security = _mapping(config.get("security"), "security")

    raw_workdir = storage.get("workdir")
    if not isinstance(raw_workdir, str) or not raw_workdir.strip():
        raise ValueError("classlive.storage.workdir doit être un chemin absolu non vide.")
    workdir = Path(raw_workdir).expanduser()
    if not workdir.is_absolute():
        raise ValueError("classlive.storage.workdir doit être absolu.")
    workdir = workdir.resolve()

    events_dir = storage.get("events_dir", "Evts")
    if events_dir == "événements":
        # Anciennes installations : préserver config.yml mais imposer le nouveau dossier.
        events_dir = "Evts"
    if events_dir != "Evts":
        raise ValueError("classlive.storage.events_dir doit être Evts (nomenclature obligatoire).")

    host = server.get("host", "0.0.0.0")
    port = server.get("port", 8080)
    level = logging.get("level", "INFO")
    api_key = security.get("api_key")
    if not isinstance(host, str) or not host:
        raise ValueError("classlive.server.host invalide.")
    if type(port) is not int or not (1 <= port <= 65535):
        raise ValueError("classlive.server.port doit être compris entre 1 et 65535.")
    if not isinstance(level, str) or level.upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        raise ValueError("classlive.logging.level invalide.")
    if api_key is not None and (not isinstance(api_key, str) or not api_key.strip()):
        raise ValueError("classlive.security.api_key doit être une chaîne non vide ou null.")
    cors_origins = security.get('cors_origins', ['*'])
    if not isinstance(cors_origins, list) or not cors_origins or any(not isinstance(o, str) or not o.strip() for o in cors_origins):
        raise ValueError("classlive.security.cors_origins doit être une liste non vide de chaînes (ex: [\"*\"]).")
    trainer_username = security.get('trainer_username', 'formateur')
    trainer_password = os.getenv('CLASSLIVE_TRAINER_PASSWORD')
    if not isinstance(trainer_username, str) or not trainer_username.strip():
        raise ValueError('classlive.security.trainer_username invalide.')
    return Settings(trainer_username=trainer_username, trainer_password=trainer_password, workdir=workdir, events_dir=events_dir, host=host, port=port,
                    log_level=level.upper(), api_key=api_key, cors_origins=tuple(cors_origins))
