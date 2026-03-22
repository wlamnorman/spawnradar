"""Shared search-query builders for ingestion sources."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.games.models import Game


@dataclass(frozen=True)
class SourceTags:
    """The game tag context that produced a particular search query.

    Each field records which tag (if any) drove the query, so the scoring
    engine can grant provenance credit even when the tag words don't appear
    literally in the prospect's profile text.
    """

    genre: str | None = None
    audience: str | None = None
    mechanics: str | None = None
    tone: str | None = None


@dataclass(frozen=True)
class TaggedQuery:
    """A search query plus the game tag context that produced it."""

    text: str
    source_tags: SourceTags = field(default_factory=SourceTags)

    # Convenience properties kept for backward-compat with scoring engine
    @property
    def source_genre_tag(self) -> str | None:
        return self.source_tags.genre

    @property
    def source_audience_tag(self) -> str | None:
        return self.source_tags.audience

    @property
    def source_mechanics_tag(self) -> str | None:
        return self.source_tags.mechanics

    @property
    def source_tone_tag(self) -> str | None:
        return self.source_tags.tone


def build_tagged_queries(
    game: Game,
    *,
    genre_templates: Sequence[str],
    audience_templates: Sequence[str],
    mechanics_templates: Sequence[str] = (),
    tone_templates: Sequence[str] = (),
    game_name_templates: Sequence[str] = (),
    include_game_name: bool = True,
    run_index: int = 0,
) -> list[TaggedQuery]:
    """Build deduplicated search queries that preserve source tag context."""
    queries: list[TaggedQuery] = []
    seen: set[str] = set()

    genre_tags = _rotate(game.ordered_genre_tags(), run_index)
    audience_tags = _rotate(game.ordered_audience_tags(), run_index)
    mechanics_tags = _rotate(game.ordered_mechanics_tags(), run_index)
    tone_tags = _rotate(game.ordered_tone_tags(), run_index)
    rotated_genre_templates = _rotate(list(genre_templates), run_index)
    rotated_audience_templates = _rotate(list(audience_templates), run_index)
    rotated_mechanics_templates = _rotate(list(mechanics_templates), run_index)
    rotated_tone_templates = _rotate(list(tone_templates), run_index)
    rotated_name_templates = _rotate(list(game_name_templates), run_index)

    def add(text: str, source_tags: SourceTags) -> None:
        cleaned = text.strip()
        lowered = cleaned.lower()
        if not cleaned or lowered in seen:
            return
        seen.add(lowered)
        queries.append(TaggedQuery(text=cleaned, source_tags=source_tags))

    for tag in genre_tags:
        for template in rotated_genre_templates:
            add(
                template.format(tag=tag, game_name=game.name),
                SourceTags(genre=tag),
            )

    for tag in audience_tags:
        for template in rotated_audience_templates:
            add(
                template.format(tag=tag, game_name=game.name),
                SourceTags(audience=tag),
            )

    for tag in mechanics_tags:
        for template in rotated_mechanics_templates:
            add(
                template.format(tag=tag, game_name=game.name),
                SourceTags(mechanics=tag),
            )

    for tag in tone_tags:
        for template in rotated_tone_templates:
            add(
                template.format(tag=tag, game_name=game.name),
                SourceTags(tone=tag),
            )

    if include_game_name or not queries:
        templates = rotated_name_templates or ["{game_name}"]
        for template in templates:
            add(template.format(game_name=game.name), SourceTags())

    return queries


def build_basic_queries(
    game: Game,
    *,
    include_game_name: bool = True,
    run_index: int = 0,
) -> list[str]:
    """Build simple deduplicated keyword queries from game tags."""
    base_queries = [
        *game.ordered_genre_tags(),
        *game.ordered_audience_tags(),
    ]
    if include_game_name:
        base_queries.append(game.name)

    queries: list[str] = []
    seen: set[str] = set()

    for query in _rotate(base_queries, run_index):
        cleaned = query.strip()
        lowered = cleaned.lower()
        if not cleaned or lowered in seen:
            continue
        seen.add(lowered)
        queries.append(cleaned)

    return queries


def _rotate(values: Sequence[str], run_index: int) -> list[str]:
    if not values:
        return []
    offset = run_index % len(values)
    rotated = list(values[offset:]) + list(values[:offset])
    return rotated
