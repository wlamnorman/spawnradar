"""Persistence helpers for Steam enrichment of cached IGDB games."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.database import get_connection
from app.steam_enrichment.models import (
    SteamBackfillCandidate,
    SteamMappedTag,
    SteamResolvedLink,
)


class SteamEnrichmentRepository:
    """Store Steam links, raw tags, mapped tags, and sync state."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def mark_pending(self, igdb_id: int) -> None:
        """Ensure a cached IGDB game is queued for enrichment."""

        now = datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO steam_game_sync_state
                    (igdb_id, sync_status, updated_at)
                VALUES (?, 'pending', ?)
                ON CONFLICT(igdb_id) DO NOTHING
                """,
                (igdb_id, now),
            )

    def load_backfill_candidates(
        self,
        *,
        limit: int,
        include_no_match: bool = False,
    ) -> list[SteamBackfillCandidate]:
        """Return cached IGDB games that still need Steam enrichment."""

        where = ["(state.igdb_id IS NULL OR state.sync_status = 'pending')"]
        if include_no_match:
            where.append("state.sync_status = 'no_match'")
        where_sql = " OR ".join(where)
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT
                    g.igdb_id,
                    g.name,
                    g.slug,
                    g.summary,
                    g.first_release_date,
                    g.developer_names_json,
                    COUNT(DISTINCT cgp.account_id) AS popularity_count
                FROM igdb_games g
                LEFT JOIN creator_games_played cgp ON cgp.igdb_game_id = g.igdb_id
                LEFT JOIN steam_game_sync_state state ON state.igdb_id = g.igdb_id
                WHERE {where_sql}
                GROUP BY
                    g.igdb_id, g.name, g.slug, g.summary, g.first_release_date,
                    g.developer_names_json
                ORDER BY popularity_count DESC, g.last_synced_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            SteamBackfillCandidate(
                igdb_id=int(row["igdb_id"]),
                name=str(row["name"]),
                slug=str(row["slug"]),
                summary=str(row["summary"])
                if row["summary"] is not None
                else None,
                first_release_date=row["first_release_date"],
                developer_names=tuple(
                    str(name)
                    for name in json.loads(row["developer_names_json"] or "[]")
                ),
                popularity_count=int(row["popularity_count"] or 0),
            )
            for row in rows
        ]

    def local_tag_keys_for(self, igdb_id: int) -> set[tuple[str, str]]:
        """Return existing canonical tag keys for one cached IGDB game."""

        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT tag_type, CAST(tag_id AS TEXT) AS tag_id
                FROM igdb_game_tags
                WHERE igdb_id = ?
                """,
                (igdb_id,),
            ).fetchall()
        return {(str(row["tag_type"]), str(row["tag_id"])) for row in rows}

    def replace_enrichment(
        self,
        *,
        link: SteamResolvedLink,
        raw_tags: tuple[str, ...],
        normalized_tags: tuple[str, ...],
        mapped_tags: tuple[SteamMappedTag, ...],
    ) -> None:
        """Replace the stored enrichment for one linked IGDB game."""

        now = datetime.now(UTC).isoformat()
        deduped_mapped_tags = self._dedupe_mapped_tags(mapped_tags)
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO steam_game_links
                    (igdb_id, steam_app_id, store_url, match_method, resolved_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(igdb_id) DO UPDATE SET
                    steam_app_id = excluded.steam_app_id,
                    store_url = excluded.store_url,
                    match_method = excluded.match_method,
                    resolved_at = excluded.resolved_at
                """,
                (
                    link.igdb_id,
                    link.steam_app_id,
                    link.store_url,
                    link.match_method,
                    now,
                ),
            )
            conn.execute(
                "DELETE FROM steam_game_tags WHERE igdb_id = ?",
                (link.igdb_id,),
            )
            conn.execute(
                "DELETE FROM steam_game_mapped_tags WHERE igdb_id = ?",
                (link.igdb_id,),
            )
            conn.executemany(
                """
                INSERT INTO steam_game_tags
                    (igdb_id, steam_app_id, raw_tag, normalized_tag, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        link.igdb_id,
                        link.steam_app_id,
                        raw_tag,
                        normalized_tag,
                        now,
                    )
                    for raw_tag, normalized_tag in zip(
                        raw_tags, normalized_tags, strict=True
                    )
                ],
            )
            conn.executemany(
                """
                INSERT INTO steam_game_mapped_tags
                    (igdb_id, source_tag, mapped_tag_type, mapped_tag_id,
                     mapped_tag_name, mapping_kind, mapped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        link.igdb_id,
                        entry.source_tag,
                        entry.tag_type,
                        str(entry.tag_id),
                        entry.tag_name,
                        entry.mapping_kind,
                        now,
                    )
                    for entry in deduped_mapped_tags
                ],
            )
            conn.execute(
                """
                INSERT INTO steam_game_sync_state
                    (igdb_id, sync_status, last_attempted_at, last_succeeded_at,
                     updated_at, last_error)
                VALUES (?, 'linked', ?, ?, ?, NULL)
                ON CONFLICT(igdb_id) DO UPDATE SET
                    sync_status = excluded.sync_status,
                    last_attempted_at = excluded.last_attempted_at,
                    last_succeeded_at = excluded.last_succeeded_at,
                    updated_at = excluded.updated_at,
                    last_error = NULL
                """,
                (link.igdb_id, now, now, now),
            )

    def mark_no_match(self, igdb_id: int, reason: str) -> None:
        """Persist a factual no-match outcome for one cached game."""

        now = datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO steam_game_sync_state
                    (igdb_id, sync_status, last_attempted_at, updated_at, last_error)
                VALUES (?, 'no_match', ?, ?, ?)
                ON CONFLICT(igdb_id) DO UPDATE SET
                    sync_status = excluded.sync_status,
                    last_attempted_at = excluded.last_attempted_at,
                    updated_at = excluded.updated_at,
                    last_error = excluded.last_error
                """,
                (igdb_id, now, now, reason),
            )

    def mark_error(self, igdb_id: int, error: str) -> None:
        """Persist a fetch/parse error for one cached game."""

        now = datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO steam_game_sync_state
                    (igdb_id, sync_status, last_attempted_at, updated_at, last_error)
                VALUES (?, 'error', ?, ?, ?)
                ON CONFLICT(igdb_id) DO UPDATE SET
                    sync_status = excluded.sync_status,
                    last_attempted_at = excluded.last_attempted_at,
                    updated_at = excluded.updated_at,
                    last_error = excluded.last_error
                """,
                (igdb_id, now, now, error),
            )

    @staticmethod
    def _dedupe_mapped_tags(
        mapped_tags: tuple[SteamMappedTag, ...],
    ) -> tuple[SteamMappedTag, ...]:
        """Keep only the first mapping for each canonical tag.

        Different Steam source tags can collapse onto the same canonical tag.
        We persist the first-seen mapping only, which preserves deterministic
        source attribution without storing duplicates like `Deckbuilder` twice.
        """

        seen: set[tuple[str, str]] = set()
        deduped: list[SteamMappedTag] = []
        for entry in mapped_tags:
            key = (entry.tag_type, str(entry.tag_id))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(entry)
        return tuple(deduped)
