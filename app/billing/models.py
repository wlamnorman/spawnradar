"""Billing domain models: subscriptions and tier limits."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

TRIAL_DAYS = 3


class Tier(StrEnum):
    """Available subscription tiers."""

    STARTER = "starter"
    PRO = "pro"


TIER_LIMITS: dict[Tier, dict[str, int]] = {
    Tier.STARTER: {"games": 1, "prospects_per_run": 50},
    Tier.PRO: {"games": 5, "prospects_per_run": 500},
}

TIER_PRICES: dict[Tier, int] = {
    Tier.STARTER: 10,
    Tier.PRO: 25,
}

PUBLIC_TIERS: list[Tier] = [Tier.STARTER, Tier.PRO]


@dataclass(frozen=True)
class Subscription:
    """A developer's active subscription record."""

    subscription_id: str
    user_id: str
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    tier: Tier
    status: str  # active | cancelled | past_due
    current_period_end: str | None
    trial_ends_at: str | None
    created_at: str
    updated_at: str

    @property
    def is_trialing(self) -> bool:
        from datetime import UTC, datetime

        if self.trial_ends_at is None:
            return False
        if self.tier == Tier.PRO:
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
        import math
        from datetime import UTC, datetime

        delta = datetime.fromisoformat(self.trial_ends_at) - datetime.now(UTC)
        return max(0, math.ceil(delta.total_seconds() / 86400))
