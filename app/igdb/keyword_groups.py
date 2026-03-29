"""Canonical IGDB keyword groupings for discovery experiments.

This file is based on ``igdb_keywords_filtered_pass2.txt`` but deduplicates
obvious variant spellings such as ``deck building`` / ``deck-building`` /
``deckbuilder`` into one canonical concept while keeping the underlying IGDB
keyword aliases available for search.

The intent is:
- show one clean customer-facing concept
- retain all useful IGDB keyword variants for retrieval
- split the canonical concepts into Genre, Theme, and Mechanic buckets

All strings in ``igdb_keywords`` are intended to be IGDB keyword names.
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
        "2d platformer", IGDBKeywordBucket.GENRE, ("2d platformer",)
    ),
    CanonicalIGDBKeyword("2d rpg", IGDBKeywordBucket.GENRE, ("2d rpg",)),
    CanonicalIGDBKeyword(
        "3d platformer", IGDBKeywordBucket.GENRE, ("3d platformer",)
    ),
    CanonicalIGDBKeyword(
        "3d shooter", IGDBKeywordBucket.GENRE, ("3d shooter",)
    ),
    CanonicalIGDBKeyword(
        "action adventure rpg",
        IGDBKeywordBucket.GENRE,
        ("action adventure rpg",),
    ),
    CanonicalIGDBKeyword(
        "action platformer", IGDBKeywordBucket.GENRE, ("action platformer",)
    ),
    CanonicalIGDBKeyword(
        "action roguelike", IGDBKeywordBucket.GENRE, ("action roguelike",)
    ),
    CanonicalIGDBKeyword(
        "action roguelite", IGDBKeywordBucket.GENRE, ("action roguelite",)
    ),
    CanonicalIGDBKeyword(
        "action rpg", IGDBKeywordBucket.GENRE, ("action-rpg", "arpg")
    ),
    CanonicalIGDBKeyword("adventure", IGDBKeywordBucket.GENRE, ("adventure",)),
    CanonicalIGDBKeyword(
        "analog horror", IGDBKeywordBucket.THEME, ("analog horror",)
    ),
    CanonicalIGDBKeyword(
        "arcade shooter", IGDBKeywordBucket.GENRE, ("arcade shooter",)
    ),
    CanonicalIGDBKeyword(
        "arena shooter", IGDBKeywordBucket.GENRE, ("arena shooter",)
    ),
    CanonicalIGDBKeyword(
        "asymmetrical multiplayer",
        IGDBKeywordBucket.MECHANIC,
        ("asymmetrical", "asymmetric co-op", "asynchronous multiplayer"),
    ),
    CanonicalIGDBKeyword(
        "auto battler",
        IGDBKeywordBucket.GENRE,
        ("auto battler", "autobattler"),
    ),
    CanonicalIGDBKeyword(
        "automation", IGDBKeywordBucket.MECHANIC, ("automation",)
    ),
    CanonicalIGDBKeyword(
        "base building", IGDBKeywordBucket.MECHANIC, ("base building",)
    ),
    CanonicalIGDBKeyword(
        "base defense", IGDBKeywordBucket.MECHANIC, ("base defense",)
    ),
    CanonicalIGDBKeyword(
        "base management", IGDBKeywordBucket.MECHANIC, ("base management",)
    ),
    CanonicalIGDBKeyword(
        "battle arena", IGDBKeywordBucket.GENRE, ("battle arena",)
    ),
    CanonicalIGDBKeyword(
        "block puzzle", IGDBKeywordBucket.GENRE, ("block puzzle",)
    ),
    CanonicalIGDBKeyword(
        "boomer shooter", IGDBKeywordBucket.GENRE, ("boomer shooter",)
    ),
    CanonicalIGDBKeyword("brawler", IGDBKeywordBucket.GENRE, ("brawler",)),
    CanonicalIGDBKeyword(
        "bullet heaven", IGDBKeywordBucket.GENRE, ("bullet heaven",)
    ),
    CanonicalIGDBKeyword(
        "bullet hell", IGDBKeywordBucket.GENRE, ("bullet hell",)
    ),
    CanonicalIGDBKeyword(
        "business simulation",
        IGDBKeywordBucket.GENRE,
        ("business simulation", "business simulator"),
    ),
    CanonicalIGDBKeyword(
        "card based combat", IGDBKeywordBucket.MECHANIC, ("card based combat",)
    ),
    CanonicalIGDBKeyword(
        "card battler", IGDBKeywordBucket.GENRE, ("card battler",)
    ),
    CanonicalIGDBKeyword(
        "card collection", IGDBKeywordBucket.MECHANIC, ("card collection",)
    ),
    CanonicalIGDBKeyword("casual", IGDBKeywordBucket.GENRE, ("casual",)),
    CanonicalIGDBKeyword(
        "character action", IGDBKeywordBucket.GENRE, ("character action",)
    ),
    CanonicalIGDBKeyword(
        "city builder", IGDBKeywordBucket.GENRE, ("city builder",)
    ),
    CanonicalIGDBKeyword("clicker", IGDBKeywordBucket.GENRE, ("clicker",)),
    CanonicalIGDBKeyword(
        "collectathon", IGDBKeywordBucket.GENRE, ("collectathon",)
    ),
    CanonicalIGDBKeyword(
        "collectible card game",
        IGDBKeywordBucket.GENRE,
        ("collectible card game",),
    ),
    CanonicalIGDBKeyword(
        "colony builder", IGDBKeywordBucket.GENRE, ("colony builder",)
    ),
    CanonicalIGDBKeyword(
        "colony simulator", IGDBKeywordBucket.GENRE, ("colony simulator",)
    ),
    CanonicalIGDBKeyword(
        "combat simulator", IGDBKeywordBucket.GENRE, ("combat simulator",)
    ),
    CanonicalIGDBKeyword(
        "community sim", IGDBKeywordBucket.GENRE, ("community sim",)
    ),
    CanonicalIGDBKeyword(
        "co-op campaign", IGDBKeywordBucket.MECHANIC, ("co-op campaign",)
    ),
    CanonicalIGDBKeyword(
        "couch co-op", IGDBKeywordBucket.MECHANIC, ("couch co-op",)
    ),
    CanonicalIGDBKeyword(
        "cozy", IGDBKeywordBucket.THEME, ("cozy", "cozy adventure")
    ),
    CanonicalIGDBKeyword(
        "crafting", IGDBKeywordBucket.MECHANIC, ("crafting",)
    ),
    CanonicalIGDBKeyword(
        "crafting survival", IGDBKeywordBucket.GENRE, ("crafting survival",)
    ),
    CanonicalIGDBKeyword(
        "creature collector", IGDBKeywordBucket.GENRE, ("creature collector",)
    ),
    CanonicalIGDBKeyword("crpg", IGDBKeywordBucket.GENRE, ("crpg",)),
    CanonicalIGDBKeyword(
        "cyberpunk", IGDBKeywordBucket.THEME, ("cyberpunk rpg",)
    ),
    CanonicalIGDBKeyword(
        "dating sim",
        IGDBKeywordBucket.GENRE,
        ("dating sim", "dating simulation"),
    ),
    CanonicalIGDBKeyword(
        "deckbuilder",
        IGDBKeywordBucket.GENRE,
        ("deck building", "deck-building", "deckbuilder"),
    ),
    CanonicalIGDBKeyword(
        "detective mystery", IGDBKeywordBucket.THEME, ("detective mystery",)
    ),
    CanonicalIGDBKeyword("driving", IGDBKeywordBucket.GENRE, ("driving",)),
    CanonicalIGDBKeyword("drpg", IGDBKeywordBucket.GENRE, ("drpg",)),
    CanonicalIGDBKeyword(
        "dungeon crawler", IGDBKeywordBucket.GENRE, ("dungeon crawler",)
    ),
    CanonicalIGDBKeyword(
        "dungeon management", IGDBKeywordBucket.GENRE, ("dungeon management",)
    ),
    CanonicalIGDBKeyword(
        "endless runner", IGDBKeywordBucket.GENRE, ("endless runner",)
    ),
    CanonicalIGDBKeyword(
        "escape room", IGDBKeywordBucket.GENRE, ("escape room",)
    ),
    CanonicalIGDBKeyword(
        "extraction", IGDBKeywordBucket.MECHANIC, ("extraction",)
    ),
    CanonicalIGDBKeyword(
        "extraction horror", IGDBKeywordBucket.GENRE, ("extraction horror",)
    ),
    CanonicalIGDBKeyword(
        "extraction shooter", IGDBKeywordBucket.GENRE, ("extraction shooter",)
    ),
    CanonicalIGDBKeyword(
        "exploration", IGDBKeywordBucket.MECHANIC, ("exploration",)
    ),
    CanonicalIGDBKeyword(
        "exploration rpg", IGDBKeywordBucket.GENRE, ("exploration rpg",)
    ),
    CanonicalIGDBKeyword("factory", IGDBKeywordBucket.GENRE, ("factory",)),
    CanonicalIGDBKeyword("farm", IGDBKeywordBucket.GENRE, ("farm", "farming")),
    CanonicalIGDBKeyword(
        "farming simulator", IGDBKeywordBucket.GENRE, ("farming simulator",)
    ),
    CanonicalIGDBKeyword(
        "first person horror",
        IGDBKeywordBucket.GENRE,
        ("first person horror",),
    ),
    CanonicalIGDBKeyword(
        "first person shooter",
        IGDBKeywordBucket.GENRE,
        ("first person shooter",),
    ),
    CanonicalIGDBKeyword(
        "first-person platforming",
        IGDBKeywordBucket.GENRE,
        ("first-person platforming",),
    ),
    CanonicalIGDBKeyword(
        "flight simulation",
        IGDBKeywordBucket.GENRE,
        ("flight simulation", "flight simulator"),
    ),
    CanonicalIGDBKeyword("fmv", IGDBKeywordBucket.GENRE, ("fmv",)),
    CanonicalIGDBKeyword(
        "foraging", IGDBKeywordBucket.MECHANIC, ("foraging",)
    ),
    CanonicalIGDBKeyword("god game", IGDBKeywordBucket.GENRE, ("god game",)),
    CanonicalIGDBKeyword(
        "gothic horror", IGDBKeywordBucket.THEME, ("gothic horror",)
    ),
    CanonicalIGDBKeyword(
        "grand strategy", IGDBKeywordBucket.GENRE, ("grand strategy",)
    ),
    CanonicalIGDBKeyword(
        "graphic adventure", IGDBKeywordBucket.GENRE, ("graphic adventure",)
    ),
    CanonicalIGDBKeyword(
        "hacking simulator", IGDBKeywordBucket.GENRE, ("hacking simulator",)
    ),
    CanonicalIGDBKeyword(
        "horde survival", IGDBKeywordBucket.GENRE, ("horde survival",)
    ),
    CanonicalIGDBKeyword(
        "horizontal shooter", IGDBKeywordBucket.GENRE, ("horizontal shooter",)
    ),
    CanonicalIGDBKeyword("horror", IGDBKeywordBucket.THEME, ("horror",)),
    CanonicalIGDBKeyword(
        "immersive sim", IGDBKeywordBucket.GENRE, ("immersive sim",)
    ),
    CanonicalIGDBKeyword(
        "indie mmorpg", IGDBKeywordBucket.GENRE, ("indie mmorpg",)
    ),
    CanonicalIGDBKeyword(
        "interactive fiction",
        IGDBKeywordBucket.GENRE,
        ("interactive fiction",),
    ),
    CanonicalIGDBKeyword(
        "inventory management",
        IGDBKeywordBucket.MECHANIC,
        ("inventory management",),
    ),
    CanonicalIGDBKeyword("jrpg", IGDBKeywordBucket.GENRE, ("jrpg",)),
    CanonicalIGDBKeyword(
        "life simulation",
        IGDBKeywordBucket.GENRE,
        ("life simulation", "life simulator"),
    ),
    CanonicalIGDBKeyword(
        "logic puzzle", IGDBKeywordBucket.GENRE, ("logic puzzle",)
    ),
    CanonicalIGDBKeyword(
        "looter shooter", IGDBKeywordBucket.GENRE, ("looter shooter",)
    ),
    CanonicalIGDBKeyword(
        "management", IGDBKeywordBucket.MECHANIC, ("management",)
    ),
    CanonicalIGDBKeyword(
        "mascot horror", IGDBKeywordBucket.THEME, ("mascot horror",)
    ),
    CanonicalIGDBKeyword(
        "metroidvania", IGDBKeywordBucket.GENRE, ("metroidvania",)
    ),
    CanonicalIGDBKeyword(
        "micromanagement", IGDBKeywordBucket.MECHANIC, ("micromanagement",)
    ),
    CanonicalIGDBKeyword(
        "military simulator", IGDBKeywordBucket.GENRE, ("military simulator",)
    ),
    CanonicalIGDBKeyword(
        "movement shooter", IGDBKeywordBucket.GENRE, ("movement shooter",)
    ),
    CanonicalIGDBKeyword("mmorpg", IGDBKeywordBucket.GENRE, ("mmorpg",)),
    CanonicalIGDBKeyword(
        "narrative adventure",
        IGDBKeywordBucket.GENRE,
        ("narrative adventure",),
    ),
    CanonicalIGDBKeyword(
        "open world", IGDBKeywordBucket.MECHANIC, ("open world",)
    ),
    CanonicalIGDBKeyword(
        "open world survival craft",
        IGDBKeywordBucket.GENRE,
        ("open world survival craft",),
    ),
    CanonicalIGDBKeyword(
        "party game", IGDBKeywordBucket.GENRE, ("party game",)
    ),
    CanonicalIGDBKeyword(
        "party-based", IGDBKeywordBucket.MECHANIC, ("party-based",)
    ),
    CanonicalIGDBKeyword(
        "party-based combat",
        IGDBKeywordBucket.MECHANIC,
        ("party-based combat",),
    ),
    CanonicalIGDBKeyword(
        "party-based rpg", IGDBKeywordBucket.GENRE, ("party-based rpg",)
    ),
    CanonicalIGDBKeyword(
        "physics puzzle",
        IGDBKeywordBucket.GENRE,
        ("physics puzzle", "physics puzzles"),
    ),
    CanonicalIGDBKeyword(
        "physics-based platformer",
        IGDBKeywordBucket.GENRE,
        ("physics-based platformer",),
    ),
    CanonicalIGDBKeyword(
        "precision platforming",
        IGDBKeywordBucket.GENRE,
        ("precision platforming",),
    ),
    CanonicalIGDBKeyword(
        "programming game", IGDBKeywordBucket.GENRE, ("programming game",)
    ),
    CanonicalIGDBKeyword(
        "psychological horror",
        IGDBKeywordBucket.THEME,
        ("psychological horror",),
    ),
    CanonicalIGDBKeyword("puzzle", IGDBKeywordBucket.GENRE, ("puzzle",)),
    CanonicalIGDBKeyword(
        "puzzle platformer", IGDBKeywordBucket.GENRE, ("puzzle platformer",)
    ),
    CanonicalIGDBKeyword(
        "puzzle shooter", IGDBKeywordBucket.GENRE, ("puzzle shooter",)
    ),
    CanonicalIGDBKeyword(
        "real time tactics", IGDBKeywordBucket.GENRE, ("real time tactics",)
    ),
    CanonicalIGDBKeyword(
        "resource management",
        IGDBKeywordBucket.MECHANIC,
        ("resource management",),
    ),
    CanonicalIGDBKeyword(
        "restaurant management",
        IGDBKeywordBucket.GENRE,
        ("restaurant management",),
    ),
    CanonicalIGDBKeyword("rhythm", IGDBKeywordBucket.GENRE, ("rhythm",)),
    CanonicalIGDBKeyword("roguelike", IGDBKeywordBucket.GENRE, ("roguelike",)),
    CanonicalIGDBKeyword(
        "roguelike deckbuilder",
        IGDBKeywordBucket.GENRE,
        ("roguelike deckbuilder",),
    ),
    CanonicalIGDBKeyword("roguelite", IGDBKeywordBucket.GENRE, ("roguelite",)),
    CanonicalIGDBKeyword("sandbox", IGDBKeywordBucket.GENRE, ("sandbox",)),
    CanonicalIGDBKeyword(
        "sandbox rpg", IGDBKeywordBucket.GENRE, ("sandbox rpg",)
    ),
    CanonicalIGDBKeyword(
        "settlement building",
        IGDBKeywordBucket.MECHANIC,
        ("settlement building",),
    ),
    CanonicalIGDBKeyword(
        "shop management",
        IGDBKeywordBucket.GENRE,
        ("shop management", "shop simulator"),
    ),
    CanonicalIGDBKeyword(
        "simulation", IGDBKeywordBucket.GENRE, ("simulation",)
    ),
    CanonicalIGDBKeyword(
        "social deduction", IGDBKeywordBucket.GENRE, ("social deduction",)
    ),
    CanonicalIGDBKeyword(
        "social simulation", IGDBKeywordBucket.GENRE, ("social simulation",)
    ),
    CanonicalIGDBKeyword("soulslike", IGDBKeywordBucket.GENRE, ("soulslike",)),
    CanonicalIGDBKeyword(
        "space shooter", IGDBKeywordBucket.GENRE, ("space shooter",)
    ),
    CanonicalIGDBKeyword(
        "space simulation", IGDBKeywordBucket.GENRE, ("space simulation",)
    ),
    CanonicalIGDBKeyword(
        "space strategy", IGDBKeywordBucket.GENRE, ("space strategy",)
    ),
    CanonicalIGDBKeyword(
        "squad based shooter",
        IGDBKeywordBucket.GENRE,
        ("squad based shooter",),
    ),
    CanonicalIGDBKeyword(
        "squad tactics", IGDBKeywordBucket.GENRE, ("squad tactics",)
    ),
    CanonicalIGDBKeyword("stealth", IGDBKeywordBucket.MECHANIC, ("stealth",)),
    CanonicalIGDBKeyword(
        "story driven rpg", IGDBKeywordBucket.GENRE, ("story driven rpg",)
    ),
    CanonicalIGDBKeyword("strategy", IGDBKeywordBucket.GENRE, ("strategy",)),
    CanonicalIGDBKeyword(
        "strategy card", IGDBKeywordBucket.GENRE, ("strategy card",)
    ),
    CanonicalIGDBKeyword(
        "strategy rpg", IGDBKeywordBucket.GENRE, ("strategy rpg",)
    ),
    CanonicalIGDBKeyword("survival", IGDBKeywordBucket.GENRE, ("survival",)),
    CanonicalIGDBKeyword(
        "survival horror", IGDBKeywordBucket.GENRE, ("survival horror",)
    ),
    CanonicalIGDBKeyword(
        "survival management",
        IGDBKeywordBucket.GENRE,
        ("survival management",),
    ),
    CanonicalIGDBKeyword(
        "survival rpg", IGDBKeywordBucket.GENRE, ("survival rpg",)
    ),
    CanonicalIGDBKeyword(
        "survival shooter", IGDBKeywordBucket.GENRE, ("survival shooter",)
    ),
    CanonicalIGDBKeyword(
        "tactical rpg", IGDBKeywordBucket.GENRE, ("tactical rpg",)
    ),
    CanonicalIGDBKeyword(
        "tactical turn-based combat",
        IGDBKeywordBucket.MECHANIC,
        ("tactical turn-based combat",),
    ),
    CanonicalIGDBKeyword(
        "text adventure", IGDBKeywordBucket.GENRE, ("text adventure",)
    ),
    CanonicalIGDBKeyword(
        "third person rpg", IGDBKeywordBucket.GENRE, ("third person rpg",)
    ),
    CanonicalIGDBKeyword(
        "time management", IGDBKeywordBucket.MECHANIC, ("time management",)
    ),
    CanonicalIGDBKeyword(
        "top down shooter", IGDBKeywordBucket.GENRE, ("top down shooter",)
    ),
    CanonicalIGDBKeyword(
        "town building", IGDBKeywordBucket.GENRE, ("town building",)
    ),
    CanonicalIGDBKeyword(
        "town management", IGDBKeywordBucket.GENRE, ("town management",)
    ),
    CanonicalIGDBKeyword(
        "traditional roguelike",
        IGDBKeywordBucket.GENRE,
        ("traditional roguelike",),
    ),
    CanonicalIGDBKeyword("trivia", IGDBKeywordBucket.GENRE, ("trivia",)),
    CanonicalIGDBKeyword(
        "turn based strategy",
        IGDBKeywordBucket.GENRE,
        ("turn based strategy",),
    ),
    CanonicalIGDBKeyword(
        "turn-based rpg", IGDBKeywordBucket.GENRE, ("turn-based rpg",)
    ),
    CanonicalIGDBKeyword(
        "turn-based tactics", IGDBKeywordBucket.GENRE, ("turn-based tactics",)
    ),
    CanonicalIGDBKeyword(
        "vehicle simulation", IGDBKeywordBucket.GENRE, ("vehicle simulation",)
    ),
    CanonicalIGDBKeyword(
        "visual novel", IGDBKeywordBucket.GENRE, ("visual novel",)
    ),
    CanonicalIGDBKeyword(
        "walking simulator", IGDBKeywordBucket.GENRE, ("walking simulator",)
    ),
    CanonicalIGDBKeyword("wargame", IGDBKeywordBucket.GENRE, ("wargame",)),
    CanonicalIGDBKeyword(
        "word puzzle", IGDBKeywordBucket.GENRE, ("word puzzle",)
    ),
    CanonicalIGDBKeyword(
        "world building", IGDBKeywordBucket.MECHANIC, ("world building",)
    ),
    CanonicalIGDBKeyword(
        "zombie shooter", IGDBKeywordBucket.GENRE, ("zombie shooter",)
    ),
    CanonicalIGDBKeyword(
        "zombie survival", IGDBKeywordBucket.GENRE, ("zombie survival",)
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
