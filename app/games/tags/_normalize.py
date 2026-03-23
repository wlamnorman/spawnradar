"""Tag normalization: key cleaning, fuzzy matching and search index building.

The search index maps normalized keys to canonical tag names. It is built once
at import time from the catalog and alias tables in ``_catalog``.
"""

from __future__ import annotations

import re

from app.games.tags._catalog import ALIASES_BY_KIND, CATALOG_BY_KIND
from app.games.tags._types import TagKind


def normalize_key(value: str) -> str:
    """Reduce a raw tag string to a stable comparison key.

    Strips leading/trailing whitespace, lowercases, expands ``&`` to ``and``,
    and collapses any run of non-alphanumeric characters to a single space.
    """
    cleaned = value.strip().lower()
    cleaned = cleaned.replace("&", " and ")
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def levenshtein_distance(left: str, right: str) -> int:
    """Return the Levenshtein edit distance between two strings."""
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, start=1):
        current = [row]
        for col, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[col - 1] + 1,  # insert
                    previous[col] + 1,  # delete
                    previous[col - 1]
                    + (0 if left_char == right_char else 1),  # replace
                )
            )
        previous = current
    return previous[-1]


def _max_edit_distance(left: str, right: str) -> int:
    """Return the maximum edit distance we'll accept for a fuzzy match."""
    return 1 if max(len(left), len(right)) <= 8 else 2


def fuzzy_match(
    normalized: str, kind: TagKind, search_keys: dict[str, str]
) -> str | None:
    """Return the best catalog match for *normalized* within allowed edit distance.

    Returns ``None`` when no candidate is close enough. Short strings (< 6
    chars) are excluded because they produce too many false positives.
    """
    if len(normalized) < 6:
        return None

    normalized_word_count = len(normalized.split())
    best_match: str | None = None
    best_distance: int | None = None

    for key, canonical in search_keys.items():
        # Fast pre-filters to avoid O(n²) Levenshtein on the full index.
        if not key or key[0] != normalized[0]:
            continue
        if abs(len(key.split()) - normalized_word_count) > 1:
            continue

        distance = levenshtein_distance(normalized, key)
        limit = _max_edit_distance(normalized, key)
        ratio = distance / max(len(normalized), len(key))
        if distance > limit or ratio > 0.14:
            continue

        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_match = canonical

    return best_match


# ---------------------------------------------------------------------------
# Search index — built once at module import
# ---------------------------------------------------------------------------

# Maps kind → {normalized_key: canonical_name} (catalog entries only).
_CANONICAL_KEY_TO_NAME: dict[TagKind, dict[str, str]] = {}

# Maps kind → {normalized_key: canonical_name} (catalog + aliases).
_SEARCH_KEYS: dict[TagKind, dict[str, str]] = {}


def _build_index() -> None:
    for kind, catalog in CATALOG_BY_KIND.items():
        canonical_map: dict[str, str] = {
            normalize_key(tag): tag for tag in catalog
        }
        search_map: dict[str, str] = dict(canonical_map)
        for alias, target in ALIASES_BY_KIND[kind].items():
            search_map[normalize_key(alias)] = target
        _CANONICAL_KEY_TO_NAME[kind] = canonical_map
        _SEARCH_KEYS[kind] = search_map


_build_index()


def search_keys_for(kind: TagKind) -> dict[str, str]:
    """Return the full search index (catalog + aliases) for *kind*."""
    return _SEARCH_KEYS[kind]


def canonical_keys_for(kind: TagKind) -> dict[str, str]:
    """Return the catalog-only index (no aliases) for *kind*."""
    return _CANONICAL_KEY_TO_NAME[kind]
