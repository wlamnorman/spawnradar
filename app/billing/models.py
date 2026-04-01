"""Billing domain models: subscriptions and tier limits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class Tier(StrEnum):
    """Available subscription tiers."""

    INDIE = "indie"


TIER_LIMITS: dict[Tier, dict[str, int]] = {
    Tier.INDIE: {
        "games": 3,
    },
}

FREE_LIMITS: dict[str, int] = {
    "games": 1,
}

TIER_PRICES: dict[Tier, int] = {
    Tier.INDIE: 19,
}

PUBLIC_TIERS: list[Tier] = [Tier.INDIE]


@dataclass(frozen=True)
class Subscription:
    """A developer's active subscription record."""

    subscription_id: str
    user_id: str
    paddle_customer_id: str | None
    paddle_subscription_id: str | None
    tier: Tier
    status: str  # active | canceled | past_due | paused | comped
    current_period_end: str | None
    created_at: str
    updated_at: str

    @property
    def has_subscription(self) -> bool:
        """Return True if the user has an active paid Paddle subscription."""
        return bool(self.paddle_subscription_id)

    @property
    def is_comped(self) -> bool:
        """Return True for manually granted complimentary access."""
        return self.status == "comped"

    @property
    def has_access(self) -> bool:
        """Return True if the user has active paid or complimentary access."""
        if self.is_comped:
            return True
        if not self.has_subscription:
            return False
        if self.status not in {"active", "canceled"}:
            return False
        if self.current_period_end is None:
            return self.status == "active"
        return datetime.fromisoformat(self.current_period_end) > datetime.now(
            UTC
        )

    @property
    def effective_tier(self) -> Tier:
        """Return the active product tier."""
        return self.tier
