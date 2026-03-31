"""Conservative mapping from Steam tags into SpawnRadar setup fields.

This module intentionally maps only high-confidence Steam tags that line up
cleanly with SpawnRadar's existing IGDB-backed setup taxonomy. The goal is to
prefill a few stable fields well, not to aggressively interpret every noisy
store tag on the page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.igdb.taxonomy import IGDBGameMode, IGDBGenre, IGDBTheme


@dataclass(frozen=True)
class SteamTagMappingResult:
    """Mapped SpawnRadar setup fields derived from Steam tags."""

    igdb_genre_ids: list[int] = field(default_factory=list)
    igdb_theme_ids: list[int] = field(default_factory=list)
    igdb_game_mode_ids: list[int] = field(default_factory=list)
    igdb_keyword_ids: list[str] = field(default_factory=list)


MAX_AUTO_GENRES = 8
MAX_AUTO_THEMES = 4
MAX_AUTO_KEYWORDS = 4


def _normalize_lookup_key(value: str) -> str:
    """Normalize Steam labels so spacing and punctuation variants match.

    This keeps the mapping resilient to labels like:
    - ``rogue-like deckbuilder``
    - ``rogue like deck builder``
    - ``deck-building``
    """

    normalized = re.sub(r"[^a-z0-9]+", " ", value.strip().casefold())
    normalized = " ".join(normalized.split())
    normalized = normalized.replace("rogue like", "roguelike")
    normalized = normalized.replace("deck builder", "deckbuilder")
    normalized = normalized.replace("single player", "single-player")
    normalized = normalized.replace("co op", "co-op")
    normalized = normalized.replace("sci fi", "sci-fi")
    return normalized


_STEAM_API_GENRE_TO_IGDB_IDS: dict[str, tuple[int, ...]] = {
    "adventure": (IGDBGenre.ADVENTURE,),
    "indie": (IGDBGenre.INDIE,),
    "platformer": (IGDBGenre.PLATFORM,),
    "puzzle": (IGDBGenre.PUZZLE,),
    "racing": (IGDBGenre.RACING,),
    "rpg": (IGDBGenre.ROLE_PLAYING,),
    "simulation": (IGDBGenre.SIMULATOR,),
    "strategy": (IGDBGenre.STRATEGY,),
    "turn-based strategy": (IGDBGenre.TURN_BASED_STRATEGY,),
    "visual novel": (IGDBGenre.VISUAL_NOVEL,),
}

_STABLE_STORE_TAG_TO_GENRE_IDS: dict[str, tuple[int, ...]] = {
    "adventure": (IGDBGenre.ADVENTURE,),
    "card game": (IGDBGenre.CARD_AND_BOARD_GAME,),
    "indie": (IGDBGenre.INDIE,),
    "platformer": (IGDBGenre.PLATFORM,),
    "puzzle": (IGDBGenre.PUZZLE,),
    "racing": (IGDBGenre.RACING,),
    "rpg": (IGDBGenre.ROLE_PLAYING,),
    "simulation": (IGDBGenre.SIMULATOR,),
    "strategy": (IGDBGenre.STRATEGY,),
    "turn-based strategy": (IGDBGenre.TURN_BASED_STRATEGY,),
    "visual novel": (IGDBGenre.VISUAL_NOVEL,),
}

_STABLE_STORE_TAG_TO_THEME_IDS: dict[str, tuple[int, ...]] = {
    "action": (IGDBTheme.ACTION,),
    "comedy": (IGDBTheme.COMEDY,),
    "fantasy": (IGDBTheme.FANTASY,),
    "historical": (IGDBTheme.HISTORICAL,),
    "horror": (IGDBTheme.HORROR,),
    "mystery": (IGDBTheme.MYSTERY,),
    "open world": (IGDBTheme.OPEN_WORLD,),
    "party": (IGDBTheme.PARTY,),
    "romance": (IGDBTheme.ROMANCE,),
    "sandbox": (IGDBTheme.SANDBOX,),
    "sci-fi": (IGDBTheme.SCIENCE_FICTION,),
    "science fiction": (IGDBTheme.SCIENCE_FICTION,),
    "stealth": (IGDBTheme.STEALTH,),
    "survival": (IGDBTheme.SURVIVAL,),
    "war": (IGDBTheme.WARFARE,),
    "warfare": (IGDBTheme.WARFARE,),
}

_STEAM_API_CATEGORY_TO_GAME_MODE_IDS: dict[str, tuple[int, ...]] = {
    "co-op": (IGDBGameMode.CO_OPERATIVE,),
    "cooperative": (IGDBGameMode.CO_OPERATIVE,),
    "multiplayer": (IGDBGameMode.MULTIPLAYER,),
    "single-player": (IGDBGameMode.SINGLE_PLAYER,),
    "singleplayer": (IGDBGameMode.SINGLE_PLAYER,),
    "split screen": (IGDBGameMode.SPLIT_SCREEN,),
}

_STABLE_STORE_TAG_TO_KEYWORDS: dict[str, tuple[str, ...]] = {
    "automation": ("automation",),
    "base building": ("base building",),
    "bullet hell": ("bullet hell",),
    "casual": ("casual",),
    "city builder": ("city builder",),
    "cozy": ("cozy",),
    "crafting": ("crafting",),
    "deck building": ("deckbuilder",),
    "deck-building": ("deckbuilder",),
    "deckbuilder": ("deckbuilder",),
    "deckbuilding": ("deckbuilder",),
    "dungeon crawler": ("dungeon crawler",),
    "exploration": ("exploration",),
    "inventory management": ("inventory management",),
    "jrpg": ("jrpg",),
    "metroidvania": ("metroidvania",),
    "psychological horror": ("psychological horror",),
    "resource management": ("resource management",),
    "roguelike": ("roguelike",),
    "rogue-like": ("roguelike",),
    "rogue-like deck builder": ("roguelike", "deckbuilder"),
    "roguelike deckbuilder": ("roguelike", "deckbuilder"),
    "roguelite": ("roguelite",),
    "soulslike": ("soulslike",),
    "turn-based rpg": ("turn-based rpg",),
    "turn-based tactics": ("turn-based tactics",),
    "walking simulator": ("walking simulator",),
}

_STEAM_API_GENRE_TO_IGDB_IDS = {
    _normalize_lookup_key(key): value
    for key, value in _STEAM_API_GENRE_TO_IGDB_IDS.items()
}

_STABLE_STORE_TAG_TO_GENRE_IDS = {
    _normalize_lookup_key(key): value
    for key, value in _STABLE_STORE_TAG_TO_GENRE_IDS.items()
}

_STABLE_STORE_TAG_TO_THEME_IDS = {
    _normalize_lookup_key(key): value
    for key, value in _STABLE_STORE_TAG_TO_THEME_IDS.items()
}

_STEAM_API_CATEGORY_TO_GAME_MODE_IDS = {
    _normalize_lookup_key(key): value
    for key, value in _STEAM_API_CATEGORY_TO_GAME_MODE_IDS.items()
}

_STABLE_STORE_TAG_TO_KEYWORDS = {
    _normalize_lookup_key(key): value
    for key, value in _STABLE_STORE_TAG_TO_KEYWORDS.items()
}

_KEYWORD_SUBSTRING_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("roguelite", ("roguelite",)),
    ("roguelike", ("roguelike",)),
    ("deckbuilder", ("deckbuilder",)),
)


def _append_unique_int(values: list[int], additions: tuple[int, ...]) -> None:
    for value in additions:
        if value not in values:
            values.append(int(value))


def _append_unique_str(values: list[str], additions: tuple[str, ...]) -> None:
    for value in additions:
        if value not in values:
            values.append(value)


def _append_keyword_matches_from_tag(
    values: list[str], normalized_tag: str
) -> None:
    for needle, additions in _KEYWORD_SUBSTRING_RULES:
        if needle in normalized_tag:
            _append_unique_str(values, additions)


def _limited_ints(values: list[int], limit: int) -> list[int]:
    return values[:limit]


def _limited_strings(values: list[str], limit: int) -> list[str]:
    return values[:limit]


def map_steam_tags_to_setup_fields(
    *,
    api_genre_labels: list[str],
    api_category_labels: list[str],
    raw_tags: list[str],
    text_blobs: list[str] | None = None,
) -> SteamTagMappingResult:
    """Map high-confidence Steam metadata into SpawnRadar setup fields.

    Trust order:
    1. Steam app-details genres
    2. Steam app-details categories for game modes
    3. A small allowlist of stable store tags for themes and keywords
    """

    igdb_genre_ids: list[int] = []
    igdb_theme_ids: list[int] = []
    igdb_game_mode_ids: list[int] = []
    igdb_keyword_ids: list[str] = []

    for genre_label in api_genre_labels:
        normalized = _normalize_lookup_key(genre_label)
        if not normalized:
            continue
        _append_unique_int(
            igdb_genre_ids,
            _STEAM_API_GENRE_TO_IGDB_IDS.get(normalized, ()),
        )

    for category_label in api_category_labels:
        normalized = _normalize_lookup_key(category_label)
        if not normalized:
            continue
        _append_unique_int(
            igdb_game_mode_ids,
            _STEAM_API_CATEGORY_TO_GAME_MODE_IDS.get(normalized, ()),
        )

    for raw_tag in raw_tags:
        normalized = _normalize_lookup_key(raw_tag)
        if not normalized:
            continue
        _append_unique_int(
            igdb_genre_ids,
            _STABLE_STORE_TAG_TO_GENRE_IDS.get(normalized, ()),
        )
        _append_unique_int(
            igdb_theme_ids,
            _STABLE_STORE_TAG_TO_THEME_IDS.get(normalized, ()),
        )
        _append_unique_str(
            igdb_keyword_ids,
            _STABLE_STORE_TAG_TO_KEYWORDS.get(normalized, ()),
        )
        _append_keyword_matches_from_tag(igdb_keyword_ids, normalized)

    for text_blob in text_blobs or ():
        normalized = _normalize_lookup_key(text_blob)
        if not normalized:
            continue
        _append_keyword_matches_from_tag(igdb_keyword_ids, normalized)

    return SteamTagMappingResult(
        igdb_genre_ids=_limited_ints(igdb_genre_ids, MAX_AUTO_GENRES),
        igdb_theme_ids=_limited_ints(igdb_theme_ids, MAX_AUTO_THEMES),
        igdb_game_mode_ids=igdb_game_mode_ids,
        igdb_keyword_ids=_limited_strings(igdb_keyword_ids, MAX_AUTO_KEYWORDS),
    )
