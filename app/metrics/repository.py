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
    game_id: str | None
    occurred_at: str
    value: float
    dedupe_key: str | None
    metadata: dict[str, object]


@dataclass(frozen=True)
class DiscoveryRunFact:
    run_id: str
    user_id: str
    game_id: str
    started_at: str
    completed_at: str | None
    status: str
    discovered_count: int
    scored_count: int
    queued_count: int
    error_message: str | None


@dataclass(frozen=True)
class ProspectScoreObservation:
    observation_id: str
    run_id: str
    user_id: str
    game_id: str
    score: float
    queued: bool
    occurred_at: str


class MetricsRepository:
    """Persist append-only metrics and analytics facts.

    This stays separate from operational tables where necessary. In particular,
    discovery run facts live outside the billing `discovery_runs` table because
    the billing table cascades on user/game deletion, while analytics needs a
    stable history for long-term reporting.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def record_metric_event(
        self,
        metric_key: str,
        *,
        user_id: str | None = None,
        game_id: str | None = None,
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
                    (event_id, metric_key, user_id, game_id, occurred_at, value,
                     dedupe_key, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    metric_key,
                    user_id,
                    game_id,
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
                game_id=row["game_id"],
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

    def create_discovery_run_fact(
        self, run_id: str, user_id: str, game_id: str, *, started_at: str
    ) -> None:
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO discovery_run_facts
                    (run_id, user_id, game_id, started_at, status)
                VALUES (?, ?, ?, ?, 'started')
                """,
                (run_id, user_id, game_id, started_at),
            )

    def complete_discovery_run_fact(
        self,
        run_id: str,
        *,
        completed_at: str,
        discovered_count: int,
        scored_count: int,
        queued_count: int,
    ) -> None:
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE discovery_run_facts
                SET completed_at = ?,
                    status = 'completed',
                    discovered_count = ?,
                    scored_count = ?,
                    queued_count = ?,
                    error_message = NULL
                WHERE run_id = ?
                """,
                (
                    completed_at,
                    discovered_count,
                    scored_count,
                    queued_count,
                    run_id,
                ),
            )

    def fail_discovery_run_fact(
        self, run_id: str, *, failed_at: str, error_message: str
    ) -> None:
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE discovery_run_facts
                SET completed_at = ?,
                    status = 'failed',
                    error_message = ?
                WHERE run_id = ?
                """,
                (failed_at, error_message, run_id),
            )

    def list_discovery_run_facts(self) -> list[DiscoveryRunFact]:
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM discovery_run_facts
                ORDER BY started_at ASC
                """
            ).fetchall()
        return [
            DiscoveryRunFact(
                run_id=row["run_id"],
                user_id=row["user_id"],
                game_id=row["game_id"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                status=row["status"],
                discovered_count=int(row["discovered_count"]),
                scored_count=int(row["scored_count"]),
                queued_count=int(row["queued_count"]),
                error_message=row["error_message"],
            )
            for row in rows
        ]

    def first_discovery_run_start_by_user(self) -> dict[str, str]:
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT user_id, MIN(started_at) AS first_started_at
                FROM discovery_run_facts
                GROUP BY user_id
                """
            ).fetchall()
        return {
            str(row["user_id"]): str(row["first_started_at"])
            for row in rows
            if row["user_id"] is not None
            and row["first_started_at"] is not None
        }

    def record_prospect_score_observation(
        self,
        run_id: str,
        *,
        user_id: str,
        game_id: str,
        score: float,
        queued: bool,
        occurred_at: str,
    ) -> None:
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO prospect_score_observations
                    (observation_id, run_id, user_id, game_id, score, queued, occurred_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    run_id,
                    user_id,
                    game_id,
                    score,
                    int(queued),
                    occurred_at,
                ),
            )

    def list_prospect_score_observations(
        self,
    ) -> list[ProspectScoreObservation]:
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM prospect_score_observations
                ORDER BY occurred_at ASC
                """
            ).fetchall()
        return [
            ProspectScoreObservation(
                observation_id=row["observation_id"],
                run_id=row["run_id"],
                user_id=row["user_id"],
                game_id=row["game_id"],
                score=float(row["score"]),
                queued=bool(row["queued"]),
                occurred_at=row["occurred_at"],
            )
            for row in rows
        ]
