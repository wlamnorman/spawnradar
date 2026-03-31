"""Deterministic Steam tag mapping into SpawnRadar's canonical tag space.

Rules here should stay conservative:

- keep raw Steam tags separately
- map only stable concepts into current setup fields
- use explicit decomposition rules for compound labels when a combined
  canonical target does not exist

This module is shared by both setup import and background IGDB enrichment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.igdb.taxonomy import (
    IGDBGameMode,
    IGDBGenre,
    IGDBPlayerPerspective,
    IGDBTheme,
    keyword_bucket_for_value,
    keyword_label_for_value,
)
from app.steam_enrichment.models import SteamMappedTag


@dataclass(frozen=True)
class SteamSetupFieldMapping:
    """Grouped setup-field mappings for existing form flows."""

    igdb_genre_ids: list[int] = field(default_factory=list)
    igdb_theme_ids: list[int] = field(default_factory=list)
    igdb_game_mode_ids: list[int] = field(default_factory=list)
    igdb_player_perspective_ids: list[int] = field(default_factory=list)
    igdb_keyword_ids: list[str] = field(default_factory=list)


def normalize_steam_label(value: str) -> str:
    """Normalize Steam labels for deterministic lookup and soft matching."""

    normalized = re.sub(r"[^a-z0-9]+", " ", value.strip().casefold())
    normalized = " ".join(normalized.split())
    normalized = normalized.replace("rogue like", "roguelike")
    normalized = normalized.replace("deck builder", "deckbuilder")
    normalized = normalized.replace("single player", "single-player")
    normalized = normalized.replace("co op", "co-op")
    normalized = normalized.replace("sci fi", "sci-fi")
    normalized = normalized.replace("souls like", "soulslike")
    normalized = normalized.replace("third person", "third-person")
    normalized = normalized.replace("first person", "first-person")
    normalized = normalized.replace("turn based", "turn-based")
    return normalized


def _mapped(
    source_tag: str,
    tag_type: str,
    tag_id: int | str,
    tag_name: str,
    mapping_kind: str,
) -> SteamMappedTag:
    return SteamMappedTag(
        source_tag=source_tag,
        tag_type=tag_type,
        tag_id=tag_id,
        tag_name=tag_name,
        mapping_kind=mapping_kind,
    )


_STEAM_API_GENRE_RULES: dict[str, tuple[tuple[str, int | str, str], ...]] = {
    "adventure": (("genre", IGDBGenre.ADVENTURE, IGDBGenre.ADVENTURE.label),),
    "indie": (("genre", IGDBGenre.INDIE, IGDBGenre.INDIE.label),),
    "platformer": (("genre", IGDBGenre.PLATFORM, IGDBGenre.PLATFORM.label),),
    "puzzle": (("genre", IGDBGenre.PUZZLE, IGDBGenre.PUZZLE.label),),
    "racing": (("genre", IGDBGenre.RACING, IGDBGenre.RACING.label),),
    "rpg": (("genre", IGDBGenre.ROLE_PLAYING, IGDBGenre.ROLE_PLAYING.label),),
    "simulation": (("genre", IGDBGenre.SIMULATOR, IGDBGenre.SIMULATOR.label),),
    "strategy": (("genre", IGDBGenre.STRATEGY, IGDBGenre.STRATEGY.label),),
    "turn-based strategy": (
        (
            "genre",
            IGDBGenre.TURN_BASED_STRATEGY,
            IGDBGenre.TURN_BASED_STRATEGY.label,
        ),
    ),
    "visual novel": (
        ("genre", IGDBGenre.VISUAL_NOVEL, IGDBGenre.VISUAL_NOVEL.label),
    ),
}

_STEAM_API_CATEGORY_RULES: dict[
    str, tuple[tuple[str, int | str, str], ...]
] = {
    "co-op": (
        (
            "game_mode",
            IGDBGameMode.CO_OPERATIVE,
            IGDBGameMode.CO_OPERATIVE.label,
        ),
    ),
    "cooperative": (
        (
            "game_mode",
            IGDBGameMode.CO_OPERATIVE,
            IGDBGameMode.CO_OPERATIVE.label,
        ),
    ),
    "multiplayer": (
        (
            "game_mode",
            IGDBGameMode.MULTIPLAYER,
            IGDBGameMode.MULTIPLAYER.label,
        ),
    ),
    "single-player": (
        (
            "game_mode",
            IGDBGameMode.SINGLE_PLAYER,
            IGDBGameMode.SINGLE_PLAYER.label,
        ),
    ),
    "singleplayer": (
        (
            "game_mode",
            IGDBGameMode.SINGLE_PLAYER,
            IGDBGameMode.SINGLE_PLAYER.label,
        ),
    ),
    "split screen": (
        (
            "game_mode",
            IGDBGameMode.SPLIT_SCREEN,
            IGDBGameMode.SPLIT_SCREEN.label,
        ),
    ),
    "full controller support": (),
}

_STEAM_STORE_RULES: dict[str, tuple[tuple[str, int | str, str], ...]] = {
    "adventure": (("genre", IGDBGenre.ADVENTURE, IGDBGenre.ADVENTURE.label),),
    "card game": (
        (
            "genre",
            IGDBGenre.CARD_AND_BOARD_GAME,
            IGDBGenre.CARD_AND_BOARD_GAME.label,
        ),
    ),
    "cozy": (("theme", "cozy", "Cozy"),),
    "city builder": (("genre", "city builder", "City Builder"),),
    "casual": (("theme", "casual", "Casual"),),
    "crafting": (("mechanic", "crafting", "Crafting"),),
    "deckbuilder": (("genre", "deckbuilder", "Deckbuilder"),),
    "deck building": (("genre", "deckbuilder", "Deckbuilder"),),
    "deck-building": (("genre", "deckbuilder", "Deckbuilder"),),
    "deckbuilding": (("genre", "deckbuilder", "Deckbuilder"),),
    "dungeon crawler": (("genre", "dungeon crawler", "Dungeon Crawler"),),
    "exploration": (("mechanic", "exploration", "Exploration"),),
    "first-person": (
        (
            "player_perspective",
            IGDBPlayerPerspective.FIRST_PERSON,
            IGDBPlayerPerspective.FIRST_PERSON.label,
        ),
    ),
    "indie": (("genre", IGDBGenre.INDIE, IGDBGenre.INDIE.label),),
    "inventory management": (
        ("mechanic", "inventory management", "Inventory Management"),
    ),
    "jrpg": (("genre", "jrpg", "JRPG"),),
    "metroidvania": (("genre", "metroidvania", "Metroidvania"),),
    "multiplayer": (
        (
            "game_mode",
            IGDBGameMode.MULTIPLAYER,
            IGDBGameMode.MULTIPLAYER.label,
        ),
    ),
    "online co-op": (
        (
            "game_mode",
            IGDBGameMode.MULTIPLAYER,
            IGDBGameMode.MULTIPLAYER.label,
        ),
        (
            "game_mode",
            IGDBGameMode.CO_OPERATIVE,
            IGDBGameMode.CO_OPERATIVE.label,
        ),
    ),
    "party-based rpg": (("genre", "party-based rpg", "Party-Based RPG"),),
    "platformer": (("genre", IGDBGenre.PLATFORM, IGDBGenre.PLATFORM.label),),
    "procedural generation": (
        ("mechanic", "world building", "World Building"),
    ),
    "psychological horror": (
        ("theme", "psychological horror", "Psychological Horror"),
    ),
    "puzzle": (("genre", IGDBGenre.PUZZLE, IGDBGenre.PUZZLE.label),),
    "racing": (("genre", IGDBGenre.RACING, IGDBGenre.RACING.label),),
    "resource management": (
        ("mechanic", "resource management", "Resource Management"),
    ),
    "roguelike": (("genre", "roguelike", "Roguelike"),),
    "roguelike deckbuilder": (
        ("genre", "roguelike", "Roguelike"),
        ("genre", "deckbuilder", "Deckbuilder"),
    ),
    "rogue-like": (("genre", "roguelike", "Roguelike"),),
    "rogue-like deckbuilder": (
        ("genre", "roguelike", "Roguelike"),
        ("genre", "deckbuilder", "Deckbuilder"),
    ),
    "roguelite": (("genre", "roguelite", "Roguelite"),),
    "rpg": (("genre", IGDBGenre.ROLE_PLAYING, IGDBGenre.ROLE_PLAYING.label),),
    "sci-fi": (
        ("theme", IGDBTheme.SCIENCE_FICTION, IGDBTheme.SCIENCE_FICTION.label),
    ),
    "science fiction": (
        ("theme", IGDBTheme.SCIENCE_FICTION, IGDBTheme.SCIENCE_FICTION.label),
    ),
    "shooter": (("genre", IGDBGenre.SHOOTER, IGDBGenre.SHOOTER.label),),
    "single-player": (
        (
            "game_mode",
            IGDBGameMode.SINGLE_PLAYER,
            IGDBGameMode.SINGLE_PLAYER.label,
        ),
    ),
    "singleplayer": (
        (
            "game_mode",
            IGDBGameMode.SINGLE_PLAYER,
            IGDBGameMode.SINGLE_PLAYER.label,
        ),
    ),
    "souls-like": (("genre", "soulslike", "Soulslike"),),
    "soulslike": (("genre", "soulslike", "Soulslike"),),
    "strategy": (("genre", IGDBGenre.STRATEGY, IGDBGenre.STRATEGY.label),),
    "survival": (("theme", IGDBTheme.SURVIVAL, IGDBTheme.SURVIVAL.label),),
    "tactical": (("genre", IGDBGenre.TACTICAL, IGDBGenre.TACTICAL.label),),
    "third-person": (
        (
            "player_perspective",
            IGDBPlayerPerspective.THIRD_PERSON,
            IGDBPlayerPerspective.THIRD_PERSON.label,
        ),
    ),
    "turn-based rpg": (("genre", "turn-based rpg", "Turn-Based RPG"),),
    "turn-based strategy": (
        (
            "genre",
            IGDBGenre.TURN_BASED_STRATEGY,
            IGDBGenre.TURN_BASED_STRATEGY.label,
        ),
    ),
    "turn-based tactics": (
        ("genre", "turn-based tactics", "Turn-Based Tactics"),
    ),
    "visual novel": (
        ("genre", IGDBGenre.VISUAL_NOVEL, IGDBGenre.VISUAL_NOVEL.label),
    ),
}

_COMPOUND_SPLIT_RULES: dict[str, tuple[tuple[str, int | str, str], ...]] = {
    "action rpg": (
        ("theme", IGDBTheme.ACTION, IGDBTheme.ACTION.label),
        ("genre", IGDBGenre.ROLE_PLAYING, IGDBGenre.ROLE_PLAYING.label),
    ),
    "first-person shooter": (
        (
            "player_perspective",
            IGDBPlayerPerspective.FIRST_PERSON,
            IGDBPlayerPerspective.FIRST_PERSON.label,
        ),
        ("genre", IGDBGenre.SHOOTER, IGDBGenre.SHOOTER.label),
    ),
    "survival horror": (
        ("theme", IGDBTheme.SURVIVAL, IGDBTheme.SURVIVAL.label),
        ("theme", IGDBTheme.HORROR, IGDBTheme.HORROR.label),
    ),
    "third-person shooter": (
        (
            "player_perspective",
            IGDBPlayerPerspective.THIRD_PERSON,
            IGDBPlayerPerspective.THIRD_PERSON.label,
        ),
        ("genre", IGDBGenre.SHOOTER, IGDBGenre.SHOOTER.label),
    ),
}

_KEYWORD_SUBSTRING_RULES: tuple[
    tuple[str, tuple[tuple[str, int | str, str], ...]], ...
] = (
    ("roguelite", (("genre", "roguelite", "Roguelite"),)),
    ("roguelike", (("genre", "roguelike", "Roguelike"),)),
    ("deckbuilder", (("genre", "deckbuilder", "Deckbuilder"),)),
)

_TEXT_PHRASE_RULES: dict[str, tuple[tuple[str, int | str, str], ...]] = {
    "base building": (("mechanic", "base building", "Base Building"),),
    "city builder": (("genre", "city builder", "City Builder"),),
    "deck building": (("genre", "deckbuilder", "Deckbuilder"),),
    "deckbuilder": (("genre", "deckbuilder", "Deckbuilder"),),
    "dungeon crawler": (("genre", "dungeon crawler", "Dungeon Crawler"),),
    "inventory management": (
        ("mechanic", "inventory management", "Inventory Management"),
    ),
    "metroidvania": (("genre", "metroidvania", "Metroidvania"),),
    "psychological horror": (
        ("theme", "psychological horror", "Psychological Horror"),
    ),
    "resource management": (
        ("mechanic", "resource management", "Resource Management"),
    ),
    "roguelike": (("genre", "roguelike", "Roguelike"),),
    "roguelite": (("genre", "roguelite", "Roguelite"),),
    "soulslike": (("genre", "soulslike", "Soulslike"),),
    "survival horror": (
        ("theme", IGDBTheme.SURVIVAL, IGDBTheme.SURVIVAL.label),
        ("theme", IGDBTheme.HORROR, IGDBTheme.HORROR.label),
    ),
    "turn-based rpg": (("genre", "turn-based rpg", "Turn-Based RPG"),),
    "turn-based tactics": (
        ("genre", "turn-based tactics", "Turn-Based Tactics"),
    ),
}


def _dedupe_mapped_tags(values: list[SteamMappedTag]) -> list[SteamMappedTag]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[SteamMappedTag] = []
    for value in values:
        key = (value.tag_type, str(value.tag_id), value.source_tag.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _map_rules(
    source_tag: str,
    normalized_tag: str,
    rules: dict[str, tuple[tuple[str, int | str, str], ...]],
    mapping_kind: str,
) -> list[SteamMappedTag]:
    entries = rules.get(normalized_tag, ())
    return [
        _mapped(source_tag, tag_type, tag_id, tag_name, mapping_kind)
        for tag_type, tag_id, tag_name in entries
    ]


def _count_phrase_occurrences(text: str, phrase: str) -> int:
    pattern = rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])"
    return len(re.findall(pattern, text))


def map_steam_terms_to_canonical_tags(
    *,
    api_genre_labels: list[str],
    api_category_labels: list[str],
    raw_tags: list[str],
    text_blobs: list[str] | None = None,
) -> list[SteamMappedTag]:
    """Map Steam metadata into SpawnRadar's canonical tag space."""

    results: list[SteamMappedTag] = []

    for label in api_genre_labels:
        normalized = normalize_steam_label(label)
        if normalized:
            results.extend(
                _map_rules(
                    label,
                    normalized,
                    _STEAM_API_GENRE_RULES,
                    "exact_api_genre",
                )
            )

    for label in api_category_labels:
        normalized = normalize_steam_label(label)
        if normalized:
            results.extend(
                _map_rules(
                    label,
                    normalized,
                    _STEAM_API_CATEGORY_RULES,
                    "exact_api_category",
                )
            )

    for raw_tag in raw_tags:
        normalized = normalize_steam_label(raw_tag)
        if not normalized:
            continue
        results.extend(
            _map_rules(
                raw_tag, normalized, _STEAM_STORE_RULES, "exact_store_tag"
            )
        )
        if normalized not in _STEAM_STORE_RULES:
            results.extend(
                _map_rules(
                    raw_tag,
                    normalized,
                    _COMPOUND_SPLIT_RULES,
                    "compound_split",
                )
            )
        for needle, additions in _KEYWORD_SUBSTRING_RULES:
            if needle in normalized:
                results.extend(
                    _mapped(
                        raw_tag,
                        tag_type,
                        tag_id,
                        tag_name,
                        "substring_keyword",
                    )
                    for tag_type, tag_id, tag_name in additions
                )

    if text_blobs:
        occurrence_counts = dict.fromkeys(_TEXT_PHRASE_RULES, 0)
        for blob in text_blobs:
            normalized_blob = normalize_steam_label(blob)
            if not normalized_blob:
                continue
            for phrase in _TEXT_PHRASE_RULES:
                occurrence_counts[phrase] += _count_phrase_occurrences(
                    normalized_blob, phrase
                )
        for phrase, count in occurrence_counts.items():
            if count < 2:
                continue
            results.extend(
                _mapped(
                    phrase,
                    tag_type,
                    tag_id,
                    tag_name,
                    "text_phrase",
                )
                for tag_type, tag_id, tag_name in _TEXT_PHRASE_RULES[phrase]
            )

    return _dedupe_mapped_tags(results)


