"""Resolve one cached IGDB game to one Steam app or reject all candidates.

The resolver is intentionally soft internally:

- normalized title checks
- fuzzy title similarity
- developer normalization/overlap
- release-year sanity
- canonical tag overlap

But the persisted outcome is binary:
- accepted link
- or no link
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from difflib import SequenceMatcher

from app.steam_enrichment.models import (
    SteamCandidateEvaluation,
    SteamResolutionResult,
    SteamResolvedLink,
    SteamStoreGame,
)

_ROMAN_NUMERAL_REPLACEMENTS = {
    " i ": " 1 ",
    " ii ": " 2 ",
    " iii ": " 3 ",
    " iv ": " 4 ",
    " v ": " 5 ",
    " vi ": " 6 ",
    " vii ": " 7 ",
    " viii ": " 8 ",
    " ix ": " 9 ",
    " x ": " 10 ",
}

_DEVELOPER_STOP_WORDS = {
    "games",
    "game",
    "studios",
    "studio",
    "interactive",
    "entertainment",
    "software",
    "inc",
    "incorporated",
    "llc",
    "ltd",
    "limited",
    "corp",
    "corporation",
    "company",
    "co",
}

_TITLE_SUFFIX_VARIANTS = (
    "the definitive edition",
    "definitive edition",
    "game of the year edition",
    "goty edition",
    "director s cut",
    "anniversary edition",
    "complete edition",
    "ultimate edition",
    "deluxe edition",
    "gold edition",
    "remastered",
    "enhanced",
    "legacy",
)


def normalize_title(value: str) -> str:
    """Normalize game titles for fuzzy matching."""

    normalized = f" {value.strip().casefold()} "
    for roman, arabic in _ROMAN_NUMERAL_REPLACEMENTS.items():
        normalized = normalized.replace(roman, arabic)
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _strip_title_suffix_variants(value: str) -> str:
    """Drop known edition/remaster suffixes from a normalized title.

    This only removes trailing variants. It does not delete internal tokens,
    which keeps distinct games like "Vice City Definitive Edition" separate
    from "Grand Theft Auto V".
    """

    normalized = value
    changed = True
    while changed and normalized:
        changed = False
        for suffix in _TITLE_SUFFIX_VARIANTS:
            if normalized == suffix:
                continue
            if normalized.endswith(f" {suffix}"):
                normalized = normalized[: -len(suffix) - 1].strip()
                changed = True
                break
    return normalized


def normalize_developer(value: str) -> str:
    """Normalize developer names while stripping weak legal suffixes."""

    cleaned = re.sub(r"[^a-z0-9]+", " ", value.strip().casefold())
    tokens = [token for token in cleaned.split() if token]
    filtered = [
        token for token in tokens if token not in _DEVELOPER_STOP_WORDS
    ]
    if filtered:
        return " ".join(filtered)
    return " ".join(tokens)


def parse_release_year(value: int | str | None) -> int | None:
    """Extract a release year from an IGDB timestamp or a Steam date string."""

    if value is None:
        return None
    if isinstance(value, int):
        try:
            return datetime.fromtimestamp(value, tz=UTC).year
        except (OverflowError, OSError, ValueError):
            return None
    match = re.search(r"(19|20)\d{2}", value)
    if match is None:
        return None
    return int(match.group(0))


def _developer_overlap(
    igdb_developers: tuple[str, ...], steam_developers: tuple[str, ...]
) -> bool:
    if not igdb_developers or not steam_developers:
        return False
    left = {
        normalize_developer(name)
        for name in igdb_developers
        if normalize_developer(name)
    }
    right = {
        normalize_developer(name)
        for name in steam_developers
        if normalize_developer(name)
    }
    return bool(left & right)


def _title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(
        None, normalize_title(left), normalize_title(right)
    ).ratio()


def resolve_steam_candidate(
    *,
    igdb_id: int,
    igdb_name: str,
    igdb_developers: tuple[str, ...],
    igdb_release_year: int | None,
    local_tag_keys: set[tuple[str, str]],
    candidates: list[SteamStoreGame],
    candidate_mapped_tag_keys: dict[int, set[tuple[str, str]]],
) -> SteamResolutionResult:
    """Resolve one accepted Steam candidate or reject all."""

    if not candidates:
        return SteamResolutionResult(
            accepted_link=None,
            accepted_candidate=None,
            evaluations=(),
            rejection_reason="no_candidates",
        )

    evaluations: list[SteamCandidateEvaluation] = []
    normalized_target = normalize_title(igdb_name)
    normalized_target_base = _strip_title_suffix_variants(normalized_target)

    for candidate in candidates:
        normalized_candidate_name = normalize_title(candidate.name)
        normalized_candidate_base = _strip_title_suffix_variants(
            normalized_candidate_name
        )
        normalized_name_exact = normalized_candidate_name == normalized_target
        normalized_variant_exact = (
            normalized_candidate_base == normalized_target_base
        )
        title_similarity = _title_similarity(igdb_name, candidate.name)
        developer_overlap = _developer_overlap(
            igdb_developers, candidate.developers
        )
        steam_year = parse_release_year(candidate.release_date)
        release_year_close = (
            igdb_release_year is not None
            and steam_year is not None
            and abs(igdb_release_year - steam_year) <= 1
        )
        overlap_count = len(
            local_tag_keys
            & candidate_mapped_tag_keys.get(candidate.app_id, set())
        )

        score = 0.0
        reasons: list[str] = []
        if normalized_name_exact:
            score += 100.0
            reasons.append("normalized_title_exact")
        elif normalized_variant_exact:
            score += 96.0
            reasons.append("normalized_title_variant_exact")
        else:
            score += title_similarity * 50.0
            if title_similarity >= 0.9:
                reasons.append("strong_title_similarity")
        if developer_overlap:
            score += 18.0
            reasons.append("developer_overlap")
        if release_year_close:
            score += 10.0
            reasons.append("release_year_close")
        if overlap_count > 0:
            score += min(18.0, overlap_count * 6.0)
            reasons.append("canonical_tag_overlap")

        evaluations.append(
            SteamCandidateEvaluation(
                candidate=candidate,
                normalized_name_exact=normalized_name_exact,
                normalized_variant_exact=normalized_variant_exact,
                title_similarity=title_similarity,
                developer_overlap=developer_overlap,
                release_year_close=release_year_close,
                canonical_overlap_count=overlap_count,
                score=score,
                acceptance_reasons=tuple(reasons),
            )
        )

    evaluations.sort(key=lambda item: item.score, reverse=True)
    best = evaluations[0]
    second = evaluations[1] if len(evaluations) > 1 else None

    strong_title = (
        best.normalized_name_exact
        or best.normalized_variant_exact
        or best.title_similarity >= 0.93
    )
    corroborating = (
        best.developer_overlap
        or best.release_year_close
        or best.canonical_overlap_count > 0
    )
    clear_winner = second is None or (best.score - second.score) >= 8.0

    if not strong_title:
        return SteamResolutionResult(
            accepted_link=None,
            accepted_candidate=None,
            evaluations=tuple(evaluations),
            rejection_reason="title_too_weak",
        )
    if not clear_winner:
        return SteamResolutionResult(
            accepted_link=None,
            accepted_candidate=None,
            evaluations=tuple(evaluations),
            rejection_reason="ambiguous_top_candidates",
        )
    if not (
        best.normalized_name_exact
        or best.normalized_variant_exact
        or corroborating
    ):
        return SteamResolutionResult(
            accepted_link=None,
            accepted_candidate=None,
            evaluations=tuple(evaluations),
            rejection_reason="missing_corroboration",
        )

    match_method_parts = []
    if best.normalized_name_exact:
        match_method_parts.append("name_normalized")
    elif best.normalized_variant_exact:
        match_method_parts.append("name_normalized_variant")
    else:
        match_method_parts.append("name_fuzzy")
    if best.developer_overlap:
        match_method_parts.append("developer_normalized")
    if best.release_year_close:
        match_method_parts.append("release_year")
    if best.canonical_overlap_count > 0:
        match_method_parts.append("tag_overlap")

    accepted_link = SteamResolvedLink(
        igdb_id=igdb_id,
        steam_app_id=best.candidate.app_id,
        store_url=best.candidate.store_url,
        match_method="+".join(match_method_parts),
    )
    return SteamResolutionResult(
        accepted_link=accepted_link,
        accepted_candidate=best.candidate,
        evaluations=tuple(evaluations),
    )
