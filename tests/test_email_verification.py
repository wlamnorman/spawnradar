"""Tests for email verification: token lifecycle, service methods and HTTP flows."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth.repository import (
    EmailVerificationTokenRepository,
)
from app.auth.service import AuthService
from app.database import get_connection
from app.email.service import EmailMessage, EmailService
from app.main import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def email_verification_token_repo(db_path):
    return EmailVerificationTokenRepository(db_path)


@pytest.fixture
def auth_service_with_verification(
    user_repo, session_repo, email_verification_token_repo
):
    return AuthService(
        user_repo,
        session_repo,
        email_verification_token_repo=email_verification_token_repo,
    )


@pytest.fixture
def unverified_user(auth_service_with_verification):
    return auth_service_with_verification.register(
        "unverified@example.com", "password123"
    )


@pytest.fixture
def verified_user(auth_service_with_verification, user_repo):
    user = auth_service_with_verification.register(
        "verified@example.com", "password123"
    )
    user_repo.mark_email_verified(user.user_id)
    return user_repo.get_by_id(user.user_id)


# ---------------------------------------------------------------------------
# Helpers shared with HTTP-layer tests
# ---------------------------------------------------------------------------


def _make_http_client(monkeypatch, tmp_path) -> tuple[TestClient, str]:
    db_path = str(tmp_path / "verify-test.sqlite3")
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("DEV_AUTO_LOGIN", raising=False)
    for key in (
        "PADDLE_API_KEY",
        "PADDLE_CLIENT_SIDE_TOKEN",
        "PADDLE_WEBHOOK_SECRET",
        "PADDLE_INDIE_PRICE_ID",
        "PADDLE_ENVIRONMENT",
        "RESEND_API_KEY",
    ):
        monkeypatch.setenv(key, "")
    return TestClient(create_app()), db_path


def _csrf_token(client: TestClient, path: str) -> str:
    response = client.get(path)
    match = re.search(r'name="csrf-token" content="([^"]+)"', response.text)
    assert match is not None, f"No CSRF token found at {path}"
    return match.group(1)


def _register(
    client: TestClient,
    email: str = "user@example.com",
    password: str = "password123",
) -> None:
    token = _csrf_token(client, "/auth/register")
    client.post(
        "/auth/register",
        data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def _get_verification_token(db_path: str, email: str) -> str | None:
    """Fetch the most recently created unused, non-expired verification token for a user."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT t.token_id
            FROM email_verification_tokens t
            JOIN users u ON u.user_id = t.user_id
            WHERE u.email = ?
              AND t.used_at IS NULL
              AND t.expires_at > datetime('now')
            ORDER BY t.created_at DESC
            LIMIT 1
            """,
            (email,),
        ).fetchone()
    return row["token_id"] if row else None


def _is_email_verified(db_path: str, email: str) -> bool:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT email_verified FROM users WHERE email = ?", (email,)
        ).fetchone()
    return bool(row["email_verified"]) if row else False


# ===========================================================================
# Unit tests — repository layer
# ===========================================================================


class TestEmailVerificationTokenRepository:
    def test_create_and_get_token(
        self, email_verification_token_repo, unverified_user
    ):
        token_id = str(uuid.uuid4())
        expires_at = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
        email_verification_token_repo.create(
            token_id, unverified_user.user_id, expires_at
        )

        token = email_verification_token_repo.get_by_id(token_id)
        assert token is not None
        assert token.token_id == token_id
        assert token.user_id == unverified_user.user_id
        assert token.used_at is None

    def test_get_by_id_returns_none_for_unknown_token(
        self, email_verification_token_repo
    ):
        assert email_verification_token_repo.get_by_id("nonexistent") is None

    def test_get_by_id_returns_none_for_used_token(
        self, email_verification_token_repo, unverified_user
    ):
        token_id = str(uuid.uuid4())
        expires_at = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
        email_verification_token_repo.create(
            token_id, unverified_user.user_id, expires_at
        )
        email_verification_token_repo.mark_used(token_id)

        assert email_verification_token_repo.get_by_id(token_id) is None

    def test_get_by_id_returns_none_for_expired_token(
        self, db_path, unverified_user
    ):
        repo = EmailVerificationTokenRepository(db_path)
        token_id = str(uuid.uuid4())
        # Insert directly in SQLite-compatible format so the expires_at > datetime('now')
        # comparison works correctly (ISO 8601 +00:00 suffix causes string comparison issues).
        with get_connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO email_verification_tokens (token_id, user_id, expires_at)
                VALUES (?, ?, datetime('now', '-1 hour'))
                """,
                (token_id, unverified_user.user_id),
            )

        assert repo.get_by_id(token_id) is None

    def test_mark_used_sets_used_at(
        self, email_verification_token_repo, unverified_user
    ):
        token_id = str(uuid.uuid4())
        expires_at = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
        email_verification_token_repo.create(
            token_id, unverified_user.user_id, expires_at
        )
        email_verification_token_repo.mark_used(token_id)

        with get_connection(email_verification_token_repo._db_path) as conn:
            row = conn.execute(
                "SELECT used_at FROM email_verification_tokens WHERE token_id = ?",
                (token_id,),
            ).fetchone()
        assert row["used_at"] is not None

    def test_token_deleted_when_user_deleted(self, db_path, unverified_user):
        repo = EmailVerificationTokenRepository(db_path)
        token_id = str(uuid.uuid4())
        expires_at = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
        repo.create(token_id, unverified_user.user_id, expires_at)

        with get_connection(db_path) as conn:
            conn.execute(
                "DELETE FROM users WHERE user_id = ?",
                (unverified_user.user_id,),
            )

        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM email_verification_tokens WHERE token_id = ?",
                (token_id,),
            ).fetchone()
        assert row is None  # cascaded


