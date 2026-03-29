"""Durable storage for product analytics and Prometheus export facts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.database import get_connection
from app.json_codec import dump_json, load_json_object


@dataclass(frozen=True)
class MetricEvent:
    event_id: str
    metric_key: str
    user_id: str | None
    customer_game_id: str | None
    occurred_at: str
    value: float
    dedupe_key: str | None
    metadata: dict[str, object]


class MetricsRepository:
    """Persist append-only metrics and analytics facts.

    This stays separate from operational tables where necessary.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def record_metric_event(
        self,
        metric_key: str,
        *,
        user_id: str | None = None,
        customer_game_id: str | None = None,
        occurred_at: str,
        value: float = 1.0,
        dedupe_key: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> bool:
        """Insert a metric event, ignoring duplicates when dedupe_key matches."""
        event_id = str(uuid.uuid4())
        cursor = None
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO metric_events
                    (event_id, metric_key, user_id, customer_game_id, occurred_at, value,
                     dedupe_key, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    metric_key,
                    user_id,
                    customer_game_id,
                    occurred_at,
                    value,
                    dedupe_key,
                    dump_json(metadata or {}),
                ),
            )
        return bool(cursor and cursor.rowcount)

    def list_metric_events(self, metric_key: str) -> list[MetricEvent]:
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM metric_events
                WHERE metric_key = ?
                ORDER BY occurred_at ASC
                """,
                (metric_key,),
            ).fetchall()
        return [
            MetricEvent(
                event_id=row["event_id"],
                metric_key=row["metric_key"],
                user_id=row["user_id"],
                customer_game_id=row["customer_game_id"],
                occurred_at=row["occurred_at"],
                value=float(row["value"]),
                dedupe_key=row["dedupe_key"],
                metadata=load_json_object(row["metadata"]),
            )
            for row in rows
        ]

    def metric_totals(self) -> dict[str, float]:
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT metric_key, COALESCE(SUM(value), 0) AS total
                FROM metric_events
                GROUP BY metric_key
                """
            ).fetchall()
        return {str(row["metric_key"]): float(row["total"]) for row in rows}

    def first_metric_time_by_user(self, metric_key: str) -> dict[str, str]:
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT user_id, MIN(occurred_at) AS first_occurred_at
                FROM metric_events
                WHERE metric_key = ? AND user_id IS NOT NULL
                GROUP BY user_id
                """,
                (metric_key,),
            ).fetchall()
        return {
            str(row["user_id"]): str(row["first_occurred_at"])
            for row in rows
            if row["user_id"] is not None
            and row["first_occurred_at"] is not None
        }

    def has_metric_event_for_user_before(
        self, metric_key: str, user_id: str, occurred_before: str
    ) -> bool:
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM metric_events
                WHERE metric_key = ?
                  AND user_id = ?
                  AND occurred_at <= ?
                LIMIT 1
                """,
                (metric_key, user_id, occurred_before),
            ).fetchone()
        return row is not None
