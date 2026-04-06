"""Business logic for customer game creation and tag management."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.games.constants import MAX_DESCRIPTION_LENGTH, MAX_SUMMARY_LENGTH
from app.games.models import CustomerGame
from app.games.repository import (
    CustomerGameRepository,
)

if TYPE_CHECKING:
    from app.metrics.service import MetricsService

log = logging.getLogger(__name__)

MAX_GENRES = 5  # IGDB genres + genre keywords combined
MAX_THEMES = 3  # IGDB themes + theme keywords combined
MAX_MECHANICS = 3
MAX_SIMILAR_GAMES = 8


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
    if len(normalized_summary) > MAX_SUMMARY_LENGTH:
        raise ValueError(
            f"Game summary must be {MAX_SUMMARY_LENGTH} characters or fewer."
        )
    if len(normalized_description) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(
            f"Game description must be {MAX_DESCRIPTION_LENGTH} characters or fewer."
        )

    return normalized_name, normalized_summary, normalized_description


def _validate_tag_limits(
    *,
    igdb_genre_ids: list[int] | None,
    igdb_theme_ids: list[int] | None,
    igdb_keyword_ids: list[str] | None,
    similar_game_names: list[str] | None,
) -> None:
    """Enforce maximum tag counts to prevent over-tagging.

    Genre and theme limits count IGDB tags + keyword tags together —
    to the customer they're all just "genres" and "themes".
    """
    from app.igdb.keyword_groups import IGDB_KEYWORD_GROUPS, IGDBKeywordBucket

    if similar_game_names and len(similar_game_names) > MAX_SIMILAR_GAMES:
        raise ValueError(
            f"At most {MAX_SIMILAR_GAMES} similar games can be provided."
        )

    # Count keywords per bucket
    genre_kw = 0
    theme_kw = 0
    mechanic_kw = 0
    if igdb_keyword_ids:
        bucket_lookup = {kw.canonical: kw.bucket for kw in IGDB_KEYWORD_GROUPS}
        for kid in igdb_keyword_ids:
            bucket = bucket_lookup.get(kid)
            if bucket == IGDBKeywordBucket.GENRE:
                genre_kw += 1
            elif bucket == IGDBKeywordBucket.THEME:
                theme_kw += 1
            elif bucket == IGDBKeywordBucket.MECHANIC:
                mechanic_kw += 1

    # Combined totals: IGDB tags + keyword tags
    total_genres = len(igdb_genre_ids or []) + genre_kw
    total_themes = len(igdb_theme_ids or []) + theme_kw

    if total_genres > MAX_GENRES:
        raise ValueError(
            f"At most {MAX_GENRES} genres can be selected (you have {total_genres})."
        )
    if total_themes > MAX_THEMES:
        raise ValueError(
            f"At most {MAX_THEMES} themes can be selected (you have {total_themes})."
        )
    if mechanic_kw > MAX_MECHANICS:
        raise ValueError(f"At most {MAX_MECHANICS} mechanics can be selected.")


class CustomerGameService:
    """Handles customer game creation, updates and tag management."""

    def __init__(
        self,
        customer_game_repo: CustomerGameRepository,
        metrics_service: MetricsService | None = None,
        on_game_changed: Callable[[str], None] | None = None,
    ) -> None:
        self._customer_games = customer_game_repo
        self._metrics = metrics_service
        self._on_game_changed = on_game_changed

    def set_on_game_changed(self, callback: Callable[[str], None]) -> None:
        """Set the callback fired after a game is created or updated.

        Used by ``main.py`` to wire the scheduler after the service is
        already constructed.
        """
        self._on_game_changed = callback

    def create_game(
        self,
        name: str,
        description: str,
        website_url: str | None,
        summary: str = "",
        platforms: list[str] | None = None,
        igdb_genre_ids: list[int] | None = None,
        igdb_theme_ids: list[int] | None = None,
        igdb_game_mode_ids: list[int] | None = None,
        igdb_player_perspective_ids: list[int] | None = None,
        igdb_keyword_ids: list[str] | None = None,
        similar_game_names: list[str] | None = None,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> CustomerGame:
        """Create and persist a new customer game."""
        owner_workspace_id = workspace_id or user_id
        if owner_workspace_id is None:
            raise ValueError("workspace_id is required.")
        genres = igdb_genre_ids or []
        keywords = igdb_keyword_ids or []
        normalized_name, normalized_summary, normalized_description = (
            _validate_game_text_fields(name, summary, description)
        )

        if not genres:
            raise ValueError("At least one IGDB genre is required.")
        _validate_tag_limits(
            igdb_genre_ids=genres,
            igdb_theme_ids=igdb_theme_ids,
            igdb_keyword_ids=keywords,
            similar_game_names=similar_game_names,
        )

        customer_game_id = str(uuid.uuid4())
        customer_game = self._customer_games.create(
            customer_game_id=customer_game_id,
            workspace_id=owner_workspace_id,
            name=normalized_name,
            summary=normalized_summary,
            description=normalized_description,
            website_url=_normalize_url(website_url),
            platforms=platforms,
            igdb_genre_ids=genres,
            igdb_theme_ids=igdb_theme_ids,
            igdb_game_mode_ids=igdb_game_mode_ids,
            igdb_player_perspective_ids=igdb_player_perspective_ids,
            igdb_keyword_ids=keywords,
            similar_game_names=similar_game_names,
        )
        if self._metrics is not None:
            self._metrics.record_game_created(
                user_id=user_id,
                workspace_id=owner_workspace_id,
                customer_game_id=customer_game.customer_game_id,
                occurred_at=customer_game.created_at,
            )
        self._notify_game_changed(customer_game.customer_game_id)
        return customer_game

    def update_game(
        self,
        customer_game_id: str,
        name: str,
        description: str,
        website_url: str | None,
        summary: str = "",
        platforms: list[str] | None = None,
        igdb_genre_ids: list[int] | None = None,
        igdb_theme_ids: list[int] | None = None,
        igdb_game_mode_ids: list[int] | None = None,
        igdb_player_perspective_ids: list[int] | None = None,
        igdb_keyword_ids: list[str] | None = None,
        similar_game_names: list[str] | None = None,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> CustomerGame:
        """Update customer game fields, verifying ownership."""
        owner_workspace_id = workspace_id or user_id
        if owner_workspace_id is None:
            raise ValueError("workspace_id is required.")
        customer_game = self._customer_games.get_by_id(customer_game_id)
        if customer_game is None or customer_game.workspace_id != owner_workspace_id:
            raise ValueError("Customer game not found or access denied.")

        genres = igdb_genre_ids or []
        keywords = igdb_keyword_ids or []
        normalized_name, normalized_summary, normalized_description = (
            _validate_game_text_fields(name, summary, description)
        )

        if not genres:
            raise ValueError("At least one IGDB genre is required.")
        _validate_tag_limits(
            igdb_genre_ids=genres,
            igdb_theme_ids=igdb_theme_ids,
            igdb_keyword_ids=keywords,
            similar_game_names=similar_game_names,
        )

        updated = self._customer_games.update(
            customer_game_id,
            name=normalized_name,
            summary=normalized_summary,
            description=normalized_description,
            website_url=_normalize_url(website_url),
            platforms=platforms,
            igdb_genre_ids=genres,
            igdb_theme_ids=igdb_theme_ids,
            igdb_game_mode_ids=igdb_game_mode_ids,
            igdb_player_perspective_ids=igdb_player_perspective_ids,
            igdb_keyword_ids=keywords,
            similar_game_names=similar_game_names,
        )
        self._notify_game_changed(customer_game_id)
        return updated

    def delete_game(
        self,
        customer_game_id: str,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        """Permanently delete a customer game and all its associated data."""
        owner_workspace_id = workspace_id or user_id
        if owner_workspace_id is None:
            raise ValueError("workspace_id is required.")
        customer_game = self._customer_games.get_by_id(customer_game_id)
        if customer_game is None or customer_game.workspace_id != owner_workspace_id:
            raise ValueError("Customer game not found or access denied.")
        if self._metrics is not None:
            self._metrics.record_game_deleted(
                user_id=user_id,
                workspace_id=owner_workspace_id,
                customer_game_id=customer_game.customer_game_id,
                occurred_at=datetime.now(UTC).isoformat(),
            )
        self._customer_games.delete(customer_game_id)

    def duplicate_game(
        self,
        customer_game_id: str,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> CustomerGame:
        """Create a copy of a customer game with all its metadata and no child records."""
        owner_workspace_id = workspace_id or user_id
        if owner_workspace_id is None:
            raise ValueError("workspace_id is required.")
        customer_game = self._customer_games.get_by_id(customer_game_id)
        if customer_game is None or customer_game.workspace_id != owner_workspace_id:
            raise ValueError("Customer game not found or access denied.")
        new_customer_game_id = str(uuid.uuid4())
        new_name = f"Copy of {customer_game.name}"
        new_customer_game = self._customer_games.duplicate(
            source_customer_game_id=customer_game_id,
            new_customer_game_id=new_customer_game_id,
            new_name=new_name,
        )
        if self._metrics is not None:
            self._metrics.record_game_duplicated(
                user_id=user_id,
                workspace_id=owner_workspace_id,
                customer_game_id=new_customer_game.customer_game_id,
                occurred_at=new_customer_game.created_at,
            )
        return new_customer_game

    def _notify_game_changed(self, customer_game_id: str) -> None:
        """Fire the on_game_changed callback if configured."""
        if self._on_game_changed is not None:
            try:
                self._on_game_changed(customer_game_id)
            except Exception:
                log.exception(
                    "on_game_changed callback failed for %s",
                    customer_game_id,
                )
