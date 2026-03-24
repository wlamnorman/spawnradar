"""Database operations for games, assets and message templates."""

from __future__ import annotations

import re
import sqlite3

from app.database import get_connection
from app.games.models import Asset, Game, MessageTemplate
from app.games.tags import TagProfile, TagWeight
from app.ingestion.registry import DEFAULT_DISCOVERY_SOURCES, Source
from app.json_codec import (
    dump_json,
    load_json_object,
    load_json_string_list,
)

_LEGACY_DEFAULT_DISCOVERY_SOURCES = [
    Source.YOUTUBE.value,
    Source.BLUESKY.value,
]

# Old default before reddit was removed
_LEGACY_DEFAULT_WITH_REDDIT = [
    Source.YOUTUBE.value,
    "reddit",
    Source.BLUESKY.value,
]


def _parse_sources(raw: str | None) -> list[Source]:
    """Deserialize a JSON source list, dropping any unrecognised values."""
    names = load_json_string_list(
        raw
        or dump_json([source.value for source in DEFAULT_DISCOVERY_SOURCES])
    )
    # Upgrade legacy source lists that pre-date Twitch support (with or
    # without the old Reddit entry which is no longer a valid source).
    if names in (_LEGACY_DEFAULT_DISCOVERY_SOURCES, _LEGACY_DEFAULT_WITH_REDDIT):
        names = [n for n in names if n != "reddit"] + [Source.TWITCH.value]
    valid = set(Source)
    return [Source(n) for n in names if n in valid]


def _make_slug(name: str, game_id: str) -> str:
    """Generate a URL slug from a game name and its ID."""
    slug_name = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{slug_name}-{game_id[:8]}"


