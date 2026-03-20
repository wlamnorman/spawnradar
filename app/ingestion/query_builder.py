"""Shared search-query builders for ingestion sources."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.games.models import Game


@dataclass(frozen=True)
class TaggedQuery:
    """A search query plus the game tag context that produced it."""

    text: str
    source_genre_tag: str | None = None
    source_audience_tag: str | None = None


def build_tagged_queries(
    game: Game,
    *,
    genre_templates: Sequence[str],
    audience_templates: Sequence[str],
    include_game_name: bool = True,
) -> list[TaggedQuery]:
    """Build deduplicated search queries that preserve source tag context."""
    queries: list[TaggedQuery] = []
    seen: set[str] = set()

    def add(
        text: str,
        source_genre_tag: str | None,
        source_audience_tag: str | None,
    ) -> None:
        cleaned = text.strip()
        lowered = cleaned.lower()
        if not cleaned or lowered in seen:
            return
        seen.add(lowered)
        queries.append(
            TaggedQuery(
                text=cleaned,
                source_genre_tag=source_genre_tag,
                source_audience_tag=source_audience_tag,
            )
        )

    for tag in game.genre_tags:
        for template in genre_templates:
            add(
                template.format(tag=tag, game_name=game.name),
                source_genre_tag=tag,
                source_audience_tag=None,
            )

    for tag in game.audience_tags:
        for template in audience_templates:
            add(
                template.format(tag=tag, game_name=game.name),
                source_genre_tag=None,
                source_audience_tag=tag,
            )

    if include_game_name or not queries:
        add(
            game.name,
            source_genre_tag=None,
            source_audience_tag=None,
        )

    return queries


def build_basic_queries(game: Game) -> list[str]:
    """Build simple deduplicated keyword queries from game tags."""
    queries: list[str] = []
    seen: set[str] = set()

    for query in [*game.genre_tags, *game.audience_tags, game.name]:
        cleaned = query.strip()
        lowered = cleaned.lower()
        if not cleaned or lowered in seen:
            continue
        seen.add(lowered)
        queries.append(cleaned)

    return queries
