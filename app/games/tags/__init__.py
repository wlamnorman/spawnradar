"""Game tag taxonomy — public API.

All public symbols are re-exported here so callers import from
``app.games.tags`` regardless of which sub-module hosts the implementation.

Sub-module layout
-----------------
_types      TagKind / TagWeight literals and WEIGHT_PRIORITY table
_catalog    Canonical catalogs, featured subsets and alias dicts
_normalize  Key normalization, Levenshtein distance, fuzzy matching, index
_profile    TagProfile and WeightedTag dataclasses
_api        normalize_tag, build_tag_profile, catalog_for, featured_tags_for
"""

from app.games.tags._api import (
    build_tag_profile,
    catalog_for,
    featured_tags_for,
    normalize_tag,
    split_raw_tags,
)
from app.games.tags._catalog import (
    ALIASES_BY_KIND,
    CATALOG_BY_KIND,
    FEATURED_BY_KIND,
    FEATURED_GENRE_TAGS,
    FEATURED_KINDRED_TAGS,
    FEATURED_MECHANICS_TAGS,
    FEATURED_VIBE_TAGS,
    GENRE_TAG_CATALOG,
    KINDRED_TAG_CATALOG,
    MECHANICS_TAG_CATALOG,
    VIBE_TAG_CATALOG,
)
from app.games.tags._normalize import levenshtein_distance, normalize_key
from app.games.tags._profile import TagProfile, WeightedTag
from app.games.tags._types import TagKind, TagWeight  # TagWeight is a StrEnum

__all__ = [
    # Types
    "TagKind",
    "TagWeight",
    # Dataclasses
    "TagProfile",
    "WeightedTag",
    # API functions
    "build_tag_profile",
    "catalog_for",
    "featured_tags_for",
    "normalize_tag",
    "split_raw_tags",
    # Normalization utilities
    "levenshtein_distance",
    "normalize_key",
    # Catalogs (used by CLI and tests)
    "GENRE_TAG_CATALOG",
    "MECHANICS_TAG_CATALOG",
    "VIBE_TAG_CATALOG",
    "KINDRED_TAG_CATALOG",
    "FEATURED_GENRE_TAGS",
    "FEATURED_MECHANICS_TAGS",
    "FEATURED_VIBE_TAGS",
    "FEATURED_KINDRED_TAGS",
    "CATALOG_BY_KIND",
    "FEATURED_BY_KIND",
    "ALIASES_BY_KIND",
]
