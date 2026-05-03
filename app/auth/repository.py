"""Database operations for users and sessions."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from app.auth.models import (
    EmailVerificationToken,
    GuestIdentity,
    PasswordResetToken,
    Session,
    User,
    Workspace,
)
from app.database import get_connection


class UserRepository:
    """CRUD operations for the users table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def create(
        self,
        user_id: str,
        email: str,
        password_hash: str | None,
        is_admin: bool = False,
        google_id: str | None = None,
    ) -> User:
        """Insert a new user and return the created record."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, email, password_hash, google_id, is_admin)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, email, password_hash, google_id, int(is_admin)),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO workspaces
                    (workspace_id, owner_user_id, guest_id, workspace_type)
                VALUES (?, ?, NULL, 'personal')
                """,
                (user_id, user_id),
            )
        return self.get_by_id(user_id)  # type: ignore[return-value]

    def get_by_google_id(self, google_id: str) -> User | None:
        """Fetch a user by their Google subject ID."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE google_id = ?", (google_id,)
            ).fetchone()
        if row is None:
            return None
        return _row_to_user(row)

    def link_google_id(self, user_id: str, google_id: str) -> None:
        """Attach a Google ID to an existing account (e.g. after email match)."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                "UPDATE users SET google_id = ?, updated_at = datetime('now') WHERE user_id = ?",
                (google_id, user_id),
            )

    def list_all(self) -> list[User]:
        """Return all users ordered by created_at descending."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY created_at DESC"
            ).fetchall()
        return [_row_to_user(r) for r in rows]

    def get_by_id(self, user_id: str) -> User | None:
        """Fetch a user by primary key."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        if row is None:
            return None
        return _row_to_user(row)

    def get_by_email(self, email: str) -> User | None:
        """Fetch a user by email address."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()
        if row is None:
            return None
        return _row_to_user(row)

    def mark_email_verified(self, user_id: str) -> None:
        """Set email_verified = 1 for the given user."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                "UPDATE users SET email_verified = 1, updated_at = datetime('now') WHERE user_id = ?",
                (user_id,),
            )

    def delete(self, user_id: str) -> None:
        """Delete a user by ID."""
        with get_connection(self._db_path) as conn:
            conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))


class SessionRepository:
    """CRUD operations for the sessions table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def create(
        self,
        session_id: str,
        user_id: str | None,
        guest_id: str | None,
        expires_at: str,
    ) -> Session:
        """Insert a new session and return the record."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, user_id, guest_id, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, user_id, guest_id, expires_at),
            )
        return self.get_by_id(session_id)  # type: ignore[return-value]

    def create_for_user(
        self, session_id: str, user_id: str, expires_at: str
    ) -> Session:
        return self.create(session_id, user_id, None, expires_at)

    def create_for_guest(
        self, session_id: str, guest_id: str, expires_at: str
    ) -> Session:
        return self.create(session_id, None, guest_id, expires_at)

    def get_by_id(self, session_id: str) -> Session | None:
        """Fetch a session by primary key."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        return _row_to_session(row)

    def delete(self, session_id: str) -> None:
        """Delete a session (logout)."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )

    def delete_expired(self) -> None:
        """Prune sessions that have passed their expiry timestamp."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                "DELETE FROM sessions WHERE expires_at < datetime('now')"
            )

    def delete_all_for_user(self, user_id: str) -> None:
        """Delete all sessions for a user."""
        with get_connection(self._db_path) as conn:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def delete_all_for_guest(self, guest_id: str) -> None:
        """Delete all sessions for a guest identity."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                "DELETE FROM sessions WHERE guest_id = ?", (guest_id,)
            )


