"""Tests for guest identity and claim flows."""

import asyncio
import uuid
from unittest.mock import MagicMock

from app.auth.dependencies import get_current_actor, get_or_create_guest_actor
from app.billing.models import Tier


def test_regular_user_is_not_anonymous(user_repo):
    """Default user creation still produces a real authenticated account."""
    user = user_repo.create("reg-001", "dev@example.com", password_hash="hash")
    assert user.is_anonymous is False


def test_create_guest_actor_returns_actor_and_session(auth_service, guest_repo):
    """Guest creation produces a durable guest identity plus a guest session."""
    actor, session = auth_service.create_guest_actor(
        first_path="/games/setup",
        first_referrer="https://example.com",
        first_user_agent="pytest",
    )

    assert actor.is_anonymous is True
    assert actor.user_id is None
    assert actor.guest_id is not None
    assert session.user_id is None
    assert session.guest_id == actor.guest_id

    guest = guest_repo.get_by_id(actor.guest_id)
    assert guest is not None
    assert guest.first_path == "/games/setup"
    assert guest.first_referrer == "https://example.com"
    assert guest.first_user_agent == "pytest"


def test_get_current_actor_returns_existing_user_for_valid_session(
    auth_service, registered_user
):
    """A real user session resolves to an authenticated actor."""
    session = auth_service.create_session_for_user(registered_user.user_id)

    actor = asyncio.run(
        get_current_actor(
            session_id=session.session_id,
            auth_service=auth_service,
        )
    )

    assert actor is not None
    assert actor.user_id == registered_user.user_id
    assert actor.is_authenticated is True
    assert actor.is_anonymous is False


def test_dependency_creates_guest_actor_when_no_session(auth_service):
    """Meaningful writes can materialize a durable guest and set a cookie."""
    mock_request = MagicMock()
    mock_request.state = MagicMock(spec=[])
    mock_request.url = MagicMock(path="/games/setup")
    mock_request.headers = {
        "referer": "https://example.com/pricing",
        "user-agent": "pytest-agent",
    }

    actor = asyncio.run(
        get_or_create_guest_actor(
            request=mock_request,
            actor=None,
            auth_service=auth_service,
        )
    )

    assert actor.is_anonymous is True
    assert hasattr(mock_request.state, "new_session_id")
    session = auth_service.get_session(mock_request.state.new_session_id)
    assert session is not None
    assert session.guest_id == actor.guest_id


def test_transfer_game_workspace(game_repo, auth_service, user_repo):
    """Workspace transfer moves guest-owned games into a real account workspace."""
    guest_actor, _ = auth_service.create_guest_actor(
        first_path="/games/setup",
        first_referrer=None,
        first_user_agent="pytest",
    )
    real = user_repo.create("real-x", "real@example.com", password_hash="hash")
    real_workspace = auth_service.get_or_create_workspace_for_user(real.user_id)

    game_repo.create(
        customer_game_id="game-1",
        workspace_id=guest_actor.workspace_id,
        name="Test Game",
        summary=None,
        description="A test game",
        website_url=None,
    )

    count = game_repo.transfer_workspace(
        guest_actor.workspace_id,
        real_workspace.workspace_id,
    )

    assert count == 1
    transferred = game_repo.get_by_id("game-1")
    assert transferred is not None
    assert transferred.workspace_id == real_workspace.workspace_id


def test_claim_guest_workspace_transfers_and_cleans_up(
    auth_service,
    user_repo,
    game_repo,
    sub_repo,
    guest_repo,
):
    """Claiming a guest transfers durable product state into the real account."""
    guest_actor, guest_session = auth_service.create_guest_actor(
        first_path="/games/setup",
        first_referrer=None,
        first_user_agent="pytest",
    )
    game_repo.create(
        customer_game_id="game-claim",
        workspace_id=guest_actor.workspace_id,
        name="Claim Test",
        summary=None,
        description="A claimable game",
        website_url=None,
    )
    sub_repo.create(str(uuid.uuid4()), guest_actor.workspace_id, Tier.INDIE)

    real_user = user_repo.create(
        "real-claim",
        "claim@example.com",
        password_hash="hash",
    )
    real_workspace = auth_service.get_or_create_workspace_for_user(
        real_user.user_id
    )

    count = auth_service.claim_guest_workspace(
        str(guest_actor.guest_id),
        real_user.user_id,
    )

    assert count == 1
    game = game_repo.get_by_id("game-claim")
    assert game is not None
    assert game.workspace_id == real_workspace.workspace_id
    assert sub_repo.get_by_workspace(real_workspace.workspace_id) is not None
    assert sub_repo.get_by_workspace(guest_actor.workspace_id) is None
    assert auth_service.get_session(guest_session.session_id) is None

    guest = guest_repo.get_by_id(str(guest_actor.guest_id))
    assert guest is not None
    assert guest.claimed_by_user_id == real_user.user_id
