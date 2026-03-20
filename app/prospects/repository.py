"""Database operations for prospects, draft items, and outcomes."""

from __future__ import annotations

import sqlite3

from app.database import get_connection
from app.json_codec import load_json_object
from app.prospects.models import DraftItem, Outcome, Prospect, ReviewQueueItem


class ProspectRepository:
    """Read operations for the prospects table (writes are done by the pipeline)."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def get_by_id(self, prospect_id: str) -> Prospect | None:
        """Fetch a prospect by primary key."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM prospects WHERE prospect_id = ?", (prospect_id,)
            ).fetchone()
        if row is None:
            return None
        return _row_to_prospect(row)


class DraftItemRepository:
    """CRUD operations for the draft_items table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def get_by_id(self, draft_item_id: str) -> DraftItem | None:
        """Fetch a draft item by primary key."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM draft_items WHERE draft_item_id = ?",
                (draft_item_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_draft(row)

    def list_queued(self, game_id: str) -> list[ReviewQueueItem]:
        """Return queued items with explicit column aliasing."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                    d.draft_item_id, d.game_id, d.prospect_id, d.template_id,
                    d.subject_line, d.body_text, d.status, d.priority_score,
                    d.fit_summary, d.score_breakdown,
                    d.last_edited_at, d.created_at AS draft_created_at,
                    d.updated_at AS draft_updated_at,
                    p.prospect_id AS p_prospect_id, p.platform, p.handle,
                    p.display_name, p.profile_url, p.contact_channel,
                    p.contact_value, p.audience_size, p.engagement_rate,
                    p.description, p.raw_data,
                    p.created_at AS prospect_created_at,
                    p.updated_at AS prospect_updated_at
                FROM draft_items d
                JOIN prospects p ON d.prospect_id = p.prospect_id
                WHERE d.game_id = ? AND d.status = 'queued'
                ORDER BY d.priority_score DESC
                """,
                (game_id,),
            ).fetchall()

        items = []
        for row in rows:
            draft = DraftItem(
                draft_item_id=row["draft_item_id"],
                game_id=row["game_id"],
                prospect_id=row["prospect_id"],
                template_id=row["template_id"],
                subject_line=row["subject_line"],
                body_text=row["body_text"],
                status=row["status"],
                priority_score=row["priority_score"],
                fit_summary=row["fit_summary"],
                score_breakdown=load_json_object(row["score_breakdown"]),
                last_edited_at=row["last_edited_at"],
                created_at=row["draft_created_at"],
                updated_at=row["draft_updated_at"],
            )
            prospect = Prospect(
                prospect_id=row["p_prospect_id"],
                platform=row["platform"],
                handle=row["handle"],
                display_name=row["display_name"],
                profile_url=row["profile_url"],
                contact_channel=row["contact_channel"],
                contact_value=row["contact_value"],
                audience_size=row["audience_size"],
                engagement_rate=row["engagement_rate"],
                description=row["description"],
                raw_data=load_json_object(row["raw_data"]),
                created_at=row["prospect_created_at"],
                updated_at=row["prospect_updated_at"],
            )
            items.append(ReviewQueueItem(draft=draft, prospect=prospect))
        return items

    def update_status(
        self,
        draft_item_id: str,
        status: str,
        body_text: str | None = None,
    ) -> None:
        """Update the status (and optionally body) of a draft item."""
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        if body_text is not None:
            with get_connection(self._db_path) as conn:
                conn.execute(
                    """
                    UPDATE draft_items
                    SET status = ?, body_text = ?, last_edited_at = ?, updated_at = ?
                    WHERE draft_item_id = ?
                    """,
                    (status, body_text, now, now, draft_item_id),
                )
        else:
            with get_connection(self._db_path) as conn:
                conn.execute(
                    """
                    UPDATE draft_items
                    SET status = ?, updated_at = ?
                    WHERE draft_item_id = ?
                    """,
                    (status, now, draft_item_id),
                )

    def count_queued(self, game_id: str) -> int:
        """Return the count of queued draft items for a game."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM draft_items WHERE game_id = ? AND status = 'queued'",
                (game_id,),
            ).fetchone()
        return row[0] if row else 0


class OutcomeRepository:
    """Write operations for the outcomes table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def create(
        self,
        outcome_id: str,
        draft_item_id: str,
        outcome_type: str,
        notes: str | None,
    ) -> Outcome:
        """Record an outcome for a draft item action."""
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO outcomes (outcome_id, draft_item_id, outcome_type, notes, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (outcome_id, draft_item_id, outcome_type, notes, now),
            )
        return Outcome(
            outcome_id=outcome_id,
            draft_item_id=draft_item_id,
            outcome_type=outcome_type,
            notes=notes,
            created_at=now,
        )


# ---------------------------------------------------------------------------
# Row converters
# ---------------------------------------------------------------------------


def _row_to_prospect(row: sqlite3.Row) -> Prospect:
    return Prospect(
        prospect_id=row["prospect_id"],
        platform=row["platform"],
        handle=row["handle"],
        display_name=row["display_name"],
        profile_url=row["profile_url"],
        contact_channel=row["contact_channel"],
        contact_value=row["contact_value"],
        audience_size=row["audience_size"],
        engagement_rate=row["engagement_rate"],
        description=row["description"],
        raw_data=load_json_object(row["raw_data"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_draft(row: sqlite3.Row) -> DraftItem:
    return DraftItem(
        draft_item_id=row["draft_item_id"],
        game_id=row["game_id"],
        prospect_id=row["prospect_id"],
        template_id=row["template_id"],
        subject_line=row["subject_line"],
        body_text=row["body_text"],
        status=row["status"],
        priority_score=row["priority_score"],
        fit_summary=row["fit_summary"],
        score_breakdown=load_json_object(row["score_breakdown"]),
        last_edited_at=row["last_edited_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
