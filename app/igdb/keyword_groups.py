"""Canonical IGDB keyword groupings for discovery.

Deduplicates variant spellings (e.g. "deck building" / "deck-building" /
"deckbuilder" → one canonical "deckbuilder") and splits keywords into
Genre, Theme, and Mechanic buckets shown to customers alongside IGDB's
own genre and theme taxonomies.

Curation criteria (applied 2026-03-30):

1. **50+ IGDB games tagged** — keywords below this threshold have too few
   games for any meaningful Twitch streaming community to exist around
   them.  Removed 61 keywords (e.g. ``community sim``, ``drpg``,
   ``extraction shooter``).

2. **At least one well-known, actively-streamed title** — keywords whose
   top-rated games are tiny or mistagged were removed even if the game
   count was high.  Removed 17 keywords (e.g. ``block puzzle`` where the
   top "game" was Zelda OoT, ``driving`` where Fortnite was the top hit,
   ``text adventure`` where Pokémon Go was mistagged).

3. **Not redundant with IGDB genres/themes** — keywords that exactly
   duplicate an existing IGDB genre or theme add noise without adding
   signal.  Removed 12 keywords (e.g. ``survival horror`` = Horror +
   Survival themes, ``graphic adventure`` = Adventure + Point-and-click
   genres, ``squad based shooter`` = Tactical + Shooter genres).

Starting from 159 keywords in ``igdb_keywords_filtered_pass2.txt``, 90
were removed, leaving 69 high-signal keywords.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IGDBKeywordBucket(StrEnum):
    GENRE = "genre"
    THEME = "theme"
    MECHANIC = "mechanic"


@dataclass(frozen=True)
class CanonicalIGDBKeyword:
    canonical: str
    bucket: IGDBKeywordBucket
    igdb_keywords: tuple[str, ...]


IGDB_KEYWORD_GROUPS: tuple[CanonicalIGDBKeyword, ...] = (
    CanonicalIGDBKeyword(
        "asymmetrical multiplayer",
        IGDBKeywordBucket.MECHANIC,
        (
            "asymmetrical",
            "asymmetric co-op",
            "asynchronous multiplayer",
        ),
    ),
    CanonicalIGDBKeyword(
        "automation", IGDBKeywordBucket.MECHANIC, ("automation",)
    ),
    CanonicalIGDBKeyword(
        "base building", IGDBKeywordBucket.MECHANIC, ("base building",)
    ),
    CanonicalIGDBKeyword(
        "bullet hell", IGDBKeywordBucket.GENRE, ("bullet hell",)
    ),
    CanonicalIGDBKeyword("casual", IGDBKeywordBucket.THEME, ("casual",)),
    CanonicalIGDBKeyword(
        "city builder", IGDBKeywordBucket.GENRE, ("city builder",)
    ),
    CanonicalIGDBKeyword(
        "cozy",
        IGDBKeywordBucket.THEME,
        (
            "cozy",
            "cozy adventure",
        ),
    ),
    CanonicalIGDBKeyword(
        "crafting", IGDBKeywordBucket.MECHANIC, ("crafting",)
    ),
    CanonicalIGDBKeyword(
        "deckbuilder",
        IGDBKeywordBucket.GENRE,
        (
            "deck building",
            "deck-building",
            "deckbuilder",
        ),
    ),
    CanonicalIGDBKeyword(
        "dungeon crawler", IGDBKeywordBucket.GENRE, ("dungeon crawler",)
    ),
    CanonicalIGDBKeyword(
        "exploration", IGDBKeywordBucket.MECHANIC, ("exploration",)
    ),
    CanonicalIGDBKeyword(
        "first-person platforming",
        IGDBKeywordBucket.GENRE,
        ("first-person platforming",),
    ),
    CanonicalIGDBKeyword(
        "inventory management",
        IGDBKeywordBucket.MECHANIC,
        ("inventory management",),
    ),
    CanonicalIGDBKeyword("jrpg", IGDBKeywordBucket.GENRE, ("jrpg",)),
    CanonicalIGDBKeyword(
        "looter shooter", IGDBKeywordBucket.GENRE, ("looter shooter",)
    ),
    CanonicalIGDBKeyword(
        "management", IGDBKeywordBucket.MECHANIC, ("management",)
    ),
    CanonicalIGDBKeyword(
        "metroidvania", IGDBKeywordBucket.GENRE, ("metroidvania",)
    ),
    CanonicalIGDBKeyword(
        "micromanagement", IGDBKeywordBucket.MECHANIC, ("micromanagement",)
    ),
    CanonicalIGDBKeyword(
        "party-based", IGDBKeywordBucket.MECHANIC, ("party-based",)
    ),
    CanonicalIGDBKeyword(
        "party-based rpg", IGDBKeywordBucket.GENRE, ("party-based rpg",)
    ),
    CanonicalIGDBKeyword(
        "precision platforming",
        IGDBKeywordBucket.GENRE,
        ("precision platforming",),
    ),
    CanonicalIGDBKeyword(
        "psychological horror",
        IGDBKeywordBucket.THEME,
        ("psychological horror",),
    ),
    CanonicalIGDBKeyword(
        "puzzle platformer", IGDBKeywordBucket.GENRE, ("puzzle platformer",)
    ),
    CanonicalIGDBKeyword(
        "resource management",
        IGDBKeywordBucket.MECHANIC,
        ("resource management",),
    ),
    CanonicalIGDBKeyword("roguelike", IGDBKeywordBucket.GENRE, ("roguelike",)),
    CanonicalIGDBKeyword("roguelite", IGDBKeywordBucket.GENRE, ("roguelite",)),
    CanonicalIGDBKeyword("soulslike", IGDBKeywordBucket.GENRE, ("soulslike",)),
    CanonicalIGDBKeyword(
        "space simulation", IGDBKeywordBucket.GENRE, ("space simulation",)
    ),
    CanonicalIGDBKeyword(
        "time management", IGDBKeywordBucket.MECHANIC, ("time management",)
    ),
    CanonicalIGDBKeyword(
        "turn-based rpg", IGDBKeywordBucket.GENRE, ("turn-based rpg",)
    ),
    CanonicalIGDBKeyword(
        "turn-based tactics", IGDBKeywordBucket.GENRE, ("turn-based tactics",)
    ),
    CanonicalIGDBKeyword(
        "walking simulator", IGDBKeywordBucket.GENRE, ("walking simulator",)
    ),
    CanonicalIGDBKeyword(
        "world building", IGDBKeywordBucket.MECHANIC, ("world building",)
    ),
)


IGDB_GENRE_KEYWORDS: tuple[CanonicalIGDBKeyword, ...] = tuple(
    keyword
    for keyword in IGDB_KEYWORD_GROUPS
    if keyword.bucket == IGDBKeywordBucket.GENRE
)

IGDB_THEME_KEYWORDS: tuple[CanonicalIGDBKeyword, ...] = tuple(
    keyword
    for keyword in IGDB_KEYWORD_GROUPS
    if keyword.bucket == IGDBKeywordBucket.THEME
)

IGDB_MECHANIC_KEYWORDS: tuple[CanonicalIGDBKeyword, ...] = tuple(
    keyword
    for keyword in IGDB_KEYWORD_GROUPS
    if keyword.bucket == IGDBKeywordBucket.MECHANIC
)


RAW_IGDB_KEYWORD_TO_CANONICAL: dict[str, str] = {
    igdb_keyword: keyword.canonical
    for keyword in IGDB_KEYWORD_GROUPS
    for igdb_keyword in keyword.igdb_keywords
}


CANONICAL_IGDB_KEYWORD_TO_ALIASES: dict[str, tuple[str, ...]] = {
    keyword.canonical: keyword.igdb_keywords for keyword in IGDB_KEYWORD_GROUPS
}


__all__ = [
    "IGDBKeywordBucket",
    "CanonicalIGDBKeyword",
    "IGDB_KEYWORD_GROUPS",
    "IGDB_GENRE_KEYWORDS",
    "IGDB_THEME_KEYWORDS",
    "IGDB_MECHANIC_KEYWORDS",
    "RAW_IGDB_KEYWORD_TO_CANONICAL",
    "CANONICAL_IGDB_KEYWORD_TO_ALIASES",
]