class GameRepository:
    """CRUD operations for the games table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def create(
        self,
        game_id: str,
        user_id: str,
        name: str,
        summary: str | None,
        description: str,
        genre_tags: list[str],
        genre_tag_profile: TagProfile,
        mechanics_tag_profile: TagProfile,
        vibe_tag_profile: TagProfile,
        kindred_tag_profile: TagProfile,
        platform_tags: list[str],
        website_url: str | None,
        discovery_schedule: str = "manual",
    ) -> Game:
        """Insert a new game record."""
        slug = _make_slug(name, game_id)
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO games
                    (game_id, user_id, name, summary, description, slug, genre_tags,
                     genre_tag_profile, mechanics_tag_profile,
                     vibe_tag_profile, kindred_tag_profile,
                     platform_tags, website_url,
                     discovery_schedule, discovery_sources)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    user_id,
                    name,
                    summary,
                    description,
                    slug,
                    dump_json(genre_tags),
                    dump_json(genre_tag_profile.to_json_value()),
                    dump_json(mechanics_tag_profile.to_json_value()),
                    dump_json(vibe_tag_profile.to_json_value()),
                    dump_json(kindred_tag_profile.to_json_value()),
                    dump_json(platform_tags),
                    website_url,
                    discovery_schedule,
                    dump_json(
                        [source.value for source in DEFAULT_DISCOVERY_SOURCES]
                    ),
                ),
            )
        return self.get_by_id(game_id)  # type: ignore[return-value]

    def get_by_id(self, game_id: str) -> Game | None:
        """Fetch a game by primary key."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM games WHERE game_id = ?", (game_id,)
            ).fetchone()
        if row is None:
            return None
        return _row_to_game(row)

    def get_by_slug(self, slug: str) -> Game | None:
        """Fetch a game by its URL slug."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM games WHERE slug = ?", (slug,)
            ).fetchone()
        if row is None:
            return None
        return _row_to_game(row)

    def list_by_user(self, user_id: str) -> list[Game]:
        """Return all active games for a user, newest first."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM games WHERE user_id = ? AND status = 'active' ORDER BY created_at ASC",
                (user_id,),
            ).fetchall()
        return [_row_to_game(r) for r in rows]

    def update(
        self,
        game_id: str,
        *,
        name: str | None = None,
        summary: str | None = None,
        description: str | None = None,
        genre_tags: list[str] | None = None,
        genre_tag_profile: TagProfile | None = None,
        mechanics_tag_profile: TagProfile | None = None,
        vibe_tag_profile: TagProfile | None = None,
        kindred_tag_profile: TagProfile | None = None,
        platform_tags: list[str] | None = None,
        website_url: str | None = None,
        discovery_schedule: str | None = None,
    ) -> Game:
        """Partially update a game record, returning the updated entity."""
        game = self.get_by_id(game_id)
        if game is None:
            raise ValueError(f"Game {game_id} not found.")

        new_name = name if name is not None else game.name
        new_summary = summary if summary is not None else game.summary
        new_desc = description if description is not None else game.description
        new_genre = genre_tags if genre_tags is not None else game.genre_tags
        new_genre_profile = (
            genre_tag_profile
            if genre_tag_profile is not None
            else game.genre_tag_profile
        )
        new_mechanics_profile = (
            mechanics_tag_profile
            if mechanics_tag_profile is not None
            else game.mechanics_tag_profile
        )
        new_vibe_profile = (
            vibe_tag_profile
            if vibe_tag_profile is not None
            else game.vibe_tag_profile
        )
        new_kindred_profile = (
            kindred_tag_profile
            if kindred_tag_profile is not None
            else game.kindred_tag_profile
        )
        new_platform = (
            platform_tags if platform_tags is not None else game.platform_tags
        )
        new_url = website_url if website_url is not None else game.website_url
        new_schedule = (
            discovery_schedule
            if discovery_schedule is not None
            else game.discovery_schedule
        )

        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                UPDATE games
                SET name = ?, summary = ?, description = ?, genre_tags = ?,
                    genre_tag_profile = ?,
                    mechanics_tag_profile = ?, vibe_tag_profile = ?,
                    kindred_tag_profile = ?,
                    platform_tags = ?, website_url = ?, discovery_schedule = ?,
                    updated_at = datetime('now')
                WHERE game_id = ?
                """,
                (
                    new_name,
                    new_summary,
                    new_desc,
                    dump_json(new_genre),
                    dump_json(new_genre_profile.to_json_value()),
                    dump_json(new_mechanics_profile.to_json_value()),
                    dump_json(new_vibe_profile.to_json_value()),
                    dump_json(new_kindred_profile.to_json_value()),
                    dump_json(new_platform),
                    new_url,
                    new_schedule,
                    game_id,
                ),
            )
        return self.get_by_id(game_id)  # type: ignore[return-value]

    def count_by_user(self, user_id: str) -> int:
        """Return the number of active games owned by a user."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM games WHERE user_id = ? AND status = 'active'",
                (user_id,),
            ).fetchone()
        return row[0] if row else 0

    def delete(self, game_id: str) -> None:
        """Hard-delete a game and all its related data (cascaded by FK)."""
        with get_connection(self._db_path) as conn:
            conn.execute("DELETE FROM games WHERE game_id = ?", (game_id,))

    def duplicate(
        self, source_game_id: str, new_game_id: str, new_name: str
    ) -> Game:
        """Insert a copy of a game with a new ID and name."""
        source = self.get_by_id(source_game_id)
        if source is None:
            raise ValueError(f"Game {source_game_id} not found.")
        new_slug = _make_slug(new_name, new_game_id)
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO games
                    (game_id, user_id, name, summary, description, slug, genre_tags,
                     genre_tag_profile, mechanics_tag_profile,
                     vibe_tag_profile, kindred_tag_profile,
                     platform_tags, website_url,
                     discovery_schedule, discovery_sources)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_game_id,
                    source.user_id,
                    new_name,
                    source.summary,
                    source.description,
                    new_slug,
                    dump_json(source.genre_tags),
                    dump_json(source.genre_tag_profile.to_json_value()),
                    dump_json(source.mechanics_tag_profile.to_json_value()),
                    dump_json(source.vibe_tag_profile.to_json_value()),
                    dump_json(source.kindred_tag_profile.to_json_value()),
                    dump_json(source.platform_tags),
                    source.website_url,
                    source.discovery_schedule,
                    dump_json([s.value for s in source.discovery_sources]),
                ),
            )
        return self.get_by_id(new_game_id)  # type: ignore[return-value]

    def list_by_schedule(self, schedule: str) -> list[Game]:
        """Return all active games with the given discovery_schedule."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM games WHERE discovery_schedule = ? AND status = 'active'",
                (schedule,),
            ).fetchall()
        return [_row_to_game(row) for row in rows]


class AssetRepository:
    """CRUD operations for the assets table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def create(
        self,
        asset_id: str,
        game_id: str,
        asset_type: str,
        title: str,
        body: str | None,
        url: str | None,
    ) -> Asset:
        """Insert a new asset."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO assets (asset_id, game_id, asset_type, title, body, url)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (asset_id, game_id, asset_type, title, body, url),
            )
        return self.get_by_id(asset_id)  # type: ignore[return-value]

    def get_by_id(self, asset_id: str) -> Asset | None:
        """Fetch an asset by primary key."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        if row is None:
            return None
        return _row_to_asset(row)

    def list_by_game(self, game_id: str) -> list[Asset]:
        """Return all assets for a game."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM assets WHERE game_id = ? ORDER BY created_at",
                (game_id,),
            ).fetchall()
        return [_row_to_asset(r) for r in rows]

    def delete(self, asset_id: str) -> None:
        """Delete an asset by ID."""
        with get_connection(self._db_path) as conn:
            conn.execute("DELETE FROM assets WHERE asset_id = ?", (asset_id,))


class MessageTemplateRepository:
    """CRUD operations for the message_templates table."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def create(
        self,
        template_id: str,
        game_id: str,
        name: str,
        channel: str,
        subject_template: str | None,
        body_template: str,
    ) -> MessageTemplate:
        """Insert a new message template."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO message_templates
                    (template_id, game_id, name, channel, subject_template, body_template)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    template_id,
                    game_id,
                    name,
                    channel,
                    subject_template,
                    body_template,
                ),
            )
        return self.get_by_id(template_id)  # type: ignore[return-value]

    def get_by_id(self, template_id: str) -> MessageTemplate | None:
        """Fetch a template by primary key."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM message_templates WHERE template_id = ?",
                (template_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_template(row)

    def list_by_game(self, game_id: str) -> list[MessageTemplate]:
        """Return all templates for a game, ordered by creation date."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM message_templates WHERE game_id = ? ORDER BY created_at",
                (game_id,),
            ).fetchall()
        return [_row_to_template(r) for r in rows]

    def list_by_game_and_channel(
        self, game_id: str, channel: str
    ) -> list[MessageTemplate]:
        """Return templates matching a specific channel."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM message_templates
                WHERE game_id = ? AND channel = ?
                ORDER BY created_at
                """,
                (game_id, channel),
            ).fetchall()
        return [_row_to_template(r) for r in rows]

    def delete(self, template_id: str) -> None:
        """Delete a template by ID."""
        with get_connection(self._db_path) as conn:
            conn.execute(
                "DELETE FROM message_templates WHERE template_id = ?",
                (template_id,),
            )


# ---------------------------------------------------------------------------
# Row converters
# ---------------------------------------------------------------------------


def _row_to_game(row: sqlite3.Row) -> Game:
    game_id = row["game_id"]
    name = row["name"]
    slug = row["slug"] or _make_slug(name, game_id)
    genre_tags = load_json_string_list(row["genre_tags"])
    row_keys = set(row.keys())
    genre_profile = (
        TagProfile.from_json_value(load_json_object(row["genre_tag_profile"]))
        if "genre_tag_profile" in row_keys
        else TagProfile.empty()
    )
    mechanics_profile = (
        TagProfile.from_json_value(
            load_json_object(row["mechanics_tag_profile"])
        )
        if "mechanics_tag_profile" in row_keys
        else TagProfile.empty()
    )
    vibe_profile = (
        TagProfile.from_json_value(load_json_object(row["vibe_tag_profile"]))
        if "vibe_tag_profile" in row_keys
        else TagProfile.empty()
    )
    kindred_profile = (
        TagProfile.from_json_value(
            load_json_object(row["kindred_tag_profile"])
        )
        if "kindred_tag_profile" in row_keys
        else TagProfile.empty()
    )
    if not genre_profile.all_tags:
        genre_profile = TagProfile.from_flat_tags(
            genre_tags, default_weight=TagWeight.PRIMARY
        )
    return Game(
        game_id=game_id,
        user_id=row["user_id"],
        name=name,
        summary=row["summary"] if "summary" in row_keys else None,
        description=row["description"],
        slug=slug,
        genre_tags=genre_tags,
        platform_tags=load_json_string_list(row["platform_tags"]),
        website_url=row["website_url"],
        discovery_schedule=row["discovery_schedule"]
        if row["discovery_schedule"] is not None
        else "manual",
        discovery_sources=_parse_sources(row["discovery_sources"]),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        genre_tag_profile=genre_profile,
        mechanics_tag_profile=mechanics_profile,
        vibe_tag_profile=vibe_profile,
        kindred_tag_profile=kindred_profile,
    )


def _row_to_asset(row: sqlite3.Row) -> Asset:
    return Asset(
        asset_id=row["asset_id"],
        game_id=row["game_id"],
        asset_type=row["asset_type"],
        title=row["title"],
        body=row["body"],
        url=row["url"],
        created_at=row["created_at"],
    )


def _row_to_template(row: sqlite3.Row) -> MessageTemplate:
    return MessageTemplate(
        template_id=row["template_id"],
        game_id=row["game_id"],
        name=row["name"],
        channel=row["channel"],
        subject_template=row["subject_template"],
        body_template=row["body_template"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
