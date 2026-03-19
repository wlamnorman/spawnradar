"""Database operations for subscriptions."""

from __future__ import annotations

from typing import Any

from app.billing.models import Subscription, Tier
from app.database import get_connection


class SubscriptionRepository:
    """CRUD operations for the subscriptions table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def get_by_user(self, user_id: str) -> Subscription | None:
        """Fetch the active subscription for a user."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_subscription(row)

    def create(
        self,
        subscription_id: str,
        user_id: str,
        tier: Tier = Tier.STARTER,
        trial_days: int = 7,
    ) -> Subscription:
        """Create a new subscription for a user."""
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC).isoformat()
        trial_ends_at = (
            datetime.now(UTC) + timedelta(days=trial_days)
        ).isoformat()
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO subscriptions
                    (subscription_id, user_id, tier, status, trial_ends_at, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    subscription_id,
                    user_id,
                    tier.value,
                    trial_ends_at,
                    now,
                    now,
                ),
            )
        return self.get_by_user(user_id)  # type: ignore[return-value]

    def update_from_stripe(
        self,
        user_id: str,
        *,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        tier: Tier | None = None,
        status: str | None = None,
        current_period_end: str | None = None,
    ) -> None:
        """Update subscription fields from a Stripe webhook event."""
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        sub = self.get_by_user(user_id)
        if sub is None:
            return

        new_customer_id = (
            stripe_customer_id
            if stripe_customer_id is not None
            else sub.stripe_customer_id
        )
        new_sub_id = (
            stripe_subscription_id
            if stripe_subscription_id is not None
            else sub.stripe_subscription_id
        )
        new_tier = tier.value if tier is not None else sub.tier.value
        new_status = status if status is not None else sub.status
        new_period_end = (
            current_period_end
            if current_period_end is not None
            else sub.current_period_end
        )
        preserved_trial_ends_at = sub.trial_ends_at

        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE subscriptions
                SET stripe_customer_id = ?, stripe_subscription_id = ?,
                    tier = ?, status = ?, current_period_end = ?, trial_ends_at = ?, updated_at = ?
                WHERE subscription_id = ?
                """,
                (
                    new_customer_id,
                    new_sub_id,
                    new_tier,
                    new_status,
                    new_period_end,
                    preserved_trial_ends_at,
                    now,
                    sub.subscription_id,
                ),
            )


def _row_to_subscription(row: Any) -> Subscription:
    return Subscription(
        subscription_id=row["subscription_id"],
        user_id=row["user_id"],
        stripe_customer_id=row["stripe_customer_id"],
        stripe_subscription_id=row["stripe_subscription_id"],
        tier=Tier(row["tier"]),
        status=row["status"],
        current_period_end=row["current_period_end"],
        trial_ends_at=row["trial_ends_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
