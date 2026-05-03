"""IGDB canonical genre and theme taxonomy.

IDs and names are verbatim from the IGDB API (/genres and /themes endpoints).
These are stable — IGDB does not reassign IDs.

Usage:
    from app.igdb.taxonomy import IGDBGenre, IGDBTheme

    IGDBGenre.ROLE_PLAYING          # IntEnum: value = 12
    IGDBGenre.ROLE_PLAYING.label    # str: "Role-playing (RPG)"
    IGDBTheme.FANTASY.label         # str: "Fantasy"

    # Iterable for building select inputs:
    list(IGDBGenre)
    [(g.value, g.label) for g in IGDBGenre]
"""

from __future__ import annotations

from enum import IntEnum


class IGDBGenre(IntEnum):
    """IGDB genre IDs — the *type* of game."""

    POINT_AND_CLICK = 2
    FIGHTING = 4
    SHOOTER = 5
    MUSIC = 7
    PLATFORM = 8
    PUZZLE = 9
    RACING = 10
    REAL_TIME_STRATEGY = 11
    ROLE_PLAYING = 12
    SIMULATOR = 13
    SPORT = 14
    STRATEGY = 15
    TURN_BASED_STRATEGY = 16
    TACTICAL = 24
    HACK_AND_SLASH = 25
    QUIZ_TRIVIA = 26
    PINBALL = 30
    ADVENTURE = 31
    INDIE = 32
    ARCADE = 33
    VISUAL_NOVEL = 34
    CARD_AND_BOARD_GAME = 35
    MOBA = 36

    @property
    def label(self) -> str:
        """Official IGDB name string."""
        return _GENRE_LABELS[self.value]

    @classmethod
    def gaming(cls) -> frozenset[IGDBGenre]:
        """Genres relevant to creator indexing."""
        return frozenset(
            {
                cls.POINT_AND_CLICK,
                cls.FIGHTING,
                cls.SHOOTER,
                cls.MUSIC,
                cls.PLATFORM,
                cls.PUZZLE,
                cls.RACING,
                cls.REAL_TIME_STRATEGY,
                cls.ROLE_PLAYING,
                cls.SIMULATOR,
                cls.STRATEGY,
                cls.TURN_BASED_STRATEGY,
                cls.TACTICAL,
                cls.HACK_AND_SLASH,
                cls.ADVENTURE,
                cls.INDIE,
                cls.ARCADE,
                cls.VISUAL_NOVEL,
                cls.CARD_AND_BOARD_GAME,
                cls.MOBA,
            }
        )

    @classmethod
    def labels_for_ids(cls, genre_ids: list[int]) -> list[str]:
        """Convert genre IDs to labels, skipping unknown IDs."""
        return [
            cls(gid).label
            for gid in genre_ids
            if gid in cls._value2member_map_
        ]


_GENRE_LABELS: dict[int, str] = {
    2: "Point-and-click",
    4: "Fighting",
    5: "Shooter",
    7: "Music",
    8: "Platform",
    9: "Puzzle",
    10: "Racing",
    11: "Real Time Strategy (RTS)",
    12: "Role-playing (RPG)",
    13: "Simulator",
    14: "Sport",
    15: "Strategy",
    16: "Turn-based strategy (TBS)",
    24: "Tactical",
    25: "Hack and slash/Beat 'em up",
    26: "Quiz/Trivia",
    30: "Pinball",
    31: "Adventure",
    32: "Indie",
    33: "Arcade",
    34: "Visual Novel",
    35: "Card & Board Game",
    36: "MOBA",
}


