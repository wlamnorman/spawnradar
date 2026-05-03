"""Tests for the discovery pipeline (app.creator_index.discovery)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.creator_index.discovery import (
    EnrichedCreator,
    build_reference_games,
    resolve_similar_games,
    run_keyword_queries,
)
from app.games.models import CustomerGame
from app.igdb.models import IGDBGame


def _make_customer_game(**overrides) -> CustomerGame:
    defaults: dict = {
        "customer_game_id": "cg-1",
        "workspace_id": "u-1",
        "name": "Test Game",
        "summary": "A test game.",
        "description": "Full description.",
        "website_url": None,
        "status": "active",
        "slug": "test-game-cg-1",
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-01-01T00:00:00",
        "igdb_genre_ids": [15, 16],
        "igdb_theme_ids": [18],
        "igdb_game_mode_ids": [1],
        "igdb_player_perspective_ids": [],
        "igdb_keyword_ids": ["roguelike"],
        "similar_game_names": ["FTL: Faster Than Light", "Slay the Spire"],
        "llm_similar_game_names": ["Into the Breach"],
    }
    defaults.update(overrides)
    return CustomerGame(**defaults)


def _make_igdb_game(igdb_id: int, name: str, **kw) -> IGDBGame:
    return IGDBGame(
        igdb_id=igdb_id,
        name=name,
        slug=name.lower().replace(" ", "-"),
        summary=f"A game called {name}.",
        genre_ids=kw.get("genre_ids", []),
        theme_ids=kw.get("theme_ids", []),
        first_release_date=None,
        cover_url=None,
        platform_ids=[],
        platform_names=[],
        keyword_names=kw.get("keyword_names", []),
    )


# ---------------------------------------------------------------------------
# Stage A tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_resolve_similar_games_picks_exact_match():
    """When IGDB returns multiple results, prefer the exact name match."""
    ftl = _make_igdb_game(3075, "FTL: Faster Than Light")
    ftl_dlc = _make_igdb_game(9999, "FTL: Advanced Edition")

    mock_client = AsyncMock()
    mock_client.fetch_games_by_name = AsyncMock(return_value=[ftl_dlc, ftl])

    result = await resolve_similar_games(
        ["FTL: Faster Than Light"],
        mock_client,
    )
    assert len(result) == 1
    assert result[0].igdb_id == 3075


@pytest.mark.anyio
async def test_resolve_similar_games_deduplicates():
    """Same IGDB game from two different names should only appear once."""
    ftl = _make_igdb_game(3075, "FTL: Faster Than Light")

    mock_client = AsyncMock()
    mock_client.fetch_games_by_name = AsyncMock(return_value=[ftl])

    result = await resolve_similar_games(
        ["FTL: Faster Than Light", "FTL"],
        mock_client,
    )
    assert len(result) == 1


@pytest.mark.anyio
async def test_resolve_similar_games_skips_not_found():
    mock_client = AsyncMock()
    mock_client.fetch_games_by_name = AsyncMock(return_value=[])

    result = await resolve_similar_games(["NonexistentGame"], mock_client)
    assert result == []


@pytest.mark.anyio
async def test_keyword_queries_progressive_fallback():
    """Q2 fires when Q1 returns <30 games."""
    game = _make_customer_game()
    q1_results = [_make_igdb_game(i, f"Game {i}") for i in range(10)]
    q2_results = [
        _make_igdb_game(100 + i, f"Theme Game {i}") for i in range(5)
    ]

    mock_client = AsyncMock()
    mock_client.resolve_keyword_ids = AsyncMock(
        return_value={"roguelike": 416}
    )

    call_count = 0

    async def mock_fetch(keyword_ids, *, genre_ids=(), theme_ids=(), limit=50):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return q1_results  # Q1: genre+keyword
        if call_count == 2:
            return q2_results  # Q2: genre+theme
        return []  # Q3

    mock_client.fetch_games_by_keywords = mock_fetch

    result = await run_keyword_queries(game, mock_client, set())
    assert len(result) == 15  # 10 + 5
    assert call_count >= 2  # Q2 should have fired


@pytest.mark.anyio
async def test_keyword_queries_skips_existing_ids():
    """Games already in the reference set are excluded."""
    game = _make_customer_game()
    results = [_make_igdb_game(i, f"Game {i}") for i in range(5)]

    mock_client = AsyncMock()
    mock_client.resolve_keyword_ids = AsyncMock(
        return_value={"roguelike": 416}
    )
    mock_client.fetch_games_by_keywords = AsyncMock(return_value=results)

    existing = {0, 1, 2}  # 3 of the 5 already exist
    result = await run_keyword_queries(game, mock_client, existing)
    assert len(result) == 2  # only ids 3 and 4


@pytest.mark.anyio
async def test_build_reference_games_similar_first():
    """Similar games should have priority 0, keyword games priority 1."""
    game = _make_customer_game()
    ftl = _make_igdb_game(3075, "FTL: Faster Than Light")
    sts = _make_igdb_game(40477, "Slay the Spire")
    itb = _make_igdb_game(27117, "Into the Breach")
    kw_game = _make_igdb_game(99999, "Some Roguelike")

    mock_client = AsyncMock()

    async def mock_fetch_by_name(name, *, limit=3):
        lookup = {
            "ftl: faster than light": [ftl],
            "slay the spire": [sts],
            "into the breach": [itb],
        }
        return lookup.get(name.lower(), [])

    mock_client.fetch_games_by_name = mock_fetch_by_name
    mock_client.resolve_keyword_ids = AsyncMock(
        return_value={"roguelike": 416}
    )
    mock_client.fetch_games_by_keywords = AsyncMock(return_value=[kw_game])

    mock_repo = MagicMock()
    mock_repo.upsert = MagicMock()

    result = await build_reference_games(game, mock_client, mock_repo)
    assert len(result) == 4

    # Similar games have priority 0
    similar = [r for r in result if r.priority == 0]
    keyword = [r for r in result if r.priority == 1]
    assert len(similar) == 3
    assert len(keyword) == 1

    # All games were persisted
    assert mock_repo.upsert.call_count == 4


# ---------------------------------------------------------------------------
# Service-level tests for pre-population methods
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_top_categories_crawl_persists_creators():
    """run_top_categories_crawl should iterate the generator and persist each creator."""
    from app.creator_index.adapters.base import (
        AccountSeedBundle,
        SourceAccountSeed,
        TwitchProfileSeed,
    )
    from app.creator_index.service import CreatorIndexService

    fake_bundle = AccountSeedBundle(
        account=SourceAccountSeed(
            external_id="123",
            handle_current="testuser",
            display_name_current="TestUser",
            canonical_url=None,
        ),
        platform_profile=TwitchProfileSeed(
            broadcaster_id="123",
            login="testuser",
            display_name="TestUser",
            description=None,
            followers_count=None,
            viewer_count=None,
            recent_avg_live_viewers=None,
            recent_median_live_viewers=None,
            recent_avg_vod_views=None,
            recent_median_vod_views=None,
            streams_last_30d=None,
            language=None,
            games_played=(),
            avatar_url=None,
            last_live_at=None,
            fetched_at="2025-01-01T00:00:00",
            expires_at="2025-02-01T00:00:00",
        ),
        content_samples=(),
        contact_points=(),
        observed_games=(),
    )
    fake_creator = EnrichedCreator(
        bundle=fake_bundle,
        source_game_name="Fortnite",
        source_igdb_game_id=None,
    )

    async def fake_crawl(*args, **kwargs):
        yield fake_creator

    with (
        patch(
            "app.creator_index.service.crawl_top_categories",
            side_effect=fake_crawl,
        ),
        patch.object(
            CreatorIndexService,
            "_persist_enriched_creator",
            new=AsyncMock(return_value=(1, 0, 0)),
        ) as mock_persist,
    ):
        service = CreatorIndexService.__new__(CreatorIndexService)
        service._db_path = ":memory:"
        service._twitch_stream_client = MagicMock()
        service._enrichment = MagicMock()
        service._igdb_repo = MagicMock()

        count = await service.run_top_categories_crawl()

    assert count == 1
    mock_persist.assert_awaited_once_with(fake_creator)


@pytest.mark.anyio
async def test_run_catalog_discovery_loads_and_runs(tmp_path: Path):
    """run_catalog_discovery should load catalog games and run discover_creators for each."""
    from app.creator_index.adapters.base import (
        AccountSeedBundle,
        SourceAccountSeed,
        TwitchProfileSeed,
    )
    from app.creator_index.service import CreatorIndexService

    # Write a catalog definition
    definition = {
        "customer_game_name": "Test Catalog Game",
        "customer_game_slug_hint": "test-catalog",
        "baseline_summary": "A test game.",
        "broad_igdb_genres": [{"id": 32, "label": "Indie"}],
        "broad_igdb_themes": [],
        "required_game_modes": [],
        "extra_custom_tags": [],
    }
    (tmp_path / "test.json").write_text(json.dumps(definition))

    fake_bundle = AccountSeedBundle(
        account=SourceAccountSeed(
            external_id="456",
            handle_current="cataloguser",
            display_name_current="CatalogUser",
            canonical_url=None,
        ),
        platform_profile=TwitchProfileSeed(
            broadcaster_id="456",
            login="cataloguser",
            display_name="CatalogUser",
            description=None,
            followers_count=None,
            viewer_count=None,
            recent_avg_live_viewers=None,
            recent_median_live_viewers=None,
            recent_avg_vod_views=None,
            recent_median_vod_views=None,
            streams_last_30d=None,
            language=None,
            games_played=(),
            avatar_url=None,
            last_live_at=None,
            fetched_at="2025-01-01T00:00:00",
            expires_at="2025-02-01T00:00:00",
        ),
        content_samples=(),
        contact_points=(),
        observed_games=(),
    )
    fake_creator = EnrichedCreator(
        bundle=fake_bundle,
        source_game_name="Some Game",
        source_igdb_game_id=None,
    )

    async def fake_discover(*args, **kwargs):
        yield fake_creator

    with (
        patch(
            "app.creator_index.service.discover_creators",
            side_effect=fake_discover,
        ),
        patch.object(
            CreatorIndexService,
            "_persist_enriched_creator",
            new=AsyncMock(return_value=(1, 0, 0)),
        ) as mock_persist,
    ):
        service = CreatorIndexService.__new__(CreatorIndexService)
        service._db_path = ":memory:"
        service._igdb_client = MagicMock()
        service._twitch_stream_client = MagicMock()
        service._enrichment = MagicMock()
        service._igdb_repo = MagicMock()

        results = await service.run_catalog_discovery(tmp_path)

    assert results == {"Test Catalog Game": 1}
    mock_persist.assert_awaited_once_with(fake_creator)
