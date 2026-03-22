"""Billing domain models: subscriptions and tier limits."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

TRIAL_DAYS = 3
DISCOVERY_RUNS_PER_HOUR = 3
DISCOVERY_RUNS_PER_DAY = 5


class Tier(StrEnum):
    """Available subscription tiers."""

    INDIE = "indie"


TIER_LIMITS: dict[Tier, dict[str, int]] = {
    Tier.INDIE: {
        "games": 3,
        "prospects_per_run": 50,
        "discovery_runs_per_month": 20,
    },
}

TRIAL_LIMITS: dict[str, int] = {
    "games": 1,
    "prospects_per_run": 50,
    "discovery_runs_per_month": 3,
}
EXPIRED_LIMITS: dict[str, int] = {
    "games": 0,
    "prospects_per_run": 0,
    "discovery_runs_per_month": 0,
}

TIER_PRICES: dict[Tier, int] = {
    Tier.INDIE: 20,
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
    status: str  # active | canceled | past_due | paused | trialing | comped
    current_period_end: str | None
    trial_ends_at: str | None
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
        if self.status not in {"active", "trialing", "canceled"}:
            return False
        if self.current_period_end is None:
            return self.status in {"active", "trialing"}
        return datetime.fromisoformat(self.current_period_end) > datetime.now(UTC)

    @property
    def has_product_access(self) -> bool:
        """Return True if the user can use the product right now."""
        return self.has_access or self.is_trialing

    @property
    def is_trialing(self) -> bool:
        """Return True if the user is within an Indie trial period."""
        if self.has_subscription:
            return False
        if self.trial_ends_at is None:
            return False
        return datetime.fromisoformat(self.trial_ends_at) > datetime.now(UTC)

    @property
    def effective_tier(self) -> Tier:
        """Return the active product tier."""
        return self.tier

    @property
    def trial_days_remaining(self) -> int | None:
        """Days left in trial, or None if not trialing."""
        if not self.is_trialing or self.trial_ends_at is None:
            return None
        delta = datetime.fromisoformat(self.trial_ends_at) - datetime.now(UTC)
        return max(0, math.ceil(delta.total_seconds() / 86400))
