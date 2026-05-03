"""Helpers for matching creator played games to customer games.

Coverage is the primary ranking score; overlap is characterization only.
Both use a saturating piecewise evidence curve.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.games.models import CustomerGame
from app.igdb.keyword_groups import RAW_IGDB_KEYWORD_TO_CANONICAL
from app.igdb.taxonomy import (
    IGDBGenre,
    IGDBTheme,
    keyword_bucket_for_value,
    keyword_label_for_value,
)

TagKey = tuple[str, int | str]
TagCounts = dict[TagKey, int]

GENRE_WEIGHT = 3
THEME_WEIGHT = 1
MECHANIC_WEIGHT = 1


# ---------------------------------------------------------------------------
# Evidence function
# ---------------------------------------------------------------------------


def tag_evidence(distinct_games_count: int) -> float:
    """Map distinct supporting games to capped evidence."""
    if distinct_games_count <= 0:
        return 0.0
    elif distinct_games_count == 1:
        return 0.93
    elif distinct_games_count == 2:
        return 0.967
    else:
        return 1.0


# ---------------------------------------------------------------------------
# Tag helpers
# ---------------------------------------------------------------------------


def customer_game_tag_counts(customer_game: CustomerGame) -> TagCounts:
    """Return customer-game tags in shared IGDB tag space."""
    counts: TagCounts = {}
    for tag_id in customer_game.igdb_genre_ids:
        counts[("genre", int(tag_id))] = 1
    for tag_id in customer_game.igdb_theme_ids:
        counts[("theme", int(tag_id))] = 1
    official_genre_labels = {
        label.casefold()
        for label in IGDBGenre.labels_for_ids(customer_game.igdb_genre_ids)
    }
    official_theme_labels = {
        label.casefold()
        for label in IGDBTheme.labels_for_ids(customer_game.igdb_theme_ids)
    }
    for keyword in customer_game.igdb_keyword_ids:
        bucket = keyword_bucket_for_value(keyword)
        label = keyword_label_for_value(keyword)
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
        counts[(bucket.value, str(keyword))] = 1
    return counts


def customer_game_tag_keys(customer_game: CustomerGame) -> tuple[TagKey, ...]:
    """Return the unified customer-game tag keys used for queries/ranking."""
    return tuple(customer_game_tag_counts(customer_game))


def tag_weight(tag_key: TagKey) -> float:
    """Return the importance weight for a tag key."""
    kind = tag_key[0]
    if kind == "genre":
        return GENRE_WEIGHT
    if kind == "mechanic":
        return MECHANIC_WEIGHT
    return THEME_WEIGHT


def canonicalize_keyword(raw: str) -> str | None:
    """Map a raw IGDB keyword to its canonical form or ``None`` if unknown.

    Use this when building creator tag profiles from observed IGDB game
    keywords.  For example, ``"deck-building"`` → ``"deckbuilder"``.
    """
    return RAW_IGDB_KEYWORD_TO_CANONICAL.get(raw)


# ---------------------------------------------------------------------------
# Coverage & overlap
# ---------------------------------------------------------------------------


def compute_coverage(
    customer_game: CustomerGame,
    creator_tag_counts: TagCounts,
) -> float:
    """Primary ranking score: how much of the target game's identity is
    covered by the creator's observed games.

    Returns a value in [0.0, 1.0].
    """
    target_tags = customer_game_tag_counts(customer_game)
    if not target_tags or not creator_tag_counts:
        return 0.0

    numerator = 0.0
    denominator = 0.0
    for tag_key in target_tags:
        w = tag_weight(tag_key)
        denominator += w
        creator_count = creator_tag_counts.get(tag_key, 0)
        numerator += w * tag_evidence(creator_count)

    if denominator == 0.0:
        return 0.0
    return numerator / denominator


def compute_overlap(
    customer_game: CustomerGame,
    creator_tag_counts: TagCounts,
    creator_all_tag_counts: TagCounts,
) -> float:
    """Creator characterization: how concentrated the creator's broader
    tag profile is in the target neighbourhood.
    """
    target_tags = customer_game_tag_counts(customer_game)
    if not target_tags or not creator_all_tag_counts:
        return 0.0

    # overlap_weight: weighted evidence for target tags only
    overlap_weight = 0.0
    for tag_key in target_tags:
        w = tag_weight(tag_key)
        creator_count = creator_tag_counts.get(tag_key, 0)
        overlap_weight += w * tag_evidence(creator_count)

    # creator_relevant_weight: weighted evidence across ALL creator tags
    creator_relevant_weight = 0.0
    for tag_key, count in creator_all_tag_counts.items():
        w = tag_weight(tag_key)
        creator_relevant_weight += w * tag_evidence(count)

    if creator_relevant_weight == 0.0:
        return 0.0
    return overlap_weight / creator_relevant_weight


# ---------------------------------------------------------------------------
# Match summary used by ranking surfaces
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProfileGameMatch:
    """Coverage-driven match result for one creator profile against one game."""

    coverage_score: float
    overlap_tags: tuple[TagKey, ...]


def match_creator_tags_to_game(
    customer_game: CustomerGame,
    *,
    creator_tag_counts: TagCounts,
) -> ProfileGameMatch:
    """Return the primary coverage score plus the overlapping tag keys."""
    cg_tag_counts = customer_game_tag_counts(customer_game)
    if not cg_tag_counts or not creator_tag_counts:
        return ProfileGameMatch(coverage_score=0.0, overlap_tags=())

    overlap_keys = tuple(
        sorted(
            (
                tag_key
                for tag_key in cg_tag_counts
                if tag_key in creator_tag_counts
            ),
            key=lambda tag_key: (tag_key[0], str(tag_key[1])),
        )
    )
    if not overlap_keys:
        return ProfileGameMatch(coverage_score=0.0, overlap_tags=())

    return ProfileGameMatch(
        coverage_score=compute_coverage(
            customer_game,
            creator_tag_counts,
        ),
        overlap_tags=overlap_keys,
    )