class IGDBTheme(IntEnum):
    """IGDB theme IDs — the *setting, mood or atmosphere* of a game.

    Themes replace SpawnRadar's separate 'vibe' and 'mechanics' tag dimensions.
    IGDB's theme taxonomy covers both atmospheric qualities (Fantasy, Horror)
    and gameplay modes (Survival, Stealth, Sandbox).
    """

    ACTION = 1
    FANTASY = 17
    SCIENCE_FICTION = 18
    HORROR = 19
    THRILLER = 20
    SURVIVAL = 21
    HISTORICAL = 22
    STEALTH = 23
    COMEDY = 27
    BUSINESS = 28
    DRAMA = 31
    NON_FICTION = 32
    SANDBOX = 33
    EDUCATIONAL = 34
    KIDS = 35
    OPEN_WORLD = 38
    WARFARE = 39
    PARTY = 40
    FOUR_X = 41
    EROTIC = 42
    MYSTERY = 43
    ROMANCE = 44

    @property
    def label(self) -> str:
        """Official IGDB name string."""
        return _THEME_LABELS[self.value]

    @classmethod
    def gaming(cls) -> frozenset[IGDBTheme]:
        """Themes relevant to creator indexing."""
        return frozenset(
            {
                cls.ACTION,
                cls.FANTASY,
                cls.SCIENCE_FICTION,
                cls.HORROR,
                cls.THRILLER,
                cls.SURVIVAL,
                cls.HISTORICAL,
                cls.STEALTH,
                cls.COMEDY,
                cls.DRAMA,
                cls.SANDBOX,
                cls.OPEN_WORLD,
                cls.WARFARE,
                cls.PARTY,
                cls.FOUR_X,
                cls.MYSTERY,
                cls.ROMANCE,
            }
        )

    @classmethod
    def labels_for_ids(cls, theme_ids: list[int]) -> list[str]:
        """Convert theme IDs to labels, skipping unknown IDs."""
        return [
            cls(tid).label
            for tid in theme_ids
            if tid in cls._value2member_map_
        ]


_THEME_LABELS: dict[int, str] = {
    1: "Action",
    17: "Fantasy",
    18: "Science fiction",
    19: "Horror",
    20: "Thriller",
    21: "Survival",
    22: "Historical",
    23: "Stealth",
    27: "Comedy",
    28: "Business",
    31: "Drama",
    32: "Non-fiction",
    33: "Sandbox",
    34: "Educational",
    35: "Kids",
    38: "Open world",
    39: "Warfare",
    40: "Party",
    41: "4X (explore, expand, exploit and exterminate)",
    42: "Erotic",
    43: "Mystery",
    44: "Romance",
}


class IGDBGameMode(IntEnum):
    """IGDB game mode IDs."""

    SINGLE_PLAYER = 1
    MULTIPLAYER = 2
    CO_OPERATIVE = 3
    SPLIT_SCREEN = 4
    MASSIVELY_MULTIPLAYER_ONLINE = 5
    BATTLE_ROYALE = 6

    @property
    def label(self) -> str:
        return _GAME_MODE_LABELS[self.value]

    @classmethod
    def labels_for_ids(cls, game_mode_ids: list[int]) -> list[str]:
        return [
            cls(mode_id).label
            for mode_id in game_mode_ids
            if mode_id in cls._value2member_map_
        ]


_GAME_MODE_LABELS: dict[int, str] = {
    1: "Single player",
    2: "Multiplayer",
    3: "Co-operative",
    4: "Split screen",
    5: "Massively Multiplayer Online (MMO)",
    6: "Battle Royale",
}


class IGDBPlayerPerspective(IntEnum):
    """IGDB player perspective IDs."""

    FIRST_PERSON = 1
    THIRD_PERSON = 2
    BIRD_VIEW_ISOMETRIC = 3
    SIDE_VIEW = 4
    TEXT = 5
    AUDITORY = 6
    VIRTUAL_REALITY = 7

    @property
    def label(self) -> str:
        return _PLAYER_PERSPECTIVE_LABELS[self.value]

    @classmethod
    def labels_for_ids(cls, player_perspective_ids: list[int]) -> list[str]:
        return [
            cls(perspective_id).label
            for perspective_id in player_perspective_ids
            if perspective_id in cls._value2member_map_
        ]


_PLAYER_PERSPECTIVE_LABELS: dict[int, str] = {
    1: "First person",
    2: "Third person",
    3: "Bird view / Isometric",
    4: "Side view",
    5: "Text",
    6: "Auditory",
    7: "Virtual Reality",
}


