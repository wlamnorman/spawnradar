"""Bluesky creator discovery via the public XRPC API."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol

import httpx

from app.games.models import Game
from app.ingestion.base import CandidateRecord, CandidateSource
from app.ingestion.constants import RECENT_TEXT_SIGNAL_LIMIT
from app.ingestion.query_builder import TaggedQuery, build_tagged_queries
from app.ingestion.raw_data import BlueskyActorData
from app.ingestion.registry import Source, register

_BSKY_XRPC_BASE = "https://public.api.bsky.app/xrpc"
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_HEADERS = {
    "User-Agent": "SpawnRadar/1.0 (+https://spawnradar.app)",
    "Accept": "application/json",
}


class _ResponseLike(Protocol):
    """Minimal HTTP response interface needed by Bluesky helpers."""

    def raise_for_status(self) -> None: ...
    def json(self) -> dict[str, object]: ...


class _ClientLike(Protocol):
    """Minimal async client interface needed by Bluesky helpers."""

    async def get(
        self,
        url: str,
        *,
        params: object | None = None,
        **kwargs: object,
    ) -> _ResponseLike: ...


@register(Source.BLUESKY)
class BlueskySource(CandidateSource):
    """Discover Bluesky accounts relevant to a game's genre and audience."""

    def __init__(
        self,
        delay_seconds: float = 0.25,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._delay = delay_seconds
        self._timeout = timeout_seconds

    async def discover(self, game: Game, limit: int) -> list[CandidateRecord]:
        """Return up to *limit* Bluesky accounts relevant to *game*."""
        queries = _build_queries(game)
        seen_handles: set[str] = set()
        candidates: list[CandidateRecord] = []
        collect_target = min(limit * 2, 60)

        async with httpx.AsyncClient(
            headers=_HEADERS, timeout=self._timeout
        ) as client:
            for i, tagged_query in enumerate(queries):
                if len(candidates) >= collect_target:
                    break
                try:
                    batch = await self._search_actors(
                        client,
                        tagged_query.text,
                        min(limit, 25),
                        tagged_query.source_genre_tag,
                        tagged_query.source_audience_tag,
                    )
                except Exception:
                    continue

                for record in batch:
                    if record.handle in seen_handles:
                        continue
                    seen_handles.add(record.handle)
                    candidates.append(record)
                    if len(candidates) >= collect_target:
                        break

                if i < len(queries) - 1:
                    await asyncio.sleep(self._delay)

            candidates = await self._enrich_with_recent_posts(
                client, candidates
            )

        return candidates[:limit]

    async def _search_actors(
        self,
        client: httpx.AsyncClient,
        query: str,
        limit: int,
        source_genre_tag: str | None,
        source_audience_tag: str | None,
    ) -> list[CandidateRecord]:
        """Search for Bluesky accounts matching *query*."""
        response = await client.get(
            f"{_BSKY_XRPC_BASE}/app.bsky.actor.searchActors",
            params={"q": query, "limit": limit},
        )
        response.raise_for_status()

        records: list[CandidateRecord] = []
        for actor_value in _as_list(response.json().get("actors")):
            actor = _as_dict(actor_value)
            if actor is None:
                continue
            record = _parse_actor(
                actor,
                query,
                source_genre_tag,
                source_audience_tag,
            )
            if record is not None:
                records.append(record)
        return records

    async def _enrich_with_recent_posts(
        self,
        client: httpx.AsyncClient,
        candidates: list[CandidateRecord],
    ) -> list[CandidateRecord]:
        """Fetch recent posts for each candidate to populate text signals."""
        tasks = [
            asyncio.create_task(_fetch_recent_posts(client, candidate))
            for candidate in candidates
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        enriched: list[CandidateRecord] = []
        for candidate, result in zip(candidates, results, strict=False):
            if isinstance(result, BaseException):
                enriched.append(candidate)
            else:
                enriched.append(result)
        return enriched


def _build_queries(game: Game) -> list[TaggedQuery]:
    """Build Bluesky actor-search queries from the game's tags."""
    return build_tagged_queries(
        game,
        genre_templates=("{tag} game", "{tag}"),
        audience_templates=("{tag}",),
    )


def _parse_actor(
    actor: Mapping[str, object],
    query: str,
    source_genre_tag: str | None,
    source_audience_tag: str | None,
) -> CandidateRecord | None:
    """Convert an actor search result into a normalized candidate."""
    did = str(actor.get("did", "")).strip()
    handle = str(actor.get("handle", "")).strip().lstrip("@")
    if not did or not handle:
        return None

    display_name = str(actor.get("displayName") or handle).strip()
    description = str(actor.get("description", "")).strip() or None
    avatar_url = str(actor.get("avatar", "")).strip() or None
    followers_count = _optional_int(actor.get("followersCount"))
    posts_count = _optional_int(actor.get("postsCount"))

    contact_value: str | None = None
    contact_channel = "bluesky_reply"
    if description:
        match = _EMAIL_RE.search(description)
        if match is not None:
            contact_value = match.group(0)
            contact_channel = "email"

    raw_data = BlueskyActorData(
        did=did,
        handle=handle,
        query=query,
        followers_count=followers_count,
        posts_count=posts_count,
        avatar_url=avatar_url,
        source_genre_tag=source_genre_tag,
        source_audience_tag=source_audience_tag,
    ).model_dump()

    return CandidateRecord(
        platform="bluesky",
        handle=handle,
        display_name=display_name,
        profile_url=f"https://bsky.app/profile/{handle}",
        contact_channel=contact_channel,
        contact_value=contact_value,
        audience_size=followers_count,
        engagement_rate=None,
        description=description[:500] if description else None,
        raw_data=raw_data,
        text_signals=[description] if description else [],
        prospect_type=_infer_prospect_type(display_name, description),
    )


async def _fetch_recent_posts(
    client: httpx.AsyncClient | _ClientLike,
    candidate: CandidateRecord,
) -> CandidateRecord:
    """Enrich a candidate with recent post text and activity."""
    response = await client.get(
        f"{_BSKY_XRPC_BASE}/app.bsky.feed.getAuthorFeed",
        params={"actor": candidate.handle, "limit": RECENT_TEXT_SIGNAL_LIMIT},
    )
    response.raise_for_status()

    post_texts: list[str] = []
    timestamps: list[str] = []
    engagement_total = 0
    feed_items = _as_list(response.json().get("feed"))

    for item in feed_items:
        item_dict = _as_dict(item) or {}
        post = _as_dict(item_dict.get("post")) or {}
        record = _as_dict(post.get("record")) or {}
        text = _normalize_post_text(record.get("text", ""))
        if text and len(post_texts) < RECENT_TEXT_SIGNAL_LIMIT:
            post_texts.append(text)

        timestamp = str(
            post.get("indexedAt") or record.get("createdAt") or ""
        ).strip()
        if timestamp:
            timestamps.append(timestamp)

        engagement_total += (
            _int_or_zero(post.get("likeCount"))
            + _int_or_zero(post.get("repostCount"))
            + _int_or_zero(post.get("replyCount"))
        )

    last_post_days = (
        _days_since_timestamp(timestamps[0]) if timestamps else None
    )

    engagement_rate: float | None = candidate.engagement_rate
    if candidate.audience_size and candidate.audience_size > 0 and feed_items:
        engagement_rate = round(
            engagement_total / len(feed_items) / candidate.audience_size,
            4,
        )

    data = BlueskyActorData.model_validate(candidate.raw_data)
    return replace(
        candidate,
        engagement_rate=engagement_rate,
        last_active_days=last_post_days,
        text_signals=post_texts or candidate.text_signals,
        raw_data=data.model_copy(
            update={
                "last_post_days_ago": last_post_days,
                "recent_post_texts": post_texts,
            }
        ).model_dump(),
    )


def _infer_prospect_type(display_name: str, description: str | None) -> str:
    """Infer whether this account looks like a creator or developer."""
    haystack = f"{display_name} {description or ''}".lower()
    developer_markers = (
        "indie dev",
        "game dev",
        "gamedev",
        "solo dev",
        "developer",
        "making games",
    )
    if any(marker in haystack for marker in developer_markers):
        return "developer"
    return "creator"


def _optional_int(value: object) -> int | None:
    """Convert numeric JSON fields to int without throwing."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _int_or_zero(value: object) -> int:
    """Convert a JSON numeric field to int, defaulting to zero."""
    parsed = _optional_int(value)
    return parsed if parsed is not None else 0


def _as_list(value: object) -> list[object]:
    """Return a JSON array as a concrete Python list."""
    return value if isinstance(value, list) else []


def _as_dict(value: object) -> dict[str, object] | None:
    """Return a JSON object as a concrete dict."""
    return value if isinstance(value, dict) else None


def _normalize_post_text(value: object) -> str:
    """Collapse whitespace and trim post text for scoring."""
    text = " ".join(str(value or "").split())
    return text[:280]


def _days_since_timestamp(value: str) -> int | None:
    """Convert an ISO timestamp into whole UTC days ago."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)

    delta = datetime.now(UTC) - parsed.astimezone(UTC)
    return max(delta.days, 0)
