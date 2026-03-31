"""Shared models for the standalone game-import subsystem.

The subsystem intentionally exposes both raw imported source data and a
normalized draft. The raw layer preserves provenance; the draft layer is what a
future setup UI would pre-fill for user review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ImportedGameSourceData:
    """Raw, deterministic fields extracted from an external game source."""

    source_kind: str
    source_url: str
    source_id: str | None
    name: str | None
    short_description: str | None
    full_description: str | None
    platform_labels: list[str] = field(default_factory=list)
    api_genre_labels: list[str] = field(default_factory=list)
    api_category_labels: list[str] = field(default_factory=list)
    raw_tags: list[str] = field(default_factory=list)
    website_url: str | None = None
    image_url: str | None = None
    release_date: str | None = None
    supported_languages: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ImportedGameDraft:
    """Normalized data suitable for pre-filling a game-setup form."""

    source_kind: str
    source_url: str
    source_id: str | None
    name: str
    summary: str
    description: str
    platform_labels: list[str] = field(default_factory=list)
    igdb_genre_ids: list[int] = field(default_factory=list)
    igdb_theme_ids: list[int] = field(default_factory=list)
    igdb_game_mode_ids: list[int] = field(default_factory=list)
    igdb_keyword_ids: list[str] = field(default_factory=list)
    tag_candidates: list[str] = field(default_factory=list)
    website_url: str | None = None
    image_url: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ImportedGamePreview:
    """Combined import result returned by the service layer."""

    source: ImportedGameSourceData
    draft: ImportedGameDraft