class GuestIdentityRepository:
    """CRUD operations for durable pre-signup guest identities."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def create(
        self,
        guest_id: str,
        *,
        first_path: str | None,
        first_referrer: str | None,
        first_user_agent: str | None,
        first_seen_at: str,
    ) -> GuestIdentity:
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO guest_identities
                    (guest_id, claimed_by_user_id, first_path, first_referrer,
                     first_user_agent, first_seen_at, last_seen_at, claimed_at,
                     created_at, updated_at)
                VALUES (?, NULL, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    guest_id,
                    first_path,
                    first_referrer,
                    first_user_agent,
                    first_seen_at,
                    first_seen_at,
                    first_seen_at,
                    first_seen_at,
                ),
            )
        return self.get_by_id(guest_id)  # type: ignore[return-value]

    def get_by_id(self, guest_id: str) -> GuestIdentity | None:
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM guest_identities WHERE guest_id = ?",
                (guest_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_guest_identity(row)

    def touch(self, guest_id: str, occurred_at: str) -> None:
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE guest_identities
                SET last_seen_at = ?, updated_at = ?
                WHERE guest_id = ?
                """,
                (occurred_at, occurred_at, guest_id),
            )

    def mark_claimed(
        self, guest_id: str, user_id: str, claimed_at: str
    ) -> None:
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE guest_identities
                SET claimed_by_user_id = ?, claimed_at = ?, updated_at = ?
                WHERE guest_id = ?
                """,
                (user_id, claimed_at, claimed_at, guest_id),
            )


class WorkspaceRepository:
    """CRUD operations for workspace ownership records."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def get_by_id(self, workspace_id: str) -> Workspace | None:
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_workspace(row)

    def get_by_user(self, user_id: str) -> Workspace | None:
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE owner_user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_workspace(row)

    def get_by_guest(self, guest_id: str) -> Workspace | None:
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE guest_id = ?",
                (guest_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_workspace(row)

    def get_or_create_for_user(
        self, user_id: str, occurred_at: str | None = None
    ) -> Workspace:
        existing = self.get_by_user(user_id)
        if existing is not None:
            return existing
        timestamp = occurred_at or datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO workspaces
                    (workspace_id, owner_user_id, guest_id, workspace_type,
                     created_at, updated_at)
                VALUES (?, ?, NULL, 'personal', ?, ?)
                """,
                (user_id, user_id, timestamp, timestamp),
            )
        return self.get_by_user(user_id)  # type: ignore[return-value]

    def create_for_guest(self, guest_id: str, occurred_at: str) -> Workspace:
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO workspaces
                    (workspace_id, owner_user_id, guest_id, workspace_type,
                     created_at, updated_at)
                VALUES (?, NULL, ?, 'guest', ?, ?)
                """,
                (guest_id, guest_id, occurred_at, occurred_at),
            )
        return self.get_by_guest(guest_id)  # type: ignore[return-value]

    def delete(self, workspace_id: str) -> None:
        with get_connection(self._db_path) as conn:
            conn.execute(
                "DELETE FROM workspaces WHERE workspace_id = ?",
                (workspace_id,),
            )


class PasswordResetTokenRepository:
    """CRUD operations for the password_reset_tokens table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def create(
        self, token_id: str, user_id: str, expires_at: str
    ) -> PasswordResetToken:
        """Insert a new reset token and return the record."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO password_reset_tokens (token_id, user_id, expires_at)
                VALUES (?, ?, ?)
                """,
                (token_id, user_id, expires_at),
            )
        return self.get_by_id(token_id)  # type: ignore[return-value]

    def get_by_id(self, token_id: str) -> PasswordResetToken | None:
        """Fetch a token by primary key — only returns unused, non-expired tokens."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM password_reset_tokens
                WHERE token_id = ?
                  AND used_at IS NULL
                  AND expires_at > datetime('now')
                """,
                (token_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_reset_token(row)

    def mark_used(self, token_id: str) -> None:
        """Set used_at to the current time for the given token."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                "UPDATE password_reset_tokens SET used_at = datetime('now') WHERE token_id = ?",
                (token_id,),
            )


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        user_id=row["user_id"],
        email=row["email"],
        password_hash=row["password_hash"],
        google_id=row["google_id"],
        is_admin=bool(row["is_admin"]),
        email_verified=bool(row["email_verified"]),
        is_anonymous=False,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_guest_identity(row: sqlite3.Row) -> GuestIdentity:
    return GuestIdentity(
        guest_id=row["guest_id"],
        claimed_by_user_id=row["claimed_by_user_id"],
        first_path=row["first_path"],
        first_referrer=row["first_referrer"],
        first_user_agent=row["first_user_agent"],
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        claimed_at=row["claimed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_workspace(row: sqlite3.Row) -> Workspace:
    return Workspace(
        workspace_id=row["workspace_id"],
        owner_user_id=row["owner_user_id"],
        guest_id=row["guest_id"],
        workspace_type=row["workspace_type"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        session_id=row["session_id"],
        user_id=row["user_id"],
        guest_id=row["guest_id"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
    )


def _row_to_reset_token(row: sqlite3.Row) -> PasswordResetToken:
    return PasswordResetToken(
        token_id=row["token_id"],
        user_id=row["user_id"],
        expires_at=row["expires_at"],
        used_at=row["used_at"],
        created_at=row["created_at"],
    )


class EmailVerificationTokenRepository:
    """CRUD operations for the email_verification_tokens table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def create(
        self, token_id: str, user_id: str, expires_at: str
    ) -> EmailVerificationToken:
        """Insert a new verification token and return the record."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO email_verification_tokens (token_id, user_id, expires_at)
                VALUES (?, ?, ?)
                """,
                (token_id, user_id, expires_at),
            )
        return self.get_by_id(token_id)  # type: ignore[return-value]

    def get_by_id(self, token_id: str) -> EmailVerificationToken | None:
        """Fetch a token by primary key — only returns unused, non-expired tokens."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM email_verification_tokens
                WHERE token_id = ?
                  AND used_at IS NULL
                  AND expires_at > datetime('now')
                """,
                (token_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_email_verification_token(row)

    def mark_used(self, token_id: str) -> None:
        """Set used_at to the current time for the given token."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                "UPDATE email_verification_tokens SET used_at = datetime('now') WHERE token_id = ?",
                (token_id,),
            )


def _row_to_email_verification_token(
    row: sqlite3.Row,
) -> EmailVerificationToken:
    return EmailVerificationToken(
        token_id=row["token_id"],
        user_id=row["user_id"],
        expires_at=row["expires_at"],
        used_at=row["used_at"],
        created_at=row["created_at"],
    )