def map_steam_tags_to_setup_fields(
    *,
    api_genre_labels: list[str],
    api_category_labels: list[str],
    raw_tags: list[str],
    text_blobs: list[str] | None = None,
) -> SteamSetupFieldMapping:
    """Return grouped setup fields from mapped Steam terms."""

    mapped = map_steam_terms_to_canonical_tags(
        api_genre_labels=api_genre_labels,
        api_category_labels=api_category_labels,
        raw_tags=raw_tags,
        text_blobs=text_blobs,
    )
    result = SteamSetupFieldMapping()
    for entry in mapped:
        if entry.tag_type == "genre":
            if isinstance(entry.tag_id, int):
                if entry.tag_id not in result.igdb_genre_ids:
                    result.igdb_genre_ids.append(entry.tag_id)
            else:
                if entry.tag_id not in result.igdb_keyword_ids:
                    result.igdb_keyword_ids.append(entry.tag_id)
        elif entry.tag_type == "theme":
            if isinstance(entry.tag_id, int):
                if entry.tag_id not in result.igdb_theme_ids:
                    result.igdb_theme_ids.append(entry.tag_id)
            else:
                if entry.tag_id not in result.igdb_keyword_ids:
                    result.igdb_keyword_ids.append(entry.tag_id)
        elif entry.tag_type == "mechanic":
            if str(entry.tag_id) not in result.igdb_keyword_ids:
                result.igdb_keyword_ids.append(str(entry.tag_id))
        elif entry.tag_type == "game_mode":
            if (
                isinstance(entry.tag_id, int)
                and entry.tag_id not in result.igdb_game_mode_ids
            ):
                result.igdb_game_mode_ids.append(entry.tag_id)
        elif (
            entry.tag_type == "player_perspective"
            and isinstance(entry.tag_id, int)
            and entry.tag_id not in result.igdb_player_perspective_ids
        ):
            result.igdb_player_perspective_ids.append(entry.tag_id)
    return result


def mapped_tag_name_for(tag_type: str, tag_id: int | str) -> str | None:
    """Return a label for a mapped canonical tag."""

    if isinstance(tag_id, str):
        label = keyword_label_for_value(tag_id)
        return label
    if tag_type == "genre":
        if tag_id in IGDBGenre._value2member_map_:
            return IGDBGenre(tag_id).label
        return None
    if tag_type == "theme":
        if tag_id in IGDBTheme._value2member_map_:
            return IGDBTheme(tag_id).label
        return None
    if tag_type == "game_mode":
        if tag_id in IGDBGameMode._value2member_map_:
            return IGDBGameMode(tag_id).label
        return None
    if tag_type == "player_perspective":
        if tag_id in IGDBPlayerPerspective._value2member_map_:
            return IGDBPlayerPerspective(tag_id).label
        return None
    return None


def mapped_tag_bucket_for(tag_id: str) -> str | None:
    """Return the keyword bucket for a canonical keyword string."""

    bucket = keyword_bucket_for_value(tag_id)
    if bucket is None:
        return None
    return bucket.value
