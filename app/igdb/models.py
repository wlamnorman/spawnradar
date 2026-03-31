from __future__ import annotations

from dataclasses import dataclass, field

from app.igdb.taxonomy import IGDBGenre, IGDBTheme


@dataclass(frozen=True)
class IGDBGame:
    igdb_id: int
    name: str
    slug: str
    summary: str | None
    genre_ids: list[IGDBGenre]
    theme_ids: list[IGDBTheme]
    first_release_date: int | None
    cover_url: str | None = None
    developer_names: list[str] = field(default_factory=list)
    platform_ids: list[int] = field(default_factory=list)
    platform_names: list[str] = field(default_factory=list)
    keyword_names: list[str] = field(default_factory=list)
