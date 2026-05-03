from __future__ import annotations

import sqlite3

import pytest

from app.igdb.models import IGDBGame
from app.igdb.repository import IGDBRepository
from app.igdb.taxonomy import IGDBGenre, IGDBTheme
from app.steam_enrichment.client import SteamStoreClient, extract_store_tags
from app.steam_enrichment.models import SteamSearchCandidate, SteamStoreGame
from app.steam_enrichment.resolver import resolve_steam_candidate
from app.steam_enrichment.service import SteamTagEnrichmentService
from app.steam_enrichment.tag_mapping import map_steam_terms_to_canonical_tags


def _seed_igdb_game(
    db_path: str,
    *,
    igdb_id: int,
    name: str,
    developer_names: list[str] | None = None,
    genre_ids: list[IGDBGenre] | None = None,
    theme_ids: list[IGDBTheme] | None = None,
    keyword_names: list[str] | None = None,
    first_release_date: int | None = None,
) -> None:
    IGDBRepository(db_path).upsert(
        IGDBGame(
            igdb_id=igdb_id,
            name=name,
            slug=name.casefold().replace(" ", "-"),
            summary=None,
            developer_names=developer_names or [],
            genre_ids=genre_ids or [],
            theme_ids=theme_ids or [],
            first_release_date=first_release_date,
            keyword_names=keyword_names or [],
        )
    )


def test_map_steam_terms_splits_action_rpg_when_combined_tag_missing():
    mapped = map_steam_terms_to_canonical_tags(
        api_genre_labels=[],
        api_category_labels=[],
        raw_tags=["Action RPG"],
    )

    keys = {(entry.tag_type, str(entry.tag_id)) for entry in mapped}
    assert ("theme", "1") in keys
    assert ("genre", "12") in keys


def test_map_steam_terms_keeps_turn_based_rpg_as_exact_keyword():
    mapped = map_steam_terms_to_canonical_tags(
        api_genre_labels=[],
        api_category_labels=[],
        raw_tags=["Turn-Based RPG"],
    )

    keys = {(entry.tag_type, str(entry.tag_id)) for entry in mapped}
    assert ("genre", "turn-based rpg") in keys
    assert ("genre", "12") not in keys


def test_map_steam_terms_adds_text_phrase_after_two_mentions():
    mapped = map_steam_terms_to_canonical_tags(
        api_genre_labels=[],
        api_category_labels=[],
        raw_tags=[],
        text_blobs=[
            "A hypnotically satisfying deckbuilder roguelike with escalating runs.",
            "This deck building roguelike rewards every new deckbuilder combo.",
        ],
    )

    keys = {(entry.tag_type, str(entry.tag_id)) for entry in mapped}
    assert ("genre", "deckbuilder") in keys
    assert ("genre", "roguelike") in keys


def test_map_steam_terms_skips_text_phrase_seen_only_once():
    mapped = map_steam_terms_to_canonical_tags(
        api_genre_labels=[],
        api_category_labels=[],
        raw_tags=[],
        text_blobs=["A dungeon crawler with tense encounters."],
    )

    keys = {(entry.tag_type, str(entry.tag_id)) for entry in mapped}
    assert ("genre", "dungeon crawler") not in keys


def test_extract_store_tags_falls_back_to_tag_links_without_app_tag_class():
    html = """
    <div class="glance_tags">
        <a href="https://store.steampowered.com/tags/en/Roguelike/">Roguelike</a>
        <a href="https://store.steampowered.com/tags/en/Deckbuilding/">Deckbuilding</a>
        <a href="https://store.steampowered.com/tags/en/Roguelike/">Roguelike</a>
    </div>
    """

    assert extract_store_tags(html) == ["Roguelike", "Deckbuilding"]


