"""Canonical customer-facing platform groups."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalPlatform:
    """One normalized platform option shown in customer forms."""

    slug: str
    label: str
    igdb_ids: tuple[int, ...] = ()


CANONICAL_PLATFORMS: tuple[CanonicalPlatform, ...] = (
    CanonicalPlatform("web", "Browser", (82,)),
    CanonicalPlatform("mobile", "Mobile", (39, 34)),
    CanonicalPlatform("pc", "PC / Steam", (6, 14, 3)),
    CanonicalPlatform("switch", "Nintendo Switch", (130, 508)),
    CanonicalPlatform("playstation", "PlayStation", (167, 48)),
    CanonicalPlatform("xbox", "Xbox", (169, 49)),
    CanonicalPlatform("vr", "VR", (163, 390, 471, 386)),
    CanonicalPlatform("board-game", "Board Game"),
)

PLATFORM_OPTIONS: tuple[tuple[str, str], ...] = tuple(
    (platform.slug, platform.label) for platform in CANONICAL_PLATFORMS
)

PLATFORM_BY_SLUG: dict[str, CanonicalPlatform] = {
    platform.slug: platform for platform in CANONICAL_PLATFORMS
}
