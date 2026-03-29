"""Derived profile facets used for creator cards and matching."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.creator_index.adapters.base import (
    ContentSampleSeed,
    TwitchProfileSeed,
    YouTubeChannelSeed,
)
from app.creator_index.adapters.common import (
    dominant_language,
    latest_timestamp,
)
from app.igdb.taxonomy import IGDBGenre, IGDBTheme

_SUMMARY_MAX_CHARS = 260
_MIN_DESCRIPTION_WORDS = 5
_PLATFORM_LABELS = {"twitch": "Twitch", "youtube": "YouTube"}

# Build text-matching catalogs from IGDB taxonomy
_GENRE_LABELS = [g.label.lower() for g in IGDBGenre.gaming()]
_THEME_LABELS = [t.label.lower() for t in IGDBTheme.gaming()]


@dataclass(frozen=True)
class CreatorProfileFacetSeed:
    summary_text: str
    genre_tags: tuple[str, ...]
    interest_tags: tuple[str, ...]
    language: str | None
    games_played: tuple[str, ...]
    last_activity_at: str | None


def build_creator_profile_facets(
    platform: str,
    profile: TwitchProfileSeed | YouTubeChannelSeed,
    content_samples: tuple[ContentSampleSeed, ...],
) -> CreatorProfileFacetSeed:
    """Build a concise summary plus topic tags from profile/content text."""
    description = (profile.description or "").strip()
    text_fragments = [description]
    text_fragments.extend(
        sample.title_or_text for sample in content_samples[:5]
    )
    text_fragments.extend(
        sample.body_text or "" for sample in content_samples[:3]
    )
    combined_text = " ".join(
        fragment for fragment in text_fragments if fragment
    )

    genre_tags = tuple(_match_igdb_labels(combined_text, _GENRE_LABELS, limit=6))
    interest_tags = tuple(
        _match_igdb_labels(combined_text, _THEME_LABELS, limit=8)
    )
    last_activity_at = latest_timestamp(
        [
            getattr(profile, "last_live_at", None),
            getattr(profile, "last_upload_at", None),
            *(sample.published_at for sample in content_samples),
        ]
    )
    summary_text = _build_summary(
        platform=platform,
        description=description,
        genre_tags=genre_tags,
        interest_tags=interest_tags,
        content_samples=content_samples,
    )

    # Language: Twitch has it directly; YouTube falls back to video audio languages.
    language = getattr(profile, "language", None) or getattr(
        profile, "default_language", None
    ) or dominant_language([s.language for s in content_samples])

    # Games played: only Twitch exposes a structured game field today.
    games_played: tuple[str, ...] = getattr(profile, "games_played", ())

    return CreatorProfileFacetSeed(
        summary_text=summary_text,
        genre_tags=genre_tags,
        interest_tags=interest_tags,
        language=language,
        games_played=games_played,
        last_activity_at=last_activity_at,
    )


def _match_igdb_labels(
    text: str, labels: list[str], *, limit: int
) -> list[str]:
    """Match IGDB taxonomy labels against combined text."""
    haystack = f" {text.lower()} "
    matches: list[str] = []
    seen: set[str] = set()
    for label in labels:
        if label and f" {label} " in haystack and label not in seen:
            seen.add(label)
            matches.append(label.title())
            if len(matches) >= limit:
                return matches
    return matches


def _build_summary(
    *,
    platform: str,
    description: str,
    genre_tags: tuple[str, ...],
    interest_tags: tuple[str, ...],
    content_samples: tuple[ContentSampleSeed, ...],
) -> str:
    cleaned_description = _clean_description(description)
    if (
        cleaned_description
        and len(cleaned_description.split()) >= _MIN_DESCRIPTION_WORDS
    ):
        return _truncate(cleaned_description)

    platform_label = _PLATFORM_LABELS.get(platform, platform.title())
    parts: list[str] = [f"{platform_label} gaming creator"]
    if genre_tags:
        parts.append(f"covering {', '.join(genre_tags[:3])}")
    if interest_tags:
        parts.append(f"with interests in {', '.join(interest_tags[:3])}")

    recent_titles = [sample.title_or_text for sample in content_samples[:2]]
    if recent_titles:
        parts.append(f"recent content includes {', '.join(recent_titles)}")
    return _truncate(". ".join(part for part in parts if part))


def _clean_description(description: str) -> str:
    cleaned = re.sub(r"https?://\S+", "", description)
    cleaned = re.sub(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", "", cleaned
    )
    return re.sub(r"\s+", " ", cleaned).strip(" ,.-")


def _truncate(value: str) -> str:
    if len(value) <= _SUMMARY_MAX_CHARS:
        return value
    return f"{value[: _SUMMARY_MAX_CHARS - 3].rstrip()}..."
