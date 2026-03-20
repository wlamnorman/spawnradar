"""YouTube channel discovery via the YouTube Data API v3.

Reference: https://developers.google.com/youtube/v3/getting-started

Uses the following endpoints (quota cost per call):
  - search.list         100 units  — find channels matching a query
  - channels.list         1 unit   — fetch stats + uploads playlist IDs (batched)
  - playlistItems.list    1 unit   — fetch recent video titles per channel

Typical cost per discovery run (3 queries, 30 channels):
  ~300 units for searches + ~2 units for batched channel/video lookups ≈ 302 units.
The free daily quota is 10,000 units, giving ~30 full runs per day.

Raises QuotaExceededError when the API returns a 403 quotaExceeded error so
the caller can fall back to the scraping source.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import re
from dataclasses import replace
from pathlib import Path

import httpx

from app.games.models import Game
from app.ingestion.base import (
    DEFAULT_YOUTUBE_CONFIG,
    CandidateRecord,
    CandidateSource,
    SourceRuntime,
    YouTubeConfig,
)
from app.ingestion.constants import (
    RECENT_VIDEO_THUMBNAIL_LIMIT,
    YOUTUBE_DISCOVERY_LIMIT,
)
from app.ingestion.query_builder import TaggedQuery, build_tagged_queries
from app.ingestion.raw_data import YouTubeChannelData
from app.ingestion.registry import Source, register

log = logging.getLogger(__name__)
YT_API_BASE = "https://www.googleapis.com/youtube/v3"


_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


class QuotaExceededError(Exception):
    """Raised when the YouTube Data API daily quota is exhausted."""


@register(Source.YOUTUBE_API)
class YouTubeAPISource(CandidateSource):
    """Discovers YouTube channel candidates using the YouTube Data API v3."""

    @classmethod
    def build(cls, runtime: SourceRuntime) -> YouTubeAPISource:
        if not runtime.youtube_api_key:
            raise ValueError("YouTube API key is required for YOUTUBE_API.")
        return cls(
            runtime.youtube_api_key,
            cache_dir=runtime.youtube_cache_dir or None,
        )

    @classmethod
    def effective_limit(cls, requested_limit: int) -> int:
        return min(requested_limit, YOUTUBE_DISCOVERY_LIMIT)

    def __init__(
        self,
        api_key: str,
        timeout_seconds: float = 20.0,
        cache_dir: str | None = None,
        config: YouTubeConfig = DEFAULT_YOUTUBE_CONFIG,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._config = config

    async def discover(self, game: Game, limit: int) -> list[CandidateRecord]:
        """Return up to *limit* active YouTube channel candidates for *game*.

        If cache_dir is set, results are saved to {cache_dir}/{game_id}.json
        after a live fetch and loaded from there on subsequent calls.
        Delete the file to force a fresh API call.
        """
        if self._cache_dir is not None:
            cached = _load_cache(self._cache_dir, game.game_id)
            if cached is not None:
                log.info(
                    "YouTubeAPISource: loaded %d candidates from cache (%s)",
                    len(cached),
                    self._cache_dir / f"{game.game_id}.json",
                )
                return cached[:limit]

        queries = _build_queries(game)
        seen_handles: set[str] = set()
        candidates: list[CandidateRecord] = []
        collect_target = min(limit * 2, 60)

        log.info(
            "YouTubeAPISource: running %d queries (target %d channels)",
            len(queries),
            collect_target,
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for tagged_query in queries:
                if len(candidates) >= collect_target:
                    break

                log.debug("  Query: %r", tagged_query.text)
                batch = await self._search_and_fetch(
                    client,
                    tagged_query.text,
                    tagged_query.source_genre_tag,
                    tagged_query.source_audience_tag,
                )
                new = [r for r in batch if r.handle not in seen_handles]
                for record in new:
                    seen_handles.add(record.handle)
                    candidates.append(record)
                    if len(candidates) >= collect_target:
                        break
                log.debug(
                    "  → %d results (%d new, %d total so far)",
                    len(batch),
                    len(new),
                    len(candidates),
                )

            # Enrich all candidates with recent video titles for scoring
            log.info("Fetching recent videos for %d channels", len(candidates))
            candidates = await self._enrich_with_videos(client, candidates)

        if self._cache_dir is not None:
            _save_cache(self._cache_dir, game.game_id, candidates)
            log.info(
                "YouTubeAPISource: saved %d candidates to cache (%s)",
                len(candidates),
                self._cache_dir / f"{game.game_id}.json",
            )

        return candidates[:limit]

    async def _search_and_fetch(
        self,
        client: httpx.AsyncClient,
        query: str,
        genre_tag: str | None,
        audience_tag: str | None,
    ) -> list[CandidateRecord]:
        """Run search.list then channels.list for a single query."""
        # search.list — 100 units
        search_resp = await client.get(
            f"{YT_API_BASE}/search",
            params={
                "part": "snippet",
                "q": query,
                "type": "channel",
                "maxResults": 10,
                "key": self._api_key,
            },
        )
        _check_quota(search_resp)
        search_resp.raise_for_status()

        channel_ids = [
            item["id"]["channelId"]
            for item in search_resp.json().get("items", [])
            if item.get("id", {}).get("channelId")
        ]
        if not channel_ids:
            return []

        # channels.list — 1 unit for the whole batch
        channels_resp = await client.get(
            f"{YT_API_BASE}/channels",
            params={
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(channel_ids),
                "key": self._api_key,
            },
        )
        _check_quota(channels_resp)
        channels_resp.raise_for_status()

        records: list[CandidateRecord] = []
        for item in channels_resp.json().get("items", []):
            record = _parse_channel_item(
                item, query, genre_tag, audience_tag, self._config
            )
            if record is not None:
                records.append(record)
        return records

    async def _enrich_with_videos(
        self,
        client: httpx.AsyncClient,
        candidates: list[CandidateRecord],
    ) -> list[CandidateRecord]:
        """Concurrently fetch recent video titles for all candidates."""
        tasks = [
            asyncio.create_task(_fetch_recent_videos(client, c, self._api_key))
            for c in candidates
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        enriched: list[CandidateRecord] = []
        for candidate, result in zip(candidates, results, strict=False):
            if isinstance(result, QuotaExceededError):
                raise result
            if isinstance(result, BaseException):
                enriched.append(candidate)
            else:
                enriched.append(result)
        return enriched


# ---------------------------------------------------------------------------
# Per-channel video enrichment
# ---------------------------------------------------------------------------


async def _fetch_recent_videos(
    client: httpx.AsyncClient,
    candidate: CandidateRecord,
    api_key: str,
) -> CandidateRecord:
    """Fetch recent video titles + thumbnails via playlistItems.list (1 unit).

    The uploads playlist ID is stored in raw_data by _parse_channel_item.
    Returns the candidate unchanged if the playlist ID is missing or the call fails.
    """
    uploads_playlist_id = candidate.raw_data.get("uploads_playlist_id")
    if not uploads_playlist_id:
        return candidate

    resp = await client.get(
        f"{YT_API_BASE}/playlistItems",
        params={
            "part": "snippet",
            "playlistId": uploads_playlist_id,
            "maxResults": RECENT_VIDEO_THUMBNAIL_LIMIT,
            "key": api_key,
        },
    )
    _check_quota(resp)
    resp.raise_for_status()

    titles: list[str] = []
    thumbnails: list[str] = []
    for item in resp.json().get("items", []):
        snippet = item.get("snippet", {})
        title = snippet.get("title", "")
        if title and title != "Private video" and title != "Deleted video":
            titles.append(title)

        if len(thumbnails) < RECENT_VIDEO_THUMBNAIL_LIMIT:
            thumbs = snippet.get("thumbnails", {})
            for size in ("maxres", "high", "medium", "default"):
                url = thumbs.get(size, {}).get("url", "")
                if url:
                    thumbnails.append(url)
                    break

    channel_data = YouTubeChannelData.model_validate(candidate.raw_data)
    return replace(
        candidate,
        text_signals=titles,
        raw_data=channel_data.model_copy(
            update={
                "recent_video_titles": titles,
                "recent_video_thumbnails": thumbnails,
            }
        ).model_dump(),
    )


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_channel_item(
    item: dict,
    query: str,
    genre_tag: str | None,
    audience_tag: str | None,
    config: YouTubeConfig = DEFAULT_YOUTUBE_CONFIG,
) -> CandidateRecord | None:
    """Convert a channels.list item into a CandidateRecord, or None if filtered."""
    channel_id = item.get("id", "")
    snippet = item.get("snippet", {})
    statistics = item.get("statistics", {})
    content_details = item.get("contentDetails", {})

    display_name = snippet.get("title", "").strip()
    if not channel_id or not display_name:
        return None

    # Subscriber count
    subscriber_count_str = statistics.get("subscriberCount")
    audience_size = int(subscriber_count_str) if subscriber_count_str else None

    # Video count
    video_count_str = statistics.get("videoCount")
    video_count = int(video_count_str) if video_count_str else None
    if video_count is not None and video_count < config.min_video_count:
        return None

    description = snippet.get("description", "").strip() or None

    # Handle / profile URL
    custom_url = snippet.get("customUrl", "").strip()  # e.g. "@channelname"
    handle = custom_url.lstrip("@") if custom_url else f"channel/{channel_id}"
    profile_url = (
        f"https://www.youtube.com/{custom_url}"
        if custom_url
        else f"https://www.youtube.com/channel/{channel_id}"
    )

    # Avatar
    thumbnails = snippet.get("thumbnails", {})
    avatar_url: str | None = None
    for size in ("high", "medium", "default"):
        url = thumbnails.get(size, {}).get("url", "")
        if url:
            avatar_url = url
            break

    # Email in description
    contact_value: str | None = None
    contact_channel: str | None = None
    if description:
        m = _EMAIL_RE.search(description)
        if m:
            contact_value = m.group()
            contact_channel = "email"

    # Uploads playlist ID (needed to fetch recent videos)
    uploads_playlist_id = (
        content_details.get("relatedPlaylists", {}).get("uploads", "") or None
    )

    raw_data = YouTubeChannelData(
        channel_id=channel_id,
        query=query,
        subscriber_text=f"{audience_size:,} subscribers"
        if audience_size
        else None,
        video_count=video_count,
        avatar_url=avatar_url,
        source_genre_tag=genre_tag,
        source_audience_tag=audience_tag,
    ).model_dump()

    # Store the uploads playlist ID for the video enrichment step
    raw_data["uploads_playlist_id"] = uploads_playlist_id

    return CandidateRecord(
        platform="youtube",
        handle=handle,
        display_name=display_name,
        profile_url=profile_url,
        contact_channel=contact_channel,
        contact_value=contact_value,
        audience_size=audience_size,
        engagement_rate=None,
        description=description,
        raw_data=raw_data,
        prospect_type="creator",
        # last_active_days and text_signals are set by _fetch_recent_videos
    )


def _build_queries(game: Game) -> list[TaggedQuery]:
    """Build search queries as (query, source_genre_tag, source_audience_tag)."""
    return build_tagged_queries(
        game,
        genre_templates=(
            "{tag} games",
            "indie {tag} game",
            "{tag} game review",
        ),
        audience_templates=(
            "{tag} games",
            "indie games {tag}",
        ),
    )


# ---------------------------------------------------------------------------
# Candidate cache (dev only)
# ---------------------------------------------------------------------------


def _cache_path(cache_dir: Path, game_id: str) -> Path:
    return cache_dir / f"{game_id}.json"


def _load_cache(cache_dir: Path, game_id: str) -> list[CandidateRecord] | None:
    path = _cache_path(cache_dir, game_id)
    if not path.exists():
        return None
    try:
        rows = json.loads(path.read_text())
        return [CandidateRecord(**row) for row in rows]
    except Exception as e:
        log.warning("Failed to load YouTube cache from %s: %s", path, e)
        return None


def _save_cache(
    cache_dir: Path, game_id: str, candidates: list[CandidateRecord]
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, game_id)
    try:
        path.write_text(
            json.dumps([dataclasses.asdict(c) for c in candidates], indent=2)
        )
    except Exception as e:
        log.warning("Failed to save YouTube cache to %s: %s", path, e)


# ---------------------------------------------------------------------------
# Quota error detection
# ---------------------------------------------------------------------------


def _check_quota(response: httpx.Response) -> None:
    """Raise QuotaExceededError if the response indicates quota exhaustion."""
    if response.status_code != 403:
        return
    try:
        errors = response.json().get("error", {}).get("errors", [])
        for err in errors:
            if err.get("reason") in ("quotaExceeded", "dailyLimitExceeded"):
                raise QuotaExceededError(
                    "YouTube Data API daily quota exhausted; falling back to scraper."
                )
    except (ValueError, AttributeError):
        pass