def test_resolver_accepts_soft_name_and_developer_match():
    slay_two = SteamStoreGame(
        app_id=2868840,
        name="Slay the Spire 2",
        store_url="https://store.steampowered.com/app/2868840/",
        developers=("Mega Crit",),
        release_date="2025",
    )
    slay_one = SteamStoreGame(
        app_id=646570,
        name="Slay the Spire",
        store_url="https://store.steampowered.com/app/646570/",
        developers=("Mega Crit",),
        release_date="2019",
    )

    result = resolve_steam_candidate(
        igdb_id=296831,
        igdb_name="Slay the Spire II",
        igdb_developers=("Mega Crit Games",),
        igdb_release_year=2025,
        local_tag_keys={("genre", "deckbuilder"), ("genre", "roguelike")},
        candidates=[slay_two, slay_one],
        candidate_mapped_tag_keys={
            2868840: {("genre", "deckbuilder"), ("genre", "roguelike")},
            646570: {("genre", "deckbuilder")},
        },
    )

    assert result.accepted_link is not None
    assert result.accepted_link.steam_app_id == 2868840
    assert result.accepted_link.match_method.startswith("name_normalized")


def test_resolver_accepts_known_title_suffix_variant_match():
    gta_enhanced = SteamStoreGame(
        app_id=3240220,
        name="Grand Theft Auto V Enhanced",
        store_url="https://store.steampowered.com/app/3240220/",
        developers=("Rockstar North",),
        release_date="2025",
    )
    vice_city = SteamStoreGame(
        app_id=1546990,
        name="Grand Theft Auto: Vice City – The Definitive Edition",
        store_url="https://store.steampowered.com/app/1546990/",
        developers=("Rockstar Games",),
        release_date="2023",
    )

    result = resolve_steam_candidate(
        igdb_id=1020,
        igdb_name="Grand Theft Auto V",
        igdb_developers=("Rockstar North",),
        igdb_release_year=2013,
        local_tag_keys={
            ("genre", "5"),
            ("genre", "31"),
            ("theme", "1"),
            ("theme", "38"),
        },
        candidates=[gta_enhanced, vice_city],
        candidate_mapped_tag_keys={
            3240220: {
                ("genre", "5"),
                ("theme", "1"),
                ("theme", "38"),
            },
            1546990: {
                ("genre", "31"),
                ("theme", "1"),
            },
        },
    )

    assert result.accepted_link is not None
    assert result.accepted_link.steam_app_id == 3240220
    assert result.accepted_link.match_method.startswith(
        "name_normalized_variant"
    )


@pytest.mark.anyio
async def test_enrich_igdb_game_stores_link_raw_tags_and_mapped_tags(db_path):
    _seed_igdb_game(
        db_path,
        igdb_id=296831,
        name="Slay the Spire II",
        developer_names=["Mega Crit Games"],
        genre_ids=[IGDBGenre.STRATEGY],
        theme_ids=[IGDBTheme.FANTASY],
        keyword_names=["deck-building", "roguelike"],
        first_release_date=1735689600,  # 2025-01-01
    )

    class FakeSteamClient(SteamStoreClient):
        async def search_candidates(
            self, name: str, *, limit: int = 8, client=None
        ):
            return [
                SteamSearchCandidate(
                    app_id=2868840,
                    name="Slay the Spire 2",
                    store_url="https://store.steampowered.com/app/2868840/",
                )
            ]

        async def fetch_store_game(self, app_id: int, *, client=None):
            assert app_id == 2868840
            return SteamStoreGame(
                app_id=2868840,
                name="Slay the Spire 2",
                store_url="https://store.steampowered.com/app/2868840/",
                developers=("Mega Crit",),
                release_date="2025",
                raw_tags=("Roguelike Deckbuilder", "Fantasy", "Singleplayer"),
                api_genre_labels=("Strategy",),
                api_category_labels=("Single-player",),
            )

    service = SteamTagEnrichmentService(
        db_path=db_path,
        client=FakeSteamClient(),
    )
    result = await service.enrich_igdb_game(296831)

    assert result.status == "linked"
    assert result.resolved_link is not None
    assert result.resolved_link.steam_app_id == 2868840

    with sqlite3.connect(db_path) as conn:
        link = conn.execute(
            "SELECT steam_app_id, match_method FROM steam_game_links WHERE igdb_id = ?",
            (296831,),
        ).fetchone()
        assert link == (
            2868840,
            "name_normalized+developer_normalized+release_year+tag_overlap",
        )

        raw_tags = conn.execute(
            "SELECT raw_tag, normalized_tag FROM steam_game_tags WHERE igdb_id = ? ORDER BY raw_tag",
            (296831,),
        ).fetchall()
        assert raw_tags == [
            ("Fantasy", "fantasy"),
            ("Roguelike Deckbuilder", "roguelike deckbuilder"),
            ("Singleplayer", "singleplayer"),
        ]

        mapped = conn.execute(
            """
            SELECT source_tag, mapped_tag_type, mapped_tag_id
            FROM steam_game_mapped_tags
            WHERE igdb_id = ?
            ORDER BY source_tag, mapped_tag_type, mapped_tag_id
            """,
            (296831,),
        ).fetchall()
        assert ("Roguelike Deckbuilder", "genre", "deckbuilder") in mapped
        assert ("Roguelike Deckbuilder", "genre", "roguelike") in mapped
        assert ("Single-player", "game_mode", "1") in mapped