class TestUserRepositoryVerification:
    def test_new_user_is_unverified(self, unverified_user):
        assert unverified_user.email_verified is False

    def test_mark_email_verified_sets_flag(self, user_repo, unverified_user):
        user_repo.mark_email_verified(unverified_user.user_id)
        updated = user_repo.get_by_id(unverified_user.user_id)
        assert updated.email_verified is True

    def test_mark_email_verified_is_idempotent(
        self, user_repo, unverified_user
    ):
        user_repo.mark_email_verified(unverified_user.user_id)
        user_repo.mark_email_verified(unverified_user.user_id)
        updated = user_repo.get_by_id(unverified_user.user_id)
        assert updated.email_verified is True


# ===========================================================================
# Unit tests — service layer
# ===========================================================================


class TestAuthServiceEmailVerification:
    def test_verify_email_returns_true_and_marks_user(
        self, auth_service_with_verification, user_repo, unverified_user
    ):
        mock_email = MagicMock(spec=EmailService)
        mock_email.send = MagicMock()

        auth_service_with_verification.send_verification_email(
            unverified_user, mock_email, "https://example.com"
        )

        # Grab the token from the DB
        with get_connection(user_repo._db_path) as conn:
            row = conn.execute(
                "SELECT token_id FROM email_verification_tokens WHERE user_id = ? AND used_at IS NULL",
                (unverified_user.user_id,),
            ).fetchone()
        assert row is not None

        result = auth_service_with_verification.verify_email(row["token_id"])
        assert result is True

        updated = user_repo.get_by_id(unverified_user.user_id)
        assert updated.email_verified is True

    def test_verify_email_marks_token_as_used(
        self, auth_service_with_verification, user_repo, unverified_user
    ):
        mock_email = MagicMock(spec=EmailService)
        auth_service_with_verification.send_verification_email(
            unverified_user, mock_email, "https://example.com"
        )
        with get_connection(user_repo._db_path) as conn:
            row = conn.execute(
                "SELECT token_id FROM email_verification_tokens WHERE user_id = ?",
                (unverified_user.user_id,),
            ).fetchone()
        token_id = row["token_id"]

        auth_service_with_verification.verify_email(token_id)

        # Token now used — verify_email returns False for a second attempt
        result = auth_service_with_verification.verify_email(token_id)
        assert result is False

    def test_verify_email_returns_false_for_unknown_token(
        self, auth_service_with_verification
    ):
        assert (
            auth_service_with_verification.verify_email("bad-token") is False
        )

    def test_verify_email_returns_false_without_token_repo(self, auth_service):
        """AuthService without a token repo gracefully returns False."""
        assert auth_service.verify_email("any-token") is False

    def test_send_verification_email_creates_token_and_sends(
        self, auth_service_with_verification, user_repo, unverified_user
    ):
        sent: list[EmailMessage] = []
        mock_email = MagicMock(spec=EmailService)
        mock_email.send.side_effect = lambda msg: sent.append(msg)

        auth_service_with_verification.send_verification_email(
            unverified_user, mock_email, "https://spawnradar.com"
        )

        assert len(sent) == 1
        msg = sent[0]
        assert msg.to == unverified_user.email
        assert "Verify" in msg.subject
        assert "/auth/verify-email?token=" in msg.html
        assert "/auth/verify-email?token=" in msg.text

    def test_send_verification_email_swallows_send_errors(
        self, auth_service_with_verification, unverified_user
    ):
        mock_email = MagicMock(spec=EmailService)
        mock_email.send.side_effect = Exception("SMTP down")

        # Should not raise
        auth_service_with_verification.send_verification_email(
            unverified_user, mock_email, "https://spawnradar.com"
        )

    def test_send_verification_email_is_noop_without_token_repo(
        self, auth_service, unverified_user
    ):
        mock_email = MagicMock(spec=EmailService)
        # Should not raise and should not call send
        auth_service.send_verification_email(
            unverified_user, mock_email, "https://example.com"
        )
        mock_email.send.assert_not_called()

    def test_mark_google_user_verified(
        self, auth_service_with_verification, user_repo, unverified_user
    ):
        auth_service_with_verification.mark_google_user_verified(
            unverified_user.user_id
        )
        updated = user_repo.get_by_id(unverified_user.user_id)
        assert updated.email_verified is True

    def test_verification_link_uses_base_url(
        self, auth_service_with_verification, unverified_user
    ):
        sent: list[EmailMessage] = []
        mock_email = MagicMock(spec=EmailService)
        mock_email.send.side_effect = lambda msg: sent.append(msg)

        auth_service_with_verification.send_verification_email(
            unverified_user, mock_email, "https://myapp.example.com"
        )

        assert (
            "https://myapp.example.com/auth/verify-email?token="
            in sent[0].html
        )


