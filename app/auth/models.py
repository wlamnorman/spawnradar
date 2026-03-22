"""Auth domain models."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    """Represents a registered developer account."""

    user_id: str
    email: str
    password_hash: str | None  # None for Google-only accounts
    google_id: str | None      # None for password-only accounts
    is_admin: bool
    email_verified: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Session:
    """Represents an authenticated browser session."""

    session_id: str
    user_id: str
    expires_at: str
    created_at: str


@dataclass(frozen=True)
class PasswordResetToken:
    """A single-use token for resetting a forgotten password."""

    token_id: str
    user_id: str
    expires_at: str
    used_at: str | None
    created_at: str


@dataclass(frozen=True)
class EmailVerificationToken:
    """A single-use token for verifying an email address."""

    token_id: str
    user_id: str
    expires_at: str
    used_at: str | None
    created_at: str