@pytest.mark.anyio
async def test_enrich_igdb_game_dedupes_canonical_mapped_tags_before_storing(
    db_path,
):
    _seed_igdb_game(
        db_path,
        igdb_id=251833,
        name="Balatro",
        genre_ids=[IGDBGenre.STRATEGY],
        keyword_names=["deck-building", "roguelike"],
        first_release_date=1706745600,
    )

    class FakeSteamClient(SteamStoreClient):
        async def search_candidates(
            self, name: str, *, limit: int = 8, client=None
        ):
            return [
                SteamSearchCandidate(
                    app_id=2379780,
                    name="Balatro",
                    store_url="https://store.steampowered.com/app/2379780/",
                )
            ]

        async def fetch_store_game(self, app_id: int, *, client=None):
            assert app_id == 2379780
            return SteamStoreGame(
                app_id=2379780,
                name="Balatro",
                store_url="https://store.steampowered.com/app/2379780/",
                developers=("LocalThunk",),
                release_date="2024",
                raw_tags=(
                    "Deckbuilding",
                    "Roguelike Deckbuilder",
                    "Roguelike",
                ),
                api_genre_labels=("Strategy",),
                api_category_labels=("Single-player",),
            )

    service = SteamTagEnrichmentService(
        db_path=db_path, client=FakeSteamClient()
    )
    result = await service.enrich_igdb_game(251833)

    assert result.status == "linked"

    with sqlite3.connect(db_path) as conn:
        mapped = conn.execute(
            """
            SELECT mapped_tag_type, mapped_tag_id, COUNT(*)
            FROM steam_game_mapped_tags
            WHERE igdb_id = ?
            GROUP BY mapped_tag_type, mapped_tag_id
            ORDER BY mapped_tag_type, mapped_tag_id
            """,
            (251833,),
        ).fetchall()

    counts = {(tag_type, tag_id): count for tag_type, tag_id, count in mapped}
    assert counts[("genre", "deckbuilder")] == 1
    assert counts[("genre", "roguelike")] == 1


@pytest.mark.anyio
async def test_enrich_igdb_game_uses_repeated_text_phrases_for_mapping(
    db_path,
):
    _seed_igdb_game(
        db_path,
        igdb_id=400001,
        name="Test Crawler",
        genre_ids=[IGDBGenre.ROLE_PLAYING],
        first_release_date=1704067200,
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE igdb_games SET summary = ? WHERE igdb_id = ?",
            ("A tense dungeon crawler for methodical players.", 400001),
        )

    class FakeSteamClient(SteamStoreClient):
        async def search_candidates(
            self, name: str, *, limit: int = 8, client=None
        ):
            return [
                SteamSearchCandidate(
                    app_id=900001,
                    name="Test Crawler",
                    store_url="https://store.steampowered.com/app/900001/",
                )
            ]

        async def fetch_store_game(self, app_id: int, *, client=None):
            assert app_id == 900001
            return SteamStoreGame(
                app_id=900001,
                name="Test Crawler",
                store_url="https://store.steampowered.com/app/900001/",
                developers=("Example Studio",),
                release_date="2024",
                short_description="Enter a dungeon crawler built around attrition.",
                detailed_description="",
                raw_tags=(),
                api_genre_labels=("RPG",),
                api_category_labels=("Single-player",),
            )

    service = SteamTagEnrichmentService(
        db_path=db_path, client=FakeSteamClient()
    )
    result = await service.enrich_igdb_game(400001)

    assert result.status == "linked"
    keys = {
        (entry.tag_type, str(entry.tag_id)) for entry in result.mapped_tags
    }
    assert ("genre", "dungeon crawler") in keys
