"""Tests for the headless source-index crawler."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.creator_index.adapters.base import (
    AccountSeedBundle,
    ContactPointSeed,
    ContactType,
    ContentSampleSeed,
    ObservedGameSeed,
    SourceAccountSeed,
    TwitchProfileSeed,
    YouTubeChannelSeed,
)
from app.creator_index.adapters.youtube import YouTubeChannelAdapter
from app.creator_index.enrichment import TwitchEnrichment
from app.creator_index.facets import build_creator_profile_facets
from app.creator_index.repository import CreatorIndexRepository
from app.creator_index.service import CreatorIndexService
from app.database import get_connection
from app.runtime import SourceRuntime
from app.scheduler.setup import create_scheduler

# ---------------------------------------------------------------------------
# Clip record parsing
# ---------------------------------------------------------------------------


def test_parse_clip_record_extracts_game_id_and_view_count():
    from app.creator_index.enrichment import _parse_clip_record

    raw = {
        "id": "clip123",
        "broadcaster_id": "999",
        "broadcaster_name": "TestStreamer",
        "game_id": "33214",
        "title": "Amazing play",
        "view_count": 1500,
        "created_at": "2025-06-15T12:00:00Z",
        "thumbnail_url": "https://clips.example.com/thumb.jpg",
        "url": "https://clips.twitch.tv/clip123",
        "language": "en",
    }
    record = _parse_clip_record(raw)
    assert record is not None
    assert record.clip_id == "clip123"
    assert record.game_id == "33214"
    assert record.view_count == 1500
    assert record.created_at == "2025-06-15T12:00:00Z"
    assert record.title == "Amazing play"
    assert record.broadcaster_id == "999"


def test_parse_clip_record_returns_none_for_missing_id():
    from app.creator_index.enrichment import _parse_clip_record

    assert _parse_clip_record({"title": "no id"}) is None


def test_parse_clip_record_returns_none_for_missing_game_id():
    from app.creator_index.enrichment import _parse_clip_record

    assert _parse_clip_record({"id": "c1", "title": "t"}) is None


@pytest.mark.anyio
async def test_fetch_clips_returns_clip_records(monkeypatch):
    """Enrichment fetches clips for each broadcaster, returning TwitchClipRecords."""
    from app.creator_index.enrichment import TwitchClipRecord

    clip_data = {
        "data": [
            {
                "id": "clip1",
                "broadcaster_id": "111",
                "broadcaster_name": "Streamer",
                "game_id": "33214",
                "title": "Cool clip",
                "view_count": 500,
                "created_at": "2025-06-01T10:00:00Z",
                "thumbnail_url": "https://example.com/thumb.jpg",
                "url": "https://clips.twitch.tv/clip1",
                "language": "en",
            }
        ],
        "pagination": {},
    }

    async def fake_request(
        client,
        method,
        url,
        *,
        params=None,
        headers=None,
        refresh_headers=None,
    ):
        return clip_data

    monkeypatch.setattr(
        "app.creator_index.enrichment.twitch_request_json", fake_request
    )

    enrichment = TwitchEnrichment("cid", "csecret")

    async with httpx.AsyncClient() as client:
        headers = {"Authorization": "Bearer fake", "Client-Id": "cid"}
        result = await enrichment.fetch_clips_for_users(
            ["111"], client=client, headers=headers
        )

    assert "111" in result
    assert len(result["111"]) == 1
    assert isinstance(result["111"][0], TwitchClipRecord)
    assert result["111"][0].game_id == "33214"


@pytest.mark.anyio
async def test_resolve_game_names_maps_twitch_ids_to_names(monkeypatch):

    games_response = {
        "data": [
            {"id": "33214", "name": "Fortnite", "box_art_url": None},
            {"id": "21779", "name": "League of Legends", "box_art_url": None},
        ]
    }

    async def fake_request(
        client,
        method,
        url,
        *,
        params=None,
        headers=None,
        refresh_headers=None,
    ):
        return games_response

    monkeypatch.setattr(
        "app.creator_index.enrichment.twitch_request_json", fake_request
    )

    enrichment = TwitchEnrichment("cid", "csecret")

    async with httpx.AsyncClient() as client:
        headers = {"Authorization": "Bearer fake", "Client-Id": "cid"}
        result = await enrichment.resolve_game_names(
            {"33214", "21779"}, client=client, headers=headers
        )

    assert result["33214"] == "Fortnite"
    assert result["21779"] == "League of Legends"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_twitch_bundle_for_game(
    external_id: str,
    game_name: str,
) -> AccountSeedBundle:
    return AccountSeedBundle(
        account=SourceAccountSeed(
            external_id=external_id,
            handle_current=f"{external_id}-tv",
            display_name_current=f"{game_name} TV",
            canonical_url=f"https://www.twitch.tv/{external_id}-tv",
        ),
        platform_profile=TwitchProfileSeed(
            broadcaster_id=external_id,
            login=f"{external_id}-tv",
            display_name=f"{game_name} TV",
            description="Email me at creator@example.com",
            followers_count=1200,
            viewer_count=88,
            recent_avg_live_viewers=None,
            recent_median_live_viewers=None,
            recent_avg_vod_views=250,
            recent_median_vod_views=250,
            streams_last_30d=1,
            language="en",
            games_played=(game_name, "Another Game"),
            avatar_url="https://static.example/avatar.png",
            last_live_at="2026-03-24T10:00:00+00:00",
            fetched_at="2026-03-24T10:05:00+00:00",
            expires_at="2026-03-24T16:05:00+00:00",
        ),
        content_samples=(
            ContentSampleSeed(
                external_content_id=f"vod-{external_id}",
                content_type="vod",
                title_or_text=f"{game_name} first look",
                body_text="Recent VOD about the game",
                url="https://www.twitch.tv/videos/1",
                thumbnail_url="https://static.example/thumb.jpg",
                published_at="2026-03-24T09:00:00+00:00",
                engagement_count=250,
                language="en",
                position_rank=0,
                fetched_at="2026-03-24T10:05:00+00:00",
                expires_at="2026-03-24T16:05:00+00:00",
            ),
        ),
        contact_points=(
            ContactPointSeed(
                contact_type=ContactType.EMAIL,
                contact_value="creator@example.com",
                source_kind="profile_description",
                source_url="https://www.twitch.tv/example/about",
            ),
        ),
    )


def _insert_test_igdb_game(db_path: str, igdb_game_id: int, name: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO igdb_games (
                igdb_id, name, slug, summary, first_release_date,
                platform_ids_json, platform_names_json,
                last_synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                igdb_game_id,
                name,
                name.casefold().replace(" ", "-"),
                None,
                None,
                "[]",
                "[]",
                "2026-01-01T00:00:00+00:00",
            ),
        )


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


def test_create_scheduler_registers_creator_index_jobs(db_path):
    scheduler = create_scheduler(db_path, SourceRuntime())

    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert set(jobs) == {
        "creator_index_twitch_sync",
        "steam_tag_backfill",
        "top_categories_crawl",
    }
    assert (
        jobs["creator_index_twitch_sync"].trigger.__class__.__name__
        == "IntervalTrigger"
    )
    assert jobs["creator_index_twitch_sync"].trigger.jitter == 60
    assert (
        jobs["top_categories_crawl"].trigger.__class__.__name__
        == "IntervalTrigger"
    )
    assert jobs["top_categories_crawl"].trigger.jitter == 60
    assert (
        jobs["steam_tag_backfill"].trigger.__class__.__name__
        == "IntervalTrigger"
    )
    assert jobs["steam_tag_backfill"].trigger.jitter == 60


# ---------------------------------------------------------------------------
# YouTube adapter error handling
# ---------------------------------------------------------------------------


def test_youtube_adapter_skips_missing_upload_playlist_items():
    adapter = YouTubeChannelAdapter("yt-test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            request=request,
            json={"error": {"code": 404, "message": "playlist not found"}},
        )

    async def run() -> dict[str, list[dict[str, object]]]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await adapter._fetch_uploads_for_channels(
                client,
                {"channel-1": "playlist-1"},
            )

    rows = asyncio.run(run())

    assert rows == {"channel-1": []}


def test_youtube_adapter_skips_failed_query_search():
    adapter = YouTubeChannelAdapter("yt-test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            request=request,
            json={"error": {"code": 500, "message": "server error"}},
        )

    async def run() -> list[AccountSeedBundle]:
        transport = httpx.MockTransport(handler)
        original_client = httpx.AsyncClient

        def build_client(*args, **kwargs):
            kwargs["transport"] = transport
            return original_client(*args, **kwargs)

        httpx.AsyncClient = build_client  # type: ignore[assignment]
        try:
            return list(await adapter.discover_seed_accounts("strife", 5))
        finally:
            httpx.AsyncClient = original_client  # type: ignore[assignment]

    bundles = asyncio.run(run())

    assert bundles == []


# ---------------------------------------------------------------------------
# Persistence: _persist_bundles
# ---------------------------------------------------------------------------


def test_game_plays_observation_count_increments_on_repeated_sync(db_path):
    service = CreatorIndexService(db_path=db_path)
    bundle = _fake_twitch_bundle_for_game("tw-fleet-tactics", "Fleet Tactics")

    asyncio.run(service._persist_bundles("twitch", (bundle,)))
    asyncio.run(service._persist_bundles("twitch", (bundle,)))

    repo = CreatorIndexRepository(db_path)
    accounts = repo.list_source_accounts()
    assert len(accounts) == 1
    plays = repo.list_creator_games_played(accounts[0].account_id)

    assert {p.game_name_raw for p in plays} == {
        "Fleet Tactics",
        "Another Game",
    }
    assert all(p.observation_count == 2 for p in plays)
    assert len(plays) == 2


def test_language_persisted_from_twitch_profile(db_path):
    service = CreatorIndexService(db_path=db_path)
    bundle = _fake_twitch_bundle_for_game("tw-lang-test", "Lang Test")

    asyncio.run(service._persist_bundles("twitch", (bundle,)))

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT language FROM creator_profile_facets_latest"
        ).fetchone()

    assert row["language"] == "en"


def test_twitch_persists_compact_content_samples_but_keeps_observed_games(
    db_path,
):
    service = CreatorIndexService(db_path=db_path)
    bundle = AccountSeedBundle(
        account=SourceAccountSeed(
            external_id="tw-compact",
            handle_current="compact-tv",
            display_name_current="Compact TV",
            canonical_url="https://www.twitch.tv/compact-tv",
        ),
        platform_profile=TwitchProfileSeed(
            broadcaster_id="tw-compact",
            login="compact-tv",
            display_name="Compact TV",
            description=None,
            followers_count=100,
            viewer_count=25,
            recent_avg_live_viewers=None,
            recent_median_live_viewers=None,
            recent_avg_vod_views=200,
            recent_median_vod_views=200,
            streams_last_30d=2,
            language="en",
            games_played=("Live Game",),
            avatar_url=None,
            last_live_at="2026-03-24T10:00:00+00:00",
            fetched_at="2026-03-24T10:05:00+00:00",
            expires_at="2026-03-24T16:05:00+00:00",
        ),
        content_samples=(
            ContentSampleSeed(
                external_content_id="vod-1",
                content_type="vod",
                title_or_text="First VOD",
                body_text=None,
                url="https://www.twitch.tv/videos/1",
                thumbnail_url=None,
                published_at="2026-03-24T09:00:00+00:00",
                engagement_count=200,
                language="en",
                position_rank=0,
                fetched_at="2026-03-24T10:05:00+00:00",
                expires_at="2026-03-24T16:05:00+00:00",
            ),
            ContentSampleSeed(
                external_content_id="vod-2",
                content_type="vod",
                title_or_text="Second VOD",
                body_text=None,
                url="https://www.twitch.tv/videos/2",
                thumbnail_url=None,
                published_at="2026-03-24T08:00:00+00:00",
                engagement_count=100,
                language="en",
                position_rank=1,
                fetched_at="2026-03-24T10:05:00+00:00",
                expires_at="2026-03-24T16:05:00+00:00",
            ),
        ),
        observed_games=(
            ObservedGameSeed(game_name="Live Game"),
            ObservedGameSeed(game_name="Clip Game"),
            ObservedGameSeed(game_name="Archive Game"),
        ),
    )

    asyncio.run(service._persist_bundles("twitch", (bundle,)))

    with get_connection(db_path) as conn:
        sample_count = conn.execute(
            "SELECT COUNT(*) AS count FROM content_samples_latest"
        ).fetchone()["count"]
        game_rows = conn.execute(
            """
            SELECT game_name_raw
            FROM creator_games_played
            ORDER BY game_name_raw
            """
        ).fetchall()

    assert sample_count == 1
    assert [row["game_name_raw"] for row in game_rows] == [
        "Archive Game",
        "Clip Game",
        "Live Game",
    ]


def test_async_persisted_creator_becomes_rankable_prospect(db_path):
    from app.creator_index.discovery import EnrichedCreator
    from app.creator_index.stream_discovery import TwitchGame
    from app.games.models import CustomerGame
    from app.igdb.models import IGDBGame
    from app.igdb.repository import IGDBRepository
    from app.igdb.taxonomy import IGDBGenre
    from app.prospects.service import ProspectRankingService

    service = CreatorIndexService(db_path=db_path)
    creator = EnrichedCreator(
        bundle=AccountSeedBundle(
            account=SourceAccountSeed(
                external_id="tw-prospect",
                handle_current="prospect-tv",
                display_name_current="Prospect TV",
                canonical_url="https://www.twitch.tv/prospect-tv",
            ),
            platform_profile=TwitchProfileSeed(
                broadcaster_id="tw-prospect",
                login="prospect-tv",
                display_name="Prospect TV",
                description=None,
                followers_count=2500,
                viewer_count=150,
                recent_avg_live_viewers=None,
                recent_median_live_viewers=None,
                recent_avg_vod_views=400,
                recent_median_vod_views=400,
                streams_last_30d=3,
                language="en",
                games_played=(),
                avatar_url=None,
                last_live_at="2026-03-24T10:00:00+00:00",
                fetched_at="2026-03-24T10:05:00+00:00",
                expires_at="2026-03-24T16:05:00+00:00",
            ),
            content_samples=(),
            contact_points=(),
            observed_games=(
                ObservedGameSeed(
                    game_name="Slay the Spire",
                    platform_game_id="game-40477",
                ),
            ),
        ),
        source_game_name="Slay the Spire",
        source_igdb_game_id=40477,
    )

    async def fake_fetch_game(igdb_game_id: int) -> bool:
        IGDBRepository(db_path).upsert(
            IGDBGame(
                igdb_id=igdb_game_id,
                name="Slay the Spire",
                slug="slay-the-spire",
                summary=None,
                genre_ids=[IGDBGenre.STRATEGY],
                theme_ids=[],
                first_release_date=None,
                cover_url=None,
                platform_ids=[],
                platform_names=[],
                keyword_names=[],
            )
        )
        return True

    with (
        patch.object(
            service,
            "_fetch_twitch_games_by_ids",
            new=AsyncMock(
                return_value={
                    "game-40477": TwitchGame(
                        twitch_game_id="game-40477",
                        name="Slay the Spire",
                        box_art_url=None,
                        igdb_game_id="40477",
                    )
                }
            ),
        ),
        patch(
            "app.creator_index.service.IGDBSyncService.fetch_game",
            new=AsyncMock(side_effect=fake_fetch_game),
        ),
    ):
        asyncio.run(service._persist_enriched_creator(creator))

    game = CustomerGame(
        customer_game_id="cg-1",
        workspace_id="u-1",
        name="Test Strategy Game",
        summary=None,
        description="Test strategy game",
        website_url=None,
        status="active",
        slug="test-strategy-game",
        created_at="2026-03-24T10:00:00+00:00",
        updated_at="2026-03-24T10:00:00+00:00",
        igdb_genre_ids=[IGDBGenre.STRATEGY],
        igdb_theme_ids=[],
        igdb_game_mode_ids=[],
        igdb_player_perspective_ids=[],
        igdb_keyword_ids=[],
        similar_game_names=[],
        llm_similar_game_names=[],
    )

    prospects, total, _ = ProspectRankingService(db_path).rank_prospects(game)

    assert len(prospects) == 1
    assert prospects[0].profile.handle == "prospect-tv"
    assert prospects[0].coverage_score > 0


# ---------------------------------------------------------------------------
# Facets: unit-level tests for build_creator_profile_facets
# ---------------------------------------------------------------------------


def _make_twitch_profile(**overrides) -> TwitchProfileSeed:
    defaults = {
        "broadcaster_id": "tw-1",
        "login": "creator1",
        "display_name": "Creator One",
        "description": None,
        "followers_count": 100,
        "viewer_count": None,
        "recent_avg_live_viewers": None,
        "recent_median_live_viewers": None,
        "recent_avg_vod_views": None,
        "recent_median_vod_views": None,
        "streams_last_30d": 0,
        "language": "en",
        "games_played": (),
        "avatar_url": None,
        "last_live_at": None,
        "fetched_at": "2026-03-24T10:00:00+00:00",
        "expires_at": "2026-03-25T10:00:00+00:00",
    }
    return TwitchProfileSeed(**{**defaults, **overrides})


def test_facets_language_from_twitch_profile():
    profile = _make_twitch_profile(language="ja")
    facets = build_creator_profile_facets("twitch", profile, ())
    assert facets.language == "ja"


def test_facets_language_none_when_profile_and_samples_have_none():
    profile = _make_twitch_profile(language=None)
    facets = build_creator_profile_facets("twitch", profile, ())
    assert facets.language is None


def test_facets_games_played_passed_through():
    profile = _make_twitch_profile(games_played=("Elden Ring", "Dark Souls"))
    facets = build_creator_profile_facets("twitch", profile, ())
    assert facets.games_played == ("Elden Ring", "Dark Souls")


def test_bundle_from_records_extracts_games_from_clips():
    from app.creator_index.enrichment import (
        TwitchClipRecord,
        TwitchUser,
        bundle_from_records,
    )

    user = TwitchUser(
        user_id="111",
        login="streamer",
        display_name="Streamer",
        description="I play games",
        profile_image_url=None,
    )
    clips = [
        TwitchClipRecord(
            clip_id="c1",
            broadcaster_id="111",
            game_id="33214",
            title="clip1",
            view_count=100,
            created_at="2025-06-01T00:00:00Z",
            thumbnail_url=None,
            url=None,
            language="en",
        ),
        TwitchClipRecord(
            clip_id="c2",
            broadcaster_id="111",
            game_id="21779",
            title="clip2",
            view_count=200,
            created_at="2025-05-01T00:00:00Z",
            thumbnail_url=None,
            url=None,
            language="en",
        ),
    ]
    game_names = {"33214": "Fortnite", "21779": "League of Legends"}

    bundle = bundle_from_records(
        user=user,
        channel_info=None,
        stream=None,
        videos=[],
        clips=clips,
        clip_game_names=game_names,
        follower_total=1000,
    )

    assert bundle is not None
    observed_names = {og.game_name for og in bundle.observed_games}
    assert "Fortnite" in observed_names
    assert "League of Legends" in observed_names
    for og in bundle.observed_games:
        assert og.platform_game_id is not None


def test_bundle_from_records_deduplicates_clip_and_stream_games():
    """If a game appears in both the live stream and clips, it's deduplicated."""
    from app.creator_index.enrichment import (
        TwitchClipRecord,
        TwitchStreamRecord,
        TwitchUser,
        bundle_from_records,
    )

    user = TwitchUser(
        user_id="111",
        login="streamer",
        display_name="Streamer",
        description=None,
        profile_image_url=None,
    )
    stream = TwitchStreamRecord(
        user_id="111",
        game_id="33214",
        game_name="Fortnite",
        title="Live now!",
        tags=(),
        viewer_count=500,
        language="en",
        started_at="2025-06-15T10:00:00Z",
    )
    clips = [
        TwitchClipRecord(
            clip_id="c1",
            broadcaster_id="111",
            game_id="33214",
            title="clip",
            view_count=100,
            created_at="2025-06-01T00:00:00Z",
            thumbnail_url=None,
            url=None,
            language="en",
        ),
    ]
    game_names = {"33214": "Fortnite"}

    bundle = bundle_from_records(
        user=user,
        channel_info=None,
        stream=stream,
        videos=[],
        clips=clips,
        clip_game_names=game_names,
        follower_total=1000,
    )

    assert bundle is not None
    fortnite_obs = [
        og for og in bundle.observed_games if og.game_name == "Fortnite"
    ]
    assert len(fortnite_obs) == 1


