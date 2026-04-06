"""Ownership context for guest/user workspace resolution."""

from __future__ import annotations

from dataclasses import dataclass

from app.auth.models import Actor, Session
from app.auth.service import AuthService
from app.billing.models import FREE_LIMITS, TIER_LIMITS, Subscription
from app.billing.service import BillingService


@dataclass(frozen=True)
class OwnershipContext:
    """Resolved request ownership state for product routes."""

    actor: Actor | None
    subscription: Subscription | None
    can_add_game: bool
    is_limited: bool
    game_limit: int

    @property
    def workspace_id(self) -> str | None:
        actor = self.actor
        return actor.workspace_id if actor is not None else None

    @property
    def is_anonymous(self) -> bool:
        actor = self.actor
        return bool(actor is not None and actor.is_anonymous)

    @property
    def is_authenticated(self) -> bool:
        actor = self.actor
        return bool(actor is not None and actor.is_authenticated)

    def require_actor(self) -> Actor:
        """Return the current actor, raising if the context is public-only."""
        actor = self.actor
        if actor is None:
            raise RuntimeError("OwnershipContext has no actor.")
        return actor

    def can_access_workspace(self, workspace_id: str) -> bool:
        """Return whether the current actor can operate on a workspace."""
        actor = self.actor
        if actor is None:
            return False
        return actor.is_admin or actor.workspace_id == workspace_id


class OwnershipService:
    """Resolve actor/workspace/subscription state for request handling."""

    def __init__(
        self,
        auth_service: AuthService,
        billing_service: BillingService,
    ) -> None:
        self._auth = auth_service
        self._billing = billing_service

    def get_context_for_session(
        self, session_id: str | None
    ) -> OwnershipContext:
        """Resolve the current ownership context for a browser session."""
        if session_id is None:
            return self.get_context_for_actor(None)
        return self.get_context_for_actor(
            self._auth.get_actor_for_session(session_id)
        )

    def get_context_for_actor(self, actor: Actor | None) -> OwnershipContext:
        """Resolve product access facts for an actor or public request."""
        if actor is None:
            return OwnershipContext(
                actor=None,
                subscription=None,
                can_add_game=True,
                is_limited=True,
                game_limit=FREE_LIMITS["games"],
            )

        subscription = self._billing.get_subscription_for_workspace(
            actor.workspace_id
        )
        is_limited = subscription is None or not subscription.has_access
        if is_limited:
            game_limit = FREE_LIMITS["games"]
        else:
            assert subscription is not None
            game_limit = TIER_LIMITS[subscription.effective_tier]["games"]
        return OwnershipContext(
            actor=actor,
            subscription=subscription,
            can_add_game=self._billing.check_game_limit_for_workspace(
                actor.workspace_id
            ),
            is_limited=is_limited,
            game_limit=game_limit,
        )

    def create_guest_context(
        self,
        *,
        first_path: str | None,
        first_referrer: str | None,
        first_user_agent: str | None,
    ) -> tuple[OwnershipContext, Session]:
        """Create a durable guest actor and return its resolved context."""
        actor, session = self._auth.create_guest_actor(
            first_path=first_path,
            first_referrer=first_referrer,
            first_user_agent=first_user_agent,
        )
        return self.get_context_for_actor(actor), session
