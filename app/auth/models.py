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
    is_anonymous: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class GuestIdentity:
    """Represents an anonymous pre-signup visitor with durable product state."""

    guest_id: str
    claimed_by_user_id: str | None
    first_path: str | None
    first_referrer: str | None
    first_user_agent: str | None
    first_seen_at: str
    last_seen_at: str
    claimed_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Workspace:
    """Durable ownership container for games and subscriptions."""

    workspace_id: str
    owner_user_id: str | None
    guest_id: str | None
    workspace_type: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Session:
    """Represents an authenticated browser session."""

    session_id: str
    user_id: str | None
    guest_id: str | None
    expires_at: str
    created_at: str

    @property
    def is_guest(self) -> bool:
        return self.guest_id is not None and self.user_id is None


@dataclass(frozen=True)
class Actor:
    """Current request identity for public/product routes."""

    workspace_id: str
    user_id: str | None
    guest_id: str | None
    email: str | None
    is_admin: bool
    email_verified: bool
    created_at: str
    updated_at: str

    @property
    def is_anonymous(self) -> bool:
        return self.guest_id is not None and self.user_id is None

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None


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