# ---------------------------------------------------------------------------
# Keyword groups (canonical concepts with IGDB alias expansion)
# ---------------------------------------------------------------------------

# Re-export the core types so callers can import from taxonomy.
from app.igdb.keyword_groups import (  # noqa: E402, F401
    CANONICAL_IGDB_KEYWORD_TO_ALIASES,
    IGDB_GENRE_KEYWORDS,
    IGDB_KEYWORD_GROUPS,
    IGDB_MECHANIC_KEYWORDS,
    IGDB_THEME_KEYWORDS,
    RAW_IGDB_KEYWORD_TO_CANONICAL,
    CanonicalIGDBKeyword,
    IGDBKeywordBucket,
)

_SPECIAL_KEYWORD_LABEL_TOKENS = {
    "2d": "2D",
    "3d": "3D",
    "4x": "4X",
    "arpg": "ARPG",
    "co-op": "Co-op",
    "crpg": "CRPG",
    "drpg": "DRPG",
    "fmv": "FMV",
    "jrpg": "JRPG",
    "mmo": "MMO",
    "moba": "MOBA",
    "pve": "PvE",
    "pvp": "PvP",
    "rpg": "RPG",
    "rts": "RTS",
    "tbs": "TBS",
    "vr": "VR",
}
_CANONICAL_KEYWORD_TO_BUCKET = {
    keyword.canonical: keyword.bucket for keyword in IGDB_KEYWORD_GROUPS
}


def canonical_keyword_for_igdb_name(raw: str) -> str | None:
    """Map a raw IGDB keyword name to its canonical curated concept."""
    return RAW_IGDB_KEYWORD_TO_CANONICAL.get(raw)


def keyword_bucket_for_value(value: str) -> IGDBKeywordBucket | None:
    """Return the curated bucket for a canonical keyword value."""
    return _CANONICAL_KEYWORD_TO_BUCKET.get(value)


def keyword_label_for_value(value: str) -> str | None:
    """Render a canonical keyword into a human-readable label."""
    if value not in _CANONICAL_KEYWORD_TO_BUCKET:
        return None
    return " ".join(
        _SPECIAL_KEYWORD_LABEL_TOKENS.get(token, token.capitalize())
        for token in value.split()
    )


def keyword_labels_for_values(values: list[str]) -> list[str]:
    """Convert canonical keyword strings to human-readable labels."""
    labels: list[str] = []
    for value in values:
        label = keyword_label_for_value(value)
        if label is not None:
            labels.append(label)
    return labels


def all_canonical_keywords() -> tuple[CanonicalIGDBKeyword, ...]:
    """Return all canonical keywords (the full curated set)."""
    return IGDB_KEYWORD_GROUPS


def canonical_to_igdb_aliases(canonical: str) -> tuple[str, ...]:
    """Return the IGDB keyword strings that map to a canonical concept.

    Used by the discovery pipeline to expand a customer-selected keyword
    (e.g. ``"deckbuilder"``) into all IGDB variants for search.
    Falls back to ``(canonical,)`` if not found.
    """
    return CANONICAL_IGDB_KEYWORD_TO_ALIASES.get(canonical, (canonical,))


__all__ = [
    "IGDBGenre",
    "IGDBTheme",
    "IGDBGameMode",
    "IGDBPlayerPerspective",
    "CanonicalIGDBKeyword",
    "IGDBKeywordBucket",
    "IGDB_KEYWORD_GROUPS",
    "IGDB_GENRE_KEYWORDS",
    "IGDB_THEME_KEYWORDS",
    "IGDB_MECHANIC_KEYWORDS",
    "CANONICAL_IGDB_KEYWORD_TO_ALIASES",
    "RAW_IGDB_KEYWORD_TO_CANONICAL",
    "canonical_keyword_for_igdb_name",
    "keyword_bucket_for_value",
    "keyword_label_for_value",
    "keyword_labels_for_values",
    "all_canonical_keywords",
    "canonical_to_igdb_aliases",
]
