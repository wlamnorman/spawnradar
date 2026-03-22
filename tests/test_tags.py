"""Tests for the canonical tag taxonomy and normalization rules."""

from typing import Literal

from app.games.models import Game
from app.games.tags import (
    TagProfile,
    build_tag_profile,
    normalize_tag,
)
from app.ingestion.query_builder import (
    SourceTags,
    TaggedQuery,
    build_tagged_queries,
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


# ---------------------------------------------------------------------------
# Mechanics tag normalization
# ---------------------------------------------------------------------------

_MECHANICS_NORMALIZATION_CASES: list[tuple[str, str]] = [
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


def test_normalize_mechanics_tags():
    for raw, expected in _MECHANICS_NORMALIZATION_CASES:
        assert normalize_tag(raw, "mechanics") == expected, (
            f"normalize_tag({raw!r}, 'mechanics') should be {expected!r}"
        )


def test_build_tag_profile_mechanics_normalizes_and_dedupes():
    profile = build_tag_profile(
        "mechanics",
        primary_raw="proc gen, perma death, speedrun",
        secondary_raw="procgen, meta progression",
    )

    assert profile.primary == ("procedural generation", "permadeath", "speedrun-viable")
    # procgen deduped (already in primary), meta-progression new
    assert profile.secondary == ("meta-progression",)


# ---------------------------------------------------------------------------
# Tone tag normalization
# ---------------------------------------------------------------------------

_TONE_NORMALIZATION_CASES: list[tuple[str, str]] = [
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


def test_normalize_tone_tags():
    for raw, expected in _TONE_NORMALIZATION_CASES:
        assert normalize_tag(raw, "tone") == expected, (
            f"normalize_tag({raw!r}, 'tone') should be {expected!r}"
        )


def test_build_tag_profile_tone_normalizes_and_dedupes():
    profile = build_tag_profile(
        "tone",
        primary_raw="pixel, retro, dark",
        secondary_raw="pixelart, atmospheric",
    )

    assert profile.primary == ("pixel art", "retro aesthetic", "dark")
    # pixelart deduped (already "pixel art"), atmospheric new
    assert profile.secondary == ("atmospheric",)


# ---------------------------------------------------------------------------
# New flagship audience tag aliases
# ---------------------------------------------------------------------------

_FLAGSHIP_AUDIENCE_CASES: list[tuple[str, str]] = [
    ("lol players", "league of legends players"),
    ("league of legends fans", "league of legends players"),
    ("stardew fans", "stardew valley fans"),
    ("stardew players", "stardew valley fans"),
    ("stardew valley players", "stardew valley fans"),
    ("elden ring players", "elden ring fans"),
    ("hollow knight players", "hollow knight fans"),
    ("hades players", "hades fans"),
    ("fromsoft players", "fromsoft fans"),
    ("from software fans", "fromsoft fans"),
    ("minecraft players", "minecraft fans"),
    ("terraria players", "terraria fans"),
    ("valheim players", "valheim fans"),
    ("total war players", "total war fans"),
    ("dark souls players", "dark souls fans"),
    ("dead cells players", "dead cells fans"),
    ("diablo players", "diablo fans"),
    ("persona players", "persona fans"),
    ("poe fans", "path of exile fans"),
    ("path of exile players", "path of exile fans"),
    ("octopath players", "octopath fans"),
    ("octopath traveler fans", "octopath fans"),
    ("ori players", "ori fans"),
    ("monster train players", "monster train fans"),
    ("inscryption players", "inscryption fans"),
    ("celeste fans", "celeste fans"),  # exact match, no alias needed
    ("dont starve fans", "dont starve fans"),  # exact match
    ("don't starve fans", "dont starve fans"),
    ("dont starve players", "dont starve fans"),
    ("baldur's gate fans", "baldurs gate fans"),
    ("baldurs gate players", "baldurs gate fans"),
    ("binding of isaac players", "binding of isaac fans"),
    ("civilization players", "civilization fans"),
    ("civ fans", "civilization fans"),
    ("cities skylines players", "cities skylines fans"),
]


def test_normalize_flagship_audience_aliases():
    for raw, expected in _FLAGSHIP_AUDIENCE_CASES:
        assert normalize_tag(raw, "audience") == expected, (
            f"normalize_tag({raw!r}, 'audience') should be {expected!r}"
        )


# ---------------------------------------------------------------------------
# SourceTags and TaggedQuery dataclass behaviour
# ---------------------------------------------------------------------------


def test_source_tags_defaults_to_none():
    tags = SourceTags()
    assert tags.genre is None
    assert tags.audience is None
    assert tags.mechanics is None
    assert tags.tone is None


def test_source_tags_immutable():
    tags = SourceTags(genre="roguelite")
    raised = False
    try:
        tags.genre = "roguelike"  # type: ignore[misc]
    except Exception:
        raised = True
    assert raised or tags.genre == "roguelite"


def test_tagged_query_compat_properties():
    tq = TaggedQuery(
        text="roguelite game",
        source_tags=SourceTags(genre="roguelite", mechanics="permadeath"),
    )
    assert tq.source_genre_tag == "roguelite"
    assert tq.source_mechanics_tag == "permadeath"
    assert tq.source_audience_tag is None
    assert tq.source_tone_tag is None


def test_tagged_query_default_source_tags():
    tq = TaggedQuery(text="some query")
    assert tq.source_tags == SourceTags()
    assert tq.source_genre_tag is None


# ---------------------------------------------------------------------------
# build_tagged_queries — source tag provenance
# ---------------------------------------------------------------------------


def _make_game(
    genre_primary: str = "",
    audience_primary: str = "",
    mechanics_primary: str = "",
    tone_primary: str = "",
) -> Game:
    return Game(
        game_id="g1",
        user_id="u1",
        name="Test Game",
        summary=None,
        description="A test game.",
        genre_tags=[],
        audience_tags=[],
        platform_tags=["pc"],
        website_url=None,
        status="active",
        slug="test-game",
        created_at="2026-01-01",
        updated_at="2026-01-01",
        genre_tag_profile=build_tag_profile("genre", primary_raw=genre_primary),
        audience_tag_profile=build_tag_profile(
            "audience", primary_raw=audience_primary
        ),
        mechanics_tag_profile=build_tag_profile(
            "mechanics", primary_raw=mechanics_primary
        ),
        tone_tag_profile=build_tag_profile("tone", primary_raw=tone_primary),
    )


def test_build_tagged_queries_genre_source_tags():
    game = _make_game(genre_primary="roguelite")
    queries = build_tagged_queries(
        game,
        genre_templates=("{tag} game",),
        audience_templates=("{tag} players",),
        game_name_templates=("{game_name}",),
    )
    genre_queries = [q for q in queries if q.source_tags.genre == "roguelite"]
    assert any(q.text == "roguelite game" for q in genre_queries)
    for q in genre_queries:
        assert q.source_tags.audience is None
        assert q.source_tags.mechanics is None
        assert q.source_tags.tone is None


def test_build_tagged_queries_audience_source_tags():
    game = _make_game(audience_primary="elden ring fans")
    queries = build_tagged_queries(
        game,
        genre_templates=("{tag} game",),
        audience_templates=("{tag}",),
        game_name_templates=("{game_name}",),
    )
    audience_queries = [
        q for q in queries if q.source_tags.audience == "elden ring fans"
    ]
    assert len(audience_queries) >= 1
    assert all(q.source_tags.genre is None for q in audience_queries)


def test_build_tagged_queries_mechanics_source_tags():
    game = _make_game(mechanics_primary="procedural generation")
    queries = build_tagged_queries(
        game,
        genre_templates=("{tag} game",),
        audience_templates=("{tag}",),
        mechanics_templates=("games with {tag}",),
        game_name_templates=("{game_name}",),
    )
    mech_queries = [
        q for q in queries if q.source_tags.mechanics == "procedural generation"
    ]
    assert any(q.text == "games with procedural generation" for q in mech_queries)
    assert all(q.source_tags.genre is None for q in mech_queries)


def test_build_tagged_queries_tone_source_tags():
    game = _make_game(tone_primary="pixel art")
    queries = build_tagged_queries(
        game,
        genre_templates=("{tag} game",),
        audience_templates=("{tag}",),
        tone_templates=("{tag} indie",),
        game_name_templates=("{game_name}",),
    )
    tone_queries = [q for q in queries if q.source_tags.tone == "pixel art"]
    assert any(q.text == "pixel art indie" for q in tone_queries)
    assert all(q.source_tags.genre is None for q in tone_queries)


def test_build_tagged_queries_deduplicates_across_tag_types():
    """A query text that would be produced by two different tags is only emitted once."""
    game = _make_game(genre_primary="strategy", audience_primary="strategy fans")
    queries = build_tagged_queries(
        game,
        genre_templates=("strategy",),
        audience_templates=("strategy fans",),
        game_name_templates=("{game_name}",),
    )
    texts = [q.text for q in queries]
    assert len(texts) == len(set(texts)), "build_tagged_queries produced duplicate texts"


def test_build_tagged_queries_game_name_has_empty_source_tags():
    game = _make_game(genre_primary="roguelite")
    queries = build_tagged_queries(
        game,
        genre_templates=("{tag} game",),
        audience_templates=("{tag}",),
        game_name_templates=("{game_name}",),
    )
    name_queries = [q for q in queries if q.text == "Test Game"]
    assert len(name_queries) == 1
    assert name_queries[0].source_tags == SourceTags()
