"""YouTube channel discovery via public search results.

Uses the same ytInitialData JSON approach as the original
discover_youtube_prospects.py script, adapted to be async with httpx.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Collection
from dataclasses import replace
from typing import Any
from urllib.parse import quote_plus

import httpx
from selectolax.parser import HTMLParser

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
    RECENT_VIDEO_TITLE_LIMIT,
    YOUTUBE_DISCOVERY_LIMIT,
)
from app.ingestion.query_builder import (
    TaggedQuery,
    build_tagged_queries,
)
from app.ingestion.raw_data import YouTubeChannelData
from app.ingestion.registry import Source, register

YOUTUBE_SEARCH_URL = "https://www.youtube.com/results"
CHANNEL_FILTER = "EgIQAg%3D%3D"  # YouTube search filter: channels only


_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_LOCALIZED_DIGIT_TRANSLATION = str.maketrans(
    {
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "٫": ".",
        "٬": ",",
    }
)
_SUBSCRIBER_MULTIPLIER_ALIASES: tuple[tuple[str, int], ...] = (
    ("b", 1_000_000_000),
    ("billion", 1_000_000_000),
    ("میلیارد", 1_000_000_000),
    ("مليار", 1_000_000_000),
    ("m", 1_000_000),
    ("million", 1_000_000),
    ("میلیون", 1_000_000),
    ("مليون", 1_000_000),
    ("k", 1_000),
    ("thousand", 1_000),
    ("هزار", 1_000),
    ("الف", 1_000),
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@register(Source.YOUTUBE)
class YouTubeSource(CandidateSource):
    """Discovers YouTube channel candidates relevant to a game's tags.

    Builds search queries from genre tags, fetches YouTube
    search results pages and parses the embedded ytInitialData JSON to
    extract channel information.

    Channels are filtered by:
    - Minimum video count (MIN_VIDEO_COUNT): removes stub/abandoned channels.
    - Recent activity (MAX_INACTIVE_DAYS): removes channels that haven't
      uploaded recently, checked via a concurrent fetch of each channel's
      /videos page.
    """

    platform = "youtube"

    def __init__(
        self,
        delay_seconds: float = 1.0,
        timeout_seconds: float = 20.0,
        config: YouTubeConfig = DEFAULT_YOUTUBE_CONFIG,
    ) -> None:
        self._delay = delay_seconds
        self._timeout = timeout_seconds
        self._config = config

    @classmethod
    def build(cls, runtime: SourceRuntime) -> YouTubeSource:
        del runtime
        return cls()

    @classmethod
    def effective_limit(cls, requested_limit: int) -> int:
        return min(requested_limit, YOUTUBE_DISCOVERY_LIMIT)

    async def discover(
        self,
        game: Game,
        limit: int,
        *,
        run_index: int = 0,
        excluded_handles: Collection[str] | None = None,
        page_cursors: dict[str, str] | None = None,
    ) -> list[CandidateRecord]:
        """Return up to *limit* active YouTube channel candidates for *game*."""
        queries = _build_queries(game, run_index)
        seen_handles: set[str] = {
            handle.lower() for handle in (excluded_handles or ())
        }
        candidates: list[CandidateRecord] = []

        # Collect more than needed so recency filtering doesn't leave us short
        collect_target = min(limit * (4 if run_index else 2), 120)

        async with httpx.AsyncClient(
            headers=_HEADERS, timeout=self._timeout
        ) as client:
            for i, tagged_query in enumerate(queries):
                if len(candidates) >= collect_target:
                    break
                try:
                    batch = await self._search_channels(
                        client,
                        tagged_query,
                        limit,
                    )
                except Exception:
                    continue

                for record in batch:
                    normalized_handle = record.handle.lower()
                    if normalized_handle not in seen_handles:
                        seen_handles.add(normalized_handle)
                        candidates.append(record)
                        if len(candidates) >= collect_target:
                            break

                if i < len(queries) - 1:
                    await asyncio.sleep(self._delay)

            # Drop channels that haven't uploaded recently
            candidates = await self._filter_inactive(client, candidates)

        return candidates[:limit]

    async def _search_channels(
        self,
        client: httpx.AsyncClient,
        tagged_query: TaggedQuery,
        limit: int,
    ) -> list[CandidateRecord]:
        """Fetch one search results page and parse channel cards from it."""
        url = f"{YOUTUBE_SEARCH_URL}?search_query={quote_plus(tagged_query.text)}&sp={CHANNEL_FILTER}"
        response = await client.get(url)
        response.raise_for_status()

        initial_data = _extract_initial_data(response.text)
        renderers = list(_iter_renderers(initial_data, "channelRenderer"))

        records: list[CandidateRecord] = []
        seen_ids: set[str] = set()

        for renderer in renderers:
            if len(records) >= limit:
                break
            record = _parse_channel_renderer(
                renderer, tagged_query, self._config
            )
            if record is None or record.handle in seen_ids:
                continue
            seen_ids.add(record.handle)
            records.append(record)

        return records

    async def _filter_inactive(
        self,
        client: httpx.AsyncClient,
        candidates: list[CandidateRecord],
    ) -> list[CandidateRecord]:
        """Concurrently check each channel's recent uploads and drop inactive ones.

        Channels whose raw_data already contains last_upload_days_ago (stored
        in the prospects table from a previous run) skip the HTTP fetch entirely.
        For the rest, the /videos page is fetched concurrently.

        Channels that return an error or have no parseable upload date are kept
        (benefit of the doubt).  Channels whose most recent upload is older than
        MAX_INACTIVE_DAYS are dropped.
        """
        needs_fetch: list[CandidateRecord] = []
        already_known: list[CandidateRecord] = []

        for candidate in candidates:
            data = YouTubeChannelData.model_validate(candidate.raw_data)
            if data.last_upload_days_ago is not None:
                already_known.append(candidate)
            else:
                needs_fetch.append(candidate)

        # Resolve recency + thumbnails for channels we haven't seen before
        tasks = [
            asyncio.create_task(
                _fetch_videos_page_data(client, c.profile_url or "")
            )
            for c in needs_fetch
        ]
        fetched_results = await asyncio.gather(*tasks, return_exceptions=True)

        active: list[CandidateRecord] = []

        for candidate, result in zip(
            needs_fetch, fetched_results, strict=False
        ):
            if isinstance(result, BaseException):
                active.append(candidate)
                continue
            days_ago, thumbnails, titles = result
            if days_ago is None:
                active.append(candidate)
            elif days_ago <= self._config.max_inactive_days:
                channel_data = YouTubeChannelData.model_validate(
                    candidate.raw_data
                )
                active.append(
                    replace(
                        candidate,
                        last_active_days=days_ago,
                        text_signals=titles,
                        raw_data=channel_data.model_copy(
                            update={
                                "last_upload_days_ago": days_ago,
                                "recent_video_thumbnails": thumbnails,
                                "recent_video_titles": titles,
                            }
                        ).model_dump(),
                    )
                )
            # else: inactive → drop

        for candidate in already_known:
            data = YouTubeChannelData.model_validate(candidate.raw_data)
            if data.last_upload_days_ago <= self._config.max_inactive_days:  # type: ignore[operator]
                active.append(
                    replace(
                        candidate,
                        last_active_days=data.last_upload_days_ago,
                        text_signals=data.recent_video_titles or [],
                    )
                )

        return active


# ---------------------------------------------------------------------------
# Recency helpers
# ---------------------------------------------------------------------------


async def _fetch_videos_page_data(
    client: httpx.AsyncClient, profile_url: str
) -> tuple[int | None, list[str], list[str]]:
    """Fetch a channel's /videos page and return (days_since_upload, thumbnails, titles).

    days_since_upload is None if the date cannot be determined.
    thumbnails: up to RECENT_VIDEO_THUMBNAIL_LIMIT thumbnail URLs for recent videos.
    titles: up to RECENT_VIDEO_TITLE_LIMIT video titles — used by the scoring engine to assess content fit.
    Returns (None, [], []) on any error.
    """
    if not profile_url:
        return None, [], []
    try:
        videos_url = profile_url.rstrip("/") + "/videos"
        response = await client.get(videos_url)
        response.raise_for_status()
        data = _extract_initial_data(response.text)

        days_ago: int | None = None
        for node in _iter_renderers(data, "publishedTimeText"):
            text = _simple_text(node)
            if text:
                days_ago = _parse_relative_time_to_days(text)
                break

        thumbnails: list[str] = []
        titles: list[str] = []
        for renderer in _iter_renderers(data, "videoRenderer"):
            title = _simple_text(renderer.get("title"))
            if title and len(titles) < RECENT_VIDEO_TITLE_LIMIT:
                titles.append(title)

            if len(thumbnails) < RECENT_VIDEO_THUMBNAIL_LIMIT:
                thumb_list = renderer.get("thumbnail", {}).get(
                    "thumbnails", []
                )
                if thumb_list:
                    url = str(thumb_list[-1].get("url", ""))
                    if url.startswith("//"):
                        url = "https:" + url
                    if url.startswith("http"):
                        thumbnails.append(url)

            if (
                len(thumbnails) >= RECENT_VIDEO_THUMBNAIL_LIMIT
                and len(titles) >= RECENT_VIDEO_TITLE_LIMIT
            ):
                break

        return days_ago, thumbnails, titles
    except Exception:
        return None, [], []


def _parse_relative_time_to_days(text: str) -> int | None:
    """Convert a YouTube relative timestamp to approximate days.

    Examples: '3 months ago' → 90, '1 year ago' → 365, '2 weeks ago' → 14.
    """
    t = text.lower()
    patterns = [
        (r"(\d+)\s*year", 365),
        (r"(\d+)\s*month", 30),
        (r"(\d+)\s*week", 7),
        (r"(\d+)\s*day", 1),
    ]
    for pattern, multiplier in patterns:
        m = re.search(pattern, t)
        if m:
            return int(m.group(1)) * multiplier
    # "just now", "X hours ago", "X minutes ago" → uploaded today
    if re.search(r"hour|minute|just now", t):
        return 0
    return None


# ---------------------------------------------------------------------------
# Parsing helpers (adapted from discover_youtube_prospects.py)
# ---------------------------------------------------------------------------


def _build_queries(game: Game, run_index: int = 0) -> list[TaggedQuery]:
    """Build search queries for YouTube scraper discovery."""
    return build_tagged_queries(
        game,
        suffixes=(
            "games",
            "game",
            "gameplay",
            "game review",
            "gaming channel",
            "streamer",
            "youtuber",
            "lets play",
        ),
        game_name_suffixes=("gameplay", "review", "lets play"),
        run_index=run_index,
    )


def _extract_initial_data(html: str) -> dict[str, Any]:
    """Extract the ytInitialData JSON blob from a YouTube HTML page.

    Uses selectolax to locate the correct <script> tag, then
    json.JSONDecoder.raw_decode to consume exactly the JSON object without
    relying on a regex over the full page text.
    """
    marker = "var ytInitialData = "
    tree = HTMLParser(html)
    for script in tree.css("script"):
        text = script.text(deep=False)
        if marker not in text:
            continue
        start = text.index(marker) + len(marker)
        data, _ = json.JSONDecoder().raw_decode(text, start)
        return data  # type: ignore[return-value]
    raise RuntimeError("Could not locate ytInitialData in YouTube HTML.")


def _iter_renderers(node: Any, key: str):
    """Recursively yield all dicts keyed by *key* in *node*."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, dict):
                yield v
            else:
                yield from _iter_renderers(v, key)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_renderers(item, key)


