"""Helpers for preparing a local dev database."""

from __future__ import annotations

import uuid

import bcrypt

from app.auth.models import User
from app.auth.repository import UserRepository
from app.database import get_connection, initialize_database

DEV_EMAIL = "dev@spawnradar.local"
DEV_PASSWORD = "dev"


def ensure_dev_user(db_path: str) -> User:
    """Ensure the local dev user exists and return it."""
    initialize_database(db_path)
    user_repo = UserRepository(db_path)
    existing = user_repo.get_by_email(DEV_EMAIL)
    if existing is not None:
        if not existing.email_verified:
            with get_connection(db_path) as conn:
                conn.execute("UPDATE users SET email_verified = 1 WHERE user_id = ?", (existing.user_id,))
        return user_repo.get_by_id(existing.user_id)  # type: ignore[return-value]

    hashed = bcrypt.hashpw(DEV_PASSWORD.encode(), bcrypt.gensalt()).decode()
    user = user_repo.create(
        user_id=str(uuid.uuid4()),
        email=DEV_EMAIL,
        password_hash=hashed,
    )
    with get_connection(db_path) as conn:
        conn.execute("UPDATE users SET email_verified = 1 WHERE user_id = ?", (user.user_id,))
    return user_repo.get_by_id(user.user_id)  # type: ignore[return-value]
