"""Tests for the canonical tag taxonomy and normalization rules."""

from __future__ import annotations

from typing import cast

import pytest

from app.games.models import Game
from app.games.tags import (
    ALIASES_BY_KIND,
    CATALOG_BY_KIND,
    FEATURED_BY_KIND,
    GENRE_TAG_CATALOG,
    KINDRED_TAG_CATALOG,
    TagKind,
    TagProfile,
    TagWeight,
    WeightedTag,
    build_tag_profile,
    levenshtein_distance,
    normalize_key,
    normalize_tag,
    split_raw_tags,
)
from app.ingestion.query_builder import (
    SourceTags,
    TaggedQuery,
    build_tagged_queries,
)

# ===========================================================================
# Catalog integrity
# ===========================================================================


@pytest.mark.parametrize("kind", ["genre", "mechanics", "vibe", "kindred"])
def test_catalog_has_no_duplicates(kind: str) -> None:
    catalog = CATALOG_BY_KIND[kind]  # type: ignore[literal-required]
    assert len(catalog) == len(set(catalog)), f"{kind} catalog contains duplicates"


@pytest.mark.parametrize("kind", ["genre", "mechanics", "vibe", "kindred"])
def test_catalog_is_sorted(kind: str) -> None:
    catalog = CATALOG_BY_KIND[kind]  # type: ignore[literal-required]
    assert catalog == sorted(catalog), (
        f"{kind} catalog is not sorted alphabetically"
    )


@pytest.mark.parametrize("kind", ["genre", "mechanics", "vibe", "kindred"])
def test_catalog_entries_are_lowercase_and_stripped(kind: str) -> None:
    catalog = CATALOG_BY_KIND[kind]  # type: ignore[literal-required]
    for tag in catalog:
        assert tag == tag.strip(), f"{kind!r} tag {tag!r} has leading/trailing whitespace"
        assert tag == tag.lower(), f"{kind!r} tag {tag!r} is not lowercase"


@pytest.mark.parametrize("kind", ["genre", "mechanics", "vibe", "kindred"])
def test_featured_tags_are_subset_of_catalog(kind: str) -> None:
    catalog = set(CATALOG_BY_KIND[kind])  # type: ignore[literal-required]
    featured = FEATURED_BY_KIND[kind]  # type: ignore[literal-required]
    extras = [t for t in featured if t not in catalog]
    assert not extras, f"{kind} featured tags not in catalog: {extras}"


@pytest.mark.parametrize("kind", ["genre", "mechanics", "vibe", "kindred"])
def test_alias_values_resolve_to_catalog(kind: str) -> None:
    catalog = set(CATALOG_BY_KIND[kind])  # type: ignore[literal-required]
    aliases = ALIASES_BY_KIND[kind]  # type: ignore[literal-required]
    bad = {alias: target for alias, target in aliases.items() if target not in catalog}
    assert not bad, f"{kind} aliases point to non-catalog targets: {bad}"


@pytest.mark.parametrize("kind", ["genre", "mechanics", "vibe", "kindred"])
def test_aliases_resolve_to_their_target(kind: str) -> None:
    """Every alias must produce its declared canonical value when normalized."""
    aliases = ALIASES_BY_KIND[kind]  # type: ignore[literal-required]
    bad = {
        alias: (target, normalize_tag(alias, cast(TagKind, kind)))
        for alias, target in aliases.items()
        if normalize_tag(alias, cast(TagKind, kind)) != target
    }
    assert not bad, (
        f"{kind} aliases that don't resolve correctly: "
        + ", ".join(f"{k!r} → got {v[1]!r}, want {v[0]!r}" for k, v in bad.items())
    )


# ===========================================================================
# normalize_key
# ===========================================================================


def test_normalize_key_lowercases() -> None:
    assert normalize_key("RogueLite") == "roguelite"


def test_normalize_key_strips_whitespace() -> None:
    assert normalize_key("  roguelite  ") == "roguelite"


def test_normalize_key_collapses_punctuation() -> None:
    assert normalize_key("twin-stick shooter!") == "twin stick shooter"


def test_normalize_key_expands_ampersand() -> None:
    assert normalize_key("run & gun") == "run and gun"