def test_bundle_extracts_discord_from_profile_description():
    from app.creator_index.enrichment import (
        TwitchUser,
        bundle_from_records,
    )

    user = TwitchUser(
        user_id="111",
        login="streamer",
        display_name="Streamer",
        description="Business: biz@example.com | Discord: https://discord.gg/myserver",
        profile_image_url=None,
    )

    bundle = bundle_from_records(
        user=user,
        channel_info=None,
        stream=None,
        videos=[],
        follower_total=100,
    )

    assert bundle is not None
    types = {cp.contact_type for cp in bundle.contact_points}
    assert ContactType.EMAIL in types
    assert ContactType.DISCORD in types
    emails = [
        cp
        for cp in bundle.contact_points
        if cp.contact_type == ContactType.EMAIL
    ]
    assert emails[0].contact_value == "biz@example.com"
    discords = [
        cp
        for cp in bundle.contact_points
        if cp.contact_type == ContactType.DISCORD
    ]
    assert discords[0].contact_value == "https://discord.gg/myserver"
    assert discords[0].source_kind == "profile_description"


def test_bundle_extracts_contacts_from_vod_descriptions():
    from app.creator_index.enrichment import (
        TwitchUser,
        TwitchVideoRecord,
        bundle_from_records,
    )

    user = TwitchUser(
        user_id="111",
        login="streamer",
        display_name="Streamer",
        description=None,
        profile_image_url=None,
    )
    videos = [
        TwitchVideoRecord(
            video_id="v1",
            title="Stream VOD",
            description="Join my Discord https://discord.gg/vodserver and email me at vod@example.com",
            thumbnail_url=None,
            created_at="2025-06-01T00:00:00Z",
            view_count=100,
            url="https://www.twitch.tv/videos/v1",
            stream_id=None,
            language="en",
            game_id=None,
            game_name=None,
            video_type="archive",
            duration="1h30m",
        ),
    ]

    bundle = bundle_from_records(
        user=user,
        channel_info=None,
        stream=None,
        videos=videos,
        follower_total=100,
    )

    assert bundle is not None
    emails = [
        cp
        for cp in bundle.contact_points
        if cp.contact_type == ContactType.EMAIL
    ]
    discords = [
        cp
        for cp in bundle.contact_points
        if cp.contact_type == ContactType.DISCORD
    ]
    assert len(emails) == 1
    assert emails[0].contact_value == "vod@example.com"
    assert emails[0].source_kind == "video_description"
    assert len(discords) == 1
    assert discords[0].contact_value == "https://discord.gg/vodserver"
    assert discords[0].source_kind == "video_description"


