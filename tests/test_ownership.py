"""Tests for ownership context resolution."""

from app.ownership.service import OwnershipService


def test_public_request_has_limited_context(auth_service, billing_service):
    service = OwnershipService(auth_service, billing_service)

    context = service.get_context_for_session(None)

    assert context.actor is None
    assert context.subscription is None
    assert context.is_limited is True
    assert context.can_add_game is True
    assert context.game_limit == 1


def test_registered_user_context_reflects_paid_access(
    auth_service,
    billing_service,
    workspace_repo,
    registered_user,
):
    service = OwnershipService(auth_service, billing_service)
    workspace = workspace_repo.get_by_user(registered_user.user_id)
    assert workspace is not None
    billing_service.grant_comped_access(workspace.workspace_id)

    session = auth_service.create_session_for_user(registered_user.user_id)
    context = service.get_context_for_session(session.session_id)

    actor = context.require_actor()
    assert actor.user_id == registered_user.user_id
    assert context.subscription is not None
    assert context.is_limited is False
    assert context.can_access_workspace(workspace.workspace_id) is True


def test_create_guest_context_returns_guest_actor(
    auth_service,
    billing_service,
):
    service = OwnershipService(auth_service, billing_service)

    context, session = service.create_guest_context(
        first_path="/games/setup",
        first_referrer=None,
        first_user_agent="pytest",
    )

    actor = context.require_actor()
    assert actor.is_anonymous is True
    assert session.guest_id == actor.guest_id
    assert context.subscription is None
    assert context.is_limited is True
    assert context.can_access_workspace(actor.workspace_id) is True