def test_normalize_key_empty_string() -> None:
    assert normalize_key("") == ""


def test_normalize_key_whitespace_only() -> None:
    assert normalize_key("   ") == ""


# ===========================================================================
# levenshtein_distance
# ===========================================================================


def test_levenshtein_identical_strings() -> None:
    assert levenshtein_distance("roguelite", "roguelite") == 0


def test_levenshtein_empty_left() -> None:
    assert levenshtein_distance("", "abc") == 3


def test_levenshtein_empty_right() -> None:
    assert levenshtein_distance("abc", "") == 3


def test_levenshtein_one_substitution() -> None:
    assert levenshtein_distance("kitten", "sitten") == 1


def test_levenshtein_one_deletion() -> None:
    assert levenshtein_distance("roguelite", "roguelite"[:-1]) == 1


def test_levenshtein_one_insertion() -> None:
    assert levenshtein_distance("roguelite", "roguelitee") == 1


def test_levenshtein_typical_typo() -> None:
    # "roguelite" vs "rogue liite" → normalized both end up close
    assert levenshtein_distance("roguelite", "rogueliite") == 1


# ===========================================================================
# normalize_tag — genre
# ===========================================================================


_GENRE_CASES: list[tuple[str, str]] = [
    ("rts", "real-time strategy"),
    ("real time strategy", "real-time strategy"),
    ("real time stategy", "real-time strategy"),
    ("turn based strategy", "turn-based strategy"),
    ("turn based stratgy", "turn-based strategy"),
    ("turn based tactics", "turn-based tactics"),
    ("turn based tattics", "turn-based tactics"),
    ("tower defence", "tower defense"),
    ("tower defnse", "tower defense"),
    ("deck builder", "deckbuilder"),
    ("deck bulider", "deckbuilder"),
    ("metroid-vania", "metroidvania"),
    ("metroidvaina", "metroidvania"),
    ("rogue lite", "roguelite"),
    ("rogue liite", "roguelite"),
    ("rogue like", "roguelike"),
    ("shoot em up", "shmup"),
    ("walking sim", "walking simulator"),
    ("walking simulatr", "walking simulator"),
    ("visual noval", "visual novel"),
    ("citybuilding", "city builder"),
    ("city bulider", "city builder"),
    ("farming simulator", "farming sim"),
    ("bullet-heaven", "bullet heaven"),
    ("bullet heavn", "bullet heaven"),
    ("puzzle-platformer", "puzzle platformer"),
    ("puzzle platfromer", "puzzle platformer"),
    ("twin stick shooter", "twin-stick shooter"),
    ("twin stick shootr", "twin-stick shooter"),
    # Abbreviation aliases
    ("fps", "first-person shooter"),
    ("tps", "third-person shooter"),
    ("srpg", "tactical rpg"),
    ("tcg", "trading card game"),
]


@pytest.mark.parametrize("raw,expected", _GENRE_CASES)
def test_normalize_genre_tag(raw: str, expected: str) -> None:
    assert normalize_tag(raw, "genre") == expected, (
        f"normalize_tag({raw!r}, 'genre') → expected {expected!r}"
    )


def test_normalize_tag_empty_string() -> None:
    assert normalize_tag("", "genre") == ""


def test_normalize_tag_keeps_unknown_tag_as_normalized_key() -> None:
    # Unknown tags survive as lowercased/normalized strings.
    assert normalize_tag("slay the spire challenge ladder", "genre") == (
        "slay the spire challenge ladder"
    )


def test_normalize_tag_returns_catalog_form_not_alias_key() -> None:
    # Alias resolution must produce the catalog value, not the alias key.
    result = normalize_tag("FPS", "genre")
    assert result == "first-person shooter"
    assert result in GENRE_TAG_CATALOG


# ===========================================================================
# normalize_tag — mechanics
# ===========================================================================


