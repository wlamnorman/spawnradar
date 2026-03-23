"""Core type definitions for the tag taxonomy."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

TagKind = Literal["genre", "mechanics", "vibe", "kindred"]


class TagWeight(StrEnum):
    """Importance tier for a tag within its profile bucket.

    Only genre profiles use both tiers. Mechanics, vibe and kindred profiles
    only use PRIMARY — any tag (catalog entry or freeform) can be primary.
    """

    PRIMARY = "primary"
    SECONDARY = "secondary"

    @property
    def score(self) -> int:
        """Higher score wins when the same tag appears in multiple buckets."""
        return 2 if self is TagWeight.PRIMARY else 1