def test_bundle_deduplicates_contacts_across_profile_and_vods():
    from app.creator_index.enrichment import (
        TwitchUser,
        TwitchVideoRecord,
        bundle_from_records,
    )

    user = TwitchUser(
        user_id="111",
        login="streamer",
        display_name="Streamer",
        description="biz@example.com https://discord.gg/myserver",
        profile_image_url=None,
    )
    videos = [
        TwitchVideoRecord(
            video_id="v1",
            title="VOD",
            description="biz@example.com https://discord.gg/myserver",
            thumbnail_url=None,
            created_at="2025-06-01T00:00:00Z",
            view_count=50,
            url="https://www.twitch.tv/videos/v1",
            stream_id=None,
            language="en",
            game_id=None,
            game_name=None,
            video_type="archive",
            duration="2h",
        ),
    ]

    bundle = bundle_from_records(
        user=user,
        channel_info=None,
        stream=None,
        videos=videos,
        follower_total=100,
    )

    assert bundle is not None
    emails = [
        cp
        for cp in bundle.contact_points
        if cp.contact_type == ContactType.EMAIL
    ]
    discords = [
        cp
        for cp in bundle.contact_points
        if cp.contact_type == ContactType.DISCORD
    ]
    # Each should appear only once despite being in both profile and VOD
    assert len(emails) == 1
    assert len(discords) == 1
    # Profile description takes priority
    assert emails[0].source_kind == "profile_description"
    assert discords[0].source_kind == "profile_description"


