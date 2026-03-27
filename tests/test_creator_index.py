"""Tests for the headless source-index crawler."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx

from app.creator_index.account_discovery import (
    CrawlPlatform,
    DiscoveredAccountBatch,
)
from app.creator_index.adapters.base import (
    AccountSeedAdapter,
    AccountSeedBundle,
    ContactPointSeed,
    ContentSampleSeed,
    SourceAccountSeed,
    TwitchProfileSeed,
    YouTubeChannelSeed,
)
from app.creator_index.adapters.twitch import TwitchAccountAdapter, _build_queries
from app.creator_index.adapters.youtube import YouTubeChannelAdapter
from app.creator_index.bootstrap import DEFAULT_CRAWL_SEEDS
from app.creator_index.facets import build_creator_profile_facets
from app.creator_index.models import PlatformSyncSummary
from app.creator_index.repository import CreatorIndexRepository
from app.creator_index.service import CreatorIndexService
from app.database import get_connection
from app.runtime import SourceRuntime
from app.scheduler.setup import create_scheduler


def test_twitch_query_builder_prefers_broad_game_and_genre_queries(
    db_path, registered_user
):
    from app.games.service import CustomerGameService
    from app.games.repository import CustomerGameRepository

    service = CustomerGameService(CustomerGameRepository(db_path))
    game = service.create_game(
        user_id=registered_user.user_id,
        name="Strife Of Stars",
        description="Space tactics game.",
        website_url=None,
        summary="Space tactics.",
        igdb_genre_ids=[12, 15],
        igdb_theme_ids=[18],
    )

    queries = _build_queries(game)

    assert "Strife Of Stars" in queries
    assert "Role-playing (RPG)" in queries
    assert "Strategy" in queries
    assert "Role-playing (RPG) Strategy" not in queries
    assert all(
        "streamer" not in query.casefold()
        and "playthrough" not in query.casefold()
        and " live" not in query.casefold()
        for query in queries
    )


def test_parse_clip_record_extracts_game_id_and_view_count():
    from app.creator_index.adapters.twitch import _parse_clip_record

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
    from app.creator_index.adapters.twitch import _parse_clip_record

    assert _parse_clip_record({"title": "no id"}) is None


def test_parse_clip_record_returns_none_for_missing_game_id():
    from app.creator_index.adapters.twitch import _parse_clip_record

    assert _parse_clip_record({"id": "c1", "title": "t"}) is None


import pytest


@pytest.mark.anyio
async def test_fetch_clips_returns_clip_records(monkeypatch):
    """Adapter fetches clips for each broadcaster, returning TwitchClipRecords."""
    from app.creator_index.adapters.twitch import TwitchAccountAdapter, TwitchClipRecord

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

    async def fake_request(client, method, url, *, params=None, headers=None):
        return clip_data

    monkeypatch.setattr(
        "app.creator_index.adapters.twitch.twitch_request_json", fake_request
    )

    adapter = TwitchAccountAdapter("cid", "csecret")
    import httpx
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": "Bearer fake", "Client-Id": "cid"}
        result = await adapter._fetch_clips_for_users(
            client, headers, ["111"]
        )

    assert "111" in result
    assert len(result["111"]) == 1
    assert isinstance(result["111"][0], TwitchClipRecord)
    assert result["111"][0].game_id == "33214"


@pytest.mark.anyio
async def test_resolve_game_names_maps_twitch_ids_to_names(monkeypatch):
    from app.creator_index.adapters.twitch import TwitchAccountAdapter

    games_response = {
        "data": [
            {"id": "33214", "name": "Fortnite", "box_art_url": None},
            {"id": "21779", "name": "League of Legends", "box_art_url": None},
        ]
    }

    async def fake_request(client, method, url, *, params=None, headers=None):
        return games_response

    monkeypatch.setattr(
        "app.creator_index.adapters.twitch.twitch_request_json", fake_request
    )

    adapter = TwitchAccountAdapter("cid", "csecret")
    import httpx
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": "Bearer fake", "Client-Id": "cid"}
        result = await adapter._resolve_game_names(
            client, headers, {"33214", "21779"}
        )

    assert result["33214"] == "Fortnite"
    assert result["21779"] == "League of Legends"


def _record_call(
    calls: list[tuple[str, int, dict[str, str]]],
    *,
    scope_key: str,
    limit: int,
    page_cursors: dict[str, str] | None,
    cursor_key: str,
) -> None:
    cursors = page_cursors if page_cursors is not None else {}
    calls.append((scope_key, limit, dict(cursors)))
    cursors[cursor_key] = f"cursor:{scope_key}"


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
                contact_type="email",
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
                raw_payload_json, last_synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                igdb_game_id,
                name,
                name.casefold().replace(" ", "-"),
                None,
                None,
                "[]",
                "[]",
                "{}",
                "2026-01-01T00:00:00+00:00",
            ),
        )


class _FakeTwitchAdapter(AccountSeedAdapter):
    platform = "twitch"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, dict[str, str]]] = []

    @classmethod
    def build(cls, runtime: SourceRuntime) -> _FakeTwitchAdapter:
        del runtime
        return cls()

    async def discover_game_accounts(
        self,
        customer_game,
        limit: int,
        *,
        page_cursors: dict[str, str] | None = None,
        skip_external_ids: frozenset[str] = frozenset(),
    ):
        del skip_external_ids
        _record_call(
            self.calls,
            scope_key=customer_game.customer_game_id,
            limit=limit,
            page_cursors=page_cursors,
            cursor_key="search:twitch",
        )
        return [
            AccountSeedBundle(
                account=SourceAccountSeed(
                    external_id=f"tw-{customer_game.customer_game_id}",
                    handle_current=f"{customer_game.slug}-tv",
                    display_name_current=f"{customer_game.name} TV",
                    canonical_url=f"https://www.twitch.tv/{customer_game.slug}-tv",
                ),
                platform_profile=TwitchProfileSeed(
                    broadcaster_id=f"tw-{customer_game.customer_game_id}",
                    login=f"{customer_game.slug}-tv",
                    display_name=f"{customer_game.name} TV",
                    description="Email me at creator@example.com",
                    followers_count=1200,
                    viewer_count=88,
                    recent_avg_live_viewers=None,
                    recent_median_live_viewers=None,
                    recent_avg_vod_views=250,
                    recent_median_vod_views=250,
                    streams_last_30d=1,
                    language="en",
                    games_played=(customer_game.name, "Another Game"),
                    avatar_url="https://static.example/avatar.png",
                    last_live_at="2026-03-24T10:00:00+00:00",
                    fetched_at="2026-03-24T10:05:00+00:00",
                    expires_at="2026-03-24T16:05:00+00:00",
                ),
                content_samples=(
                    ContentSampleSeed(
                        external_content_id=f"vod-{customer_game.customer_game_id}",
                        content_type="vod",
                        title_or_text=f"{customer_game.name} first look",
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
                        contact_type="email",
                        contact_value="creator@example.com",
                        source_kind="profile_description",
                        source_url="https://www.twitch.tv/example/about",
                    ),
                ),
            )
        ]

    async def discover_seed_accounts(
        self,
        query_text: str,
        limit: int,
        *,
        page_cursors: dict[str, str] | None = None,
        skip_external_ids: frozenset[str] = frozenset(),
    ):
        del skip_external_ids
        _record_call(
            self.calls,
            scope_key=query_text,
            limit=limit,
            page_cursors=page_cursors,
            cursor_key=f"search:{query_text}",
        )
        return [
            AccountSeedBundle(
                account=SourceAccountSeed(
                    external_id=f"tw-seed-{query_text}",
                    handle_current=f"seed-{query_text}",
                    display_name_current=f"Seed {query_text}",
                    canonical_url="https://www.twitch.tv/seed",
                ),
                platform_profile=TwitchProfileSeed(
                    broadcaster_id=f"tw-seed-{query_text}",
                    login=f"seed-{query_text}",
                    display_name=f"Seed {query_text}",
                    description=None,
                    followers_count=500,
                    viewer_count=25,
                    recent_avg_live_viewers=None,
                    recent_median_live_viewers=None,
                    recent_avg_vod_views=None,
                    recent_median_vod_views=None,
                    streams_last_30d=0,
                    language="en",
                    games_played=(),
                    avatar_url=None,
                    last_live_at="2026-03-24T11:00:00+00:00",
                    fetched_at="2026-03-24T11:05:00+00:00",
                    expires_at="2026-03-24T17:05:00+00:00",
                ),
            )
        ]


class _FakeYouTubeAdapter(AccountSeedAdapter):
    platform = "youtube"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, dict[str, str]]] = []

    @classmethod
    def build(cls, runtime: SourceRuntime) -> _FakeYouTubeAdapter:
        del runtime
        return cls()

    async def discover_game_accounts(
        self,
        customer_game,
        limit: int,
        *,
        page_cursors: dict[str, str] | None = None,
        skip_external_ids: frozenset[str] = frozenset(),
    ):
        del skip_external_ids
        _record_call(
            self.calls,
            scope_key=customer_game.customer_game_id,
            limit=limit,
            page_cursors=page_cursors,
            cursor_key="search:youtube",
        )
        return [
            AccountSeedBundle(
                account=SourceAccountSeed(
                    external_id=f"yt-{customer_game.customer_game_id}",
                    handle_current=f"{customer_game.slug}-yt",
                    display_name_current=f"{customer_game.name} Plays",
                    canonical_url=f"https://www.youtube.com/channel/yt-{customer_game.customer_game_id}",
                ),
                platform_profile=YouTubeChannelSeed(
                    channel_id=f"yt-{customer_game.customer_game_id}",
                    handle=f"@{customer_game.slug}",
                    display_name=f"{customer_game.name} Plays",
                    description="Videos about tactics indies",
                    subscriber_count=3400,
                    video_count=128,
                    recent_avg_views=4200,
                    recent_median_views=3800,
                    uploads_last_30d=6,
                    default_language="en",
                    country=None,
                    channel_created_at=None,
                    avatar_url="https://img.example/avatar.jpg",
                    uploads_playlist_id=f"uu-{customer_game.customer_game_id}",
                    last_upload_at="2026-03-23T12:00:00+00:00",
                    fetched_at="2026-03-24T10:15:00+00:00",
                    expires_at="2026-03-25T10:15:00+00:00",
                ),
                content_samples=(
                    ContentSampleSeed(
                        external_content_id=f"video-a-{customer_game.customer_game_id}",
                        content_type="video",
                        title_or_text=f"{customer_game.name} review",
                        body_text="Long-form review",
                        url="https://www.youtube.com/watch?v=a",
                        thumbnail_url="https://img.example/a.jpg",
                        published_at="2026-03-22T12:00:00+00:00",
                        engagement_count=None,
                        language=None,
                        position_rank=0,
                        fetched_at="2026-03-24T10:15:00+00:00",
                        expires_at="2026-03-25T10:15:00+00:00",
                    ),
                    ContentSampleSeed(
                        external_content_id=f"video-b-{customer_game.customer_game_id}",
                        content_type="video",
                        title_or_text=f"{customer_game.name} gameplay",
                        body_text="Gameplay preview",
                        url="https://www.youtube.com/watch?v=b",
                        thumbnail_url="https://img.example/b.jpg",
                        published_at="2026-03-21T12:00:00+00:00",
                        engagement_count=None,
                        language=None,
                        position_rank=1,
                        fetched_at="2026-03-24T10:15:00+00:00",
                        expires_at="2026-03-25T10:15:00+00:00",
                    ),
                ),
            )
        ]

    async def discover_seed_accounts(
        self,
        query_text: str,
        limit: int,
        *,
        page_cursors: dict[str, str] | None = None,
        skip_external_ids: frozenset[str] = frozenset(),
    ):
        del skip_external_ids
        _record_call(
            self.calls,
            scope_key=query_text,
            limit=limit,
            page_cursors=page_cursors,
            cursor_key=f"search:{query_text}",
        )
        return [
            AccountSeedBundle(
                account=SourceAccountSeed(
                    external_id=f"yt-seed-{query_text}",
                    handle_current=f"seed-{query_text}",
                    display_name_current=f"Seed {query_text}",
                    canonical_url="https://www.youtube.com/channel/seed",
                ),
                platform_profile=YouTubeChannelSeed(
                    channel_id=f"yt-seed-{query_text}",
                    handle="@seed",
                    display_name=f"Seed {query_text}",
                    description=None,
                    subscriber_count=1500,
                    video_count=64,
                    recent_avg_views=2100,
                    recent_median_views=1800,
                    uploads_last_30d=4,
                    default_language=None,
                    country=None,
                    channel_created_at=None,
                    avatar_url=None,
                    uploads_playlist_id="uu-seed",
                    last_upload_at="2026-03-23T12:00:00+00:00",
                    fetched_at="2026-03-24T10:15:00+00:00",
                    expires_at="2026-03-25T10:15:00+00:00",
                ),
            )
        ]


class _FailingYouTubeAdapter(AccountSeedAdapter):
    platform = "youtube"

    @classmethod
    def build(cls, runtime: SourceRuntime) -> _FailingYouTubeAdapter:
        del runtime
        return cls()

    async def discover_game_accounts(
        self,
        customer_game,
        limit: int,
        *,
        page_cursors: dict[str, str] | None = None,
        skip_external_ids: frozenset[str] = frozenset(),
    ):
        del customer_game, limit, page_cursors, skip_external_ids
        raise RuntimeError("youtube adapter boom")

    async def discover_seed_accounts(
        self,
        query_text: str,
        limit: int,
        *,
        page_cursors: dict[str, str] | None = None,
        skip_external_ids: frozenset[str] = frozenset(),
    ):
        del query_text, limit, page_cursors, skip_external_ids
        raise RuntimeError("youtube adapter boom")


def test_creator_index_sync_persists_platform_rows_and_cursors(
    db_path, game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Fleet Tactics",
        summary="Turn-based fleet combat.",
        description="Turn-based fleet combat.",
        website_url=None,
        igdb_genre_ids=[12, 24],  # Strategy, Tactical
    )
    _insert_test_igdb_game(db_path, 296831, "Slay the Spire II")
    youtube = _FakeYouTubeAdapter()
    service = CreatorIndexService(
        db_path=db_path,
        adapters={
            "youtube": youtube,
        },
    )
    twitch_batch = DiscoveredAccountBatch(
        platform=CrawlPlatform.TWITCH,
        bundles=(
            _fake_twitch_bundle_for_game(
                f"tw-{game.customer_game_id}", game.name
            ),
        ),
        igdb_game_id=296831,
    )

    with patch.object(
        service,
        "_select_igdb_game_for_customer_game",
        return_value=296831,
    ), patch.object(
        service,
        "discover_account_bundles",
        new=AsyncMock(return_value=twitch_batch),
    ):
        summary = asyncio.run(
            service.sync_customer_game(
                game,
                platforms=("twitch", "youtube"),
                limit_per_platform=5,
            )
        )

    assert summary.accounts_synced == 2
    assert summary.content_samples_synced == 3
    assert summary.contact_points_synced == 1

    with get_connection(db_path) as conn:
        source_accounts = conn.execute(
            """
            SELECT platform, external_id, display_name_current, canonical_url
            FROM source_accounts
            ORDER BY platform
            """
        ).fetchall()
        twitch_row = conn.execute(
            """
            SELECT followers_count, viewer_count, recent_avg_live_viewers,
                   recent_median_live_viewers, recent_avg_vod_views,
                   recent_median_vod_views, streams_last_30d
            FROM twitch_profiles_latest
            """
        ).fetchone()
        youtube_row = conn.execute(
            """
            SELECT subscriber_count, video_count, recent_avg_views,
                   recent_median_views, uploads_last_30d
            FROM youtube_channels_latest
            """
        ).fetchone()
        samples_count = conn.execute(
            "SELECT COUNT(*) AS count FROM content_samples_latest"
        ).fetchone()["count"]
        contacts_count = conn.execute(
            "SELECT COUNT(*) AS count FROM contact_points"
        ).fetchone()["count"]
        facet_rows = conn.execute(
            """
            SELECT platform, summary_text, genre_tags_json, interest_tags_json,
                   language, last_activity_at
            FROM creator_profile_facets_latest
            ORDER BY platform
            """
        ).fetchall()
        game_play_rows = conn.execute(
            """
            SELECT game_name_raw, game_name_key, platform, observation_count
            FROM creator_games_played
            ORDER BY game_name_key
            """
        ).fetchall()
        jobs = conn.execute(
            "SELECT platform, status FROM crawl_jobs ORDER BY platform"
        ).fetchall()
        cursors = conn.execute(
            """
            SELECT platform, cursor_scope, cursor_key, cursor_value
            FROM crawl_cursors
            ORDER BY platform
            """
        ).fetchall()

    assert [
        (
            row["platform"],
            row["external_id"],
            row["display_name_current"],
            row["canonical_url"],
        )
        for row in source_accounts
    ] == [
        (
            "twitch",
            f"tw-{game.customer_game_id}",
            f"{game.name} TV",
            f"https://www.twitch.tv/tw-{game.customer_game_id}-tv",
        ),
        (
            "youtube",
            f"yt-{game.customer_game_id}",
            f"{game.name} Plays",
            f"https://www.youtube.com/channel/yt-{game.customer_game_id}",
        ),
    ]
    assert twitch_row["followers_count"] == 1200
    assert twitch_row["viewer_count"] == 88
    assert twitch_row["recent_avg_live_viewers"] == 88
    assert twitch_row["recent_median_live_viewers"] == 88
    assert twitch_row["recent_avg_vod_views"] == 250
    assert twitch_row["recent_median_vod_views"] == 250
    assert twitch_row["streams_last_30d"] == 1
    assert youtube_row["subscriber_count"] == 3400
    assert youtube_row["video_count"] == 128
    assert youtube_row["recent_avg_views"] == 4200
    assert youtube_row["recent_median_views"] == 3800
    assert youtube_row["uploads_last_30d"] == 6
    assert samples_count == 3
    assert contacts_count == 1
    assert [row["platform"] for row in facet_rows] == ["twitch", "youtube"]
    assert all(row["summary_text"] for row in facet_rows)
    assert [row["language"] for row in facet_rows] == ["en", "en"]
    assert [row["last_activity_at"] for row in facet_rows] == [
        "2026-03-24T10:00:00+00:00",
        "2026-03-23T12:00:00+00:00",
    ]
    # Games played: Twitch fake returns (game.name, "Another Game") for the creator.
    assert len(game_play_rows) == 2
    assert {row["platform"] for row in game_play_rows} == {"twitch"}
    assert {row["game_name_raw"] for row in game_play_rows} == {
        game.name,
        "Another Game",
    }
    assert all(
        row["observation_count"] == 1 for row in game_play_rows
    )
    assert [(row["platform"], row["status"]) for row in jobs] == [
        ("youtube", "completed"),
    ]
    assert [(row["platform"], row["cursor_key"]) for row in cursors] == [
        ("youtube", "search:youtube"),
    ]
    assert {row["cursor_scope"] for row in cursors} == {
        f"customer_game:{game.customer_game_id}"
    }


def test_creator_index_sync_active_customer_games_uses_all_active_games(
    db_path, game_service, registered_user
):
    game_service.create_game(
        user_id=registered_user.user_id,
        name="Fleet Tactics",
        summary="Turn-based fleet combat.",
        description="Turn-based fleet combat.",
        website_url=None,
        igdb_genre_ids=[12, 24],  # Strategy, Tactical
    )
    game_service.create_game(
        user_id=registered_user.user_id,
        name="Dungeon Garden",
        summary="Gardening roguelite.",
        description="Gardening roguelite.",
        website_url=None,
        igdb_genre_ids=[12],  # Strategy (placeholder)
    )
    service = CreatorIndexService(db_path=db_path)

    with patch.object(
        service,
        "_select_igdb_game_for_customer_game",
        side_effect=[296831, 119133],
    ), patch.object(
        service,
        "run_entrypoint",
        new=AsyncMock(
            return_value=PlatformSyncSummary(
                platform="twitch",
                accounts_synced=1,
                content_samples_synced=0,
                contact_points_synced=0,
            )
        ),
    ) as mock_run_entrypoint:
        summary = asyncio.run(
            service.sync_active_customer_games(
                platforms=("twitch",), limit_per_platform=2
            )
        )

    assert summary.games_seen == 2
    assert summary.accounts_synced == 2
    assert mock_run_entrypoint.await_count == 2


def test_creator_index_sync_active_customer_games_can_filter_by_name(
    db_path, game_service, registered_user
):
    game_service.create_game(
        user_id=registered_user.user_id,
        name="Fleet Tactics",
        summary="Turn-based fleet combat.",
        description="Turn-based fleet combat.",
        website_url=None,
        igdb_genre_ids=[12, 24],  # Strategy, Tactical
    )
    strife = game_service.create_game(
        user_id=registered_user.user_id,
        name="Strife Of Stars",
        summary="Squad tactics in deep space.",
        description="Squad tactics in deep space.",
        website_url=None,
        igdb_genre_ids=[12, 24],  # Strategy, Tactical
        igdb_theme_ids=[18],      # Sci-fi
    )
    service = CreatorIndexService(
        db_path=db_path,
        active_game_names=("Strife Of Stars",),
    )

    with patch.object(
        service,
        "_select_igdb_game_for_customer_game",
        side_effect=lambda game: 296831
        if game.customer_game_id == strife.customer_game_id
        else None,
    ), patch.object(
        service,
        "run_entrypoint",
        new=AsyncMock(
            return_value=PlatformSyncSummary(
                platform="twitch",
                accounts_synced=1,
                content_samples_synced=0,
                contact_points_synced=0,
            )
        ),
    ) as mock_run_entrypoint:
        summary = asyncio.run(
            service.sync_active_customer_games(
                platforms=("twitch",), limit_per_platform=2
            )
        )

    assert summary.games_seen == 1
    assert summary.accounts_synced == 1
    assert mock_run_entrypoint.await_count == 1


def test_creator_index_sync_customer_game_keeps_other_platforms_when_one_fails(
    db_path, game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Fleet Tactics",
        summary="Turn-based fleet combat.",
        description="Turn-based fleet combat.",
        website_url=None,
        igdb_genre_ids=[12, 24],  # Strategy, Tactical
    )
    _insert_test_igdb_game(db_path, 296831, "Slay the Spire II")
    service = CreatorIndexService(
        db_path=db_path,
        adapters={
            "youtube": _FailingYouTubeAdapter(),
        },
    )

    with patch.object(
        service,
        "_select_igdb_game_for_customer_game",
        return_value=296831,
    ), patch.object(
        service,
        "run_entrypoint",
        new=AsyncMock(
            return_value=PlatformSyncSummary(
                platform="twitch",
                accounts_synced=1,
                content_samples_synced=1,
                contact_points_synced=1,
            )
        ),
    ):
        summary = asyncio.run(
            service.sync_customer_game(
                game,
                platforms=("twitch", "youtube"),
                limit_per_platform=5,
            )
        )

    assert summary.accounts_synced == 1
    assert summary.content_samples_synced == 1
    assert summary.contact_points_synced == 1
    assert [
        (item.platform, item.skipped_reason)
        for item in summary.platform_summaries
    ] == [
        ("twitch", None),
        ("youtube", "sync_failed"),
    ]

    with get_connection(db_path) as conn:
        jobs = conn.execute(
            "SELECT platform, status FROM crawl_jobs ORDER BY platform"
        ).fetchall()

    assert [(row["platform"], row["status"]) for row in jobs] == [
        ("youtube", "failed"),
    ]


def test_creator_index_sync_bootstrap_seeds_works_without_games(db_path):
    twitch = _FakeTwitchAdapter()
    service = CreatorIndexService(
        db_path=db_path,
        adapters={"twitch": twitch},
    )

    from unittest.mock import AsyncMock, patch

    fake_summary = PlatformSyncSummary(
        platform="twitch",
        accounts_synced=1,
        content_samples_synced=0,
        contact_points_synced=0,
    )
    with patch.object(
        service, "sync_crawl_seed", new=AsyncMock(return_value=fake_summary)
    ) as mock_sync_crawl_seed:
        summary = asyncio.run(
            service.sync_bootstrap_seeds(
                platforms=("twitch",),
                limit_per_platform=2,
            )
        )

    expected_seed_count = sum(
        1
        for platform, _query_text, _weight in DEFAULT_CRAWL_SEEDS
        if platform == "twitch"
    )
    assert summary.seeds_seen == expected_seed_count
    assert summary.accounts_synced == expected_seed_count
    assert twitch.calls == []
    assert mock_sync_crawl_seed.await_count == expected_seed_count

    with get_connection(db_path) as conn:
        seed_rows = conn.execute(
            "SELECT platform, query_text, last_synced_at FROM crawl_seeds ORDER BY weight DESC"
        ).fetchall()

    assert len(seed_rows) == len(DEFAULT_CRAWL_SEEDS)
    assert all(
        row["last_synced_at"]
        for row in seed_rows
        if row["platform"] == "twitch"
    )


def test_creator_index_sync_bootstrap_seeds_can_be_disabled(db_path):
    twitch = _FakeTwitchAdapter()
    service = CreatorIndexService(
        db_path=db_path,
        adapters={"twitch": twitch},
        bootstrap_seeds_enabled=False,
    )

    summary = asyncio.run(
        service.sync_bootstrap_seeds(
            platforms=("twitch",),
            limit_per_platform=2,
        )
    )

    assert summary.seeds_seen == 0
    assert summary.accounts_synced == 0
    assert twitch.calls == []

    with get_connection(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM crawl_seeds"
        ).fetchone()["count"]

    assert count == 0


def test_create_scheduler_registers_creator_index_jobs(db_path):
    scheduler = create_scheduler(db_path, SourceRuntime())

    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert set(jobs) == {
        "creator_index_startup_sync",
        "creator_index_twitch_sync",
    }
    assert (
        jobs["creator_index_twitch_sync"].trigger.__class__.__name__
        == "IntervalTrigger"
    )
    assert jobs["creator_index_twitch_sync"].trigger.jitter == 120


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


def test_twitch_adapter_skips_failed_query_search():
    adapter = TwitchAccountAdapter("client-id", "client-secret")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "id.twitch.tv":
            return httpx.Response(
                200,
                request=request,
                json={"access_token": "token"},
            )
        return httpx.Response(
            500,
            request=request,
            json={"error": "server error"},
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
# Game plays: observation_count increments on repeated syncs
# ---------------------------------------------------------------------------


def test_game_plays_observation_count_increments_on_repeated_sync(
    db_path, game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Fleet Tactics",
        summary="Turn-based fleet combat.",
        description="Turn-based fleet combat.",
        website_url=None,
        igdb_genre_ids=[12, 24],  # Strategy, Tactical
    )
    _insert_test_igdb_game(db_path, 296831, "Slay the Spire II")
    service = CreatorIndexService(db_path=db_path)
    batch = DiscoveredAccountBatch(
        platform=CrawlPlatform.TWITCH,
        bundles=(
            _fake_twitch_bundle_for_game("tw-fleet-tactics", game.name),
        ),
        igdb_game_id=296831,
    )

    with patch.object(
        service,
        "_select_igdb_game_for_customer_game",
        return_value=296831,
    ), patch.object(
        service,
        "discover_account_bundles",
        new=AsyncMock(return_value=batch),
    ):
        asyncio.run(
            service.sync_customer_game(
                game, platforms=("twitch",), limit_per_platform=5
            )
        )
        asyncio.run(
            service.sync_customer_game(
                game, platforms=("twitch",), limit_per_platform=5
            )
        )

    repo = CreatorIndexRepository(db_path)
    accounts = repo.list_source_accounts()
    assert len(accounts) == 1
    plays = repo.list_creator_games_played(accounts[0].account_id)

    assert {p.game_name_raw for p in plays} == {game.name, "Another Game"}
    assert all(p.observation_count == 2 for p in plays)
    assert len(plays) == 2


# ---------------------------------------------------------------------------
# Language: persisted in creator_profile_facets_latest
# ---------------------------------------------------------------------------


def test_language_persisted_from_twitch_profile(
    db_path, game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Fleet Tactics",
        summary="Turn-based fleet combat.",
        description="Turn-based fleet combat.",
        website_url=None,
        igdb_genre_ids=[12, 24],  # Strategy, Tactical
    )
    _insert_test_igdb_game(db_path, 296831, "Slay the Spire II")
    service = CreatorIndexService(db_path=db_path)
    batch = DiscoveredAccountBatch(
        platform=CrawlPlatform.TWITCH,
        bundles=(
            _fake_twitch_bundle_for_game("tw-fleet-tactics", game.name),
        ),
        igdb_game_id=296831,
    )
    with patch.object(
        service,
        "_select_igdb_game_for_customer_game",
        return_value=296831,
    ), patch.object(
        service,
        "discover_account_bundles",
        new=AsyncMock(return_value=batch),
    ):
        asyncio.run(
            service.sync_customer_game(
                game, platforms=("twitch",), limit_per_platform=5
            )
        )

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT language FROM creator_profile_facets_latest"
        ).fetchone()

    # Fake Twitch adapter returns language="en" in the profile.
    assert row["language"] == "en"


def test_language_derived_from_video_samples_when_channel_has_none(
    db_path, game_service, registered_user
):
    """YouTube channels rarely set defaultLanguage; fall back to video audio languages."""
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Fleet Tactics",
        summary="Turn-based fleet combat.",
        description="Turn-based fleet combat.",
        website_url=None,
        igdb_genre_ids=[12, 24],  # Strategy, Tactical
    )

    class _YouTubeWithVideoLanguages(AccountSeedAdapter):
        platform = "youtube"

        @classmethod
        def build(cls, runtime: SourceRuntime) -> _YouTubeWithVideoLanguages:
            del runtime
            return cls()

        async def discover_game_accounts(
            self,
            customer_game,
            limit,
            *,
            page_cursors=None,
            skip_external_ids: frozenset[str] = frozenset(),
        ):
            del customer_game, limit, page_cursors, skip_external_ids
            return [
                AccountSeedBundle(
                    account=SourceAccountSeed(
                        external_id="yt-lang-test",
                        handle_current="lang-test",
                        display_name_current="Lang Test",
                        canonical_url="https://www.youtube.com/channel/yt-lang-test",
                    ),
                    platform_profile=YouTubeChannelSeed(
                        channel_id="yt-lang-test",
                        handle=None,
                        display_name="Lang Test",
                        description=None,
                        subscriber_count=500,
                        video_count=10,
                        recent_avg_views=None,
                        recent_median_views=None,
                        uploads_last_30d=2,
                        default_language=None,  # channel has no explicit language
                        country=None,
                        channel_created_at=None,
                        avatar_url=None,
                        uploads_playlist_id=None,
                        last_upload_at="2026-03-20T10:00:00+00:00",
                        fetched_at="2026-03-24T10:00:00+00:00",
                        expires_at="2026-03-25T10:00:00+00:00",
                    ),
                    content_samples=(
                        ContentSampleSeed(
                            external_content_id="v1",
                            content_type="video",
                            title_or_text="Video one",
                            body_text=None,
                            url=None,
                            thumbnail_url=None,
                            published_at="2026-03-20T10:00:00+00:00",
                            engagement_count=None,
                            language="de",
                            position_rank=0,
                            fetched_at="2026-03-24T10:00:00+00:00",
                            expires_at="2026-03-25T10:00:00+00:00",
                        ),
                        ContentSampleSeed(
                            external_content_id="v2",
                            content_type="video",
                            title_or_text="Video two",
                            body_text=None,
                            url=None,
                            thumbnail_url=None,
                            published_at="2026-03-19T10:00:00+00:00",
                            engagement_count=None,
                            language="de",
                            position_rank=1,
                            fetched_at="2026-03-24T10:00:00+00:00",
                            expires_at="2026-03-25T10:00:00+00:00",
                        ),
                    ),
                )
            ]

        async def discover_seed_accounts(
            self,
            query_text,
            limit,
            *,
            page_cursors=None,
            skip_external_ids: frozenset[str] = frozenset(),
        ):
            del query_text, limit, page_cursors, skip_external_ids
            return []

    service = CreatorIndexService(
        db_path=db_path,
        adapters={"youtube": _YouTubeWithVideoLanguages()},
    )
    asyncio.run(
        service.sync_customer_game(
            game, platforms=("youtube",), limit_per_platform=5
        )
    )

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT language FROM creator_profile_facets_latest"
        ).fetchone()

    # Both videos are "de", so dominant language should be "de".
    assert row["language"] == "de"


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
    from app.creator_index.adapters.twitch import (
        TwitchSearchChannel,
        TwitchUser,
        TwitchClipRecord,
        _bundle_from_records,
    )

    channel = TwitchSearchChannel(
        broadcaster_id="111",
        broadcaster_login="streamer",
        display_name="Streamer",
        title=None,
        thumbnail_url=None,
        broadcaster_language="en",
        game_id=None,
        game_name=None,
        tags=(),
        is_live=False,
        started_at=None,
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

    bundle = _bundle_from_records(
        channel=channel,
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
    from app.creator_index.adapters.twitch import (
        TwitchSearchChannel,
        TwitchUser,
        TwitchStreamRecord,
        TwitchClipRecord,
        _bundle_from_records,
    )

    channel = TwitchSearchChannel(
        broadcaster_id="111",
        broadcaster_login="streamer",
        display_name="Streamer",
        title=None,
        thumbnail_url=None,
        broadcaster_language="en",
        game_id=None,
        game_name=None,
        tags=(),
        is_live=True,
        started_at="2025-06-15T10:00:00Z",
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

    bundle = _bundle_from_records(
        channel=channel,
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
