"""Tests for the canonical tag taxonomy and normalization rules."""

from typing import Literal

from app.games.tags import (
    TagProfile,
    build_tag_profile,
    normalize_tag,
)

_NORMALIZATION_CASES: list[tuple[Literal["genre", "audience"], str, str]] = [
    ("genre", "rts", "real-time strategy"),
    ("genre", "real time strategy", "real-time strategy"),
    ("genre", "real time stategy", "real-time strategy"),
    ("genre", "turn based strategy", "turn-based strategy"),
    ("genre", "turn based stratgy", "turn-based strategy"),
    ("genre", "turn based tactics", "turn-based tactics"),
    ("genre", "turn based tattics", "turn-based tactics"),
    ("genre", "tower defence", "tower defense"),
    ("genre", "tower defnse", "tower defense"),
    ("genre", "deck builder", "deckbuilder"),
    ("genre", "deck bulider", "deckbuilder"),
    ("genre", "metroid-vania", "metroidvania"),
    ("genre", "metroidvaina", "metroidvania"),
    ("genre", "rogue lite", "roguelite"),
    ("genre", "rogue liite", "roguelite"),
    ("genre", "rogue like", "roguelike"),
    ("genre", "rogue lke", "roguelike"),
    ("genre", "shoot em up", "shmup"),
    ("genre", "walking sim", "walking simulator"),
    ("genre", "walking simulatr", "walking simulator"),
    ("genre", "visual noval", "visual novel"),
    ("genre", "citybuilding", "city builder"),
    ("genre", "city bulider", "city builder"),
    ("genre", "farming simulator", "farming sim"),
    ("genre", "bullet-heaven", "bullet heaven"),
    ("genre", "bullet heavn", "bullet heaven"),
    ("genre", "puzzle-platformer", "puzzle platformer"),
    ("genre", "puzzle platfromer", "puzzle platformer"),
    ("genre", "twin stick shooter", "twin-stick shooter"),
    ("genre", "twin stick shootr", "twin-stick shooter"),
    ("audience", "puzzle lovers", "puzzle fans"),
    ("audience", "puzzle players", "puzzle fans"),
    ("audience", "pc gamers", "pc players"),
    ("audience", "strategy players", "strategy fans"),
    ("audience", "tactics fans", "tactics players"),
    ("audience", "tower defence fans", "tower defense fans"),
    ("audience", "word game fans", "word game players"),
    ("audience", "wordle players", "wordle fans"),
    ("audience", "rogue lite fans", "roguelite fans"),
    ("audience", "rogue like fans", "roguelike fans"),
    ("audience", "roguelike playrs", "roguelike fans"),
    ("audience", "roguelite fns", "roguelite fans"),
    ("audience", "indie players", "indie game fans"),
    ("audience", "story players", "story-driven players"),
    ("audience", "steam users", "steam players"),
    ("audience", "speed runners", "speedrunners"),
    ("audience", "deck builder fans", "deckbuilder fans"),
    ("audience", "completionist", "completionists"),
    ("audience", "cozy players", "cozy gamers"),
    ("audience", "retro players", "retro gamers"),
    ("audience", "metroidvania players", "metroidvania fans"),
    ("audience", "soulslike players", "soulslike fans"),
    ("audience", "space fans", "space game fans"),
    ("audience", "xcom players", "xcom fans"),
    ("audience", "factorio players", "factorio fans"),
    ("audience", "rimworld players", "rimworld fans"),
    ("audience", "turn based strategy fans", "turn-based strategy fans"),
    ("audience", "hardcore strategy fans", "hardcore strategy players"),
]


def test_normalize_tag_maps_common_aliases_and_typos():
    assert len(_NORMALIZATION_CASES) >= 50
    for kind, raw, expected in _NORMALIZATION_CASES:
        assert normalize_tag(raw, kind) == expected


def test_normalize_tag_keeps_specific_franchise_phrases_custom():
    assert (
        normalize_tag("starcraft 2 strategy forums", "audience")
        == "starcraft 2 strategy forums"
    )
    assert (
        normalize_tag("factorio megabase tutorials", "audience")
        == "factorio megabase tutorials"
    )
    assert (
        normalize_tag("slay the spire challenge ladder", "genre")
        == "slay the spire challenge ladder"
    )


def test_build_tag_profile_normalizes_and_promotes_strongest_bucket():
    profile = build_tag_profile(
        "genre",
        primary_raw="rts, turn based tactics",
        secondary_raw="tower defence, deck builder, rts",
        custom_raw="metroidvaina, deck bulider",
    )

    assert profile == TagProfile(
        primary=("real-time strategy", "turn-based tactics"),
        secondary=("tower defense", "deckbuilder"),
        custom=("metroidvania",),
    )


def test_build_tag_profile_uses_legacy_tags_as_primary():
    profile = build_tag_profile(
        "audience",
        legacy_raw="puzzle lovers, speed runners, wordle players",
    )

    assert profile.primary == (
        "puzzle fans",
        "speedrunners",
        "wordle fans",
    )
    assert profile.secondary == ()
    assert profile.custom == ()


def test_build_tag_profile_keeps_unknown_custom_tags():
    profile = build_tag_profile(
        "genre",
        custom_raw="xcom-like, browser tactics, weird one-off subgenre",
    )

    assert profile.custom == (
        "xcom like",
        "browser tactics",
        "weird one off subgenre",
    )
