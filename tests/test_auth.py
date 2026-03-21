"""Tests for authentication: registration, login, sessions, logout."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.auth.models import Session, User


def test_register_creates_user_with_hashed_password(auth_service):
    user = auth_service.register("alice@example.com", "secret")
    assert isinstance(user, User)
    assert user.email == "alice@example.com"
    assert user.password_hash is not None
    # Password must not be stored in plaintext
    assert user.password_hash != "secret"
    assert user.password_hash.startswith(
        "$2b$"
    ) or user.password_hash.startswith("$2a$")


def test_login_returns_session(auth_service):
    auth_service.register("bob@example.com", "hunter2")
    session = auth_service.login("bob@example.com", "hunter2")
    assert isinstance(session, Session)
    assert session.session_id
    assert session.user_id


def test_login_with_wrong_password_raises_value_error(auth_service):
    auth_service.register("carol@example.com", "correct")
    with pytest.raises(ValueError, match="Invalid email or password"):
        auth_service.login("carol@example.com", "wrong")


def test_login_with_unknown_email_raises_value_error(auth_service):
    with pytest.raises(ValueError, match="Invalid email or password"):
        auth_service.login("nobody@example.com", "anypass")


def test_duplicate_email_raises_value_error(auth_service):
    auth_service.register("dave@example.com", "pass1")
    with pytest.raises(ValueError, match="already exists"):
        auth_service.register("dave@example.com", "pass2")


def test_session_expires_check_returns_none_for_past_expiry(
    session_repo, registered_user, auth_service
):
    # Create a session with an expiry in the past
    session_id = str(uuid.uuid4())
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    session_repo.create(session_id, registered_user.user_id, past)

    result = auth_service.get_session(session_id)
    assert result is None


def test_logout_deletes_session(auth_service):
    auth_service.register("eve@example.com", "pw")
    session = auth_service.login("eve@example.com", "pw")
    auth_service.logout(session.session_id)
    assert auth_service.get_session(session.session_id) is None


def test_get_session_returns_valid_session(auth_service):
    auth_service.register("frank@example.com", "pw")
    session = auth_service.login("frank@example.com", "pw")
    result = auth_service.get_session(session.session_id)
    assert result is not None
    assert result.session_id == session.session_id
