"""Business logic for authentication: registration, login, session management."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import bcrypt

from app.auth.models import Actor, GuestIdentity, Session, User, Workspace
from app.auth.repository import (
    EmailVerificationTokenRepository,
    GuestIdentityRepository,
    PasswordResetTokenRepository,
    SessionRepository,
    UserRepository,
    WorkspaceRepository,
)
from app.email.service import EmailMessage, EmailService

if TYPE_CHECKING:
    from app.metrics.service import MetricsService

SESSION_LIFETIME_DAYS = 30
RESET_TOKEN_LIFETIME_HOURS = 1
VERIFICATION_TOKEN_LIFETIME_HOURS = 24

log = logging.getLogger(__name__)


def _normalize_email(email: str) -> str:
    """Return a canonical email address.

    For Gmail / Googlemail addresses, strips dots and +tags from the local
    part so that me@gmail.com, m.e@gmail.com and me+tag@gmail.com all
    resolve to the same account.
    """
    email = email.strip().lower()
    local, at, domain = email.partition("@")
    if domain in ("gmail.com", "googlemail.com"):
        local = local.split("+")[0].replace(".", "")
        domain = "gmail.com"  # treat googlemail.com as gmail.com
    return f"{local}{at}{domain}"


class AuthService:
    """Handles user registration, login and session lifecycle."""

    def __init__(
        self,
        user_repo: UserRepository,
        session_repo: SessionRepository | None,
        reset_token_repo: PasswordResetTokenRepository | None = None,
        email_verification_token_repo: EmailVerificationTokenRepository
        | None = None,
        guest_repo: GuestIdentityRepository | None = None,
        workspace_repo: WorkspaceRepository | None = None,
        metrics_service: MetricsService | None = None,
    ) -> None:
        self._users = user_repo
        self._sessions = session_repo
        self._reset_tokens = reset_token_repo
        self._email_verification_tokens = email_verification_token_repo
        self._guests = guest_repo
        self._workspaces = workspace_repo
        self._metrics = metrics_service

    def register(self, email: str, password: str) -> User:
        """Create a new user account.

        Raises ValueError if the email is already registered.
        """
        email = _normalize_email(email)
        if not email or not password:
            raise ValueError("Email and password are required.")
        if self._users.get_by_email(email) is not None:
            raise ValueError("An account with that email already exists.")

        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        user_id = str(uuid.uuid4())
        user = self._users.create(user_id, email, hashed)
        self.get_or_create_workspace_for_user(user.user_id)
        if self._metrics is not None:
            self._metrics.record_account_created(user.user_id, user.created_at)
        return user

    def create_email_only_user(self, email: str) -> User:
        """Create an account with no password set yet.

        Intended for admin or CLI-created accounts that will set a password
        via the normal reset-password flow.
        """
        email = _normalize_email(email)
        if not email:
            raise ValueError("Email is required.")
        existing = self._users.get_by_email(email)
        if existing is not None:
            self.get_or_create_workspace_for_user(existing.user_id)
            return existing

        user_id = str(uuid.uuid4())
        user = self._users.create(user_id, email, password_hash=None)
        self.get_or_create_workspace_for_user(user.user_id)
        if self._metrics is not None:
            self._metrics.record_account_created(user.user_id, user.created_at)
        return user

    def login(self, email: str, password: str) -> Session:
        """Verify credentials and create a new session.

        Raises ValueError if credentials are invalid or the account uses
        Google sign-in only and has no password set.
        """
        email = _normalize_email(email)
        user = self._users.get_by_email(email)
        if user is None or user.password_hash is None:
            raise ValueError("Invalid email or password.")
        if not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            raise ValueError("Invalid email or password.")

        if self._sessions is None:
            raise ValueError("Session storage is not configured.")

        session_id = str(uuid.uuid4())
        expires_at = (
            datetime.now(UTC) + timedelta(days=SESSION_LIFETIME_DAYS)
        ).isoformat()
        self.get_or_create_workspace_for_user(user.user_id)
        session = self._sessions.create_for_user(
            session_id, user.user_id, expires_at
        )
        if self._metrics is not None:
            self._metrics.record_session_started(
                user.user_id, session.created_at
            )
        return session

    def logout(self, session_id: str) -> None:
        """Invalidate a session."""
        if self._sessions is None:
            return
        self._sessions.delete(session_id)

    def create_session_for_user(self, user_id: str) -> Session:
        """Create a new session for an existing user."""
        if self._sessions is None:
            raise ValueError("Session storage is not configured.")

        session_id = str(uuid.uuid4())
        expires_at = (
            datetime.now(UTC) + timedelta(days=SESSION_LIFETIME_DAYS)
        ).isoformat()
        self.get_or_create_workspace_for_user(user_id)
        session = self._sessions.create_for_user(
            session_id, user_id, expires_at
        )
        if self._metrics is not None:
            self._metrics.record_session_started(user_id, session.created_at)
        return session

    def create_guest_actor(
        self,
        *,
        first_path: str | None,
        first_referrer: str | None,
        first_user_agent: str | None,
    ) -> tuple[Actor, Session]:
        """Create a durable guest identity and a browser session for it."""
        if (
            self._sessions is None
            or self._guests is None
            or self._workspaces is None
        ):
            raise ValueError("Guest session storage is not configured.")

        guest_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        guest = self._guests.create(
            guest_id,
            first_path=first_path,
            first_referrer=first_referrer,
            first_user_agent=first_user_agent,
            first_seen_at=now,
        )
        workspace = self._workspaces.create_for_guest(guest.guest_id, now)
        session = self._sessions.create_for_guest(
            str(uuid.uuid4()),
            guest.guest_id,
            (
                datetime.now(UTC) + timedelta(days=SESSION_LIFETIME_DAYS)
            ).isoformat(),
        )
        return self._actor_from_guest(guest, workspace.workspace_id), session

    def get_or_create_google_user(self, google_id: str, email: str) -> User:
        """Return an existing user matched by Google ID or email, creating one if absent.

        If a user exists with the same email but no Google ID yet, the Google
        ID is linked to their account so future logins work by either method.
        """
        email = _normalize_email(email)

        # 1. Exact match on google_id
        user = self._users.get_by_google_id(google_id)
        if user is not None:
            self.get_or_create_workspace_for_user(user.user_id)
            return user

        # 2. Existing account with same email — link the Google ID
        user = self._users.get_by_email(email)
        if user is not None:
            self._users.link_google_id(user.user_id, google_id)
            self.get_or_create_workspace_for_user(user.user_id)
            return self._users.get_by_id(user.user_id)  # type: ignore[return-value]

        # 3. New user — create a password-less account
        user_id = str(uuid.uuid4())
        user = self._users.create(
            user_id, email, password_hash=None, google_id=google_id
        )
        if self._metrics is not None:
            self._metrics.record_account_created(user.user_id, user.created_at)
        return user

    def get_session(self, session_id: str) -> Session | None:
        """Return a session if it exists and has not expired, else None."""
        if self._sessions is None:
            return None
        session = self._sessions.get_by_id(session_id)
        if session is None:
            return None
        if datetime.fromisoformat(session.expires_at) < datetime.now(UTC):
            self._sessions.delete(session_id)
            return None
        return session

    def get_user_for_session(self, session_id: str) -> User | None:
        """Return the User associated with a valid session or None."""
        session = self.get_session(session_id)
        if session is None or session.user_id is None:
            return None
        return self._users.get_by_id(session.user_id)

    def get_actor_for_session(self, session_id: str) -> Actor | None:
        """Return the current request actor for a session."""
        session = self.get_session(session_id)
        if session is None:
            return None
        if session.user_id is not None:
            user = self._users.get_by_id(session.user_id)
            if user is None:
                return None
            workspace = self.get_or_create_workspace_for_user(user.user_id)
            return self._actor_from_user(user, workspace.workspace_id)
        if (
            session.guest_id is None
            or self._guests is None
            or self._workspaces is None
        ):
            return None
        guest = self._guests.get_by_id(session.guest_id)
        workspace = self._workspaces.get_by_guest(session.guest_id)
        if guest is None or workspace is None:
            return None
        self._guests.touch(guest.guest_id, datetime.now(UTC).isoformat())
        return self._actor_from_guest(guest, workspace.workspace_id)

    def get_or_create_workspace_for_user(self, user_id: str) -> Workspace:
        """Return the user's personal workspace, creating it if needed."""
        if self._workspaces is None:
            raise ValueError("Workspace storage is not configured.")
        return self._workspaces.get_or_create_for_user(user_id)

    def request_password_reset(
        self,
        email: str,
        email_service: EmailService,
        base_url: str,
    ) -> None:
        """Send a password reset email.

        Silently does nothing if the email is not registered, to avoid
        leaking whether an account exists.
        """
        email = email.strip().lower()
        user = self._users.get_by_email(email)
        if user is None or self._reset_tokens is None:
            return

        token_id = str(uuid.uuid4())
        expires_at = (
            datetime.now(UTC) + timedelta(hours=RESET_TOKEN_LIFETIME_HOURS)
        ).isoformat()
        self._reset_tokens.create(token_id, user.user_id, expires_at)

        reset_link = f"{base_url}/auth/reset-password?token={token_id}"
        html = f"""
        <div style="font-family:sans-serif;max-width:560px;margin:0 auto">
          <h2>Reset your Spawnradar password</h2>
          <p>We received a request to reset the password for your account.</p>
          <p style="margin:32px 0">
            <a href="{reset_link}"
               style="background:#6366f1;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600">
              Reset password
            </a>
          </p>
          <p style="color:#6b7280;font-size:14px">
            This link expires in {RESET_TOKEN_LIFETIME_HOURS} hour(s).
            If you did not request a password reset, you can safely ignore this email.
          </p>
          <p style="color:#6b7280;font-size:14px">
            Or copy this link into your browser:<br>
            <a href="{reset_link}">{reset_link}</a>
          </p>
        </div>
        """
        text = (
            f"Reset your Spawnradar password\n\n"
            f"Visit the link below to reset your password (expires in "
            f"{RESET_TOKEN_LIFETIME_HOURS} hour(s)):\n\n"
            f"{reset_link}\n\n"
            f"If you did not request a password reset, ignore this email."
        )

        try:
            email_service.send(
                EmailMessage(
                    to=email,
                    subject="Reset your Spawnradar password",
                    html=html,
                    text=text,
                )
            )
        except Exception:
            log.exception(
                "Could not send password reset email for %s; leaving reset token in place.",
                email,
            )

    def send_verification_email(
        self, user: User, email_service: EmailService, base_url: str
    ) -> None:
        """Send email verification link. Silently swallows errors."""
        if self._email_verification_tokens is None:
            return
        token_id = str(uuid.uuid4())
        expires_at = (
            datetime.now(UTC)
            + timedelta(hours=VERIFICATION_TOKEN_LIFETIME_HOURS)
        ).isoformat()
        self._email_verification_tokens.create(
            token_id, user.user_id, expires_at
        )
        verify_link = f"{base_url}/auth/verify-email?token={token_id}"
        html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:0 auto">
      <h2>Verify your SpawnRadar email</h2>
      <p>Thanks for signing up. Click below to verify your email and start discovering creators for your game.</p>
      <p style="margin:32px 0">
        <a href="{verify_link}"
           style="background:#6366f1;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600">
          Verify email
        </a>
      </p>
      <p style="color:#6b7280;font-size:14px">This link expires in {VERIFICATION_TOKEN_LIFETIME_HOURS} hours.</p>
      <p style="color:#6b7280;font-size:14px">Or copy this link:<br><a href="{verify_link}">{verify_link}</a></p>
    </div>
    """
        text = (
            f"Verify your SpawnRadar email\n\n"
            f"Click the link below to verify your email and start discovering creators for your game "
            f"(expires in {VERIFICATION_TOKEN_LIFETIME_HOURS} hours):\n\n"
            f"{verify_link}\n\n"
            f"If you did not sign up for SpawnRadar, ignore this email."
        )
        try:
            email_service.send(
                EmailMessage(
                    to=user.email,
                    subject="Verify your SpawnRadar email",
                    html=html,
                    text=text,
                )
            )
        except Exception:
            log.exception(
                "Could not send verification email for %s", user.email
            )

    def verify_email(self, token_id: str) -> bool:
        """Mark the user's email as verified. Returns True on success, False if token is invalid."""
        if self._email_verification_tokens is None:
            return False
        token = self._email_verification_tokens.get_by_id(token_id)
        if token is None:
            return False
        self._users.mark_email_verified(token.user_id)
        self._email_verification_tokens.mark_used(token_id)
        return True

    def mark_google_user_verified(self, user_id: str) -> None:
        """Mark a Google-authenticated user's email as verified."""
        self._users.mark_email_verified(user_id)

    def claim_guest_workspace(self, guest_id: str, new_user_id: str) -> int:
        """Transfer guest-owned product data into the user's personal workspace."""
        from app.billing.repository import SubscriptionRepository
        from app.games.repository import CustomerGameRepository

        if self._guests is None or self._workspaces is None:
            return 0

        guest_workspace = self._workspaces.get_by_guest(guest_id)
        if guest_workspace is None:
            return 0
        user_workspace = self.get_or_create_workspace_for_user(new_user_id)
        game_repo = CustomerGameRepository(self._users._db_path)
        transferred = game_repo.transfer_workspace(
            guest_workspace.workspace_id,
            user_workspace.workspace_id,
        )

        sub_repo = SubscriptionRepository(self._users._db_path)
        sub_repo.transfer_to_workspace(
            guest_workspace.workspace_id,
            user_workspace.workspace_id,
        )
        if self._sessions is not None:
            self._sessions.delete_all_for_guest(guest_id)
        now = datetime.now(UTC).isoformat()
        self._guests.mark_claimed(guest_id, new_user_id, now)
        self._workspaces.delete(guest_workspace.workspace_id)
        return transferred

    def _actor_from_user(self, user: User, workspace_id: str) -> Actor:
        return Actor(
            workspace_id=workspace_id,
            user_id=user.user_id,
            guest_id=None,
            email=user.email,
            is_admin=user.is_admin,
            email_verified=user.email_verified,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    def _actor_from_guest(
        self, guest: GuestIdentity, workspace_id: str
    ) -> Actor:
        return Actor(
            workspace_id=workspace_id,
            user_id=None,
            guest_id=guest.guest_id,
            email=None,
            is_admin=False,
            email_verified=False,
            created_at=guest.created_at,
            updated_at=guest.updated_at,
        )

    def reset_password(self, token_id: str, new_password: str) -> None:
        """Reset a user's password using a valid reset token.

        Raises ValueError if the token is invalid, expired or already used.
        """
        if self._reset_tokens is None:
            raise ValueError("Password reset is not configured.")

        token = self._reset_tokens.get_by_id(token_id)
        if token is None:
            raise ValueError("This reset link is invalid or has expired.")

        if not new_password:
            raise ValueError("New password cannot be empty.")

        hashed = bcrypt.hashpw(
            new_password.encode(), bcrypt.gensalt()
        ).decode()

        from app.database import get_connection

        with get_connection(self._users._db_path) as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = datetime('now') WHERE user_id = ?",
                (hashed, token.user_id),
            )

        self._reset_tokens.mark_used(token_id)