# ===========================================================================
# Integration tests — HTTP layer
# ===========================================================================


class TestRegistrationFlow:
    def test_register_redirects_to_verify_pending(self, monkeypatch, tmp_path):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            token = _csrf_token(client, "/auth/register")
            response = client.post(
                "/auth/register",
                data={
                    "email": "new@example.com",
                    "password": "pass123",
                    "csrf_token": token,
                },
                follow_redirects=False,
            )
        assert response.status_code == 303
        assert response.headers["location"] == "/auth/verify-pending"

    def test_registered_user_is_unverified_in_db(self, monkeypatch, tmp_path):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "check@example.com")
        assert _is_email_verified(db_path, "check@example.com") is False

    def test_register_creates_verification_token(self, monkeypatch, tmp_path):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "tokencheck@example.com")
        token = _get_verification_token(db_path, "tokencheck@example.com")
        assert token is not None

    def test_unverified_user_can_access_games(self, monkeypatch, tmp_path):
        # Game routes are open to all users (including unverified and anonymous).
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "blocked@example.com")
            response = client.get("/games", follow_redirects=False)
        assert response.status_code == 200

    def test_unverified_user_sees_verify_pending_page(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "pending@example.com")
            response = client.get("/auth/verify-pending")
        assert response.status_code == 200
        assert "pending@example.com" in response.text
        assert "Check your inbox" in response.text

    def test_verified_user_redirected_away_from_verify_pending(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "done@example.com")
            with get_connection(db_path) as conn:
                conn.execute(
                    "UPDATE users SET email_verified = 1 WHERE email = 'done@example.com'"
                )
            response = client.get(
                "/auth/verify-pending", follow_redirects=False
            )
        assert response.status_code == 303
        assert response.headers["location"] == "/games"