_MECHANICS_CASES: list[tuple[str, str]] = [
    ("proc gen", "procedural generation"),
    ("procgen", "procedural generation"),
    ("perma death", "permadeath"),
    ("perma-death", "permadeath"),
    ("speedrun", "speedrun-viable"),
    ("speedrunnable", "speedrun-viable"),
    ("physics based", "physics-based"),
    ("physics", "physics-based"),
    ("meta progression", "meta-progression"),
    ("one more turn", "one more run"),
    ("deck building", "deck construction"),
    ("card draft", "card drafting"),
    ("coop", "co-op"),
    ("cooperative", "co-op"),
    ("crafting system", "crafting"),
    ("emergent", "emergent gameplay"),
    ("loot", "loot systems"),
    ("roguelite progression", "meta-progression"),
    ("run based", "run-based"),
    ("runs", "run-based"),
    ("skill tree", "skill trees"),
    ("unit control", "unit management"),
    ("upgrades", "upgrade systems"),
]


@pytest.mark.parametrize("raw,expected", _MECHANICS_CASES)
def test_normalize_mechanics_tag(raw: str, expected: str) -> None:
    assert normalize_tag(raw, "mechanics") == expected, (
        f"normalize_tag({raw!r}, 'mechanics') → expected {expected!r}"
    )


# ===========================================================================
# normalize_tag — vibe
# ===========================================================================


_VIBE_CASES: list[tuple[str, str]] = [
    ("pixel", "pixel art"),
    ("pixels", "pixel art"),
    ("pixelart", "pixel art"),
    ("pixel-art", "pixel art"),
    ("retro", "retro aesthetic"),
    ("retro game", "retro aesthetic"),
    ("retro style", "retro aesthetic"),
    ("anime", "anime aesthetic"),
    ("anime style", "anime aesthetic"),
    ("brutal", "brutal difficulty"),
    ("comic", "cartoon"),
    ("cartoon style", "cartoon"),
    ("lofi", "lo-fi"),
    ("lo fi", "lo-fi"),
    ("medival", "medieval"),
    ("minimal", "minimalist"),
    ("noir game", "noir"),
    ("post apocalyptic", "post-apocalyptic"),
    ("post-apocalypse", "post-apocalyptic"),
    ("psychological game", "psychological"),
    ("steam punk", "steampunk"),
    ("dark game", "dark"),
    ("dark tone", "dark"),
    ("dark fantasy game", "dark fantasy"),
    ("high fantasy game", "high fantasy"),
    ("cinematic story", "cinematic"),
    ("atmospheric game", "atmospheric"),
]


@pytest.mark.parametrize("raw,expected", _VIBE_CASES)
def test_normalize_vibe_tag(raw: str, expected: str) -> None:
    assert normalize_tag(raw, "vibe") == expected, (
        f"normalize_tag({raw!r}, 'vibe') → expected {expected!r}"
    )


# ===========================================================================
# normalize_tag — kindred
# ===========================================================================


_KINDRED_CASES: list[tuple[str, str]] = [
    ("hades 2", "hades"),
    ("hades ii", "hades"),
    ("bg3", "baldurs gate"),
    ("baldurs gate 3", "baldurs gate"),
    ("ck3", "crusader kings"),
    ("ck2", "crusader kings"),
    ("diablo 4", "diablo"),
    ("diablo iv", "diablo"),
    ("overwatch 2", "overwatch"),
    ("xcom 2", "xcom"),
    ("spelunky 2", "spelunky"),
    ("starcraft 2", "starcraft"),
    ("starcraft ii", "starcraft"),
    ("risk of rain 2", "risk of rain"),
    ("ror2", "risk of rain"),
    ("gta 5", "grand theft auto"),
    ("gta v", "grand theft auto"),
    ("gta", "grand theft auto"),
    ("genshin", "genshin impact"),
    ("witcher 3", "the witcher 3"),
    ("witcher", "the witcher 3"),
    ("the witcher", "the witcher 3"),
    ("monster hunter world", "monster hunter"),
    ("ff14", "final fantasy xiv"),
    ("ffxiv", "final fantasy xiv"),
    ("csgo", "counter-strike"),
    ("cs go", "counter-strike"),
    ("cs2", "counter-strike"),
    ("lol", "league of legends"),
    ("poe", "path of exile"),
    ("don't starve together", "dont starve"),
    ("dota 2", "dota"),
    ("yakuza like a dragon", "yakuza"),
    ("like a dragon", "yakuza"),
    ("persona 5", "persona"),
    ("botw", "zelda breath of the wild"),
    ("breath of the wild", "zelda breath of the wild"),
]


