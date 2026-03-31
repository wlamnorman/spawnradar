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


def test_transfer_game_ownership(game_repo, user_repo):
    """transfer_ownership moves a game from one user to another."""
    anon = user_repo.create("anon-x", "anon-x@anonymous.local", password_hash=None, is_anonymous=True)
    real = user_repo.create("real-x", "real@example.com", password_hash="hash")
    game = game_repo.create(
        customer_game_id="game-1", user_id=anon.user_id, name="Test Game",
        summary=None, description="A test game", website_url=None,
    )
    count = game_repo.transfer_ownership(anon.user_id, real.user_id)
    assert count == 1
    transferred = game_repo.get_by_id("game-1")
    assert transferred.user_id == real.user_id


def test_claim_anonymous_games_transfers_and_cleans_up(auth_service, user_repo, game_repo, sub_repo):
    """claim_anonymous_games transfers games and deletes the anonymous user."""
    anon_user, anon_session = auth_service.create_anonymous_user()
    game = game_repo.create(
        customer_game_id="game-claim", user_id=anon_user.user_id,
        name="Claim Test", summary=None, description="A claimable game", website_url=None,
    )
    real_user = user_repo.create("real-claim", "claim@example.com", password_hash="hash")
    count = auth_service.claim_anonymous_games(anon_user.user_id, real_user.user_id)
    assert count == 1
    assert game_repo.get_by_id("game-claim").user_id == real_user.user_id
    assert user_repo.get_by_id(anon_user.user_id) is None
