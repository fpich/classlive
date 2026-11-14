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
    trainer_accounts: tuple[tuple[str, str], ...] = ()
    cors_origins: tuple[str, ...] = ("*",)
    max_students: int = 300
    retention_days: int = 365
    join_rate_limit: int = 300  # tentatives de join max/min/IP (0 = désactivé)
    audit_enabled: bool = True
    audit_file: Path | None = None
    export_max_zip_mb: int = 50

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

    session = _mapping(config.get('session'), 'session')
    max_students = session.get('max_students', 300)
    if type(max_students) is not int or not 0 <= max_students <= 100000:
        raise ValueError('classlive.session.max_students doit être un entier entre 0 (illimité) et 100000.')
    retention_days = session.get('retention_days', 365)
    if type(retention_days) is not int or not 0 <= retention_days <= 36500:
        raise ValueError('classlive.session.retention_days doit être un entier entre 0 (désactivé) et 36500.')
    join_rate_limit = session.get('join_rate_limit', 300)
    if type(join_rate_limit) is not int or not 0 <= join_rate_limit <= 100000:
        raise ValueError('classlive.session.join_rate_limit doit être un entier entre 0 (désactivé) et 100000.')

    audit_cfg = _mapping(config.get('audit'), 'audit')
    audit_enabled = audit_cfg.get('enabled', True)
    if not isinstance(audit_enabled, bool):
        raise ValueError('classlive.audit.enabled doit être un booléen.')
    audit_file = audit_cfg.get('file')
    if audit_file is not None and (not isinstance(audit_file, str) or not audit_file.strip()):
        raise ValueError('classlive.audit.file doit être un chemin non vide ou null.')

    export_cfg = _mapping(config.get('export'), 'export')
    export_max_zip_mb = export_cfg.get('max_zip_mb', 50)
    if type(export_max_zip_mb) is not int or not 1 <= export_max_zip_mb <= 2048:
        raise ValueError('classlive.export.max_zip_mb doit être un entier entre 1 et 2048.')

    accounts_raw = security.get('trainer_accounts', [])
    if not isinstance(accounts_raw, list):
        raise ValueError('classlive.security.trainer_accounts doit être une liste de {username, password}.')
    accounts = []
    for acc in accounts_raw:
        if not isinstance(acc, dict) or not isinstance(acc.get('username'), str) or not acc['username'].strip() \
                or not isinstance(acc.get('password'), str) or len(acc['password']) < 8:
            raise ValueError('Chaque compte trainer_accounts doit avoir username non vide et password >= 8 caractères.')
        accounts.append((acc['username'], acc['password']))

    audit_path = Path(audit_file).expanduser() if audit_file else (workdir / 'audit.log')
    return Settings(trainer_username=trainer_username, trainer_password=trainer_password,
                    trainer_accounts=tuple(accounts), workdir=workdir, events_dir=events_dir, host=host, port=port,
                    log_level=level.upper(), api_key=api_key, cors_origins=tuple(cors_origins),
                    max_students=max_students, retention_days=retention_days, join_rate_limit=join_rate_limit,
                    audit_enabled=audit_enabled,
                    audit_file=audit_path if audit_enabled else None, export_max_zip_mb=export_max_zip_mb)
