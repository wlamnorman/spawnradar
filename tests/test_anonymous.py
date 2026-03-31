"""Tests for anonymous user flows."""

import asyncio

import pytest
from fastapi import Response
from unittest.mock import MagicMock

from app.auth.dependencies import require_user_or_anonymous
from app.auth.models import User


def test_create_anonymous_user_sets_flag(user_repo):
    """UserRepository.create with is_anonymous=True stores the flag."""
    user = user_repo.create(
        "anon-001", "anon-001@anonymous.local",
        password_hash=None, is_anonymous=True,
    )
    assert user.is_anonymous is True


def test_regular_user_is_not_anonymous(user_repo):
    """Default user creation has is_anonymous=False."""
    user = user_repo.create("reg-001", "dev@example.com", password_hash="hash")
    assert user.is_anonymous is False


def test_create_anonymous_user_returns_user_and_session(auth_service):
    """create_anonymous_user returns a (User, Session) tuple."""
    user, session = auth_service.create_anonymous_user()
    assert user.is_anonymous is True
    assert session.user_id == user.user_id


def test_anonymous_user_email_uses_full_user_id(auth_service):
    """Anonymous email uses the full user_id for uniqueness."""
    user, _ = auth_service.create_anonymous_user()
    assert user.email == f"{user.user_id}@anonymous.local"


def test_anonymous_user_has_no_password(auth_service):
    """Anonymous users have no password hash."""
    user, _ = auth_service.create_anonymous_user()
    assert user.password_hash is None


def test_dependency_returns_existing_user_for_valid_session(auth_service, registered_user):
    """If session cookie maps to a real user, return that user."""
    session = auth_service.create_session_for_user(registered_user.user_id)
    response = Response()
    settings = MagicMock(base_url="http://localhost:8000")
    user = asyncio.run(require_user_or_anonymous(
        request=MagicMock(),
        response=response,
        session_id=session.session_id,
        auth_service=auth_service,
        settings=settings,
    ))
    assert user.user_id == registered_user.user_id
    assert user.is_anonymous is False


def test_dependency_creates_anonymous_user_when_no_session(auth_service):
    """If no session cookie, create anonymous user and set cookie on response."""
    response = Response()
    settings = MagicMock(base_url="http://localhost:8000")
    user = asyncio.run(require_user_or_anonymous(
        request=MagicMock(),
        response=response,
        session_id=None,
        auth_service=auth_service,
        settings=settings,
    ))
    assert user.is_anonymous is True
    assert "session_id" in response.headers.get("set-cookie", "")