def test_facets_games_played_empty_for_youtube():
    profile = YouTubeChannelSeed(
        channel_id="yt-1",
        handle=None,
        display_name="Channel",
        description=None,
        subscriber_count=None,
        video_count=None,
        recent_avg_views=None,
        recent_median_views=None,
        uploads_last_30d=None,
        default_language="en",
        country=None,
        channel_created_at=None,
        avatar_url=None,
        uploads_playlist_id=None,
        last_upload_at=None,
        fetched_at="2026-03-24T10:00:00+00:00",
        expires_at="2026-03-25T10:00:00+00:00",
    )
    facets = build_creator_profile_facets("youtube", profile, ())
    assert facets.games_played == ()
    assert facets.language == "en"


# ---------------------------------------------------------------------------
# _extract_panel_contacts
# ---------------------------------------------------------------------------


def test_extract_panel_contacts_finds_email_in_description():
    from app.creator_index.enrichment import _extract_panel_contacts

    panels = [
        {
            "id": "1",
            "description": "Business Inquiries: biz@example.com",
            "linkURL": None,
        }
    ]
    contacts = _extract_panel_contacts(panels, "testuser", set(), set())
    emails = [c for c in contacts if c.contact_type == ContactType.EMAIL]
    assert len(emails) == 1
    assert emails[0].contact_value == "biz@example.com"
    assert emails[0].source_kind == "channel_panel"


