"""Tests for anonymous user flows."""

import pytest

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
