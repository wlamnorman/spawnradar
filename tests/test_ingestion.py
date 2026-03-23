"""Tests for ingestion source wiring and Bluesky normalization."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx

from app.database import get_connection
from app.ingestion.base import CandidateRecord, SourceRuntime
from app.ingestion.pipeline import _resolve_source_name, run_ingestion
from app.ingestion.query_builder import SourceTags, TaggedQuery
from app.ingestion.registry import Source, available_sources
from app.ingestion.service import DiscoveryRunService
from app.ingestion.sources.bluesky import (
    BlueskySource,
    _fetch_recent_posts,
    _parse_actor,
)
from app.ingestion.sources.twitch import (
    TwitchSource,
    _candidate_from_search_result,
)
from app.ingestion.sources.youtube import _parse_subscriber_count
from app.prospects.presenter import ReviewQueuePresenter
from app.prospects.repository import DraftItemRepository, OutcomeRepository
from app.prospects.service import ProspectService
from app.scoring.llm_engine import LLMFitScores


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeClient:
    def __init__(
        self,
        feed_payload: dict[str, object],
        profile_payload: dict[str, object] | None = None,
    ) -> None:
        self._feed_payload = feed_payload
        self._profile_payload = profile_payload or {}

    async def get(
        self,
        url: str,
        *,
        params: object | None = None,
        **kwargs: object,
    ) -> _FakeResponse:
        del params, kwargs
        if url.endswith("app.bsky.actor.getProfile"):
            return _FakeResponse(self._profile_payload)
        return _FakeResponse(self._feed_payload)


class _FakeTwitchClient:
    def __init__(self, follower_totals: dict[str, int]) -> None:
        self._follower_totals = follower_totals

    async def get(
        self,
        url: str,
        *,
        params: object | None = None,
        **kwargs: object,
    ) -> _FakeResponse:
        del kwargs
        broadcaster_id = None
        if isinstance(params, dict):
            broadcaster_id = params.get("broadcaster_id")
        if not isinstance(broadcaster_id, str):
            raise AssertionError(
                f"Unexpected Twitch follower request: {url} {params!r}"
            )
        return _FakeResponse(
            {
                "total": self._follower_totals.get(broadcaster_id),
                "data": [],
                "pagination": {},
            }
        )


def test_available_sources_include_bluesky_and_twitch():
    assert Source.BLUESKY in available_sources()
    assert Source.TWITCH in available_sources()


def test_resolve_source_name_prefers_youtube_api_with_key():
    runtime = SourceRuntime(youtube_api_key="yt-test-key")

    assert _resolve_source_name(Source.YOUTUBE, runtime) == Source.YOUTUBE_API
    assert _resolve_source_name(Source.BLUESKY, runtime) == Source.BLUESKY
    assert _resolve_source_name(Source.TWITCH, runtime) == Source.TWITCH
    assert (
        DiscoveryRunService.resolve_source_name(Source.YOUTUBE, runtime)
        == Source.YOUTUBE_API
    )


def test_bluesky_actor_parsing_and_feed_enrichment():
    candidate = _parse_actor(
        {
            "did": "did:plc:testactor",
            "handle": "solo-dev.bsky.social",
            "displayName": "Solo Dev",
            "description": (
                "Indie dev making tactical roguelites. "
                "Contact me at dev@example.com"
            ),
            "avatar": "https://cdn.bsky.app/avatar.jpg",
            "followersCount": 1200,
            "postsCount": 55,
        },
        TaggedQuery(
            text="tactical game",
            source_tags=SourceTags(genre="tactical"),
        ),
    )

    assert candidate is not None
    assert candidate.platform == "bluesky"
    assert candidate.contact_channel == "email"
    assert candidate.contact_value == "dev@example.com"
    assert candidate.prospect_type == "developer"

    recent_post_at = (
        (datetime.now(UTC) - timedelta(days=2, hours=1))
        .isoformat()
        .replace("+00:00", "Z")
    )
    enriched = asyncio.run(
        _fetch_recent_posts(
            _FakeClient(
                {
                    "feed": [
                        {
                            "post": {
                                "indexedAt": recent_post_at,
                                "likeCount": 18,
                                "repostCount": 4,
                                "replyCount": 6,
                                "record": {
                                    "text": "Posting another tactical roguelite devlog today.",
                                    "createdAt": recent_post_at,
                                },
                            }
                        },
                        {
                            "post": {
                                "indexedAt": recent_post_at,
                                "likeCount": 8,
                                "repostCount": 2,
                                "replyCount": 1,
                                "record": {
                                    "text": "Exploring new turn-based combat ideas.",
                                    "createdAt": recent_post_at,
                                },
                            }
                        },
                    ]
                },
                {"followersCount": 3456, "postsCount": 99},
            ),
            candidate,
        )
    )

    assert enriched.audience_size == 3456
    assert enriched.last_active_days is not None
    assert enriched.last_active_days >= 2
    assert enriched.text_signals == [
        "Posting another tactical roguelite devlog today.",
        "Exploring new turn-based combat ideas.",
    ]
    assert enriched.raw_data["followers_count"] == 3456
    assert enriched.raw_data["posts_count"] == 99
    assert enriched.engagement_rate == 0.0056


def test_twitch_candidate_parsing_uses_live_stream_enrichment():
    candidate = _candidate_from_search_result(
        {
            "id": "141981764",
            "broadcaster_login": "twitchdev",
            "display_name": "TwitchDev",
            "game_id": "1469308723",
            "game_name": "Software and Game Development",
            "is_live": True,
            "tags": ["GameDevelopment", "English"],
            "thumbnail_url": "https://static-cdn.jtvnw.net/search-profile.png",
            "title": "Building games live",
            "started_at": "2026-03-20T10:00:00Z",
        },
        {
            "id": "141981764",
            "description": "Indie dev tools and streams. Contact: dev@example.com",
            "profile_image_url": "https://static-cdn.jtvnw.net/profile.png",
        },
        {
            "user_id": "141981764",
            "game_id": "1469308723",
            "game_name": "Software and Game Development",
            "title": "Building games live",
            "viewer_count": 142,
            "language": "en",
            "started_at": "2026-03-20T10:00:00Z",
            "thumbnail_url": "https://static-cdn.jtvnw.net/live-{width}x{height}.jpg",
            "tags": ["GameDevelopment", "English"],
        },
        TaggedQuery(
            text="game development",
            source_tags=SourceTags(vibe="indie devs"),
        ),
    )

    assert candidate is not None
    assert candidate.platform == "twitch"
    assert candidate.handle == "twitchdev"
    assert candidate.contact_channel == "email"
    assert candidate.contact_value == "dev@example.com"
    assert candidate.audience_size == 142
    assert candidate.last_active_days == 0
    assert candidate.prospect_type == "developer"
    assert candidate.raw_data["recent_video_thumbnails"] == [
        "https://static-cdn.jtvnw.net/live-640x360.jpg"
    ]
    assert candidate.text_signals[0] == "Building games live"


def test_twitch_source_fetches_follower_totals_for_cards():
    source = TwitchSource("test-client", "test-secret")

    follower_totals = asyncio.run(
        source._fetch_follower_totals(
            cast(
                httpx.AsyncClient,
                _FakeTwitchClient(
                    {
                        "141981764": 39_400,
                        "26610234": 12_345,
                    }
                ),
            ),
            {"Authorization": "Bearer test", "Client-Id": "test-client"},
            ["141981764", "26610234", "141981764"],
        )
    )

    assert follower_totals == {
        "141981764": 39_400,
        "26610234": 12_345,
    }


def test_parse_subscriber_count_supports_localized_persian_counts():
    assert _parse_subscriber_count("۳۹٫۴ هزار مشترک") == 39_400


def test_parse_subscriber_count_supports_localized_arabic_millions():
    assert _parse_subscriber_count("١٫٢ مليون مشترك") == 1_200_000


def test_run_ingestion_imports_bluesky_candidates(
    monkeypatch, db_path, game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Fleet Tactics",
        summary="Turn-based space battles for tactics players.",
        description="Turn-based space battles for tactics players.",
        genre_tags_raw="strategy, tactics, roguelite",
        platform_tags=["pc"],
        website_url=None,
    )
    game = replace(game, discovery_sources=[Source.BLUESKY])

    async def fake_discover_batches(
        self,
        game,
        limit,
        *,
        run_index=0,
        excluded_handles=None,
        page_cursors=None,
    ):
        del self, game, limit, run_index, excluded_handles
        yield [
            CandidateRecord(
                platform="bluesky",
                handle="solo-dev.bsky.social",
                display_name="Solo Dev",
                profile_url="https://bsky.app/profile/solo-dev.bsky.social",
                contact_channel="bluesky_reply",
                contact_value=None,
                audience_size=1400,
                engagement_rate=None,
                description=(
                    "Indie developer sharing strategy, tactics and roguelite updates."
                ),
                raw_data={
                    "source": "bluesky_search",
                    "did": "did:plc:solo",
                    "handle": "solo-dev.bsky.social",
                    "query": "strategy game",
                },
                last_active_days=1,
                text_signals=[
                    "Sharing a new turn-based tactics combat clip for PC players."
                ],
                prospect_type="developer",
            )
        ]

    monkeypatch.setattr(
        BlueskySource, "discover_batches", fake_discover_batches
    )

    summary = asyncio.run(
        run_ingestion(
            game,
            db_path,
            limit_per_source=5,
            twitch_client_id="test-client",
            twitch_client_secret="test-secret",
        )
    )

    assert summary == {"discovered": 1, "scored": 1, "imported": 1}

    with get_connection(db_path) as conn:
        prospect = conn.execute(
            "SELECT platform, handle, raw_data FROM prospects"
        ).fetchone()

    assert prospect["platform"] == "bluesky"
    assert prospect["handle"] == "solo-dev.bsky.social"

    raw_data = json.loads(prospect["raw_data"] or "{}")
    assert raw_data["prospect_type"] == "developer"
    assert raw_data["text_signals"] == [
        "Sharing a new turn-based tactics combat clip for PC players."
    ]


def test_run_ingestion_reruns_pass_run_index_and_exclude_seen_handles(
    monkeypatch, db_path, game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Repeatable Discovery",
        summary="Find new creators on each discovery run.",
        description="Find new creators on each discovery run.",
        genre_tags_raw="strategy, tactics",
        platform_tags=["pc"],
        website_url=None,
    )
    game = replace(game, discovery_sources=[Source.BLUESKY])

    calls: list[dict[str, object]] = []

    async def fake_discover_batches(
        self,
        game,
        limit,
        *,
        run_index=0,
        excluded_handles=None,
        page_cursors=None,
    ):
        del self, game, limit
        calls.append(
            {
                "run_index": run_index,
                "excluded_handles": set(excluded_handles or set()),
            }
        )
        if run_index == 0:
            yield [
                CandidateRecord(
                    platform="bluesky",
                    handle="alpha.bsky.social",
                    display_name="Alpha",
                    profile_url="https://bsky.app/profile/alpha.bsky.social",
                    contact_channel="bluesky_reply",
                    contact_value=None,
                    audience_size=1000,
                    engagement_rate=None,
                    description="Alpha strategy creator",
                    raw_data={
                        "did": "did:plc:alpha",
                        "handle": "alpha.bsky.social",
                    },
                    last_active_days=1,
                    text_signals=["Alpha post"],
                    prospect_type="creator",
                ),
                CandidateRecord(
                    platform="bluesky",
                    handle="beta.bsky.social",
                    display_name="Beta",
                    profile_url="https://bsky.app/profile/beta.bsky.social",
                    contact_channel="bluesky_reply",
                    contact_value=None,
                    audience_size=900,
                    engagement_rate=None,
                    description="Beta tactics creator",
                    raw_data={
                        "did": "did:plc:beta",
                        "handle": "beta.bsky.social",
                    },
                    last_active_days=2,
                    text_signals=["Beta post"],
                    prospect_type="creator",
                ),
            ]
            return

        assert set(excluded_handles or set()) == {
            "alpha.bsky.social",
            "beta.bsky.social",
        }
        yield [
            CandidateRecord(
                platform="bluesky",
                handle="gamma.bsky.social",
                display_name="Gamma",
                profile_url="https://bsky.app/profile/gamma.bsky.social",
                contact_channel="bluesky_reply",
                contact_value=None,
                audience_size=800,
                engagement_rate=None,
                description="Gamma strategy creator",
                raw_data={
                    "did": "did:plc:gamma",
                    "handle": "gamma.bsky.social",
                },
                last_active_days=1,
                text_signals=["Gamma post"],
                prospect_type="creator",
            ),
            CandidateRecord(
                platform="bluesky",
                handle="delta.bsky.social",
                display_name="Delta",
                profile_url="https://bsky.app/profile/delta.bsky.social",
                contact_channel="bluesky_reply",
                contact_value=None,
                audience_size=700,
                engagement_rate=None,
                description="Delta tactics creator",
                raw_data={
                    "did": "did:plc:delta",
                    "handle": "delta.bsky.social",
                },
                last_active_days=3,
                text_signals=["Delta post"],
                prospect_type="creator",
            ),
        ]

    monkeypatch.setattr(
        BlueskySource, "discover_batches", fake_discover_batches
    )

    first_summary = asyncio.run(
        run_ingestion(game, db_path, limit_per_source=5)
    )

    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO discovery_runs (run_id, user_id, game_id, created_at) VALUES (?, ?, ?, ?)",
            (
                "run_1",
                registered_user.user_id,
                game.game_id,
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.execute(
            "INSERT INTO discovery_runs (run_id, user_id, game_id, created_at) VALUES (?, ?, ?, ?)",
            (
                "run_2",
                registered_user.user_id,
                game.game_id,
                datetime.now(UTC).isoformat(),
            ),
        )

    second_summary = asyncio.run(
        run_ingestion(game, db_path, limit_per_source=5)
    )

    assert first_summary == {"discovered": 2, "scored": 2, "imported": 2}
    assert second_summary == {"discovered": 2, "scored": 2, "imported": 2}
    assert calls[0]["run_index"] == 0
    assert calls[0]["excluded_handles"] == set()
    assert calls[1]["run_index"] == 1
    assert calls[1]["excluded_handles"] == {
        "alpha.bsky.social",
        "beta.bsky.social",
    }

    with get_connection(db_path) as conn:
        draft_count = conn.execute(
            "SELECT COUNT(*) AS count FROM draft_items WHERE game_id = ?",
            (game.game_id,),
        ).fetchone()["count"]

    assert draft_count == 4


def test_discovery_run_service_runs_ingestion_directly(
    monkeypatch,
    discovery_run_service,
    game_service,
    registered_user,
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Service Discovery",
        summary="Run discovery through the service entry point.",
        description="Run discovery through the service entry point.",
        genre_tags_raw="strategy, tactics",
        platform_tags=["pc"],
        website_url=None,
    )
    game = replace(game, discovery_sources=[Source.BLUESKY])

    async def fake_discover_batches(
        self,
        game,
        limit,
        *,
        run_index=0,
        excluded_handles=None,
        page_cursors=None,
    ):
        del self, game, limit, run_index, excluded_handles, page_cursors
        yield [
            CandidateRecord(
                platform="bluesky",
                handle="service-fit.bsky.social",
                display_name="Service Fit",
                profile_url="https://bsky.app/profile/service-fit.bsky.social",
                contact_channel="email",
                contact_value="service@example.com",
                audience_size=1400,
                engagement_rate=None,
                description="PC strategy creator covering tactics games.",
                raw_data={
                    "did": "did:plc:service",
                    "handle": "service-fit.bsky.social",
                },
                last_active_days=1,
                text_signals=["Coverage of PC strategy and tactics games."],
                prospect_type="creator",
            )
        ]

    monkeypatch.setattr(
        BlueskySource, "discover_batches", fake_discover_batches
    )

    summary = asyncio.run(
        discovery_run_service.run_ingestion(game, limit_per_source=5)
    )

    assert summary == {"discovered": 1, "scored": 1, "imported": 1}


def test_run_ingestion_queues_first_batch_before_source_finishes(
    monkeypatch, db_path, game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Incremental Discovery",
        summary="Discovery should surface candidates before the source is done.",
        description="Discovery should surface candidates before the source is done.",
        genre_tags_raw="strategy, tactics",
        platform_tags=["pc"],
        website_url=None,
    )
    game = replace(game, discovery_sources=[Source.BLUESKY])

    first_batch_processed = asyncio.Event()
    release_second_batch = asyncio.Event()

    async def fake_discover_batches(
        self,
        game,
        limit,
        *,
        run_index=0,
        excluded_handles=None,
        page_cursors=None,
    ):
        del self, game, limit, run_index, excluded_handles, page_cursors
        yield [
            CandidateRecord(
                platform="bluesky",
                handle="first-wave.bsky.social",
                display_name="First Wave",
                profile_url="https://bsky.app/profile/first-wave.bsky.social",
                contact_channel="bluesky_reply",
                contact_value=None,
                audience_size=1000,
                engagement_rate=None,
                description="PC strategy creator covering turn-based tactics.",
                raw_data={
                    "did": "did:plc:first",
                    "handle": "first-wave.bsky.social",
                },
                last_active_days=1,
                text_signals=["First batch post about PC tactics games"],
                prospect_type="creator",
            )
        ]
        first_batch_processed.set()
        await release_second_batch.wait()
        yield [
            CandidateRecord(
                platform="bluesky",
                handle="second-wave.bsky.social",
                display_name="Second Wave",
                profile_url="https://bsky.app/profile/second-wave.bsky.social",
                contact_channel="bluesky_reply",
                contact_value=None,
                audience_size=900,
                engagement_rate=None,
                description="Second strategy creator covering tactics players.",
                raw_data={
                    "did": "did:plc:second",
                    "handle": "second-wave.bsky.social",
                },
                last_active_days=2,
                text_signals=["Second batch post about strategy tactics"],
                prospect_type="creator",
            )
        ]

    monkeypatch.setattr(
        BlueskySource, "discover_batches", fake_discover_batches
    )

    async def _run_and_assert() -> None:
        task = asyncio.create_task(
            run_ingestion(game, db_path, limit_per_source=5)
        )
        await asyncio.wait_for(first_batch_processed.wait(), timeout=1.0)

        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM draft_items WHERE game_id = ?",
                (game.game_id,),
            ).fetchone()
        assert row is not None
        assert row["count"] == 1

        release_second_batch.set()
        summary = await task
        assert summary == {"discovered": 2, "scored": 2, "imported": 2}

    asyncio.run(_run_and_assert())


def test_run_ingestion_caps_new_queue_inserts_without_removing_old_results(
    monkeypatch, db_path, game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Capped Discovery",
        summary="Keep prior queue items and cap new imports per run.",
        description="Keep prior queue items and cap new imports per run.",
        genre_tags_raw="strategy, tactics",
        platform_tags=["pc"],
        website_url=None,
    )
    game = replace(game, discovery_sources=[Source.BLUESKY])

    run_calls = 0

    def _candidate(handle: str, index: int) -> CandidateRecord:
        return CandidateRecord(
            platform="bluesky",
            handle=handle,
            display_name=f"Creator {index}",
            profile_url=f"https://bsky.app/profile/{handle}",
            contact_channel="bluesky_reply",
            contact_value=None,
            audience_size=1_000 - index,
            engagement_rate=None,
            description="Strategy creator covering turn-based tactics on PC.",
            raw_data={
                "did": f"did:plc:{handle}",
                "handle": handle,
            },
            last_active_days=1,
            text_signals=[
                "Turn-based tactics and strategy coverage for PC indie games."
            ],
            prospect_type="creator",
        )

    async def fake_discover_batches(
        self,
        game,
        limit,
        *,
        run_index=0,
        excluded_handles=None,
        page_cursors=None,
    ):
        del self, game, limit, run_index, excluded_handles, page_cursors
        nonlocal run_calls
        run_calls += 1
        if run_calls == 1:
            yield [_candidate("existing-creator.bsky.social", 0)]
            return

        for batch_index in range(3):
            offset = batch_index * 30
            yield [
                _candidate(
                    f"creator-{offset + item}.bsky.social",
                    offset + item + 1,
                )
                for item in range(30)
            ]

    monkeypatch.setattr(
        BlueskySource, "discover_batches", fake_discover_batches
    )

    first_summary = asyncio.run(
        run_ingestion(game, db_path, limit_per_source=5)
    )
    second_summary = asyncio.run(
        run_ingestion(game, db_path, limit_per_source=50)
    )

    assert first_summary == {"discovered": 1, "scored": 1, "imported": 1}
    assert second_summary["imported"] == 50
    assert second_summary["scored"] == 50

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM draft_items WHERE game_id = ?",
            (game.game_id,),
        ).fetchone()
        handles = conn.execute(
            """
            SELECT p.handle
            FROM draft_items d
            JOIN prospects p ON d.prospect_id = p.prospect_id
            WHERE d.game_id = ?
            ORDER BY p.handle
            """,
            (game.game_id,),
        ).fetchall()

    assert row is not None
    assert row["count"] == 51
    handle_values = [record["handle"] for record in handles]
    assert "creator-0.bsky.social" in handle_values
    assert "existing-creator.bsky.social" in handle_values


def test_run_ingestion_prefilters_official_and_stale_tiny_before_llm(
    monkeypatch, db_path, game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Signal Check",
        summary="Find active strategy creators worth contacting.",
        description="Find active strategy creators worth contacting.",
        genre_tags_raw="strategy, tactics",
        platform_tags=["pc"],
        website_url=None,
    )
    game = replace(game, discovery_sources=[Source.BLUESKY])

    async def fake_discover_batches(
        self,
        game,
        limit,
        *,
        run_index=0,
        excluded_handles=None,
        page_cursors=None,
    ):
        del self, game, limit, run_index, excluded_handles, page_cursors
        yield [
            CandidateRecord(
                platform="bluesky",
                handle="official-strategy.bsky.social",
                display_name="Official Strategy Game",
                profile_url="https://bsky.app/profile/official-strategy.bsky.social",
                contact_channel="bluesky_reply",
                contact_value=None,
                audience_size=8_000,
                engagement_rate=None,
                description="Official account for a strategy game launch.",
                raw_data={
                    "did": "did:plc:official",
                    "handle": "official-strategy.bsky.social",
                },
                last_active_days=2,
                text_signals=[
                    "Official strategy game trailer and launch post."
                ],
                prospect_type="creator",
            ),
            CandidateRecord(
                platform="bluesky",
                handle="tiny-stale.bsky.social",
                display_name="Tiny Stale",
                profile_url="https://bsky.app/profile/tiny-stale.bsky.social",
                contact_channel="bluesky_reply",
                contact_value=None,
                audience_size=120,
                engagement_rate=None,
                description="Turn-based tactics posts every few months.",
                raw_data={
                    "did": "did:plc:tiny",
                    "handle": "tiny-stale.bsky.social",
                },
                last_active_days=45,
                text_signals=["A tactics prototype update from last season."],
                prospect_type="creator",
            ),
            CandidateRecord(
                platform="bluesky",
                handle="one-follower.bsky.social",
                display_name="One Follower",
                profile_url="https://bsky.app/profile/one-follower.bsky.social",
                contact_channel="bluesky_reply",
                contact_value=None,
                audience_size=1,
                engagement_rate=None,
                description="PC strategy creator covering tactics and roguelites.",
                raw_data={
                    "did": "did:plc:tinyone",
                    "handle": "one-follower.bsky.social",
                    "followers_count": 1,
                },
                last_active_days=1,
                text_signals=[
                    "Weekly PC tactics breakdown and roguelite strategy recommendations."
                ],
                prospect_type="creator",
            ),
            CandidateRecord(
                platform="bluesky",
                handle="soft-drop.bsky.social",
                display_name="Soft Drop",
                profile_url="https://bsky.app/profile/soft-drop.bsky.social",
                contact_channel="bluesky_reply",
                contact_value=None,
                audience_size=75,
                engagement_rate=None,
                description="Strategy creator talking about indie games.",
                raw_data={
                    "did": "did:plc:softdrop",
                    "handle": "soft-drop.bsky.social",
                    "followers_count": 75,
                },
                last_active_days=1,
                text_signals=["Talking about indie strategy games this week."],
                prospect_type="creator",
            ),
            CandidateRecord(
                platform="bluesky",
                handle="soft-pass.bsky.social",
                display_name="Soft Pass",
                profile_url="https://bsky.app/profile/soft-pass.bsky.social",
                contact_channel="email",
                contact_value="softpass@example.com",
                audience_size=80,
                engagement_rate=None,
                description="PC strategy creator covering tactics and roguelites.",
                raw_data={
                    "did": "did:plc:softpass",
                    "handle": "soft-pass.bsky.social",
                    "followers_count": 80,
                },
                last_active_days=1,
                text_signals=[
                    "Weekly PC tactics breakdown and roguelite strategy recommendations."
                ],
                prospect_type="creator",
            ),
            CandidateRecord(
                platform="bluesky",
                handle="great-fit.bsky.social",
                display_name="Great Fit",
                profile_url="https://bsky.app/profile/great-fit.bsky.social",
                contact_channel="email",
                contact_value="creator@example.com",
                audience_size=4_200,
                engagement_rate=None,
                description="PC strategy creator covering tactics and roguelites.",
                raw_data={
                    "did": "did:plc:great",
                    "handle": "great-fit.bsky.social",
                },
                last_active_days=2,
                text_signals=[
                    "Weekly PC tactics breakdown and roguelite strategy recommendations."
                ],
                prospect_type="creator",
            ),
        ]

    llm_calls: list[list[str]] = []

    async def fake_llm_score_batch(game, prospects, api_key):
        del game, api_key
        llm_calls.append([prospect.handle for prospect in prospects])
        return {
            prospect.prospect_id: LLMFitScores(
                genre_fit=0.9,
                vibe_fit=0.8,
                format_fit=0.7,
                platform_fit=0.9,
                fit_summary="Strong fit",
                why_selected="Covers PC tactics games actively.",
            )
            for prospect in prospects
        }

    monkeypatch.setattr(
        BlueskySource, "discover_batches", fake_discover_batches
    )
    monkeypatch.setattr(
        "app.ingestion.pipeline.llm_score_batch", fake_llm_score_batch
    )

    summary = asyncio.run(
        run_ingestion(
            game,
            db_path,
            limit_per_source=10,
            anthropic_api_key="test-anthropic-key",
        )
    )

    assert summary["imported"] == 2
    assert {handle for batch in llm_calls for handle in batch} == {
        "soft-pass.bsky.social",
        "great-fit.bsky.social",
    }

    with get_connection(db_path) as conn:
        queued_handles = conn.execute(
            """
            SELECT p.handle
            FROM draft_items d
            JOIN prospects p ON d.prospect_id = p.prospect_id
            WHERE d.game_id = ?
            """,
            (game.game_id,),
        ).fetchall()

    assert {row["handle"] for row in queued_handles} == {
        "soft-pass.bsky.social",
        "great-fit.bsky.social",
    }


def test_bluesky_feed_enrichment_keeps_existing_audience_when_profile_missing():
    candidate = _parse_actor(
        {
            "did": "did:plc:testactor2",
            "handle": "creator.bsky.social",
            "displayName": "Creator",
            "description": "Indie creator",
            "followersCount": 1200,
            "postsCount": 12,
        },
        TaggedQuery(text="strategy", source_tags=SourceTags(genre="strategy")),
    )
    assert candidate is not None

    enriched = asyncio.run(
        _fetch_recent_posts(
            _FakeClient({"feed": []}, {}),
            candidate,
        )
    )

    assert enriched.audience_size == 1200
    assert enriched.raw_data["followers_count"] == 1200


def test_run_ingestion_imports_twitch_candidates_into_queue(
    monkeypatch, db_path, game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Live Strategy",
        summary="Live strategy streams for genre fans.",
        description="Find live strategy creators on Twitch.",
        genre_tags_raw="strategy, tactics",
        platform_tags=["pc"],
        website_url=None,
    )
    game = replace(game, discovery_sources=[Source.TWITCH])

    async def fake_discover_batches(
        self,
        game,
        limit,
        *,
        run_index=0,
        excluded_handles=None,
        page_cursors=None,
    ):
        del self, game, limit, run_index, excluded_handles, page_cursors
        yield [
            CandidateRecord(
                platform="twitch",
                handle="indiestrategist",
                display_name="IndieStrategist",
                profile_url="https://www.twitch.tv/indiestrategist",
                contact_channel="twitch_dm",
                contact_value="indiestrategist",
                audience_size=84,
                engagement_rate=None,
                description="Streaming turn-based tactics and roguelikes live.",
                raw_data={
                    "source": "twitch_helix",
                    "broadcaster_id": "9001",
                    "broadcaster_login": "indiestrategist",
                    "query": "strategy",
                    "followers_count": 39_400,
                    "game_name": "Software and Game Development",
                    "stream_title": "Live tactics run",
                    "avatar_url": "https://static-cdn.jtvnw.net/profile.png",
                    "recent_video_thumbnails": [
                        "https://static-cdn.jtvnw.net/live-640x360.jpg"
                    ],
                },
                last_active_days=0,
                text_signals=[
                    "Live tactics run",
                    "Streaming turn-based tactics and roguelikes live.",
                ],
                prospect_type="creator",
            )
        ]

    monkeypatch.setattr(
        TwitchSource, "discover_batches", fake_discover_batches
    )

    summary = asyncio.run(
        run_ingestion(
            game,
            db_path,
            limit_per_source=5,
            twitch_client_id="test-client",
            twitch_client_secret="test-secret",
        )
    )

    assert summary == {"discovered": 1, "scored": 1, "imported": 1}

    service = ProspectService(
        DraftItemRepository(db_path),
        OutcomeRepository(db_path),
    )
    queue_items = service.get_queue(game.game_id)
    assert len(queue_items) == 1
    assert queue_items[0].prospect.platform == "twitch"

    payload = ReviewQueuePresenter().for_api(queue_items)
    assert payload[0]["platform"] == "twitch"
    assert payload[0]["contact_value"] == "indiestrategist"
    assert payload[0]["followers_count"] == 39_400
    assert payload[0]["recent_video_thumbnails"] == [
        "https://static-cdn.jtvnw.net/live-640x360.jpg"
    ]