def test_extract_panel_contacts_finds_discord_in_linkurl():
    from app.creator_index.enrichment import _extract_panel_contacts

    panels = [
        {
            "id": "2",
            "description": None,
            "linkURL": "https://discord.gg/mycommunity",
        }
    ]
    contacts = _extract_panel_contacts(panels, "testuser", set(), set())
    discords = [c for c in contacts if c.contact_type == ContactType.DISCORD]
    assert len(discords) == 1
    assert discords[0].contact_value == "https://discord.gg/mycommunity"


def test_extract_panel_contacts_deduplicates_across_panels():
    from app.creator_index.enrichment import _extract_panel_contacts

    panels = [
        {"id": "1", "description": "Email: same@example.com", "linkURL": None},
        {
            "id": "2",
            "description": "Contact: same@example.com",
            "linkURL": None,
        },
    ]
    contacts = _extract_panel_contacts(panels, "testuser", set(), set())
    emails = [c for c in contacts if c.contact_type == ContactType.EMAIL]
    assert len(emails) == 1


def test_extract_panel_contacts_handles_empty_panels():
    from app.creator_index.enrichment import _extract_panel_contacts

    assert _extract_panel_contacts([], "testuser", set(), set()) == []


def test_extract_panel_contacts_finds_both_email_and_discord():
    """GQL panels have description (markdown) and linkURL at top level."""
    from app.creator_index.enrichment import _extract_panel_contacts

    panels = [
        {
            "id": "1",
            "description": "Reach me at contact@streamer.tv",
            "linkURL": "https://discord.gg/streamer",
        }
    ]
    contacts = _extract_panel_contacts(panels, "testuser", set(), set())
    assert len(contacts) == 2


def test_bundle_from_records_includes_panel_contacts():
    from app.creator_index.enrichment import (
        TwitchUser,
        bundle_from_records,
    )

    user = TwitchUser(
        user_id="222",
        login="paneluser",
        display_name="PanelUser",
        description="No email in description",
        profile_image_url=None,
    )
    panels = [
        {
            "id": "1",
            "description": "Business: panel@example.com",
            "linkURL": "https://discord.gg/panelserver",
        }
    ]

    bundle = bundle_from_records(
        user=user,
        channel_info=None,
        stream=None,
        videos=[],
        follower_total=500,
        panels=panels,
    )

    assert bundle is not None
    emails = [
        cp
        for cp in bundle.contact_points
        if cp.contact_type == ContactType.EMAIL
    ]
    discords = [
        cp
        for cp in bundle.contact_points
        if cp.contact_type == ContactType.DISCORD
    ]
    assert len(emails) == 1
    assert emails[0].contact_value == "panel@example.com"
    assert emails[0].source_kind == "channel_panel"
    assert len(discords) == 1
    assert discords[0].source_kind == "channel_panel"