class TestVerificationLink:
    def test_valid_token_verifies_user_and_redirects_to_games(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "click@example.com")
            token_id = _get_verification_token(db_path, "click@example.com")
            response = client.get(
                f"/auth/verify-email?token={token_id}", follow_redirects=False
            )

        assert response.status_code == 303
        assert response.headers["location"] == "/games"
        assert _is_email_verified(db_path, "click@example.com") is True

    def test_verified_user_can_access_games(self, monkeypatch, tmp_path):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "access@example.com")
            token_id = _get_verification_token(db_path, "access@example.com")
            client.get(f"/auth/verify-email?token={token_id}")
            response = client.get("/games")
        assert response.status_code == 200

    def test_invalid_token_redirects_to_verify_pending_with_error(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "badtoken@example.com")
            response = client.get(
                "/auth/verify-email?token=not-a-real-token",
                follow_redirects=False,
            )
        assert response.status_code == 303
        assert "error=invalid" in response.headers["location"]

    def test_missing_token_param_redirects_with_error(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "notoken@example.com")
            response = client.get("/auth/verify-email", follow_redirects=False)
        assert response.status_code == 303
        assert "error=invalid" in response.headers["location"]

    def test_token_is_single_use(self, monkeypatch, tmp_path):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "singleuse@example.com")
            token_id = _get_verification_token(
                db_path, "singleuse@example.com"
            )

            # First use succeeds
            r1 = client.get(
                f"/auth/verify-email?token={token_id}", follow_redirects=False
            )
            assert r1.headers["location"] == "/games"

            # Second use with the same token fails
            r2 = client.get(
                f"/auth/verify-email?token={token_id}", follow_redirects=False
            )
            assert "error=invalid" in r2.headers["location"]

    def test_expired_token_is_rejected(self, monkeypatch, tmp_path):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "expired@example.com")
            # Grab the real token id before expiring it
            real_token = _get_verification_token(
                db_path, "expired@example.com"
            )
            assert real_token is not None

            # Expire the token using SQLite-compatible format
            with get_connection(db_path) as conn:
                conn.execute(
                    "UPDATE email_verification_tokens SET expires_at = datetime('now', '-1 hour')"
                )

            # Confirm helper also sees it as gone
            assert (
                _get_verification_token(db_path, "expired@example.com") is None
            )

            response = client.get(
                f"/auth/verify-email?token={real_token}",
                follow_redirects=False,
            )
        assert "error=invalid" in response.headers["location"]
        assert _is_email_verified(db_path, "expired@example.com") is False

    def test_error_message_shown_on_invalid_token_page(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "showerr@example.com")
            # Follow redirect to the pending page with ?error=invalid
            response = client.get(
                "/auth/verify-email?token=bad", follow_redirects=True
            )
        assert "invalid or has expired" in response.text.lower()