def _parse_channel_renderer(
    renderer: dict,
    tagged_query: TaggedQuery,
    config: YouTubeConfig = DEFAULT_YOUTUBE_CONFIG,
) -> CandidateRecord | None:
    """Convert a channelRenderer dict into a CandidateRecord.

    Returns None if the channel is missing required fields, has too few
    videos, or falls outside the viable subscriber range for indie outreach.
    """
    channel_id = str(renderer.get("channelId", "")).strip()
    display_name = _simple_text(renderer.get("title"))
    if not channel_id or not display_name:
        return None

    # Hard filter: skip channels with fewer than MIN_VIDEO_COUNT videos
    video_count_text = _simple_text(renderer.get("videoCountText"))
    video_count = _parse_video_count(video_count_text)
    if video_count is not None and video_count < config.min_video_count:
        return None

    nav_url = _nested_get(
        renderer,
        "navigationEndpoint",
        "commandMetadata",
        "webCommandMetadata",
        "url",
    )
    profile_url = _build_profile_url(nav_url, channel_id)
    handle = _extract_handle(profile_url) or f"channel/{channel_id}"

    subscriber_text = _simple_text(renderer.get("subscriberCountText"))
    description = _simple_text(renderer.get("descriptionSnippet"))

    audience_size = _parse_subscriber_count(subscriber_text)

    # Attempt to find email in description
    contact_value: str | None = None
    contact_channel: str | None = None
    if description:
        email_match = _EMAIL_RE.search(description)
        if email_match:
            contact_value = email_match.group()
            contact_channel = "email"

    # Extract channel avatar (highest resolution thumbnail from search card)
    avatar_url: str | None = None
    avatar_thumbs = renderer.get("thumbnail", {}).get("thumbnails", [])
    if avatar_thumbs:
        url = str(avatar_thumbs[-1].get("url", ""))
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith("http"):
            avatar_url = url

    tags = tagged_query.source_tags
    raw_data = YouTubeChannelData(
        channel_id=channel_id,
        query=tagged_query.text,
        subscriber_text=subscriber_text or None,
        video_count=video_count,
        avatar_url=avatar_url,
        source_genre_tag=tags.genre,
        source_mechanics_tag=tags.mechanics,
        source_vibe_tag=tags.vibe,
    ).model_dump()

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
        # last_active_days and text_signals set by _filter_inactive
    )


