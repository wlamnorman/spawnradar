"""Database operations for customer games, assets and message templates."""

from __future__ import annotations

import re
import sqlite3

from app.database import get_connection
from app.games.models import CustomerGame
from app.igdb.taxonomy import keyword_bucket_for_value
from app.json_codec import (
    dump_json,
    load_json_int_list,
    load_json_string_list,
)


def _make_slug(name: str, customer_game_id: str) -> str:
    """Generate a URL slug from a customer game name and its ID."""
    slug_name = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{slug_name}-{customer_game_id[:8]}"


class CustomerGameRepository:
    """CRUD operations for the persisted customer-games table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def create(
        self,
        *,
        customer_game_id: str,
        user_id: str,
        name: str,
        summary: str | None,
        description: str,
        website_url: str | None,
        platforms: list[str] | None = None,
        igdb_genre_ids: list[int] | None = None,
        igdb_theme_ids: list[int] | None = None,
        igdb_game_mode_ids: list[int] | None = None,
        igdb_player_perspective_ids: list[int] | None = None,
        igdb_keyword_ids: list[str] | None = None,
        similar_game_names: list[str] | None = None,
    ) -> CustomerGame:
        """Insert a new customer game record."""
        genre_ids = igdb_genre_ids or []
        theme_ids = igdb_theme_ids or []
        game_mode_ids = igdb_game_mode_ids or []
        player_perspective_ids = igdb_player_perspective_ids or []
        keyword_ids = igdb_keyword_ids or []
        similar_names = similar_game_names or []
        selected_platforms = platforms or []
        slug = _make_slug(name, customer_game_id)
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO customer_games
                    (customer_game_id, user_id, name, summary, description, slug,
                     website_url, platforms,
                     igdb_genre_ids, igdb_theme_ids,
                     igdb_game_mode_ids, igdb_player_perspective_ids,
                     igdb_keyword_ids, similar_game_names)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    customer_game_id,
                    user_id,
                    name,
                    summary,
                    description,
                    slug,
                    website_url,
                    dump_json(selected_platforms),
                    dump_json(genre_ids),
                    dump_json(theme_ids),
                    dump_json(game_mode_ids),
                    dump_json(player_perspective_ids),
                    dump_json(keyword_ids),
                    dump_json(similar_names),
                ),
            )
            _replace_game_tags(
                conn,
                customer_game_id,
                genre_ids,
                theme_ids,
                game_mode_ids,
                player_perspective_ids,
                keyword_ids,
            )
        return self.get_by_id(customer_game_id)  # type: ignore[return-value]

    def get_by_id(self, customer_game_id: str) -> CustomerGame | None:
        """Fetch a customer game by primary key."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM customer_games WHERE customer_game_id = ?",
                (customer_game_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_game(row)

    def get_by_slug(self, slug: str) -> CustomerGame | None:
        """Fetch a customer game by its URL slug."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM customer_games WHERE slug = ?", (slug,)
            ).fetchone()
        if row is None:
            return None
        return _row_to_game(row)

    def list_by_user(self, user_id: str) -> list[CustomerGame]:
        """Return all active customer games for a user, newest first."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM customer_games WHERE user_id = ? AND status = 'active' ORDER BY created_at ASC",
                (user_id,),
            ).fetchall()
        return [_row_to_game(r) for r in rows]

    def list_active(self) -> list[CustomerGame]:
        """Return all active customer games across the product."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM customer_games WHERE status = 'active' ORDER BY created_at ASC"
            ).fetchall()
        return [_row_to_game(row) for row in rows]

    def update(
        self,
        customer_game_id: str,
        *,
        name: str | None = None,
        summary: str | None = None,
        description: str | None = None,
        website_url: str | None = None,
        platforms: list[str] | None = None,
        igdb_genre_ids: list[int] | None = None,
        igdb_theme_ids: list[int] | None = None,
        igdb_game_mode_ids: list[int] | None = None,
        igdb_player_perspective_ids: list[int] | None = None,
        igdb_keyword_ids: list[str] | None = None,
        similar_game_names: list[str] | None = None,
    ) -> CustomerGame:
        """Partially update a customer game record, returning the updated entity.

        When any definition field changes (name, genres, themes, keywords),
        ``llm_similar_game_names`` is cleared because the LLM suggestions are
        stale.  Customer-provided ``similar_game_names`` are never auto-cleared.
        """
        customer_game = self.get_by_id(customer_game_id)
        if customer_game is None:
            raise ValueError(f"CustomerGame {customer_game_id} not found.")

        new_name = name if name is not None else customer_game.name
        new_summary = summary if summary is not None else customer_game.summary
        new_desc = (
            description
            if description is not None
            else customer_game.description
        )
        new_url = (
            website_url
            if website_url is not None
            else customer_game.website_url
        )
        new_platforms = (
            platforms if platforms is not None else customer_game.platforms
        )
        new_igdb_genres = (
            igdb_genre_ids
            if igdb_genre_ids is not None
            else customer_game.igdb_genre_ids
        )
        new_igdb_themes = (
            igdb_theme_ids
            if igdb_theme_ids is not None
            else customer_game.igdb_theme_ids
        )
        new_igdb_game_modes = (
            igdb_game_mode_ids
            if igdb_game_mode_ids is not None
            else customer_game.igdb_game_mode_ids
        )
        new_igdb_player_perspectives = (
            igdb_player_perspective_ids
            if igdb_player_perspective_ids is not None
            else customer_game.igdb_player_perspective_ids
        )
        new_keywords = (
            igdb_keyword_ids
            if igdb_keyword_ids is not None
            else customer_game.igdb_keyword_ids
        )
        new_similar = (
            similar_game_names
            if similar_game_names is not None
            else customer_game.similar_game_names
        )

        # Clear LLM suggestions when the game definition changes
        definition_changed = (
            new_name != customer_game.name
            or new_igdb_genres != customer_game.igdb_genre_ids
            or new_igdb_themes != customer_game.igdb_theme_ids
            or new_keywords != customer_game.igdb_keyword_ids
        )
        new_llm_similar = (
            [] if definition_changed else customer_game.llm_similar_game_names
        )
        new_llm_broad = (
            [] if definition_changed else customer_game.llm_broad_game_names
        )

        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE customer_games
                SET name = ?, summary = ?, description = ?,
                    website_url = ?, platforms = ?,
                    igdb_genre_ids = ?, igdb_theme_ids = ?,
                    igdb_game_mode_ids = ?, igdb_player_perspective_ids = ?,
                    igdb_keyword_ids = ?,
                    similar_game_names = ?,
                    llm_similar_game_names = ?, llm_broad_game_names = ?,
                    updated_at = datetime('now')
                WHERE customer_game_id = ?
                """,
                (
                    new_name,
                    new_summary,
                    new_desc,
                    new_url,
                    dump_json(new_platforms),
                    dump_json(new_igdb_genres),
                    dump_json(new_igdb_themes),
                    dump_json(new_igdb_game_modes),
                    dump_json(new_igdb_player_perspectives),
                    dump_json(new_keywords),
                    dump_json(new_similar),
                    dump_json(new_llm_similar),
                    dump_json(new_llm_broad),
                    customer_game_id,
                ),
            )
            _replace_game_tags(
                conn,
                customer_game_id,
                new_igdb_genres,
                new_igdb_themes,
                new_igdb_game_modes,
                new_igdb_player_perspectives,
                new_keywords,
            )
        return self.get_by_id(customer_game_id)  # type: ignore[return-value]

    def count_by_user(self, user_id: str) -> int:
        """Return the number of active customer games owned by a user."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM customer_games WHERE user_id = ? AND status = 'active'",
                (user_id,),
            ).fetchone()
        return row[0] if row else 0

    def set_llm_game_suggestions(
        self,
        customer_game_id: str,
        tight: list[str],
        broad: list[str],
    ) -> None:
        """Store LLM-generated game suggestions (tight anchors + broad exploration).

        Called after the LLM generates suggestions as a background task
        triggered by game creation or update.
        """
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE customer_games
                SET llm_similar_game_names = ?,
                    llm_broad_game_names = ?,
                    updated_at = datetime('now')
                WHERE customer_game_id = ?
                """,
                (dump_json(tight), dump_json(broad), customer_game_id),
            )

    def delete(self, customer_game_id: str) -> None:
        """Hard-delete a customer game and all its related data (cascaded by FK)."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                "DELETE FROM customer_games WHERE customer_game_id = ?",
                (customer_game_id,),
            )

    def transfer_ownership(self, from_user_id: str, to_user_id: str) -> int:
        """Move all games from one user to another. Returns count transferred."""
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                "UPDATE customer_games SET user_id = ?, updated_at = datetime('now') WHERE user_id = ?",
                (to_user_id, from_user_id),
            )
            return cursor.rowcount

    def duplicate(
        self,
        *,
        source_customer_game_id: str,
        new_customer_game_id: str,
        new_name: str,
    ) -> CustomerGame:
        """Insert a copy of a customer game with a new ID and name.

        Customer-provided ``similar_game_names`` are copied.
        LLM suggestions are not (the duplicate is a new definition).
        """
        source = self.get_by_id(source_customer_game_id)
        if source is None:
            raise ValueError(
                f"CustomerGame {source_customer_game_id} not found."
            )
        new_slug = _make_slug(new_name, new_customer_game_id)
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO customer_games
                    (customer_game_id, user_id, name, summary, description, slug,
                     website_url, platforms,
                     igdb_genre_ids, igdb_theme_ids,
                     igdb_game_mode_ids, igdb_player_perspective_ids,
                     igdb_keyword_ids, similar_game_names)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_customer_game_id,
                    source.user_id,
                    new_name,
                    source.summary,
                    source.description,
                    new_slug,
                    source.website_url,
                    dump_json(source.platforms),
                    dump_json(source.igdb_genre_ids),
                    dump_json(source.igdb_theme_ids),
                    dump_json(source.igdb_game_mode_ids),
                    dump_json(source.igdb_player_perspective_ids),
                    dump_json(source.igdb_keyword_ids),
                    dump_json(source.similar_game_names),
                ),
            )
            _replace_game_tags(
                conn,
                new_customer_game_id,
                source.igdb_genre_ids,
                source.igdb_theme_ids,
                source.igdb_game_mode_ids,
                source.igdb_player_perspective_ids,
                source.igdb_keyword_ids,
            )
        return self.get_by_id(new_customer_game_id)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Tag helpers
# ---------------------------------------------------------------------------


def _replace_game_tags(
    conn: sqlite3.Connection,
    customer_game_id: str,
    genre_ids: list[int],
    theme_ids: list[int],
    game_mode_ids: list[int],
    player_perspective_ids: list[int],
    keyword_ids: list[str] | None = None,
) -> None:
    """Replace all tag rows for a customer game in one transaction.

    Curated keyword tags are normalized into the same conceptual buckets
    customers see in the UI: genre, theme, or mechanic.
    """
    conn.execute(
        "DELETE FROM customer_game_tags WHERE customer_game_id = ?",
        (customer_game_id,),
    )
    tag_rows: list[tuple[str, str, int | str]] = []
    tag_rows.extend((customer_game_id, "genre", gid) for gid in genre_ids)
    tag_rows.extend((customer_game_id, "theme", tid) for tid in theme_ids)
    tag_rows.extend(
        (customer_game_id, "game_mode", mid) for mid in game_mode_ids
    )
    tag_rows.extend(
        (customer_game_id, "player_perspective", pid)
        for pid in player_perspective_ids
    )
    for keyword_id in keyword_ids or []:
        bucket = keyword_bucket_for_value(keyword_id)
        if bucket is None:
            continue
        tag_rows.append((customer_game_id, bucket.value, keyword_id))
    if tag_rows:
        conn.executemany(
            "INSERT INTO customer_game_tags (customer_game_id, tag_type, tag_id) VALUES (?, ?, ?)",
            tag_rows,
        )


# ---------------------------------------------------------------------------
# Row converters
# ---------------------------------------------------------------------------


def _row_to_game(row: sqlite3.Row) -> CustomerGame:
    """Hydrate a CustomerGame from a DB row.

    Tags are read from the denormalized JSON columns (not the relational
    ``customer_game_tags`` table) for simplicity and speed.  Both sources
    are kept in sync by ``_replace_game_tags`` on every create/update.
    """
    customer_game_id = row["customer_game_id"]
    name = row["name"]
    slug = row["slug"] or _make_slug(name, customer_game_id)
    row_keys = set(row.keys())

    def _int_col(col: str) -> list[int]:
        return load_json_int_list(row[col]) if col in row_keys else []

    def _str_col(col: str) -> list[str]:
        return load_json_string_list(row[col]) if col in row_keys else []

    platforms = _str_col("platforms")
    if not platforms and "platforms_json" in row_keys:
        platforms = _str_col("platforms_json")

    return CustomerGame(
        customer_game_id=customer_game_id,
        user_id=row["user_id"],
        name=name,
        summary=row["summary"] if "summary" in row_keys else None,
        description=row["description"],
        slug=slug,
        website_url=row["website_url"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        platforms=platforms,
        igdb_genre_ids=_int_col("igdb_genre_ids"),
        igdb_theme_ids=_int_col("igdb_theme_ids"),
        igdb_game_mode_ids=_int_col("igdb_game_mode_ids"),
        igdb_player_perspective_ids=_int_col("igdb_player_perspective_ids"),
        igdb_keyword_ids=_str_col("igdb_keyword_ids"),
        similar_game_names=_str_col("similar_game_names"),
        llm_similar_game_names=_str_col("llm_similar_game_names"),
        llm_broad_game_names=_str_col("llm_broad_game_names"),
    )
