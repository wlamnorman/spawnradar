"""Business logic for game creation and tag management."""
from __future__ import annotations

import uuid

from app.games.models import Asset, Game, MessageTemplate
from app.games.repository import (
    AssetRepository,
    GameRepository,
    MessageTemplateRepository,
)


def _parse_tags(raw: str) -> list[str]:
    """Split a comma-separated tag string into a clean list."""
    return [t.strip() for t in raw.split(",") if t.strip()]


def _normalize_url(url: str | None) -> str | None:
    """Prepend https:// if the URL has no scheme."""
    if not url:
        return None
    url = url.strip()
    if url and "://" not in url:
        url = "https://" + url
    return url or None


class GameService:
    """Handles game creation, updates, and tag management."""

    def __init__(
        self,
        game_repo: GameRepository,
        asset_repo: AssetRepository,
        template_repo: MessageTemplateRepository,
    ) -> None:
        self._games = game_repo
        self._assets = asset_repo
        self._templates = template_repo

    def create_game(
        self,
        user_id: str,
        name: str,
        description: str,
        genre_tags_raw: str,
        audience_tags_raw: str,
        platform_tags: list[str],
        website_url: str | None,
        discovery_schedule: str = "manual",
    ) -> Game:
        """Create and persist a new game."""
        if not name.strip():
            raise ValueError("Game name is required.")
        if not description.strip():
            raise ValueError("Game description is required.")

        game_id = str(uuid.uuid4())
        return self._games.create(
            game_id=game_id,
            user_id=user_id,
            name=name.strip(),
            description=description.strip(),
            genre_tags=_parse_tags(genre_tags_raw),
            audience_tags=_parse_tags(audience_tags_raw),
            platform_tags=platform_tags,
            website_url=_normalize_url(website_url),
            discovery_schedule=discovery_schedule,
        )

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
        discovery_schedule: str = "manual",
    ) -> Game:
        """Update game fields, verifying ownership."""
        game = self._games.get_by_id(game_id)
        if game is None or game.user_id != user_id:
            raise ValueError("Game not found or access denied.")

        return self._games.update(
            game_id,
            name=name.strip(),
            description=description.strip(),
            genre_tags=_parse_tags(genre_tags_raw),
            audience_tags=_parse_tags(audience_tags_raw),
            platform_tags=platform_tags,
            website_url=_normalize_url(website_url),
            discovery_schedule=discovery_schedule,
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
        return self._templates.create(
            template_id=template_id,
            game_id=game_id,
            name=name.strip(),
            channel=channel,
            subject_template=subject_template or None,
            body_template=body_template,
        )

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

    def delete_asset(
        self, asset_id: str, game_id: str, user_id: str
    ) -> None:
        """Delete an asset, verifying game ownership."""
        game = self._games.get_by_id(game_id)
        if game is None or game.user_id != user_id:
            raise ValueError("Game not found or access denied.")
        self._assets.delete(asset_id)