def _simple_text(node: Any) -> str:
    """Extract plain text from a YouTube API node (simpleText or runs)."""
    if not isinstance(node, dict):
        return ""
    simple = node.get("simpleText")
    if isinstance(simple, str):
        return " ".join(simple.split())
    runs = node.get("runs")
    if isinstance(runs, list):
        parts = [str(p.get("text", "")) for p in runs if isinstance(p, dict)]
        return " ".join("".join(parts).split())
    return ""


def _nested_get(node: Any, *keys: str) -> Any:
    """Safely traverse nested dicts."""
    current = node
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _build_profile_url(nav_url: Any, channel_id: str) -> str:
    """Build an absolute YouTube channel URL."""
    if isinstance(nav_url, str) and nav_url.strip():
        url = nav_url.strip()
        if url.startswith("http"):
            return url
        return f"https://www.youtube.com{url}"
    return f"https://www.youtube.com/channel/{channel_id}"


def _extract_handle(profile_url: str) -> str:
    """Extract the channel handle/slug from a YouTube URL."""
    for marker in ("/@", "/channel/", "/c/", "/user/"):
        if marker in profile_url:
            return profile_url.split(marker, 1)[1].rstrip("/")
    return ""


def _parse_video_count(text: str) -> int | None:
    """Parse video count like '123 videos' or '1,234 videos' → int."""
    if not text:
        return None
    m = re.search(r"([\d,]+)", text)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def _parse_subscriber_count(text: str) -> int | None:
    """Parse subscriber count like '1.2M subscribers' -> 1200000."""
    if not text:
        return None
    normalized = " ".join(
        text.lower().translate(_LOCALIZED_DIGIT_TRANSLATION).split()
    )
    match = re.search(r"\d+(?:[.,]\d+)?", normalized)
    if not match:
        return None

    number_text = match.group(0)
    suffix_region = normalized[match.end() :].lstrip()
    multiplier = 1
    has_multiplier_suffix = False
    for alias, alias_multiplier in _SUBSCRIBER_MULTIPLIER_ALIASES:
        if suffix_region.startswith(alias):
            multiplier = alias_multiplier
            has_multiplier_suffix = True
            break

    if has_multiplier_suffix:
        number = float(number_text.replace(",", "."))
    else:
        number = float(number_text.replace(",", ""))
    return int(number * multiplier)
