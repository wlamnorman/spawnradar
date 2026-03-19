"""Helpers for preparing a local dev database."""

from __future__ import annotations

import uuid

import bcrypt

from app.auth.models import User
from app.auth.repository import UserRepository
from app.database import initialize_database

DEV_EMAIL = "dev@spawnradar.local"
DEV_PASSWORD = "dev"


def ensure_dev_user(db_path: str) -> User:
    """Ensure the local dev user exists and return it."""
    initialize_database(db_path)
    user_repo = UserRepository(db_path)
    existing = user_repo.get_by_email(DEV_EMAIL)
    if existing is not None:
        return existing

    hashed = bcrypt.hashpw(DEV_PASSWORD.encode(), bcrypt.gensalt()).decode()
    return user_repo.create(
        user_id=str(uuid.uuid4()),
        email=DEV_EMAIL,
        password_hash=hashed,
    )
