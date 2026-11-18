"""Authentification persistante des formateurs avec hachage Argon2."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError


# Type alias pour les jetons
Token = str
TrainerId = int


@dataclass(frozen=True)
class Trainer:
    """Représente un compte formateur."""
    id: TrainerId
    username: str
    password_hash: str | None  # None si auth externe (ex: JWT futur)
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AuthSession:
    """Session d'authentification persistante."""
    id: str
    trainer_id: TrainerId
    token_hash: str  # hachage du jeton (on ne stocke pas le jeton brut)
    created_at: datetime
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None


class TrainerAuthError(Exception):
    """Erreur d'authentification formateur."""


class InvalidTokenError(TrainerAuthError):
    """Jeton d'authentification invalide."""


class ExpiredTokenError(TrainerAuthError):
    """Jeton d'authentification expiré."""


class InactiveAccountError(TrainerAuthError):
    """Compte formateur désactivé."""


class AuthStorage:
    """Stockage SQLite des comptes formateurs et sessions.
    
    Thread-safe via RLock.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path.resolve()
        self._lock = threading.RLock()
        self._ph = PasswordHasher(
            time_cost=3,
            memory_cost=65536,
            parallelism=4,
            hash_len=32,
            salt_len=16
        )
        self._init_db()

    @contextmanager
    def _connection(self) -> sqlite3.Connection:
        """Connexion SQLite avec WAL activé et optimisations."""
        conn = sqlite3.connect(
            str(self.db_path),
            isolation_level=None,  # Autocommit mode for WAL
            timeout=15.0
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-2000")  # 2MB cache
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Initialisation de la base de données."""
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trainers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_sessions (
                    id TEXT PRIMARY KEY,
                    trainer_id INTEGER NOT NULL,
                    token_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    ip_address TEXT,
                    user_agent TEXT,
                    FOREIGN KEY (trainer_id) REFERENCES trainers(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_trainers_username ON trainers(username);
                CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON auth_sessions(token_hash);
                CREATE INDEX IF NOT EXISTS idx_sessions_trainer_id ON auth_sessions(trainer_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON auth_sessions(expires_at);
            """)

    def _hash_token(self, token: str) -> str:
        """Hachage sécurisé d'un jeton ( utiliser hmac pour éviter les rainbow tables)."""
        # Utiliser une clé secrète dérivée du chemin de la DB pour saler le hachage
        salt = self.db_path.name.encode('utf-8')
        return hmac.new(salt, token.encode('utf-8'), hashlib.sha256).hexdigest()

    def hash_password(self, password: str) -> str:
        """Hachage d'un mot de passe avec Argon2."""
        return self._ph.hash(password)

    def verify_password(self, password: str, hash: str) -> bool:
        """Vérification d'un mot de passe contre son hachage Argon2."""
        try:
            self._ph.verify(hash, password)
            return True
        except (VerifyMismatchError, Exception):
            return False

    def create_trainer(self, username: str, password: str) -> Trainer:
        """Création d'un compte formateur."""
        now = datetime.now(timezone.utc)
        password_hash = self.hash_password(password)
        
        with self._connection() as conn:
            cursor = conn.execute(
                "INSERT INTO trainers (username, password_hash, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (username, password_hash, True, now.isoformat(), now.isoformat())
            )
            trainer_id = cursor.lastrowid
            return Trainer(
                id=trainer_id,
                username=username,
                password_hash=password_hash,
                is_active=True,
                created_at=now,
                updated_at=now
            )

    def get_trainer_by_username(self, username: str) -> Trainer | None:
        """Récupération d'un formateur par son username."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM trainers WHERE username = ?",
                (username,)
            ).fetchone()
            if row is None:
                return None
            return Trainer(
                id=row['id'],
                username=row['username'],
                password_hash=row['password_hash'],
                is_active=bool(row['is_active']),
                created_at=datetime.fromisoformat(row['created_at']),
                updated_at=datetime.fromisoformat(row['updated_at'])
            )

    def get_trainer_by_id(self, trainer_id: TrainerId) -> Trainer | None:
        """Récupération d'un formateur par son ID."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM trainers WHERE id = ?",
                (trainer_id,)
            ).fetchone()
            if row is None:
                return None
            return Trainer(
                id=row['id'],
                username=row['username'],
                password_hash=row['password_hash'],
                is_active=bool(row['is_active']),
                created_at=datetime.fromisoformat(row['created_at']),
                updated_at=datetime.fromisoformat(row['updated_at'])
            )

    def update_trainer_password(self, trainer_id: TrainerId, new_password: str) -> bool:
        """Mise à jour du mot de passe d'un formateur."""
        password_hash = self.hash_password(new_password)
        now = datetime.now(timezone.utc)
        
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE trainers SET password_hash = ?, updated_at = ? WHERE id = ?",
                (password_hash, now.isoformat(), trainer_id)
            )
            return cursor.rowcount > 0

    def set_trainer_active(self, trainer_id: TrainerId, is_active: bool) -> bool:
        """Activation/désactivation d'un formateur."""
        now = datetime.now(timezone.utc)
        
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE trainers SET is_active = ?, updated_at = ? WHERE id = ?",
                (int(is_active), now.isoformat(), trainer_id)
            )
            return cursor.rowcount > 0

    def list_trainers(self) -> list[Trainer]:
        """Liste de tous les formateurs."""
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM trainers ORDER BY username").fetchall()
            return [
                Trainer(
                    id=row['id'],
                    username=row['username'],
                    password_hash=row['password_hash'],
                    is_active=bool(row['is_active']),
                    created_at=datetime.fromisoformat(row['created_at']),
                    updated_at=datetime.fromisoformat(row['updated_at'])
                )
                for row in rows
            ]

    def create_session(
        self, 
        trainer_id: TrainerId, 
        token: Token, 
        expires_in: timedelta,
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> AuthSession:
        """Création d'une session d'authentification."""
        now = datetime.now(timezone.utc)
        expires_at = now + expires_in
        token_hash = self._hash_token(token)
        session_id = secrets.token_urlsafe(16)
        
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO auth_sessions 
                   (id, trainer_id, token_hash, created_at, expires_at, ip_address, user_agent)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, trainer_id, token_hash, now.isoformat(), expires_at.isoformat(), 
                 ip_address, user_agent)
            )
            return AuthSession(
                id=session_id,
                trainer_id=trainer_id,
                token_hash=token_hash,
                created_at=now,
                expires_at=expires_at,
                ip_address=ip_address,
                user_agent=user_agent
            )

    def get_session_by_token(self, token: Token) -> tuple[AuthSession, Trainer] | None:
        """Récupération d'une session par son jeton (recherche par hachage)."""
        token_hash = self._hash_token(token)
        now = datetime.now(timezone.utc)
        
        with self._connection() as conn:
            row = conn.execute(
                """SELECT s.*, t.username, t.is_active 
                   FROM auth_sessions s
                   JOIN trainers t ON s.trainer_id = t.id
                   WHERE s.token_hash = ? AND s.expires_at > ?""",
                (token_hash, now.isoformat())
            ).fetchone()
            
            if row is None:
                return None
            
            trainer = Trainer(
                id=row['trainer_id'],
                username=row['username'],
                password_hash=None,  # Non nécessaire pour l'auth
                is_active=bool(row['is_active']),
                created_at=datetime.fromisoformat(row['created_at']),
                updated_at=datetime.fromisoformat(row['updated_at'])
            )
            
            session = AuthSession(
                id=row['id'],
                trainer_id=row['trainer_id'],
                token_hash=row['token_hash'],
                created_at=datetime.fromisoformat(row['created_at']),
                expires_at=datetime.fromisoformat(row['expires_at']),
                ip_address=row['ip_address'],
                user_agent=row['user_agent']
            )
            
            return (session, trainer)

    def invalidate_session(self, session_id: str) -> bool:
        """Invalidation d'une session."""
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM auth_sessions WHERE id = ?",
                (session_id,)
            )
            return cursor.rowcount > 0

    def invalidate_sessions_by_trainer(self, trainer_id: TrainerId) -> int:
        """Invalidation de toutes les sessions d'un formateur."""
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM auth_sessions WHERE trainer_id = ?",
                (trainer_id,)
            )
            return cursor.rowcount

    def invalidate_expired_sessions(self) -> int:
        """Invalidation des sessions expirées."""
        now = datetime.now(timezone.utc)
        
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM auth_sessions WHERE expires_at <= ?",
                (now.isoformat(),)
            )
            return cursor.rowcount

    def cleanup_old_sessions(self, max_age_days: int = 30) -> int:
        """Nettoyage des sessions anciennes (même non expirées)."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM auth_sessions WHERE created_at < ?",
                (cutoff.isoformat(),)
            )
            return cursor.rowcount


class TrainerAuth:
    """Service d'authentification des formateurs.
    
    Gère l'authentification avec persistance SQLite, hachage Argon2,
    et génération de jetons sécurisés.
    
    Thread-safe via RLock sur le storage.
    """

    # Durée par défaut des sessions
    DEFAULT_SESSION_DURATION = timedelta(hours=8)
    
    # Durée des jetons de rafraîchissement (longue durée)
    REFRESH_TOKEN_DURATION = timedelta(days=30)

    def __init__(self, storage: AuthStorage):
        self.storage = storage
        self._lock = threading.RLock()
        # Cache des sessions récentes pour performance (optionnel)
        self._session_cache: dict[Token, tuple[AuthSession, Trainer]] = {}
        self._cache_lock = threading.RLock()

    def login(self, username: str, password: str, 
              ip_address: str | None = None, 
              user_agent: str | None = None) -> Token:
        """Authentification d'un formateur.
        
        Args:
            username: Nom d'utilisateur
            password: Mot de passe en clair
            ip_address: Adresse IP du client (optionnel)
            user_agent: User-Agent du client (optionnel)
            
        Returns:
            Token: Jeton d'authentification
            
        Raises:
            InvalidTokenError: si le mot de passe est incorrect
            InactiveAccountError: si le compte est désactivé
            TrainerAuthError: si le compte n'existe pas
        """
        with self._lock:
            trainer = self.storage.get_trainer_by_username(username)
            
            if trainer is None:
                # Temps constant pour éviter l'énumération
                self._ph.verify("dummy_hash", "dummy_password")
                raise InvalidTokenError("Nom d'utilisateur ou mot de passe incorrect")
            
            if not trainer.is_active:
                raise InactiveAccountError("Compte désactivé")
            
            if trainer.password_hash is None:
                raise InvalidTokenError("Authentification externe non configurée")
            
            if not self.storage.verify_password(password, trainer.password_hash):
                raise InvalidTokenError("Nom d'utilisateur ou mot de passe incorrect")
            
            # Génération d'un jeton aléatoire sécurisé
            token = secrets.token_urlsafe(32)
            
            # Création de la session
            self.storage.create_session(
                trainer_id=trainer.id,
                token=token,
                expires_in=self.DEFAULT_SESSION_DURATION,
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            return token

    def validate_token(self, token: Token) -> tuple[Trainer, AuthSession]:
        """Validation d'un jeton d'authentification.
        
        Args:
            token: Jeton à valider
            
        Returns:
            tuple: (Trainer, AuthSession) si valide
            
        Raises:
            InvalidTokenError: si le jeton est invalide
            ExpiredTokenError: si le jeton a expiré
            InactiveAccountError: si le compte est désactivé
        """
        with self._cache_lock:
            if token in self._session_cache:
                session, trainer = self._session_cache[token]
                if session.expires_at > datetime.now(timezone.utc):
                    if not trainer.is_active:
                        raise InactiveAccountError("Compte désactivé")
                    return trainer, session
                else:
                    # Session expirée, la retirer du cache
                    del self._session_cache[token]
        
        with self._lock:
            result = self.storage.get_session_by_token(token)
            
            if result is None:
                raise InvalidTokenError("Jeton invalide ou expiré")
            
            session, trainer = result
            
            if session.expires_at <= datetime.now(timezone.utc):
                self.storage.invalidate_session(session.id)
                raise ExpiredTokenError("JetonExpired")
            
            if not trainer.is_active:
                raise InactiveAccountError("Compte désactivé")
            
            # Mise en cache pour les prochaines requêtes
            with self._cache_lock:
                self._session_cache[token] = (session, trainer)
            
            return trainer, session

    def invalidate_token(self, token: Token) -> bool:
        """Invalidation d'un jeton.
        
        Args:
            token: Jeton à invalider
            
        Returns:
            bool: True si le jeton a été trouvé et invalidé
        """
        with self._cache_lock:
            self._session_cache.pop(token, None)
        
        with self._lock:
            result = self.storage.get_session_by_token(token)
            if result is None:
                return False
            session, _ = result
            return self.storage.invalidate_session(session.id)

    def invalidate_all_sessions(self, trainer_id: TrainerId | None = None) -> int:
        """Invalidation de toutes les sessions (ou pour un formateur spécifique).
        
        Args:
            trainer_id: Si spécifié, seul les sessions de ce formateur sont invalidées
            
        Returns:
            int: Nombre de sessions invalidées
        """
        with self._cache_lock:
            if trainer_id is None:
                self._session_cache.clear()
            else:
                # Retirer du cache les sessions du formateur
                tokens_to_remove = [
                    t for t, (s, tr) in self._session_cache.items() 
                    if tr.id == trainer_id
                ]
                for t in tokens_to_remove:
                    del self._session_cache[t]
        
        with self._lock:
            if trainer_id is None:
                return self.storage.invalidate_expired_sessions()
            else:
                return self.storage.invalidate_sessions_by_trainer(trainer_id)

    def change_password(self, trainer_id: TrainerId, current_password: str, new_password: str) -> bool:
        """Changement de mot de passe.
        
        Args:
            trainer_id: ID du formateur
            current_password: Mot de passe actuel
            new_password: Nouveau mot de passe
            
        Returns:
            bool: True si le changement a réussi
            
        Raises:
            InvalidTokenError: si le mot de passe actuel est incorrect
        """
        with self._lock:
            trainer = self.storage.get_trainer_by_id(trainer_id)
            
            if trainer is None:
                raise InvalidTokenError("Formateur introuvable")
            
            if trainer.password_hash is None:
                raise InvalidTokenError("Authentification externe non configurée")
            
            if not self.storage.verify_password(current_password, trainer.password_hash):
                raise InvalidTokenError("Mot de passe actuel incorrect")
            
            # Invalider toutes les sessions existantes
            self.invalidate_all_sessions(trainer_id)
            
            return self.storage.update_trainer_password(trainer_id, new_password)

    def create_trainer(self, username: str, password: str) -> Trainer:
        """Création d'un nouveau formateur.
        
        Args:
            username: Nom d'utilisateur
            password: Mot de passe
            
        Returns:
            Trainer: Le formateur créé
        """
        with self._lock:
            return self.storage.create_trainer(username, password)

    def cleanup_old_sessions(self, max_age_days: int = 30) -> int:
        """Nettoyage des anciennes sessions.
        
        Args:
            max_age_days: Âge maximum des sessions à conserver
            
        Returns:
            int: Nombre de sessions supprimées
        """
        with self._lock:
            return self.storage.cleanup_old_sessions(max_age_days)

    def generate_token(self, trainer_id: TrainerId, 
                       expires_in: timedelta | None = None,
                       ip_address: str | None = None,
                       user_agent: str | None = None) -> Token:
        """Génération d'un nouveau jeton pour un formateur (ex: refresh token).
        
        Args:
            trainer_id: ID du formateur
            expires_in: Durée de validité (par défaut DEFAULT_SESSION_DURATION)
            ip_address: Adresse IP du client
            user_agent: User-Agent du client
            
        Returns:
            Token: Nouveau jeton
        """
        with self._lock:
            trainer = self.storage.get_trainer_by_id(trainer_id)
            if trainer is None:
                raise InvalidTokenError("Formateur introuvable")
            
            if not trainer.is_active:
                raise InactiveAccountError("Compte désactivé")
            
            # Invalider les sessions existantes pour ce formateur
            # (optionnel : on pourrait garder les anciennes si on veut supporter multiple sessions)
            # self.invalidate_all_sessions(trainer_id)
            
            token = secrets.token_urlsafe(32)
            duration = expires_in or self.DEFAULT_SESSION_DURATION
            
            self.storage.create_session(
                trainer_id=trainer_id,
                token=token,
                expires_in=duration,
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            return token


def create_trainer_auth(workdir: Path) -> TrainerAuth:
    """Création du service d'authentification à partir du répertoire de travail.
    
    Args:
        workdir: Répertoire de travail (où la DB sera stockée)
        
    Returns:
        TrainerAuth: Service d'authentification initialisé
    """
    db_path = workdir / 'trainers.db'
    storage = AuthStorage(db_path)
    return TrainerAuth(storage)