@pytest.mark.parametrize("raw,expected", _KINDRED_CASES)
def test_normalize_kindred_tag(raw: str, expected: str) -> None:
    assert normalize_tag(raw, "kindred") == expected, (
        f"normalize_tag({raw!r}, 'kindred') → expected {expected!r}"
    )


def test_normalize_kindred_canonical_entries_are_stable() -> None:
    """Every catalog entry must normalize back to itself."""
    for tag in KINDRED_TAG_CATALOG:
        result = normalize_tag(tag, "kindred")
        assert result == tag, (
            f"Catalog entry {tag!r} normalized to {result!r} — not stable"
        )


# ===========================================================================
# split_raw_tags
# ===========================================================================


def test_split_raw_tags_basic() -> None:
    assert split_raw_tags("roguelite, puzzle, strategy") == ["roguelite", "puzzle", "strategy"]


def test_split_raw_tags_strips_whitespace() -> None:
    assert split_raw_tags("  roguelite ,  puzzle  ") == ["roguelite", "puzzle"]


def test_split_raw_tags_ignores_empty_fragments() -> None:
    assert split_raw_tags("roguelite,,puzzle") == ["roguelite", "puzzle"]


def test_split_raw_tags_empty_string() -> None:
    assert split_raw_tags("") == []


def test_split_raw_tags_only_commas() -> None:
    assert split_raw_tags(",,,") == []


# ===========================================================================
# TagProfile
# ===========================================================================


def test_tag_profile_empty_is_falsy() -> None:
    assert not TagProfile.empty()
    assert not TagProfile()


def test_tag_profile_with_tags_is_truthy() -> None:
    assert TagProfile(primary=("roguelite",))


def test_tag_profile_len() -> None:
    profile = TagProfile(primary=("roguelite",), secondary=("puzzle", "strategy"))
    assert len(profile) == 3


def test_tag_profile_all_tags_respects_priority_order() -> None:
    profile = TagProfile(primary=("roguelite",), secondary=("puzzle", "strategy"))
    assert profile.all_tags == ["roguelite", "puzzle", "strategy"]


def test_tag_profile_all_tags_deduplicates() -> None:
    profile = TagProfile(primary=("roguelite",), secondary=("roguelite", "puzzle"))
    assert profile.all_tags == ["roguelite", "puzzle"]


def test_tag_profile_weighted_tags_correct_weights() -> None:
    profile = TagProfile(primary=("roguelite",), secondary=("puzzle",))
    weighted = profile.weighted_tags()
    assert len(weighted) == 2
    assert weighted[0] == WeightedTag(name="roguelite", weight=1.0, label=TagWeight.PRIMARY)
    assert weighted[1] == WeightedTag(name="puzzle", weight=0.72, label=TagWeight.SECONDARY)


def test_tag_weight_str_values() -> None:
    # StrEnum — enum members compare equal to their string values.
    assert TagWeight.PRIMARY == "primary"
    assert TagWeight.SECONDARY == "secondary"
    assert str(TagWeight.PRIMARY) == "primary"


def test_tag_profile_to_json_value_roundtrip() -> None:
    profile = TagProfile(primary=("roguelite", "strategy"), secondary=("puzzle",))
    assert TagProfile.from_json_value(profile.to_json_value()) == profile


def test_tag_profile_from_json_value_migrates_legacy_custom() -> None:
    # Old "custom" bucket should be promoted to primary.
    raw = {"primary": ["roguelite"], "secondary": [], "custom": ["xcom-like"]}
    profile = TagProfile.from_json_value(raw)
    assert "xcom-like" in profile.primary
    assert profile.secondary == ()


def test_tag_profile_from_json_value_ignores_non_strings() -> None:
    raw = {"primary": ["roguelite", 42, None, "puzzle"], "secondary": []}
    profile = TagProfile.from_json_value(raw)
    assert profile.primary == ("roguelite", "puzzle")


def test_tag_profile_from_json_value_non_dict_returns_empty() -> None:
    assert TagProfile.from_json_value(None) == TagProfile.empty()
    assert TagProfile.from_json_value("roguelite") == TagProfile.empty()
    assert TagProfile.from_json_value(42) == TagProfile.empty()


