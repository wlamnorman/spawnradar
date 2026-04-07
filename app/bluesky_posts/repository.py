"""Persistence helpers for internal Bluesky draft queue."""

from __future__ import annotations

import sqlite3
import uuid

from app.bluesky_posts.models import BlueskyPostDraft
from app.database import get_connection
from app.json_codec import dump_json, load_json_string_list


class BlueskyPostDraftRepository:
    """CRUD access for the internal Bluesky draft queue."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def get_by_game_id(self, customer_game_id: str) -> BlueskyPostDraft | None:
        """Return the draft associated with one customer game."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT *
                FROM bluesky_post_drafts
                WHERE customer_game_id = ?
                """,
                (customer_game_id,),
            ).fetchone()
        return _row_to_draft(row) if row is not None else None

    def get_by_game_slug(self, source_game_slug: str) -> BlueskyPostDraft | None:
        """Return the draft associated with one game slug."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT *
                FROM bluesky_post_drafts
                WHERE source_game_slug = ?
                """,
                (source_game_slug,),
            ).fetchone()
        return _row_to_draft(row) if row is not None else None

    def get_by_id(self, draft_id: str) -> BlueskyPostDraft | None:
        """Return one draft by primary key."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM bluesky_post_drafts WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
        return _row_to_draft(row) if row is not None else None

    def list_queue(self) -> list[BlueskyPostDraft]:
        """Return all drafts, newest first within each status bucket."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM bluesky_post_drafts
                ORDER BY
                    CASE status
                        WHEN 'draft' THEN 0
                        WHEN 'approved' THEN 1
                        WHEN 'rejected' THEN 2
                        ELSE 3
                    END,
                    updated_at DESC
                """
            ).fetchall()
        return [_row_to_draft(row) for row in rows]

    def create_for_game(
        self,
        *,
        customer_game_id: str,
        source_game_slug: str,
        workspace_id: str,
        creator_summary: str,
        body: str,
        hashtags: list[str],
        creator_handle: str | None,
        image_filename: str | None,
        image_media_type: str | None,
        image_bytes: bytes | None,
        image_alt_text: str = "",
    ) -> BlueskyPostDraft:
        """Create the single allowed draft for one game."""
        draft_id = str(uuid.uuid4())
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO bluesky_post_drafts (
                    draft_id,
                    customer_game_id,
                    source_game_slug,
                    workspace_id,
                    creator_summary,
                    status,
                    body,
                    hashtags,
                    creator_handle,
                    image_filename,
                    image_media_type,
                    image_bytes,
                    image_alt_text
                )
                VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    customer_game_id,
                    source_game_slug,
                    workspace_id,
                    creator_summary,
                    body,
                    dump_json(hashtags),
                    creator_handle,
                    image_filename,
                    image_media_type,
                    image_bytes,
                    image_alt_text,
                ),
            )
        return self.get_by_id(draft_id)  # type: ignore[return-value]

    def delete_by_game_id(self, customer_game_id: str) -> None:
        """Remove the queued draft for one game."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                "DELETE FROM bluesky_post_drafts WHERE customer_game_id = ?",
                (customer_game_id,),
            )

    def update_body_and_status(
        self,
        draft_id: str,
        *,
        body: str,
        status: str,
    ) -> BlueskyPostDraft:
        """Store an admin-edited body and review status."""
        if status not in {"draft", "approved", "rejected"}:
            raise ValueError("Invalid Bluesky draft status.")

        approved_at = "datetime('now')" if status == "approved" else "NULL"
        rejected_at = "datetime('now')" if status == "rejected" else "NULL"
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                f"""
                UPDATE bluesky_post_drafts
                SET body = ?,
                    status = ?,
                    reviewed_at = datetime('now'),
                    approved_at = {approved_at},
                    rejected_at = {rejected_at},
                    updated_at = datetime('now')
                WHERE draft_id = ?
                """,
                (body, status, draft_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Bluesky draft not found.")
        return self.get_by_id(draft_id)  # type: ignore[return-value]


def _row_to_draft(row: sqlite3.Row) -> BlueskyPostDraft:
    return BlueskyPostDraft(
        draft_id=str(row["draft_id"]),
        customer_game_id=str(row["customer_game_id"]),
        source_game_slug=str(row["source_game_slug"]),
        workspace_id=str(row["workspace_id"]),
        status=str(row["status"]),
        creator_summary=str(row["creator_summary"]),
        body=str(row["body"]),
        hashtags=load_json_string_list(row["hashtags"]),
        creator_handle=row["creator_handle"],
        image_filename=row["image_filename"],
        image_media_type=row["image_media_type"],
        image_bytes=bytes(row["image_bytes"]) if row["image_bytes"] else None,
        image_alt_text=str(row["image_alt_text"] or ""),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        reviewed_at=row["reviewed_at"],
        approved_at=row["approved_at"],
        rejected_at=row["rejected_at"],
    )
