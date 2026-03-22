"""Business logic for game creation and tag management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.games.models import (
    Asset,
    DiscoveryReadiness,
    Game,
    MessageTemplate,
)
from app.games.repository import (
    AssetRepository,
    GameRepository,
    MessageTemplateRepository,
)
from app.games.tags import build_tag_profile

if TYPE_CHECKING:
    from app.metrics.service import MetricsService

MAX_SUMMARY_LENGTH = 150
MAX_DESCRIPTION_LENGTH = 1500


def _normalize_url(url: str | None) -> str | None:
    """Prepend https:// if the URL has no scheme."""
    if not url:
        return None
    url = url.strip()
    if url and "://" not in url:
        url = "https://" + url
    return url or None


def _validate_game_text_fields(
    name: str, summary: str, description: str
) -> tuple[str, str, str]:
    normalized_name = name.strip()
    normalized_summary = summary.strip()
    normalized_description = description.strip()

    if not normalized_name:
        raise ValueError("Game name is required.")
    if not normalized_summary:
        raise ValueError("Game summary is required.")
    if not normalized_description:
        raise ValueError("Game description is required.")
    if len(normalized_summary) > MAX_SUMMARY_LENGTH:
        raise ValueError(
            f"Game summary must be {MAX_SUMMARY_LENGTH} characters or fewer."
        )
    if len(normalized_description) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(
            f"Game description must be {MAX_DESCRIPTION_LENGTH} characters or fewer."
        )

    return normalized_name, normalized_summary, normalized_description


