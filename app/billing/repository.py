"""Database operations for subscriptions and billing usage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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

    def get_by_paddle_customer(
        self, paddle_customer_id: str
    ) -> Subscription | None:
        """Fetch a subscription by Paddle customer ID."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE paddle_customer_id = ? LIMIT 1",
                (paddle_customer_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_subscription(row)

    def create(
        self,
        subscription_id: str,
        user_id: str,
        tier: Tier = Tier.INDIE,
        trial_days: int = 3,
    ) -> Subscription:
        """Create a new subscription with an active trial period."""
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

    def update_from_paddle(
        self,
        user_id: str,
        *,
        paddle_customer_id: str | None = None,
        paddle_subscription_id: str | None = None,
        tier: Tier | None = None,
        status: str | None = None,
        current_period_end: str | None = None,
    ) -> None:
        """Update subscription fields from a Paddle webhook event."""
        sub = self.get_by_user(user_id)
        if sub is None:
            return

        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE subscriptions
                SET paddle_customer_id = ?, paddle_subscription_id = ?,
                    tier = ?, status = ?, current_period_end = ?,
                    trial_ends_at = ?, updated_at = ?
                WHERE subscription_id = ?
                """,
                (
                    paddle_customer_id
                    if paddle_customer_id is not None
                    else sub.paddle_customer_id,
                    paddle_subscription_id
                    if paddle_subscription_id is not None
                    else sub.paddle_subscription_id,
                    tier.value if tier is not None else sub.tier.value,
                    status if status is not None else sub.status,
                    current_period_end
                    if current_period_end is not None
                    else sub.current_period_end,
                    sub.trial_ends_at,
                    datetime.now(UTC).isoformat(),
                    sub.subscription_id,
                ),
            )

    def grant_comped_access(
        self, user_id: str, tier: Tier = Tier.INDIE
    ) -> Subscription | None:
        """Grant complimentary access without a Paddle subscription."""
        sub = self.get_by_user(user_id)
        now = datetime.now(UTC).isoformat()

        with get_connection(self._db_path) as conn:
            if sub is None:
                conn.execute(
                    """
                    INSERT INTO subscriptions
                        (subscription_id, user_id, tier, status, trial_ends_at, current_period_end, created_at, updated_at)
                    VALUES (?, ?, ?, 'comped', NULL, NULL, ?, ?)
                    """,
                    (
                        f"comped_{user_id}",
                        user_id,
                        tier.value,
                        now,
                        now,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET paddle_subscription_id = NULL,
                        tier = ?,
                        status = 'comped',
                        trial_ends_at = NULL,
                        current_period_end = NULL,
                        updated_at = ?
                    WHERE subscription_id = ?
                    """,
                    (tier.value, now, sub.subscription_id),
                )

        return self.get_by_user(user_id)


class DiscoveryRunRepository:
    """Tracks monthly discovery run usage for billing enforcement."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def create(
        self,
        run_id: str,
        user_id: str,
        game_id: str,
        *,
        created_at: str | None = None,
    ) -> None:
        timestamp = created_at or datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO discovery_runs (run_id, user_id, game_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, user_id, game_id, timestamp),
            )

    def count_for_user_since(self, user_id: str, since: str) -> int:
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS run_count
                FROM discovery_runs
                WHERE user_id = ? AND created_at >= ?
                """,
                (user_id, since),
            ).fetchone()
        return int(row["run_count"]) if row is not None else 0


def _row_to_subscription(row: Any) -> Subscription:
    return Subscription(
        subscription_id=row["subscription_id"],
        user_id=row["user_id"],
        paddle_customer_id=row["paddle_customer_id"],
        paddle_subscription_id=row["paddle_subscription_id"],
        tier=_coerce_tier(row["tier"]),
        status=row["status"],
        current_period_end=row["current_period_end"],
        trial_ends_at=row["trial_ends_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _coerce_tier(value: Any) -> Tier:
    """Map legacy plan values onto the single supported tier."""
    if value == Tier.INDIE.value:
        return Tier.INDIE
    return Tier.INDIE
