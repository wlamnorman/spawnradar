"""Core models for Steam enrichment of cached IGDB games.

This subsystem keeps three concepts separate:

1. Steam-origin facts:
   search results, store metadata, and raw Steam tags.
2. Resolver decisions:
   a Steam app is either accepted for an IGDB game or rejected.
3. Deterministic canonical mappings:
   Steam tags mapped into SpawnRadar's existing setup taxonomy.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SteamSearchCandidate:
    """A candidate app surfaced by Steam search."""

    app_id: int
    name: str
    store_url: str


@dataclass(frozen=True)
class SteamStoreGame:
    """Steam store facts for one app."""

    app_id: int
    name: str
    store_url: str
    developers: tuple[str, ...] = ()
    release_date: str | None = None
    platform_labels: tuple[str, ...] = ()
    short_description: str | None = None
    detailed_description: str | None = None
    raw_tags: tuple[str, ...] = ()
    api_genre_labels: tuple[str, ...] = ()
    api_category_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class SteamMappedTag:
    """One deterministic canonical mapping derived from a Steam label."""

    source_tag: str
    tag_type: str
    tag_id: int | str
    tag_name: str
    mapping_kind: str


@dataclass(frozen=True)
class SteamResolvedLink:
    """A binary accepted Steam link for one local IGDB game."""

    igdb_id: int
    steam_app_id: int
    store_url: str
    match_method: str


@dataclass(frozen=True)
class SteamCandidateEvaluation:
    """Internal scoring breakdown for one Steam candidate."""

    candidate: SteamStoreGame
    normalized_name_exact: bool
    normalized_variant_exact: bool
    title_similarity: float
    developer_overlap: bool
    release_year_close: bool
    canonical_overlap_count: int
    score: float
    acceptance_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class SteamResolutionResult:
    """Resolver output.

    The database stores only accepted links, but tests and logs can inspect the
    full evaluation outcome via this object.
    """

    accepted_link: SteamResolvedLink | None
    accepted_candidate: SteamStoreGame | None
    evaluations: tuple[SteamCandidateEvaluation, ...] = ()
    rejection_reason: str | None = None


@dataclass(frozen=True)
class SteamBackfillCandidate:
    """One cached IGDB game queued for Steam enrichment."""

    igdb_id: int
    name: str
    slug: str
    first_release_date: int | None
    summary: str | None = None
    developer_names: tuple[str, ...] = ()
    popularity_count: int = 0


@dataclass(frozen=True)
class SteamEnrichmentResult:
    """End-to-end result of enriching one IGDB game."""

    igdb_id: int
    status: str
    resolved_link: SteamResolvedLink | None = None
    raw_tags: tuple[str, ...] = ()
    mapped_tags: tuple[SteamMappedTag, ...] = ()
    rejection_reason: str | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)