class TestResendVerification:
    def test_resend_creates_new_token(self, monkeypatch, tmp_path):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "resend@example.com")

            response = client.get(
                "/auth/resend-verification", follow_redirects=False
            )
            assert response.status_code == 303

        # Two tokens should now exist (original from registration + one from resend)
        with get_connection(db_path) as conn:
            count = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM email_verification_tokens t
                JOIN users u ON u.user_id = t.user_id
                WHERE u.email = 'resend@example.com' AND t.used_at IS NULL
                """
            ).fetchone()["n"]
        assert count == 2

    def test_resend_redirects_already_verified_user_to_games(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "alreadydone@example.com")
            with get_connection(db_path) as conn:
                conn.execute(
                    "UPDATE users SET email_verified = 1 WHERE email = 'alreadydone@example.com'"
                )
            response = client.get(
                "/auth/resend-verification", follow_redirects=False
            )
        assert response.headers["location"] == "/games"

    def test_second_token_can_verify_user(self, monkeypatch, tmp_path):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "resend2@example.com")
            client.get("/auth/resend-verification")
            new_token = _get_verification_token(db_path, "resend2@example.com")
            r = client.get(
                f"/auth/verify-email?token={new_token}", follow_redirects=False
            )
        assert r.headers["location"] == "/games"
        assert _is_email_verified(db_path, "resend2@example.com") is True


class TestDevLogin:
    def test_dev_login_user_is_auto_verified(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / "dev-verify.sqlite3")
        monkeypatch.setenv("DB_PATH", db_path)
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("DEV_AUTO_LOGIN", "1")
        for key in (
            "PADDLE_API_KEY",
            "PADDLE_CLIENT_SIDE_TOKEN",
            "PADDLE_WEBHOOK_SECRET",
            "PADDLE_INDIE_PRICE_ID",
            "PADDLE_ENVIRONMENT",
            "RESEND_API_KEY",
        ):
            monkeypatch.setenv(key, "")

        with TestClient(create_app()) as client:
            client.get("/auth/dev-login")
            response = client.get("/games")

        assert response.status_code == 200

    def test_dev_login_does_not_redirect_to_verify_pending(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "dev-verify2.sqlite3")
        monkeypatch.setenv("DB_PATH", db_path)
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("DEV_AUTO_LOGIN", "1")
        for key in (
            "PADDLE_API_KEY",
            "PADDLE_CLIENT_SIDE_TOKEN",
            "PADDLE_WEBHOOK_SECRET",
            "PADDLE_INDIE_PRICE_ID",
            "PADDLE_ENVIRONMENT",
            "RESEND_API_KEY",
        ):
            monkeypatch.setenv(key, "")

        with TestClient(create_app()) as client:
            client.get("/auth/dev-login")
            response = client.get(
                "/auth/verify-pending", follow_redirects=False
            )

        # Verified dev user is bounced straight to /games
        assert response.status_code == 303
        assert response.headers["location"] == "/games"


class TestAbuseResistance:
    def test_one_email_one_trial(self, monkeypatch, tmp_path):
        """Re-registering with the same email fails — no second trial."""
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "onetime@example.com")
            token = _csrf_token(client, "/auth/register")
            response = client.post(
                "/auth/register",
                data={
                    "email": "onetime@example.com",
                    "password": "pass123",
                    "csrf_token": token,
                },
                follow_redirects=False,
            )
        # Should show an error, not create a second account
        assert response.status_code in (200, 400)
        assert "already exists" in response.text.lower()

    def test_gmail_dot_trick_is_normalized(self, monkeypatch, tmp_path):
        """m.e@gmail.com and me@gmail.com are the same account."""
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "me@gmail.com")
            token = _csrf_token(client, "/auth/register")
            response = client.post(
                "/auth/register",
                data={
                    "email": "m.e@gmail.com",
                    "password": "pass123",
                    "csrf_token": token,
                },
                follow_redirects=False,
            )
        assert response.status_code in (200, 400)
        assert "already exists" in response.text.lower()

    def test_gmail_plus_tag_is_normalized(self, monkeypatch, tmp_path):
        """me+trial@gmail.com and me@gmail.com are the same account."""
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            _register(client, "me@gmail.com")
            token = _csrf_token(client, "/auth/register")
            response = client.post(
                "/auth/register",
                data={
                    "email": "me+trial@gmail.com",
                    "password": "pass123",
                    "csrf_token": token,
                },
                follow_redirects=False,
            )
        assert response.status_code in (200, 400)
        assert "already exists" in response.text.lower()

    def test_unauthenticated_user_cannot_reach_verify_pending(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            response = client.get(
                "/auth/verify-pending", follow_redirects=False
            )
        # Should redirect to login, not crash
        assert response.status_code in (303, 307)
        assert "login" in response.headers["location"]

    def test_unauthenticated_user_cannot_reach_resend(
        self, monkeypatch, tmp_path
    ):
        client, db_path = _make_http_client(monkeypatch, tmp_path)
        with client:
            response = client.get(
                "/auth/resend-verification", follow_redirects=False
            )
        assert response.status_code in (303, 307)
        assert "login" in response.headers["location"]
