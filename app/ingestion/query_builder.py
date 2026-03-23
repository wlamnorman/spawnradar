"""Shared search-query builders for ingestion sources."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.games.models import Game

# Probability that the primary genre tag is included in any given query.
_PRIMARY_GENRE_PROB = 0.85
# Probability that a second tag (from secondary genre / mechanics / tone) is
# appended to the query, creating multi-tag combinations like
# "indie roguelite permadeath gameplay".
_SECOND_TAG_PROB = 0.45
# Probability that a modifier prefix ("indie", "best", ...) is prepended.
_PREFIX_PROB = 0.30
# Probability that a query is emitted with no suffix — just the tag(s) alone.
_BARE_PROB = 0.15


@dataclass(frozen=True)
class SourceTags:
    """The game tag context that produced a particular search query.

    Each field records which tag (if any) drove the query, so the scoring
    engine can grant provenance credit even when the tag words don't appear
    literally in the prospect's profile text.
    """

    genre: str | None = None
    mechanics: str | None = None
    vibe: str | None = None


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
    def source_mechanics_tag(self) -> str | None:
        return self.source_tags.mechanics

    @property
    def source_vibe_tag(self) -> str | None:
        return self.source_tags.vibe


def build_tagged_queries(
    game: Game,
    *,
    suffixes: Sequence[str],
    prefixes: Sequence[str] = ("indie", "best", "top"),
    game_name_suffixes: Sequence[str] = (),
    n_queries: int = 25,
    run_index: int = 0,
) -> list[TaggedQuery]:
    """Build randomised search queries by composing tag components.

    Each query is assembled from optional pieces:
        [prefix?]  [primary genre tag?]  [second tag?]  [suffix?]

    For example:
        "indie roguelite permadeath gameplay"
        "roguelite dark fantasy game review"
        "best deckbuilder games"
        "roguelite streamer"
        "permadeath games"

    Primary genre tags appear in ~85% of queries. A second tag drawn from
    secondary genre, mechanics, or tone appears in ~45%. A prefix appears
    in ~30%. A small fraction (~15%) emit bare tag(s) with no suffix.

    The RNG is seeded from game_id + run_index so selection varies across
    runs but is reproducible for any given run.
    """
    rng = random.Random(f"{game.game_id}:{run_index}")

    primary_genre = list(game.genre_primary_tags)
    optional_pool: list[tuple[str, str]] = [
        *[("genre", t) for t in game.genre_secondary_tags],
        *[("mechanics", t) for t in game.ordered_mechanics_tags()],
        *[("vibe", t) for t in game.ordered_vibe_tags()],
    ]

    queries: list[TaggedQuery] = []
    seen: set[str] = set()

    def add(text: str, source_tags: SourceTags) -> None:
        cleaned = text.strip()
        if not cleaned or cleaned.lower() in seen:
            return
        seen.add(cleaned.lower())
        queries.append(TaggedQuery(text=cleaned, source_tags=source_tags))

    for _ in range(n_queries):
        parts: list[str] = []
        genre_tag: str | None = None
        mechanics_tag: str | None = None
        vibe_tag: str | None = None

        # Optional prefix
        if prefixes and rng.random() < _PREFIX_PROB:
            parts.append(rng.choice(list(prefixes)))

        # Primary genre tag
        if primary_genre and rng.random() < _PRIMARY_GENRE_PROB:
            genre_tag = rng.choice(primary_genre)
            parts.append(genre_tag)

        # Optional second tag from a different dimension
        if optional_pool and rng.random() < _SECOND_TAG_PROB:
            dim, tag = rng.choice(optional_pool)
            if tag not in parts:
                parts.append(tag)
                if dim == "genre" and not genre_tag:
                    genre_tag = tag
                elif dim == "mechanics":
                    mechanics_tag = tag
                elif dim == "vibe":
                    vibe_tag = tag

        if not parts:
            continue

        # Suffix — omitted for bare-tag queries
        if suffixes and rng.random() > _BARE_PROB:
            parts.append(rng.choice(list(suffixes)))

        add(
            " ".join(parts),
            SourceTags(genre=genre_tag, mechanics=mechanics_tag, vibe=vibe_tag),
        )

    # Game name queries always appended
    add(game.name, SourceTags())
    for suffix in game_name_suffixes:
        add(f"{game.name} {suffix}", SourceTags())

    return queries


def build_basic_queries(
    game: Game,
    *,
    include_game_name: bool = True,
    run_index: int = 0,
) -> list[str]:
    """Build simple deduplicated keyword queries from game tags."""
    base_queries = list(game.ordered_genre_tags())
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
