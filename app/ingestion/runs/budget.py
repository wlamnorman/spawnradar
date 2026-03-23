"""Per-run discovery budgeting and queue insertion rules."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.database import get_connection

_LLM_SCORE_CAP = 60
_QUEUE_EVALUATION_BUFFER = 4
_LLM_SCORE_BUFFER = 6


@dataclass
class RunQueueBudget:
    """Shared per-run budget for new queue inserts and evaluation work."""

    queue_cap: int
    inserted_new_count: int = 0
    reserved_evaluation_count: int = 0
    llm_attempted_count: int = 0
    reserved_llm_count: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)

    def should_stop(self) -> bool:
        return self.stop_event.is_set()

    async def reserve_evaluation_slots(self, desired: int) -> int:
        """Reserve a small shared shortlist budget across concurrent sources."""
        if desired <= 0 or self.queue_cap <= 0:
            return 0

        async with self.lock:
            available = max(
                0,
                self.queue_cap
                + _QUEUE_EVALUATION_BUFFER
                - self.inserted_new_count
                - self.reserved_evaluation_count,
            )
            granted = min(desired, available)
            self.reserved_evaluation_count += granted
            return granted

    async def release_evaluation_slots(self, reserved: int) -> None:
        if reserved <= 0:
            return

        async with self.lock:
            self.reserved_evaluation_count = max(
                0, self.reserved_evaluation_count - reserved
            )
            if self.inserted_new_count >= self.queue_cap:
                self.stop_event.set()

    async def reserve_llm_slots(self, desired: int) -> int:
        """Reserve per-run LLM budget so concurrent batches do not overspend."""
        if desired <= 0 or self.queue_cap <= 0:
            return 0

        async with self.lock:
            remaining_run_cap = max(
                0,
                _LLM_SCORE_CAP
                - self.llm_attempted_count
                - self.reserved_llm_count,
            )
            remaining_queue_window = max(
                0,
                self.queue_cap
                + _LLM_SCORE_BUFFER
                - self.inserted_new_count
                - self.reserved_llm_count,
            )
            granted = min(desired, remaining_run_cap, remaining_queue_window)
            self.reserved_llm_count += granted
            return granted

    async def release_llm_slots(self, reserved: int, attempted: int) -> None:
        if reserved <= 0 and attempted <= 0:
            return

        async with self.lock:
            self.reserved_llm_count = max(
                0, self.reserved_llm_count - reserved
            )
            self.llm_attempted_count += max(0, attempted)
            if self.inserted_new_count >= self.queue_cap:
                self.stop_event.set()

    async def upsert_draft_item(
        self,
        *,
        game_id: str,
        prospect_id: str,
        template_id: str | None,
        subject_line: str | None,
        body_text: str,
        priority_score: float,
        fit_summary: str,
        score_breakdown: str,
        db_path: str,
    ) -> str:
        """Upsert a queue item while enforcing the run-level insert cap."""
        now = datetime.now(UTC).isoformat()

        async with self.lock:
            with get_connection(db_path) as conn:
                existing = conn.execute(
                    "SELECT draft_item_id FROM draft_items WHERE game_id = ? AND prospect_id = ?",
                    (game_id, prospect_id),
                ).fetchone()

                if existing is not None:
                    conn.execute(
                        """
                        UPDATE draft_items
                        SET priority_score = ?, fit_summary = ?, score_breakdown = ?,
                            updated_at = ?
                        WHERE draft_item_id = ?
                        """,
                        (
                            priority_score,
                            fit_summary,
                            score_breakdown,
                            now,
                            existing["draft_item_id"],
                        ),
                    )
                    return "refreshed"

                if self.inserted_new_count >= self.queue_cap:
                    self.stop_event.set()
                    return "cap_reached"

                draft_item_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO draft_items
                        (draft_item_id, game_id, prospect_id, template_id, subject_line,
                         body_text, status, priority_score, fit_summary,
                         score_breakdown, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)
                    """,
                    (
                        draft_item_id,
                        game_id,
                        prospect_id,
                        template_id,
                        subject_line,
                        body_text,
                        priority_score,
                        fit_summary,
                        score_breakdown,
                        now,
                        now,
                    ),
                )
                self.inserted_new_count += 1
                if self.inserted_new_count >= self.queue_cap:
                    self.stop_event.set()
                return "inserted"
