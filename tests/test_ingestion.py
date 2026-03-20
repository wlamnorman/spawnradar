"""Tests for ingestion source wiring and Bluesky normalization."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.database import get_connection
from app.ingestion.base import CandidateRecord, SourceRuntime
from app.ingestion.pipeline import _resolve_source_name, run_ingestion
from app.ingestion.registry import Source, available_sources
from app.ingestion.sources.bluesky import (
    BlueskySource,
    _fetch_recent_posts,
    _parse_actor,
)


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    async def get(
        self,
        url: str,
        *,
        params: object | None = None,
        **kwargs: object,
    ) -> _FakeResponse:
        del url, params, kwargs
        return _FakeResponse(self._payload)


def test_available_sources_includes_bluesky():
    assert Source.BLUESKY in available_sources()


def test_resolve_source_name_prefers_youtube_api_with_key():
    runtime = SourceRuntime(youtube_api_key="yt-test-key")

    assert _resolve_source_name(Source.YOUTUBE, runtime) == Source.YOUTUBE_API
    assert _resolve_source_name(Source.BLUESKY, runtime) == Source.BLUESKY


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
        "tactical game",
        "tactical",
        None,
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
                }
            ),
            candidate,
        )
    )

    assert enriched.last_active_days is not None
    assert enriched.last_active_days >= 2
    assert enriched.text_signals == [
        "Posting another tactical roguelite devlog today.",
        "Exploring new turn-based combat ideas.",
    ]
    assert enriched.engagement_rate == 0.0163


def test_run_ingestion_imports_bluesky_candidates(
    monkeypatch, db_path, game_service, registered_user
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Fleet Tactics",
        description="Turn-based space battles for tactics players.",
        genre_tags_raw="strategy, tactics, roguelite",
        audience_tags_raw="tactics fans, indie strategy players",
        platform_tags=["pc"],
        website_url=None,
    )
    game = replace(game, discovery_sources=[Source.BLUESKY])

    async def fake_discover(self, game, limit):
        del self, game, limit
        return [
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
                    "Indie developer sharing strategy, tactics, and roguelite updates."
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

    monkeypatch.setattr(BlueskySource, "discover", fake_discover)

    summary = asyncio.run(run_ingestion(game, db_path, limit_per_source=5))

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