def test_tag_profile_from_flat_tags_primary() -> None:
    profile = TagProfile.from_flat_tags(["roguelite", "puzzle"], default_weight=TagWeight.PRIMARY)
    assert profile.primary == ("roguelite", "puzzle")
    assert profile.secondary == ()


def test_tag_profile_from_flat_tags_secondary() -> None:
    profile = TagProfile.from_flat_tags(["roguelite"], default_weight=TagWeight.SECONDARY)
    assert profile.primary == ()
    assert profile.secondary == ("roguelite",)


def test_tag_profile_from_flat_tags_deduplicates() -> None:
    profile = TagProfile.from_flat_tags(["roguelite", "puzzle", "roguelite"])
    assert profile.primary == ("roguelite", "puzzle")


def test_tag_profile_ordered_tags_equals_all_tags() -> None:
    profile = TagProfile(primary=("roguelite",), secondary=("puzzle",))
    assert profile.ordered_tags() == profile.all_tags


# ===========================================================================
# build_tag_profile
# ===========================================================================


def test_build_tag_profile_normalizes_and_promotes_strongest_bucket() -> None:
    profile = build_tag_profile(
        "genre",
        primary_raw="rts, turn based tactics",
        secondary_raw="tower defence, deck builder, rts",
    )
    assert profile == TagProfile(
        primary=("real-time strategy", "turn-based tactics"),
        secondary=("tower defense", "deckbuilder"),
    )


def test_build_tag_profile_uses_legacy_as_primary() -> None:
    profile = build_tag_profile("genre", legacy_raw="puzzle, strategy, roguelite")
    assert profile.primary == ("puzzle", "strategy", "roguelite")
    assert profile.secondary == ()


def test_build_tag_profile_structured_overrides_legacy() -> None:
    # If any structured bucket has data, legacy_raw is ignored.
    profile = build_tag_profile(
        "genre",
        primary_raw="roguelite",
        legacy_raw="puzzle, strategy",
    )
    assert profile.primary == ("roguelite",)


def test_build_tag_profile_keeps_unknown_tags_in_primary() -> None:
    # Unknown tags (not in catalog) are preserved as-is in primary.
    profile = build_tag_profile(
        "genre",
        primary_raw="xcom-like, browser tactics, weird one-off subgenre",
    )
    assert profile.primary == ("xcom like", "browser tactics", "weird one off subgenre")


def test_build_tag_profile_empty_inputs_return_empty() -> None:
    assert build_tag_profile("genre") == TagProfile.empty()


def test_build_tag_profile_dedupes_across_buckets() -> None:
    # Same tag in primary and secondary — kept only in primary.
    profile = build_tag_profile(
        "genre",
        primary_raw="roguelite",
        secondary_raw="roguelite, puzzle",
    )
    assert "roguelite" in profile.primary
    assert "roguelite" not in profile.secondary
    assert "puzzle" in profile.secondary


def test_build_tag_profile_mechanics() -> None:
    profile = build_tag_profile(
        "mechanics",
        primary_raw="proc gen, perma death, speedrun",
        secondary_raw="procgen, meta progression",
    )
    assert profile.primary == ("procedural generation", "permadeath", "speedrun-viable")
    assert profile.secondary == ("meta-progression",)


def test_build_tag_profile_vibe() -> None:
    profile = build_tag_profile(
        "vibe",
        primary_raw="pixel, retro, dark",
        secondary_raw="pixelart, atmospheric",
    )
    assert profile.primary == ("pixel art", "retro aesthetic", "dark")
    assert profile.secondary == ("atmospheric",)


def test_build_tag_profile_kindred_normalizes_aliases() -> None:
    profile = build_tag_profile(
        "kindred",
        primary_raw="hades 2, bg3",
        secondary_raw="genshin",
    )
    assert profile.primary == ("hades", "baldurs gate")
    assert profile.secondary == ("genshin impact",)


# ===========================================================================
# SourceTags and TaggedQuery
# ===========================================================================


