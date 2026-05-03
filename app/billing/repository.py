"""Database operations for subscriptions."""

from __future__ import annotations

import sqlite3
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from app.billing.models import Subscription, Tier
from app.database import get_connection


class SubscriptionRepository:
    """CRUD operations for the subscriptions table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def get_by_workspace(self, workspace_id: str) -> Subscription | None:
        """Fetch the active subscription for a workspace."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT *
                FROM subscriptions
                WHERE workspace_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_subscription(row)

    def get_by_user(self, user_id: str) -> Subscription | None:
        """Fetch the active subscription for a registered user's workspace."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT s.*
                FROM subscriptions s
                JOIN workspaces w ON w.workspace_id = s.workspace_id
                WHERE w.owner_user_id = ?
                ORDER BY s.created_at DESC
                LIMIT 1
                """,
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

    def list_all(self) -> list[Subscription]:
        """Return all subscriptions ordered by creation time."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM subscriptions ORDER BY created_at ASC"
            ).fetchall()
        return [_row_to_subscription(row) for row in rows]

    def create(
        self,
        subscription_id: str,
        workspace_id: str,
        tier: Tier = Tier.INDIE,
    ) -> Subscription:
        """Create a new subscription row."""
        now = datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO subscriptions
                    (subscription_id, workspace_id, tier, status, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                """,
                (
                    subscription_id,
                    workspace_id,
                    tier.value,
                    now,
                    now,
                ),
            )
        return self.get_by_workspace(workspace_id)  # type: ignore[return-value]

    def update_from_paddle(
        self,
        workspace_id: str,
        *,
        paddle_customer_id: str | None = None,
        paddle_subscription_id: str | None = None,
        tier: Tier | None = None,
        status: str | None = None,
        current_period_end: str | None = None,
    ) -> None:
        """Update subscription fields from a Paddle webhook event.

        If no subscription row exists for the user yet (e.g. the webhook
        arrived before any other action created the row), one is created first.
        If the user does not exist (FK violation) the upsert is skipped silently.
        """

        sub = self.get_by_workspace(workspace_id)
        if sub is None:
            try:
                self.create(
                    _uuid.uuid4().hex, workspace_id, tier or Tier.INDIE
                )
            except sqlite3.IntegrityError:
                return
            sub = self.get_by_workspace(workspace_id)
        if sub is None:
            return

        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE subscriptions
                SET paddle_customer_id = ?, paddle_subscription_id = ?,
                    tier = ?, status = ?, current_period_end = ?,
                    updated_at = ?
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
                    datetime.now(UTC).isoformat(),
                    sub.subscription_id,
                ),
            )

    def delete_by_workspace(self, workspace_id: str) -> None:
        """Delete all subscriptions for a workspace."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                "DELETE FROM subscriptions WHERE workspace_id = ?",
                (workspace_id,),
            )

    def delete_by_user(self, user_id: str) -> None:
        """Delete all subscriptions for a registered user's workspace."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                DELETE FROM subscriptions
                WHERE workspace_id IN (
                    SELECT workspace_id FROM workspaces WHERE owner_user_id = ?
                )
                """,
                (user_id,),
            )

    def grant_comped_access(
        self, workspace_id: str, tier: Tier = Tier.INDIE
    ) -> Subscription | None:
        """Grant complimentary access without a Paddle subscription."""
        sub = self.get_by_workspace(workspace_id)
        now = datetime.now(UTC).isoformat()

        with get_connection(self._db_path) as conn:
            if sub is None:
                conn.execute(
                    """
                    INSERT INTO subscriptions
                        (subscription_id, workspace_id, tier, status, current_period_end, created_at, updated_at)
                    VALUES (?, ?, ?, 'comped', NULL, ?, ?)
                    """,
                    (
                        f"comped_{workspace_id}",
                        workspace_id,
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
                        current_period_end = NULL,
                        updated_at = ?
                    WHERE subscription_id = ?
                    """,
                    (tier.value, now, sub.subscription_id),
                )

        return self.get_by_workspace(workspace_id)

    def transfer_to_workspace(
        self, from_workspace_id: str, to_workspace_id: str
    ) -> None:
        """Merge or move subscriptions from one workspace to another."""
        source = self.get_by_workspace(from_workspace_id)
        if source is None:
            return
        target = self.get_by_workspace(to_workspace_id)
        with get_connection(self._db_path) as conn:
            if target is None:
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET workspace_id = ?, updated_at = ?
                    WHERE workspace_id = ?
                    """,
                    (
                        to_workspace_id,
                        datetime.now(UTC).isoformat(),
                        from_workspace_id,
                    ),
                )
                return

            source_better = source.has_access and not target.has_access
            if source_better:
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET paddle_customer_id = ?, paddle_subscription_id = ?,
                        tier = ?, status = ?, current_period_end = ?, updated_at = ?
                    WHERE subscription_id = ?
                    """,
                    (
                        source.paddle_customer_id,
                        source.paddle_subscription_id,
                        source.tier.value,
                        source.status,
                        source.current_period_end,
                        datetime.now(UTC).isoformat(),
                        target.subscription_id,
                    ),
                )
            conn.execute(
                "DELETE FROM subscriptions WHERE workspace_id = ?",
                (from_workspace_id,),
            )


def _row_to_subscription(row: Any) -> Subscription:
    return Subscription(
        subscription_id=row["subscription_id"],
        workspace_id=row["workspace_id"],
        paddle_customer_id=row["paddle_customer_id"],
        paddle_subscription_id=row["paddle_subscription_id"],
        tier=_coerce_tier(row["tier"]),
        status=row["status"],
        current_period_end=row["current_period_end"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _coerce_tier(value: Any) -> Tier:
    """Normalize persisted tier values onto the single supported tier."""
    if value == Tier.INDIE.value:
        return Tier.INDIE
    return Tier.INDIE
