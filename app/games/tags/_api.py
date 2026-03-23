"""Public tag API: normalization, catalog access and profile construction."""

from __future__ import annotations

from app.games.tags._catalog import CATALOG_BY_KIND, FEATURED_BY_KIND
from app.games.tags._normalize import (
    fuzzy_match,
    normalize_key,
    search_keys_for,
)
from app.games.tags._profile import TagProfile
from app.games.tags._types import TagKind, TagWeight

# ---------------------------------------------------------------------------
# Catalog access
# ---------------------------------------------------------------------------


def catalog_for(kind: TagKind) -> list[str]:
    """Return the full canonical tag catalog for *kind*."""
    return list(CATALOG_BY_KIND[kind])


def featured_tags_for(kind: TagKind) -> list[str]:
    """Return a curated subset of tags for quick-pick UI widgets."""
    return list(FEATURED_BY_KIND[kind])


# ---------------------------------------------------------------------------
# Single-tag normalization
# ---------------------------------------------------------------------------


def normalize_tag(value: str, kind: TagKind) -> str:
    """Map *value* to its canonical form, falling back to the cleaned key.

    Lookup order:
      1. Exact match in catalog or alias table.
      2. Fuzzy (Levenshtein) match within the catalog + alias index.
      3. The normalized key itself (preserves unknown tags as-is).
    """
    key = normalize_key(value)
    if not key:
        return ""

    search_keys = search_keys_for(kind)
    direct = search_keys.get(key)
    if direct:
        return direct

    fuzzy = fuzzy_match(key, kind, search_keys)
    return fuzzy if fuzzy else key


# ---------------------------------------------------------------------------
# Profile construction
# ---------------------------------------------------------------------------


def split_raw_tags(raw: str) -> list[str]:
    """Split a comma-separated tag string into non-empty fragments."""
    return [part.strip() for part in raw.split(",") if part.strip()]


def build_tag_profile(
    kind: TagKind,
    *,
    primary_raw: str = "",
    secondary_raw: str = "",
    legacy_raw: str = "",
) -> TagProfile:
    """Build a normalized ``TagProfile`` from raw form or API input.

    Genre profiles use both *primary_raw* and *secondary_raw*.
    Mechanics, vibe and kindred profiles only use *primary_raw*.

    When both structured inputs are empty, *legacy_raw* is normalised and
    placed into the primary bucket for backward compatibility.
    """
    has_structured = bool(primary_raw.strip() or secondary_raw.strip())
    if not has_structured:
        return TagProfile.from_flat_tags(
            _normalize_many(legacy_raw, kind),
            default_weight=TagWeight.PRIMARY,
        )

    buckets: dict[TagWeight, list[str]] = {
        TagWeight.PRIMARY: _normalize_many(primary_raw, kind),
        TagWeight.SECONDARY: _normalize_many(secondary_raw, kind),
    }
    merged = _merge_weighted_buckets(buckets)
    return TagProfile(
        primary=tuple(merged[TagWeight.PRIMARY]),
        secondary=tuple(merged[TagWeight.SECONDARY]),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_many(raw: str, kind: TagKind) -> list[str]:
    """Normalize all comma-separated tags in *raw*, deduplicating the result."""
    tags: list[str] = []
    seen: set[str] = set()
    for fragment in split_raw_tags(raw):
        tag = normalize_tag(fragment, kind)
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags


def _merge_weighted_buckets(
    buckets: dict[TagWeight, list[str]],
) -> dict[TagWeight, list[str]]:
    """Resolve bucket conflicts so each tag appears in its highest-weight bucket.

    When the same tag appears in both primary and secondary, it is kept only
    in primary. Within each bucket the original insertion order is preserved.
    """
    chosen_weight: dict[str, TagWeight] = {}
    chosen_order: dict[str, int] = {}

    for weight in (TagWeight.SECONDARY, TagWeight.PRIMARY):
        for index, tag in enumerate(buckets[weight]):
            existing = chosen_weight.get(tag)
            if existing is None or weight.score > existing.score:
                chosen_weight[tag] = weight
                chosen_order[tag] = index

    result: dict[TagWeight, list[str]] = {
        TagWeight.PRIMARY: [],
        TagWeight.SECONDARY: [],
    }
    for weight in TagWeight:
        tags = [t for t, w in chosen_weight.items() if w is weight]
        tags.sort(key=lambda t: chosen_order[t])
        result[weight] = tags
    return result
