"""Canonical game tag taxonomy, normalization, and structured tag profiles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

TagKind = Literal["genre", "audience", "mechanics", "tone"]
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
    "action rpg",
    "adventure",
    "arcade",
    "asymmetric multiplayer",
    "auto battler",
    "base building",
    "battle royale",
    "beat em up",
    "bullet heaven",
    "card battler",
    "card game",
    "city builder",
    "colony sim",
    "cooperative",
    "cozy",
    "crafting",
    "crpg",
    "cyberpunk",
    "daily challenge",
    "dating sim",
    "deckbuilder",
    "detective",
    "dungeon crawler",
    "escape room",
    "extraction shooter",
    "factory automation",
    "fantasy",
    "farming sim",
    "fighting",
    "first-person shooter",
    "fishing",
    "flight sim",
    "grand strategy",
    "hack and slash",
    "hero shooter",
    "hidden object",
    "horror",
    "idle",
    "immersive sim",
    "incremental",
    "interactive fiction",
    "isometric",
    "jrpg",
    "life sim",
    "looter shooter",
    "management",
    "match-3",
    "metroidvania",
    "moba",
    "monster taming",
    "musou",
    "mystery",
    "narrative adventure",
    "nonogram",
    "open world",
    "party game",
    "physics puzzle",
    "platformer",
    "point and click",
    "precision platformer",
    "psychological horror",
    "puzzle",
    "puzzle platformer",
    "racing",
    "real-time strategy",
    "rhythm",
    "roguelike",
    "roguelite",
    "rpg",
    "run and gun",
    "sandbox",
    "sci-fi",
    "shmup",
    "simulation",
    "social deduction",
    "soulslike",
    "space",
    "space sim",
    "sports",
    "stealth",
    "strategy",
    "survival",
    "survival horror",
    "tabletop sim",
    "tactical rpg",
    "tactics",
    "text adventure",
    "third-person shooter",
    "top-down shooter",
    "tower defense",
    "trading card game",
    "trivia",
    "turn-based combat",
    "turn-based strategy",
    "turn-based tactics",
    "twin-stick shooter",
    "vehicle combat",
    "visual novel",
    "walking simulator",
    "wargame",
    "wholesome",
    "word game",
]

AUDIENCE_TAG_CATALOG = [
    "achievement hunters",
    "action players",
    "action rpg fans",
    "anime fans",
    "apex legends players",
    "automation fans",
    "baldurs gate fans",
    "battle royale players",
    "beat em up fans",
    "binding of isaac fans",
    "builders",
    "card game fans",
    "card game players",
    "casual gamers",
    "celeste fans",
    "challenge seekers",
    "cities skylines fans",
    "civilization fans",
    "co-op groups",
    "competitive players",
    "completionists",
    "cozy gamers",
    "crpg fans",
    "cyberpunk fans",
    "dark souls fans",
    "dead cells fans",
    "deckbuilder fans",
    "demo hunters",
    "diablo fans",
    "disco elysium fans",
    "dont starve fans",
    "elden ring fans",
    "factorio fans",
    "factory game fans",
    "farm sim players",
    "fighting game fans",
    "final fantasy fans",
    "fps players",
    "fromsoft fans",
    "hades fans",
    "hardcore strategy players",
    "hollow knight fans",
    "horror fans",
    "indie game fans",
    "inscryption fans",
    "jrpg fans",
    "league of legends players",
    "metroidvania fans",
    "min-maxers",
    "minecraft fans",
    "moba players",
    "mobile players",
    "monster train fans",
    "mystery fans",
    "narrative game fans",
    "octopath fans",
    "ori fans",
    "path of exile fans",
    "pc players",
    "persona fans",
    "platformer fans",
    "puzzle fans",
    "puzzle solvers",
    "retro gamers",
    "rimworld fans",
    "roguelike fans",
    "roguelite fans",
    "rpg fans",
    "sandbox fans",
    "sci-fi players",
    "sim fans",
    "singleplayer players",
    "slay the spire fans",
    "social deduction fans",
    "soulslike fans",
    "space game fans",
    "spectacle seekers",
    "speedrunners",
    "stardew valley fans",
    "starter strategy players",
    "steam deck players",
    "steam players",
    "story-driven players",
    "strategy fans",
    "stream viewers",
    "survival fans",
    "tabletop fans",
    "tactical rpg fans",
    "tactics players",
    "terraria fans",
    "theorycrafters",
    "total war fans",
    "tower defense fans",
    "trivia fans",
    "turn-based strategy fans",
    "valheim fans",
    "vampire survivors fans",
    "visual novel fans",
    "wholesome gamers",
    "wikipedia fans",
    "word game players",
    "wordle fans",
    "xcom fans",
    "zachlike fans",
]

MECHANICS_TAG_CATALOG = [
    "branching narrative",
    "card drafting",
    "co-op",
    "crafting",
    "deck construction",
    "emergent gameplay",
    "fog of war",
    "grid-based",
    "loot systems",
    "meta-progression",
    "one more run",
    "permadeath",
    "physics-based",
    "procedural generation",
    "quick sessions",
    "resource management",
    "run-based",
    "skill trees",
    "speedrun-viable",
    "time pressure",
    "unit management",
    "upgrade systems",
]

TONE_TAG_CATALOG = [
    "anime aesthetic",
    "atmospheric",
    "brutal difficulty",
    "cartoon",
    "cinematic",
    "dark",
    "dark fantasy",
    "high fantasy",
    "lo-fi",
    "medieval",
    "minimalist",
    "mythology",
    "noir",
    "pixel art",
    "post-apocalyptic",
    "psychological",
    "retro aesthetic",
    "steampunk",
]

FEATURED_GENRE_TAGS = [
    "action rpg",
    "arcade",
    "battle royale",
    "beat em up",
    "city builder",
    "daily challenge",
    "deckbuilder",
    "factory automation",
    "fighting",
    "first-person shooter",
    "jrpg",
    "metroidvania",
    "moba",
    "narrative adventure",
    "platformer",
    "puzzle",
    "racing",
    "real-time strategy",
    "roguelike",
    "roguelite",
    "rpg",
    "soulslike",
    "strategy",
    "survival",
    "tower defense",
    "turn-based strategy",
    "turn-based tactics",
    "visual novel",
    "word game",
]

FEATURED_AUDIENCE_TAGS = [
    "achievement hunters",
    "casual gamers",
    "challenge seekers",
    "co-op groups",
    "competitive players",
    "completionists",
    "cozy gamers",
    "deckbuilder fans",
    "fps players",
    "hardcore strategy players",
    "indie game fans",
    "jrpg fans",
    "moba players",
    "narrative game fans",
    "pc players",
    "puzzle fans",
    "roguelike fans",
    "roguelite fans",
    "speedrunners",
    "steam players",
    "story-driven players",
    "strategy fans",
    "tactics players",
    "wikipedia fans",
    "word game players",
    "xcom fans",
]

FEATURED_MECHANICS_TAGS = [
    "co-op",
    "meta-progression",
    "one more run",
    "permadeath",
    "procedural generation",
    "quick sessions",
    "resource management",
    "speedrun-viable",
]

FEATURED_TONE_TAGS = [
    "anime aesthetic",
    "atmospheric",
    "dark",
    "dark fantasy",
    "pixel art",
    "post-apocalyptic",
    "psychological",
    "retro aesthetic",
]

_GENRE_ALIASES = {
    "action adventure": "adventure",
    "action-roguelike": "action roguelike",
    "action-rpg": "action rpg",
    "arpg": "action rpg",
    "asymmetric": "asymmetric multiplayer",
    "auto-battler": "auto battler",
    "basebuilder": "base building",
    "battle-royale": "battle royale",
    "beat-em-up": "beat em up",
    "brawler": "beat em up",
    "brawler game": "beat em up",
    "br": "battle royale",
    "bullet-heaven": "bullet heaven",
    "bullet heaven survivor": "bullet heaven",
    "bullet hell": "shmup",
    "card battle": "card battler",
    "card-game": "card game",
    "city bulider": "city builder",
    "citybuilding": "city builder",
    "city-builder": "city builder",
    "clicker": "idle",
    "clicker game": "idle",
    "co-op": "cooperative",
    "coop": "cooperative",
    "cozy game": "cozy",
    "colony management": "colony sim",
    "classic rpg": "crpg",
    "computer rpg": "crpg",
    "daily puzzle": "daily challenge",
    "dating simulator": "dating sim",
    "deck bulider": "deckbuilder",
    "deck builder": "deckbuilder",
    "deck-building": "deckbuilder",
    "escape-room": "escape room",
    "extraction-shooter": "extraction shooter",
    "factory builder": "factory automation",
    "farming simulator": "farming sim",
    "fight": "fighting",
    "fighting game": "fighting",
    "first person shooter": "first-person shooter",
    "fps": "first-person shooter",
    "grand-strategy": "grand strategy",
    "hack-and-slash": "hack and slash",
    "hero-shooter": "hero shooter",
    "hidden-object": "hidden object",
    "idle game": "idle",
    "incremental game": "incremental",
    "interactive-fiction": "interactive fiction",
    "japanese rpg": "jrpg",
    "life simulation": "life sim",
    "looter-shooter": "looter shooter",
    "match 3": "match-3",
    "match3": "match-3",
    "metroid-vania": "metroidvania",
    "metroidvaina": "metroidvania",
    "monster tamer": "monster taming",
    "multiplayer online battle arena": "moba",
    "musuo": "musou",
    "mystery game": "mystery",
    "narrative": "narrative adventure",
    "nono": "nonogram",
    "picross": "nonogram",
    "open-world": "open world",
    "point-and-click": "point and click",
    "p&c": "point and click",
    "precision platforming": "precision platformer",
    "psychological": "psychological horror",
    "puzzle-platformer": "puzzle platformer",
    "rts": "real-time strategy",
    "real time strategy": "real-time strategy",
    "roguelite game": "roguelite",
    "rogue like": "roguelike",
    "rogue-lite": "roguelite",
    "rogue lite": "roguelite",
    "run-and-gun": "run and gun",
    "run & gun": "run and gun",
    "sci fi": "sci-fi",
    "shoot em up": "shmup",
    "shoot-em-up": "shmup",
    "social-deduction": "social deduction",
    "soulsborne": "soulslike",
    "souls-like": "soulslike",
    "space simulation": "space sim",
    "srpg": "tactical rpg",
    "strategy rpg": "tactical rpg",
    "tactical-rpg": "tactical rpg",
    "tabletop simulator": "tabletop sim",
    "text-adventure": "text adventure",
    "third person shooter": "third-person shooter",
    "tps": "third-person shooter",
    "top down shooter": "top-down shooter",
    "tower defence": "tower defense",
    "trading-card-game": "trading card game",
    "tcg": "trading card game",
    "turn based combat": "turn-based combat",
    "turn based strategy": "turn-based strategy",
    "turn based tactics": "turn-based tactics",
    "twin stick shooter": "twin-stick shooter",
    "visual-novel": "visual novel",
    "walking sim": "walking simulator",
    "wargames": "wargame",
    "wholesome game": "wholesome",
    "word puzzle": "word game",
}

_AUDIENCE_ALIASES = {
    "achievement hunter": "achievement hunters",
    "action rpg players": "action rpg fans",
    "anime players": "anime fans",
    "apex legends fans": "apex legends players",
    "automation players": "automation fans",
    "baldur's gate fans": "baldurs gate fans",
    "baldurs gate players": "baldurs gate fans",
    "battle royale fans": "battle royale players",
    "beat em up players": "beat em up fans",
    "binding of isaac players": "binding of isaac fans",
    "card players": "card game players",
    "card fans": "card game fans",
    "casual players": "casual gamers",
    "cities skylines players": "cities skylines fans",
    "civ fans": "civilization fans",
    "civilization players": "civilization fans",
    "competitive fans": "competitive players",
    "completionist": "completionists",
    "cozy players": "cozy gamers",
    "crpg players": "crpg fans",
    "cyberpunk players": "cyberpunk fans",
    "dark souls players": "dark souls fans",
    "dead cells players": "dead cells fans",
    "deck builder fans": "deckbuilder fans",
    "diablo players": "diablo fans",
    "disco elysium players": "disco elysium fans",
    "dont starve players": "dont starve fans",
    "don't starve fans": "dont starve fans",
    "elden ring fans": "elden ring fans",
    "elden ring players": "elden ring fans",
    "factorio players": "factorio fans",
    "factory fans": "factory game fans",
    "fighting fans": "fighting game fans",
    "final fantasy players": "final fantasy fans",
    "fps fans": "fps players",
    "from software fans": "fromsoft fans",
    "fromsoft players": "fromsoft fans",
    "hades players": "hades fans",
    "hardcore strategy fans": "hardcore strategy players",
    "hollow knight players": "hollow knight fans",
    "indie players": "indie game fans",
    "inscryption players": "inscryption fans",
    "jrpg players": "jrpg fans",
    "league of legends fans": "league of legends players",
    "lol players": "league of legends players",
    "metroidvania players": "metroidvania fans",
    "minecraft players": "minecraft fans",
    "moba fans": "moba players",
    "monster train players": "monster train fans",
    "mystery players": "mystery fans",
    "octopath traveler fans": "octopath fans",
    "octopath players": "octopath fans",
    "ori players": "ori fans",
    "path of exile players": "path of exile fans",
    "pc gamers": "pc players",
    "persona players": "persona fans",
    "platformer players": "platformer fans",
    "poe fans": "path of exile fans",
    "puzzle lovers": "puzzle fans",
    "puzzle players": "puzzle fans",
    "retro players": "retro gamers",
    "rimworld players": "rimworld fans",
    "rogue like fans": "roguelike fans",
    "rogue lite fans": "roguelite fans",
    "roguelike players": "roguelike fans",
    "roguelite players": "roguelite fans",
    "rpg players": "rpg fans",
    "sci fi players": "sci-fi players",
    "simulation fans": "sim fans",
    "single player players": "singleplayer players",
    "social deduction players": "social deduction fans",
    "soulslike players": "soulslike fans",
    "space fans": "space game fans",
    "speed runners": "speedrunners",
    "stardew fans": "stardew valley fans",
    "stardew players": "stardew valley fans",
    "stardew valley players": "stardew valley fans",
    "steam users": "steam players",
    "story players": "story-driven players",
    "strategy players": "strategy fans",
    "survival players": "survival fans",
    "tabletop players": "tabletop fans",
    "tactical rpg players": "tactical rpg fans",
    "tactics fans": "tactics players",
    "terraria players": "terraria fans",
    "total war players": "total war fans",
    "tower defence fans": "tower defense fans",
    "turn based strategy fans": "turn-based strategy fans",
    "valheim players": "valheim fans",
    "visual novel players": "visual novel fans",
    "wholesome fans": "wholesome gamers",
    "word game fans": "word game players",
    "wordle players": "wordle fans",
    "xcom players": "xcom fans",
}

_MECHANICS_ALIASES: dict[str, str] = {
    "branching choices": "branching narrative",
    "card draft": "card drafting",
    "coop": "co-op",
    "cooperative": "co-op",
    "crafting system": "crafting",
    "deck building": "deck construction",
    "emergent": "emergent gameplay",
    "loot": "loot systems",
    "meta progression": "meta-progression",
    "one more turn": "one more run",
    "perma death": "permadeath",
    "perma-death": "permadeath",
    "physics": "physics-based",
    "physics based": "physics-based",
    "proc gen": "procedural generation",
    "procgen": "procedural generation",
    "roguelite progression": "meta-progression",
    "run based": "run-based",
    "runs": "run-based",
    "skill tree": "skill trees",
    "speedrun": "speedrun-viable",
    "speedrunnable": "speedrun-viable",
    "unit control": "unit management",
    "upgrades": "upgrade systems",
}

_TONE_ALIASES: dict[str, str] = {
    "anime": "anime aesthetic",
    "anime style": "anime aesthetic",
    "atmospheric game": "atmospheric",
    "brutal": "brutal difficulty",
    "comic": "cartoon",
    "cartoon style": "cartoon",
    "cinematic story": "cinematic",
    "dark game": "dark",
    "dark tone": "dark",
    "dark fantasy game": "dark fantasy",
    "high fantasy game": "high fantasy",
    "lofi": "lo-fi",
    "lo fi": "lo-fi",
    "medival": "medieval",
    "minimal": "minimalist",
    "noir game": "noir",
    "pixel": "pixel art",
    "pixels": "pixel art",
    "pixelart": "pixel art",
    "pixel-art": "pixel art",
    "post apocalyptic": "post-apocalyptic",
    "post-apocalypse": "post-apocalyptic",
    "psychological game": "psychological",
    "retro": "retro aesthetic",
    "retro game": "retro aesthetic",
    "retro style": "retro aesthetic",
    "steam punk": "steampunk",
}

_CATALOG_BY_KIND: dict[TagKind, list[str]] = {
    "genre": GENRE_TAG_CATALOG,
    "audience": AUDIENCE_TAG_CATALOG,
    "mechanics": MECHANICS_TAG_CATALOG,
    "tone": TONE_TAG_CATALOG,
}
_FEATURED_BY_KIND: dict[TagKind, list[str]] = {
    "genre": FEATURED_GENRE_TAGS,
    "audience": FEATURED_AUDIENCE_TAGS,
    "mechanics": FEATURED_MECHANICS_TAGS,
    "tone": FEATURED_TONE_TAGS,
}
_ALIASES_BY_KIND: dict[TagKind, dict[str, str]] = {
    "genre": _GENRE_ALIASES,
    "audience": _AUDIENCE_ALIASES,
    "mechanics": _MECHANICS_ALIASES,
    "tone": _TONE_ALIASES,
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