class GameService:
    """Handles game creation, updates, and tag management."""

    def __init__(
        self,
        game_repo: GameRepository,
        asset_repo: AssetRepository,
        template_repo: MessageTemplateRepository,
        metrics_service: MetricsService | None = None,
    ) -> None:
        self._games = game_repo
        self._assets = asset_repo
        self._templates = template_repo
        self._metrics = metrics_service

    def get_discovery_readiness(self, game: Game) -> DiscoveryReadiness:
        """Return whether a game has enough setup data for discovery."""
        missing_fields: list[str] = []
        if not game.name.strip():
            missing_fields.append("game name")
        if not (game.summary or "").strip():
            missing_fields.append("summary")
        if not game.description.strip():
            missing_fields.append("description")
        if not game.genre_primary_tags:
            missing_fields.append("primary genre tags")
        return DiscoveryReadiness(
            can_run=not missing_fields,
            missing_fields=tuple(missing_fields),
        )

    def require_discovery_ready(self, game: Game) -> None:
        """Raise when a game is too incomplete for useful discovery."""
        readiness = self.get_discovery_readiness(game)
        if not readiness.can_run:
            raise ValueError(readiness.message)

    def create_game(
        self,
        user_id: str,
        name: str,
        description: str,
        genre_tags_raw: str,
        audience_tags_raw: str,
        platform_tags: list[str],
        website_url: str | None,
        summary: str = "",
        genre_primary_tags_raw: str = "",
        genre_secondary_tags_raw: str = "",
        genre_custom_tags_raw: str = "",
        audience_primary_tags_raw: str = "",
        audience_secondary_tags_raw: str = "",
        audience_custom_tags_raw: str = "",
        mechanics_primary_tags_raw: str = "",
        mechanics_secondary_tags_raw: str = "",
        tone_primary_tags_raw: str = "",
        tone_secondary_tags_raw: str = "",
    ) -> Game:
        """Create and persist a new game."""
        normalized_name, normalized_summary, normalized_description = (
            _validate_game_text_fields(name, summary, description)
        )

        game_id = str(uuid.uuid4())
        genre_profile = build_tag_profile(
            "genre",
            primary_raw=genre_primary_tags_raw,
            secondary_raw=genre_secondary_tags_raw,
            custom_raw=genre_custom_tags_raw,
            legacy_raw=genre_tags_raw,
        )
        audience_profile = build_tag_profile(
            "audience",
            primary_raw=audience_primary_tags_raw,
            secondary_raw=audience_secondary_tags_raw,
            custom_raw=audience_custom_tags_raw,
            legacy_raw=audience_tags_raw,
        )
        mechanics_profile = build_tag_profile(
            "mechanics",
            primary_raw=mechanics_primary_tags_raw,
            secondary_raw=mechanics_secondary_tags_raw,
        )
        tone_profile = build_tag_profile(
            "tone",
            primary_raw=tone_primary_tags_raw,
            secondary_raw=tone_secondary_tags_raw,
        )
        if not genre_profile.primary:
            raise ValueError("At least one primary genre tag is required.")
        game = self._games.create(
            game_id=game_id,
            user_id=user_id,
            name=normalized_name,
            summary=normalized_summary,
            description=normalized_description,
            genre_tags=genre_profile.all_tags,
            audience_tags=audience_profile.all_tags,
            genre_tag_profile=genre_profile,
            audience_tag_profile=audience_profile,
            mechanics_tag_profile=mechanics_profile,
            tone_tag_profile=tone_profile,
            platform_tags=platform_tags,
            website_url=_normalize_url(website_url),
        )
        if self._metrics is not None:
            self._metrics.record_game_created(
                user_id=user_id,
                game_id=game.game_id,
                occurred_at=game.created_at,
            )
        return game

    def update_game(
        self,
        game_id: str,
        user_id: str,
        name: str,
        description: str,
        genre_tags_raw: str,
        audience_tags_raw: str,
        platform_tags: list[str],
        website_url: str | None,
        summary: str = "",
        genre_primary_tags_raw: str = "",
        genre_secondary_tags_raw: str = "",
        genre_custom_tags_raw: str = "",
        audience_primary_tags_raw: str = "",
        audience_secondary_tags_raw: str = "",
        audience_custom_tags_raw: str = "",
        mechanics_primary_tags_raw: str = "",
        mechanics_secondary_tags_raw: str = "",
        tone_primary_tags_raw: str = "",
        tone_secondary_tags_raw: str = "",
    ) -> Game:
        """Update game fields, verifying ownership."""
        game = self._games.get_by_id(game_id)
        if game is None or game.user_id != user_id:
            raise ValueError("Game not found or access denied.")

        normalized_name, normalized_summary, normalized_description = (
            _validate_game_text_fields(name, summary, description)
        )

        genre_profile = build_tag_profile(
            "genre",
            primary_raw=genre_primary_tags_raw,
            secondary_raw=genre_secondary_tags_raw,
            custom_raw=genre_custom_tags_raw,
            legacy_raw=genre_tags_raw,
        )
        audience_profile = build_tag_profile(
            "audience",
            primary_raw=audience_primary_tags_raw,
            secondary_raw=audience_secondary_tags_raw,
            custom_raw=audience_custom_tags_raw,
            legacy_raw=audience_tags_raw,
        )
        mechanics_profile = build_tag_profile(
            "mechanics",
            primary_raw=mechanics_primary_tags_raw,
            secondary_raw=mechanics_secondary_tags_raw,
        )
        tone_profile = build_tag_profile(
            "tone",
            primary_raw=tone_primary_tags_raw,
            secondary_raw=tone_secondary_tags_raw,
        )
        if not genre_profile.primary:
            raise ValueError("At least one primary genre tag is required.")
        return self._games.update(
            game_id,
            name=normalized_name,
            summary=normalized_summary,
            description=normalized_description,
            genre_tags=genre_profile.all_tags,
            audience_tags=audience_profile.all_tags,
            genre_tag_profile=genre_profile,
            audience_tag_profile=audience_profile,
            mechanics_tag_profile=mechanics_profile,
            tone_tag_profile=tone_profile,
            platform_tags=platform_tags,
            website_url=_normalize_url(website_url),
        )

    def add_template(
        self,
        game_id: str,
        user_id: str,
        name: str,
        channel: str,
        subject_template: str | None,
        body_template: str,
    ) -> MessageTemplate:
        """Add a message template to a game."""
        game = self._games.get_by_id(game_id)
        if game is None or game.user_id != user_id:
            raise ValueError("Game not found or access denied.")

        template_id = str(uuid.uuid4())
        template = self._templates.create(
            template_id=template_id,
            game_id=game_id,
            name=name.strip(),
            channel=channel,
            subject_template=subject_template or None,
            body_template=body_template,
        )
        if self._metrics is not None:
            self._metrics.record_message_template_created(
                user_id=user_id,
                game_id=game_id,
                occurred_at=template.created_at,
            )
        return template

    def delete_template(
        self, template_id: str, game_id: str, user_id: str
    ) -> None:
        """Delete a template, verifying game ownership."""
        game = self._games.get_by_id(game_id)
        if game is None or game.user_id != user_id:
            raise ValueError("Game not found or access denied.")
        self._templates.delete(template_id)

    def add_asset(
        self,
        game_id: str,
        user_id: str,
        asset_type: str,
        title: str,
        body: str | None,
        url: str | None,
    ) -> Asset:
        """Add a promotional asset to a game."""
        game = self._games.get_by_id(game_id)
        if game is None or game.user_id != user_id:
            raise ValueError("Game not found or access denied.")

        asset_id = str(uuid.uuid4())
        return self._assets.create(
            asset_id=asset_id,
            game_id=game_id,
            asset_type=asset_type,
            title=title.strip(),
            body=body or None,
            url=url or None,
        )

    def delete_game(self, game_id: str, user_id: str) -> None:
        """Permanently delete a game and all its associated data."""
        game = self._games.get_by_id(game_id)
        if game is None or game.user_id != user_id:
            raise ValueError("Game not found or access denied.")
        if self._metrics is not None:
            self._metrics.record_game_deleted(
                user_id=user_id,
                game_id=game.game_id,
                occurred_at=datetime.now(UTC).isoformat(),
            )
        self._games.delete(game_id)

    def duplicate_game(self, game_id: str, user_id: str) -> Game:
        """Create a copy of a game with all its metadata but an empty queue."""
        game = self._games.get_by_id(game_id)
        if game is None or game.user_id != user_id:
            raise ValueError("Game not found or access denied.")
        new_game_id = str(uuid.uuid4())
        new_name = f"Copy of {game.name}"
        new_game = self._games.duplicate(game_id, new_game_id, new_name)
        if self._metrics is not None:
            self._metrics.record_game_duplicated(
                user_id=user_id,
                game_id=new_game.game_id,
                occurred_at=new_game.created_at,
            )
        return new_game

    def delete_asset(self, asset_id: str, game_id: str, user_id: str) -> None:
        """Delete an asset, verifying game ownership."""
        game = self._games.get_by_id(game_id)
        if game is None or game.user_id != user_id:
            raise ValueError("Game not found or access denied.")
        self._assets.delete(asset_id)
