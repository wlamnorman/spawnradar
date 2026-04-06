"""Customer-game domain models."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.igdb.platforms import PLATFORM_BY_SLUG
from app.igdb.taxonomy import (
    IGDBGameMode,
    IGDBGenre,
    IGDBKeywordBucket,
    IGDBPlayerPerspective,
    IGDBTheme,
    keyword_bucket_for_value,
    keyword_labels_for_values,
)


def _labels_for_keyword_bucket(
    keyword_ids: list[str],
    bucket: IGDBKeywordBucket,
    *,
    exclude_labels: set[str] | None = None,
) -> list[str]:
    values = [
        keyword
        for keyword in keyword_ids
        if keyword_bucket_for_value(keyword) == bucket
    ]
    labels = keyword_labels_for_values(values)
    if exclude_labels is None:
        return labels
    return [
        label for label in labels if label.casefold() not in exclude_labels
    ]


@dataclass(frozen=True)
class CustomerGame:
    """A customer-created game with IGDB taxonomy tags and metadata."""

    customer_game_id: str
    workspace_id: str
    name: str
    summary: str | None
    description: str
    website_url: str | None
    status: str
    slug: str
    created_at: str
    updated_at: str
    platforms: list[str] = field(default_factory=list)
    igdb_genre_ids: list[int] = field(default_factory=list)
    igdb_theme_ids: list[int] = field(default_factory=list)
    igdb_game_mode_ids: list[int] = field(default_factory=list)
    igdb_player_perspective_ids: list[int] = field(default_factory=list)
    igdb_keyword_ids: list[str] = field(default_factory=list)
    similar_game_names: list[str] = field(default_factory=list)
    llm_similar_game_names: list[str] = field(default_factory=list)
    llm_broad_game_names: list[str] = field(default_factory=list)

    @property
    def user_id(self) -> str:
        """Convenience alias for personal-workspace callers."""
        return self.workspace_id

    @property
    def platform_labels(self) -> list[str]:
        """Human-readable platform labels in saved order."""
        return [
            platform.label
            for slug in self.platforms
            if (platform := PLATFORM_BY_SLUG.get(slug)) is not None
        ]

    @property
    def genre_labels(self) -> list[str]:
        """Human-readable genre labels, including curated subgenres."""
        official = IGDBGenre.labels_for_ids(self.igdb_genre_ids)
        return official + _labels_for_keyword_bucket(
            self.igdb_keyword_ids,
            IGDBKeywordBucket.GENRE,
            exclude_labels={label.casefold() for label in official},
        )

    @property
    def theme_labels(self) -> list[str]:
        """Human-readable theme labels, including curated theme concepts."""
        official = IGDBTheme.labels_for_ids(self.igdb_theme_ids)
        return official + _labels_for_keyword_bucket(
            self.igdb_keyword_ids,
            IGDBKeywordBucket.THEME,
            exclude_labels={label.casefold() for label in official},
        )

    @property
    def mechanic_labels(self) -> list[str]:
        """Human-readable mechanic labels from curated concepts."""
        return _labels_for_keyword_bucket(
            self.igdb_keyword_ids,
            IGDBKeywordBucket.MECHANIC,
        )

    @property
    def game_mode_labels(self) -> list[str]:
        """Human-readable IGDB game mode names."""
        return IGDBGameMode.labels_for_ids(self.igdb_game_mode_ids)

    @property
    def player_perspective_labels(self) -> list[str]:
        """Human-readable IGDB player perspective names."""
        return IGDBPlayerPerspective.labels_for_ids(
            self.igdb_player_perspective_ids
        )

    @property
    def keyword_labels(self) -> list[str]:
        """Human-readable keyword labels (title-cased)."""
        return keyword_labels_for_values(self.igdb_keyword_ids)

    @property
    def all_similar_game_names(self) -> list[str]:
        """Customer-provided + LLM-suggested similar games, deduplicated."""
        seen: set[str] = set()
        result: list[str] = []
        for name in self.similar_game_names + self.llm_similar_game_names:
            key = name.lower().strip()
            if key and key not in seen:
                seen.add(key)
                result.append(name)
        return result