def test_source_tags_defaults_to_none() -> None:
    tags = SourceTags()
    assert tags.genre is None
    assert tags.mechanics is None
    assert tags.vibe is None


def test_source_tags_immutable() -> None:
    tags = SourceTags(genre="roguelite")
    with pytest.raises((AttributeError, TypeError)):
        tags.genre = "roguelike"  # type: ignore[misc]


def test_tagged_query_compat_properties() -> None:
    tq = TaggedQuery(
        text="roguelite game",
        source_tags=SourceTags(genre="roguelite", mechanics="permadeath"),
    )
    assert tq.source_genre_tag == "roguelite"
    assert tq.source_mechanics_tag == "permadeath"
    assert tq.source_vibe_tag is None


def test_tagged_query_default_source_tags() -> None:
    tq = TaggedQuery(text="some query")
    assert tq.source_tags == SourceTags()
    assert tq.source_genre_tag is None


# ===========================================================================
# build_tagged_queries
# ===========================================================================


def _make_game(
    genre_primary: str = "",
    mechanics_primary: str = "",
    vibe_primary: str = "",
    kindred_primary: str = "",
) -> Game:
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    return Game(
        game_id="g1",
        user_id="u1",
        name="Test Game",
        summary=None,
        description="A test game.",
        genre_tags=[],
        platform_tags=["pc"],
        website_url=None,
        status="active",
        slug="test-game",
        created_at=now,
        updated_at=now,
        genre_tag_profile=build_tag_profile("genre", primary_raw=genre_primary),
        mechanics_tag_profile=build_tag_profile("mechanics", primary_raw=mechanics_primary),
        vibe_tag_profile=build_tag_profile("vibe", primary_raw=vibe_primary),
        kindred_tag_profile=build_tag_profile("kindred", primary_raw=kindred_primary),
    )


def test_build_tagged_queries_includes_game_name() -> None:
    game = _make_game(genre_primary="roguelite")
    queries = build_tagged_queries(game, suffixes=("game", "gameplay"), n_queries=20)
    texts = [q.text for q in queries]
    assert "Test Game" in texts


def test_build_tagged_queries_no_duplicates() -> None:
    game = _make_game(genre_primary="strategy")
    queries = build_tagged_queries(game, suffixes=("game",), n_queries=30)
    texts = [q.text for q in queries]
    assert len(texts) == len(set(texts))


def test_build_tagged_queries_game_name_has_empty_source_tags() -> None:
    game = _make_game(genre_primary="roguelite")
    queries = build_tagged_queries(game, suffixes=("game",), n_queries=20)
    name_queries = [q for q in queries if q.text == "Test Game"]
    assert len(name_queries) == 1
    assert name_queries[0].source_tags == SourceTags()


def test_build_tagged_queries_genre_tags_carry_source_tag() -> None:
    game = _make_game(genre_primary="roguelite")
    queries = build_tagged_queries(game, suffixes=("game",), n_queries=50, run_index=0)
    genre_queries = [q for q in queries if q.source_tags.genre == "roguelite"]
    assert len(genre_queries) >= 1


def test_build_tagged_queries_different_run_index_gives_different_queries() -> None:
    game = _make_game(genre_primary="roguelite")
    q0 = {q.text for q in build_tagged_queries(game, suffixes=("game", "gameplay"), run_index=0)}
    q1 = {q.text for q in build_tagged_queries(game, suffixes=("game", "gameplay"), run_index=1)}
    # At least some queries differ between runs.
    assert q0 != q1


def test_build_tagged_queries_same_run_index_is_reproducible() -> None:
    game = _make_game(genre_primary="roguelite")
    q0a = [q.text for q in build_tagged_queries(game, suffixes=("game",), run_index=0)]
    q0b = [q.text for q in build_tagged_queries(game, suffixes=("game",), run_index=0)]
    assert q0a == q0b


def test_build_tagged_queries_game_name_suffixes_appended() -> None:
    game = _make_game(genre_primary="roguelite")
    queries = build_tagged_queries(
        game,
        suffixes=("game",),
        game_name_suffixes=("review", "gameplay"),
        n_queries=5,
    )
    texts = [q.text for q in queries]
    assert "Test Game review" in texts
    assert "Test Game gameplay" in texts
