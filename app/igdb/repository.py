from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from app.database import get_connection
from app.igdb.models import IGDBGame
from app.igdb.taxonomy import (
    canonical_keyword_for_igdb_name,
    keyword_bucket_for_value,
    keyword_label_for_value,
)


class IGDBRepository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def upsert(self, game: IGDBGame) -> None:
        now = datetime.now(UTC).isoformat()
        with get_connection(self._db_path) as con:
            con.execute(
                """
                INSERT INTO igdb_games
                    (igdb_id, name, slug, summary, first_release_date,
                     cover_url, platform_ids_json, platform_names_json,
                     last_synced_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(igdb_id) DO UPDATE SET
                    name               = excluded.name,
                    slug               = excluded.slug,
                    summary            = excluded.summary,
                    first_release_date = excluded.first_release_date,
                    cover_url          = excluded.cover_url,
                    platform_ids_json  = excluded.platform_ids_json,
                    platform_names_json = excluded.platform_names_json,
                    last_synced_at     = excluded.last_synced_at
                """,
                (
                    game.igdb_id,
                    game.name,
                    game.slug,
                    game.summary,
                    game.first_release_date,
                    game.cover_url,
                    json.dumps(game.platform_ids),
                    json.dumps(game.platform_names),
                    now,
                ),
            )
            con.execute(
                "DELETE FROM igdb_game_tags WHERE igdb_id = ?",
                (game.igdb_id,),
            )
            rows: list[tuple[int, str, str, int | str]] = []
            rows.extend(
                (game.igdb_id, "genre", genre.label, genre.value)
                for genre in game.genre_ids
            )
            rows.extend(
                (game.igdb_id, "theme", theme.label, theme.value)
                for theme in game.theme_ids
            )
            official_genre_labels = {
                genre.label.casefold() for genre in game.genre_ids
            }
            official_theme_labels = {
                theme.label.casefold() for theme in game.theme_ids
            }
            keyword_rows: dict[tuple[str, str], tuple[int, str, str, str]] = {}
            for raw_keyword in game.keyword_names:
                canonical = canonical_keyword_for_igdb_name(raw_keyword)
                if canonical is None:
                    continue
                bucket = keyword_bucket_for_value(canonical)
                label = keyword_label_for_value(canonical)
                if bucket is None or label is None:
                    continue
                if (
                    bucket.value == "genre"
                    and label.casefold() in official_genre_labels
                ):
                    continue
                if (
                    bucket.value == "theme"
                    and label.casefold() in official_theme_labels
                ):
                    continue
                keyword_rows[(bucket.value, canonical)] = (
                    game.igdb_id,
                    bucket.value,
                    label,
                    canonical,
                )
            rows.extend(keyword_rows.values())
            con.executemany(
                "INSERT OR IGNORE INTO igdb_game_tags"
                " (igdb_id, tag_type, tag_name, tag_id) VALUES (?,?,?,?)",
                rows,
            )

    def get(self, igdb_id: int) -> sqlite3.Row | None:
        with get_connection(self._db_path) as con:
            return con.execute(
                "SELECT * FROM igdb_games WHERE igdb_id = ?", (igdb_id,)
            ).fetchone()

    def get_tags(self, igdb_id: int) -> list[sqlite3.Row]:
        with get_connection(self._db_path) as con:
            return con.execute(
                "SELECT tag_type, tag_name, tag_id FROM igdb_game_tags WHERE igdb_id = ?",
                (igdb_id,),
            ).fetchall()

    def list_by_tag(
        self, *, tag_type: str, tag_id: int | str, limit: int = 500
    ) -> list[sqlite3.Row]:
        with get_connection(self._db_path) as con:
            return con.execute(
                """
                SELECT g.* FROM igdb_games g
                JOIN igdb_game_tags t ON t.igdb_id = g.igdb_id
                WHERE t.tag_type = ? AND t.tag_id = ?
                LIMIT ?
                """,
                (tag_type, tag_id, limit),
            ).fetchall()

    def count(self) -> int:
        with get_connection(self._db_path) as con:
            return con.execute("SELECT COUNT(*) FROM igdb_games").fetchone()[0]

    def oldest_synced_ids(self, limit: int) -> list[int]:
        with get_connection(self._db_path) as con:
            return [
                r[0]
                for r in con.execute(
                    "SELECT igdb_id FROM igdb_games ORDER BY last_synced_at ASC LIMIT ?",
                    (limit,),
                ).fetchall()
            ]

    def search_by_name(
        self, query: str, *, limit: int = 8
    ) -> list[sqlite3.Row]:
        """Search cached IGDB games by name using exact/prefix/contains order."""
        normalized = query.strip().lower()
        if not normalized:
            return []
        with get_connection(self._db_path) as con:
            return con.execute(
                """
                SELECT igdb_id, name, slug
                FROM igdb_games
                WHERE LOWER(name) LIKE ?
                ORDER BY
                    CASE
                        WHEN LOWER(name) = ? THEN 0
                        WHEN LOWER(name) LIKE ? THEN 1
                        ELSE 2
                    END,
                    LENGTH(name) ASC,
                    name ASC
                LIMIT ?
                """,
                (
                    f"%{normalized}%",
                    normalized,
                    f"{normalized}%",
                    limit,
                ),
            ).fetchall()
