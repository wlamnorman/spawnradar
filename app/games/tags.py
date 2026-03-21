"""Canonical game tag taxonomy, normalization, and structured tag profiles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

TagKind = Literal["genre", "audience"]
TagWeight = Literal["primary", "secondary", "custom"]

_WEIGHT_PRIORITY: dict[TagWeight, int] = {
    "primary": 3,
    "secondary": 2,
    "custom": 1,
}


GENRE_TAG_CATALOG = [
    "4x",
    "action",
    "action roguelike",
    "adventure",
    "arcade",
    "auto battler",
    "base building",
    "bullet heaven",
    "card battler",
    "city builder",
    "cozy",
    "colony sim",
    "crafting",
    "daily challenge",
    "deckbuilder",
    "detective",
    "dungeon crawler",
    "factory automation",
    "farming sim",
    "grand strategy",
    "hidden object",
    "horror",
    "idle",
    "immersive sim",
    "incremental",
    "life sim",
    "management",
    "metroidvania",
    "monster taming",
    "musou",
    "narrative adventure",
    "open world",
    "party game",
    "platformer",
    "precision platformer",
    "puzzle",
    "puzzle platformer",
    "racing",
    "real-time strategy",
    "rhythm",
    "roguelike",
    "roguelite",
    "rpg",
    "sandbox",
    "sci-fi",
    "shmup",
    "simulation",
    "soulslike",
    "space",
    "space sim",
    "sports",
    "stealth",
    "strategy",
    "survival",
    "survival horror",
    "tactics",
    "tower defense",
    "trivia",
    "turn-based combat",
    "turn-based strategy",
    "turn-based tactics",
    "twin-stick shooter",
    "visual novel",
    "walking simulator",
    "word game",
]

AUDIENCE_TAG_CATALOG = [
    "achievement hunters",
    "action players",
    "automation fans",
    "builders",
    "card game players",
    "casual gamers",
    "challenge seekers",
    "co-op groups",
    "competitive players",
    "completionists",
    "cozy gamers",
    "deckbuilder fans",
    "demo hunters",
    "factorio fans",
    "factory game fans",
    "farm sim players",
    "hardcore strategy players",
    "horror fans",
    "indie game fans",
    "metroidvania fans",
    "mobile players",
    "narrative game fans",
    "pc players",
    "platformer fans",
    "puzzle fans",
    "puzzle solvers",
    "retro gamers",
    "rimworld fans",
    "roguelike fans",
    "roguelite fans",
    "rpg fans",
    "sandbox fans",
    "sim fans",
    "sci-fi players",
    "singleplayer players",
    "slay the spire fans",
    "soulslike fans",
    "space game fans",
    "spectacle seekers",
    "speedrunners",
    "starter strategy players",
    "steam deck players",
    "steam players",
    "story-driven players",
    "strategy fans",
    "stream viewers",
    "survival fans",
    "tactics players",
    "theorycrafters",
    "tower defense fans",
    "trivia fans",
    "turn-based strategy fans",
    "vampire survivors fans",
    "wikipedia fans",
    "word game players",
    "wordle fans",
    "xcom fans",
    "zachlike fans",
]

FEATURED_GENRE_TAGS = [
    "strategy",
    "turn-based tactics",
    "turn-based strategy",
    "roguelite",
    "roguelike",
    "puzzle",
    "word game",
    "deckbuilder",
    "tower defense",
    "factory automation",
    "metroidvania",
    "platformer",
    "rpg",
    "arcade",
    "real-time strategy",
    "survival",
    "narrative adventure",
    "daily challenge",
]

FEATURED_AUDIENCE_TAGS = [
    "strategy fans",
    "tactics players",
    "puzzle fans",
    "puzzle solvers",
    "roguelite fans",
    "roguelike fans",
    "deckbuilder fans",
    "word game players",
    "wordle fans",
    "indie game fans",
    "pc players",
    "steam players",
    "speedrunners",
    "challenge seekers",
    "story-driven players",
    "completionists",
    "xcom fans",
    "wikipedia fans",
]

_GENRE_ALIASES = {
    "action adventure": "adventure",
    "action-roguelike": "action roguelike",
    "auto-battler": "auto battler",
    "basebuilder": "base building",
    "bullet-heaven": "bullet heaven",
    "bullet heaven survivor": "bullet heaven",
    "card battle": "card battler",
    "city bulider": "city builder",
    "citybuilding": "city builder",
    "city-builder": "city builder",
    "cozy game": "cozy",
    "colony management": "colony sim",
    "daily puzzle": "daily challenge",
    "deck bulider": "deckbuilder",
    "deck builder": "deckbuilder",
    "deck-building": "deckbuilder",
    "factory builder": "factory automation",
    "farming simulator": "farming sim",
    "grand-strategy": "grand strategy",
    "hidden-object": "hidden object",
    "idle game": "idle",
    "incremental game": "incremental",
    "life simulation": "life sim",
    "metroid-vania": "metroidvania",
    "metroidvaina": "metroidvania",
    "monster tamer": "monster taming",
    "musuo": "musou",
    "narrative": "narrative adventure",
    "open-world": "open world",
    "precision platforming": "precision platformer",
    "puzzle-platformer": "puzzle platformer",
    "rts": "real-time strategy",
    "real time strategy": "real-time strategy",
    "sci fi": "sci-fi",
    "rogue like": "roguelike",
    "rogue-lite": "roguelite",
    "rogue lite": "roguelite",
    "shoot em up": "shmup",
    "shoot-em-up": "shmup",
    "space simulation": "space sim",
    "story adventure": "narrative adventure",
    "survivorlike": "bullet heaven",
    "tower defence": "tower defense",
    "turn based combat": "turn-based combat",
    "turn based strategy": "turn-based strategy",
    "turn based tactics": "turn-based tactics",
    "twin stick shooter": "twin-stick shooter",
    "visual-novel": "visual novel",
    "walking sim": "walking simulator",
    "word puzzle": "word game",
}

_AUDIENCE_ALIASES = {
    "achievement hunter": "achievement hunters",
    "automation players": "automation fans",
    "card players": "card game players",
    "casual players": "casual gamers",
    "completionist": "completionists",
    "cozy players": "cozy gamers",
    "deck builder fans": "deckbuilder fans",
    "factorio players": "factorio fans",
    "factory fans": "factory game fans",
    "hardcore strategy fans": "hardcore strategy players",
    "indie players": "indie game fans",
    "metroidvania players": "metroidvania fans",
    "pc gamers": "pc players",
    "platformer players": "platformer fans",
    "puzzle lovers": "puzzle fans",
    "puzzle players": "puzzle fans",
    "retro players": "retro gamers",
    "rimworld players": "rimworld fans",
    "rogue like fans": "roguelike fans",
    "rogue lite fans": "roguelite fans",
    "roguelike players": "roguelike fans",
    "roguelite players": "roguelite fans",
    "rpg players": "rpg fans",
    "simulation fans": "sim fans",
    "sci fi players": "sci-fi players",
    "single player players": "singleplayer players",
    "soulslike players": "soulslike fans",
    "space fans": "space game fans",
    "speed runners": "speedrunners",
    "steam users": "steam players",
    "story players": "story-driven players",
    "strategy players": "strategy fans",
    "survival players": "survival fans",
    "tactics fans": "tactics players",
    "tower defence fans": "tower defense fans",
    "turn based strategy fans": "turn-based strategy fans",
    "word game fans": "word game players",
    "wordle players": "wordle fans",
    "xcom players": "xcom fans",
}

_CATALOG_BY_KIND: dict[TagKind, list[str]] = {
    "genre": GENRE_TAG_CATALOG,
    "audience": AUDIENCE_TAG_CATALOG,
}
_FEATURED_BY_KIND: dict[TagKind, list[str]] = {
    "genre": FEATURED_GENRE_TAGS,
    "audience": FEATURED_AUDIENCE_TAGS,
}
_ALIASES_BY_KIND: dict[TagKind, dict[str, str]] = {
    "genre": _GENRE_ALIASES,
    "audience": _AUDIENCE_ALIASES,
}

_CANONICAL_KEY_TO_NAME: dict[TagKind, dict[str, str]] = {}
_SEARCH_KEYS: dict[TagKind, dict[str, str]] = {}


def _normalize_key(value: str) -> str:
    cleaned = value.strip().lower()
    cleaned = cleaned.replace("&", " and ")
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


for _kind, _catalog in _CATALOG_BY_KIND.items():
    canonical_map = {_normalize_key(tag): tag for tag in _catalog}
    search_keys = dict(canonical_map)
    for alias, canonical in _ALIASES_BY_KIND[_kind].items():
        search_keys[_normalize_key(alias)] = canonical
    _CANONICAL_KEY_TO_NAME[_kind] = canonical_map
    _SEARCH_KEYS[_kind] = search_keys


@dataclass(frozen=True)
class WeightedTag:
    """A tag with a relative importance value for scoring and query order."""

    name: str
    weight: float
    label: TagWeight


@dataclass(frozen=True)
class TagProfile:
    """Structured tags split into primary, secondary, and custom buckets."""

    primary: tuple[str, ...] = ()
    secondary: tuple[str, ...] = ()
    custom: tuple[str, ...] = ()

    @classmethod
    def empty(cls) -> TagProfile:
        return cls()

    @classmethod
    def from_flat_tags(
        cls, tags: list[str], *, default_weight: TagWeight = "primary"
    ) -> TagProfile:
        cleaned = tuple(_dedupe_preserving_order(tags))
        if default_weight == "primary":
            return cls(primary=cleaned)
        if default_weight == "secondary":
            return cls(secondary=cleaned)
        return cls(custom=cleaned)

    @classmethod
    def from_json_value(cls, value: object) -> TagProfile:
        if not isinstance(value, dict):
            return cls.empty()
        return cls(
            primary=tuple(
                item
                for item in value.get("primary", [])
                if isinstance(item, str)
            ),
            secondary=tuple(
                item
                for item in value.get("secondary", [])
                if isinstance(item, str)
            ),
            custom=tuple(
                item
                for item in value.get("custom", [])
                if isinstance(item, str)
            ),
        )

    def to_json_value(self) -> dict[str, list[str]]:
        return {
            "primary": list(self.primary),
            "secondary": list(self.secondary),
            "custom": list(self.custom),
        }

    @property
    def all_tags(self) -> list[str]:
        return _dedupe_preserving_order(
            [*self.primary, *self.secondary, *self.custom]
        )

    def ordered_tags(self) -> list[str]:
        return self.all_tags

    def weighted_tags(self) -> list[WeightedTag]:
        weighted: list[WeightedTag] = []
        for tag in self.primary:
            weighted.append(WeightedTag(name=tag, weight=1.0, label="primary"))
        for tag in self.secondary:
            weighted.append(
                WeightedTag(name=tag, weight=0.72, label="secondary")
            )
        for tag in self.custom:
            weighted.append(WeightedTag(name=tag, weight=0.55, label="custom"))
        return weighted


def catalog_for(kind: TagKind) -> list[str]:
    """Return the full canonical tag catalog for a kind."""
    return list(_CATALOG_BY_KIND[kind])


def featured_tags_for(kind: TagKind) -> list[str]:
    """Return a small featured subset for quick selection in the UI."""
    return list(_FEATURED_BY_KIND[kind])


def normalize_tag(value: str, kind: TagKind) -> str:
    """Normalize one tag to a canonical taxonomy value when possible."""
    normalized = _normalize_key(value)
    if not normalized:
        return ""

    direct = _SEARCH_KEYS[kind].get(normalized)
    if direct:
        return direct

    fuzzy = _fuzzy_catalog_match(normalized, kind)
    if fuzzy:
        return fuzzy

    return normalized


def build_tag_profile(
    kind: TagKind,
    *,
    primary_raw: str = "",
    secondary_raw: str = "",
    custom_raw: str = "",
    legacy_raw: str = "",
) -> TagProfile:
    """Build a normalized structured profile from form inputs."""
    has_structured = any(
        value.strip() for value in (primary_raw, secondary_raw, custom_raw)
    )
    if not has_structured:
        return TagProfile.from_flat_tags(
            _normalize_many(legacy_raw, kind),
            default_weight="primary",
        )

    buckets: dict[TagWeight, list[str]] = {
        "primary": _normalize_many(primary_raw, kind),
        "secondary": _normalize_many(secondary_raw, kind),
        "custom": _normalize_many(custom_raw, kind),
    }
    merged = _merge_weighted_buckets(buckets)
    return TagProfile(
        primary=tuple(merged["primary"]),
        secondary=tuple(merged["secondary"]),
        custom=tuple(merged["custom"]),
    )


def split_raw_tags(raw: str) -> list[str]:
    """Split a comma-separated tag input into cleaned string fragments."""
    return [part.strip() for part in raw.split(",") if part.strip()]


def _normalize_many(raw: str, kind: TagKind) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for part in split_raw_tags(raw):
        tag = normalize_tag(part, kind)
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags


def _merge_weighted_buckets(
    buckets: dict[TagWeight, list[str]],
) -> dict[TagWeight, list[str]]:
    chosen_weight: dict[str, TagWeight] = {}
    chosen_order: dict[str, int] = {}

    for weight in ("custom", "secondary", "primary"):
        items = buckets[weight]
        for index, tag in enumerate(items):
            existing = chosen_weight.get(tag)
            if (
                existing is None
                or _WEIGHT_PRIORITY[weight] > _WEIGHT_PRIORITY[existing]
            ):
                chosen_weight[tag] = weight
                chosen_order[tag] = index

    result: dict[TagWeight, list[str]] = {
        "primary": [],
        "secondary": [],
        "custom": [],
    }
    for weight in ("primary", "secondary", "custom"):
        tags = [
            tag for tag, bucket in chosen_weight.items() if bucket == weight
        ]
        tags.sort(key=lambda tag: chosen_order[tag])
        result[weight] = tags
    return result


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _fuzzy_catalog_match(normalized: str, kind: TagKind) -> str | None:
    if len(normalized) < 6:
        return None

    best_match: str | None = None
    best_distance: int | None = None
    normalized_word_count = len(normalized.split())

    for key, canonical in _SEARCH_KEYS[kind].items():
        if not key or key[0] != normalized[0]:
            continue
        if abs(len(key.split()) - normalized_word_count) > 1:
            continue

        distance = _levenshtein_distance(normalized, key)
        limit = _max_edit_distance(normalized, key)
        ratio = distance / max(len(normalized), len(key))
        if distance > limit or ratio > 0.14:
            continue
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_match = canonical

    return best_match


def _max_edit_distance(left: str, right: str) -> int:
    longest = max(len(left), len(right))
    if longest <= 8:
        return 1
    return 2


def _levenshtein_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for row_index, left_char in enumerate(left, start=1):
        current = [row_index]
        for column_index, right_char in enumerate(right, start=1):
            insert_cost = current[column_index - 1] + 1
            delete_cost = previous[column_index] + 1
            replace_cost = previous[column_index - 1] + (
                0 if left_char == right_char else 1
            )
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]
