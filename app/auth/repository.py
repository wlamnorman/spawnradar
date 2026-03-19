"""Database operations for users and sessions."""
from __future__ import annotations

from app.auth.models import PasswordResetToken, Session, User
from app.database import get_connection


class UserRepository:
    """CRUD operations for the users table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def create(self, user_id: str, email: str, password_hash: str, is_admin: bool = False) -> User:
        """Insert a new user and return the created record."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, email, password_hash, is_admin)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, email, password_hash, int(is_admin)),
            )
        return self.get_by_id(user_id)  # type: ignore[return-value]

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


class SessionRepository:
    """CRUD operations for the sessions table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def create(self, session_id: str, user_id: str, expires_at: str) -> Session:
        """Insert a new session and return the record."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, user_id, expires_at)
                VALUES (?, ?, ?)
                """,
                (session_id, user_id, expires_at),
            )
        return self.get_by_id(session_id)  # type: ignore[return-value]

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
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def delete_expired(self) -> None:
        """Prune sessions that have passed their expiry timestamp."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                "DELETE FROM sessions WHERE expires_at < datetime('now')"
            )


class PasswordResetTokenRepository:
    """CRUD operations for the password_reset_tokens table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def create(self, token_id: str, user_id: str, expires_at: str) -> PasswordResetToken:
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


def _row_to_user(row: object) -> User:
    return User(
        user_id=row["user_id"],
        email=row["email"],
        password_hash=row["password_hash"],
        is_admin=bool(row["is_admin"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_session(row: object) -> Session:
    return Session(
        session_id=row["session_id"],
        user_id=row["user_id"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
    )


def _row_to_reset_token(row: object) -> PasswordResetToken:
    return PasswordResetToken(
        token_id=row["token_id"],
        user_id=row["user_id"],
        expires_at=row["expires_at"],
        used_at=row["used_at"],
        created_at=row["created_at"],
    )
