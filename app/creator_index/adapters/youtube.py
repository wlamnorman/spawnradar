"""YouTube Data API adapter for the background creator index."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from app.creator_index.adapters.base import (
    AccountSeedAdapter,
    AccountSeedBundle,
    ContactPointSeed,
    ContactType,
    ContentSampleSeed,
    SourceAccountSeed,
    YouTubeChannelSeed,
)
from app.creator_index.adapters.common import (
    as_list,
    chunks,
    count_recent_timestamps,
    extract_emails,
    mean_int,
    median_int,
    optional_int,
)
from app.creator_index.adapters.youtube_scraping import (
    CHANNEL_FILTER,
    YOUTUBE_SEARCH_URL,
    YT_SCRAPE_HEADERS,
)
from app.creator_index.adapters.youtube_scraping import (
    extract_initial_data as _extract_initial_data,
)
from app.creator_index.adapters.youtube_scraping import (
    iter_renderers as _iter_renderers,
)
from app.games.models import CustomerGame
from app.runtime import SourceRuntime

_YT_API_BASE = "https://www.googleapis.com/youtube/v3"
_HEADERS = {
    "User-Agent": "SpawnRadar/1.0 (+https://spawnradar.com)",
    "Accept": "application/json",
}
_SCRAPE_HEADERS = YT_SCRAPE_HEADERS
log = logging.getLogger(__name__)


class YouTubeChannelAdapter(AccountSeedAdapter):
    """Discover YouTube channels and recent uploads for the local creator index."""

    platform = "youtube"

    def __init__(self, api_key: str, *, timeout_seconds: float = 20.0) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds

    @classmethod
    def build(cls, runtime: SourceRuntime) -> YouTubeChannelAdapter:
        if not runtime.youtube_api_key:
            raise ValueError(
                "YouTube source-index adapter requires a YouTube API key."
            )
        return cls(runtime.youtube_api_key)

    async def lookup_channel_by_url(
        self, url: str, db_path: str
    ) -> str | None:
        """Resolve a YouTube channel URL to a ``source_accounts.account_id``.

        Accepts ``https://youtube.com/@handle`` and
        ``https://youtube.com/channel/UCxxxxxxx`` forms.  The channel is
        upserted into ``source_accounts`` so later queries can join on it.

        Returns the ``account_id`` string if resolved, else ``None``.
        """
        import re as _re

        from app.database import get_connection

        handle_match = _re.search(r"/@([\w.-]+)", url)
        channel_match = _re.search(r"/channel/(UC[\w-]+)", url)

        if handle_match:
            param = {"forHandle": f"@{handle_match.group(1)}"}
        elif channel_match:
            param = {"id": channel_match.group(1)}
        else:
            return None

        params = {"part": "id,snippet", "key": self._api_key, **param}
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=_HEADERS
        ) as client:
            resp = await client.get(
                f"{_YT_API_BASE}/channels", params=params
            )
        if resp.status_code != 200:
            return None
        items = resp.json().get("items", [])
        if not items:
            return None

        channel_id = str(items[0].get("id", "")).strip()
        if not channel_id:
            return None

        now = datetime.now(UTC).isoformat()
        account_id = f"sa_yt_{channel_id}"
        with get_connection(db_path) as con:
            con.execute(
                """INSERT INTO source_accounts
                   (account_id, platform, external_id, handle_current,
                    display_name_current, canonical_url, account_type, status,
                    first_seen_at, last_seen_at, created_at, updated_at)
                   VALUES (?, 'youtube', ?, ?, ?, ?, 'creator', 'active',
                           ?, ?, ?, ?)
                   ON CONFLICT(platform, external_id) DO UPDATE SET
                       last_seen_at = excluded.last_seen_at,
                       updated_at = excluded.updated_at""",
                (
                    account_id,
                    channel_id,
                    items[0].get("snippet", {}).get("customUrl") or channel_id,
                    items[0].get("snippet", {}).get("title") or channel_id,
                    f"https://www.youtube.com/channel/{channel_id}",
                    now, now, now, now,
                ),
            )
            # Return the actual account_id (may differ if row already existed)
            row = con.execute(
                "SELECT account_id FROM source_accounts WHERE platform='youtube' AND external_id=?",
                (channel_id,),
            ).fetchone()
        return row[0] if row else None

    async def discover_game_accounts(
        self,
        customer_game: CustomerGame,
        limit: int,
        *,
        page_cursors: dict[str, str] | None = None,
        skip_external_ids: frozenset[str] = frozenset(),
    ) -> Sequence[AccountSeedBundle]:
        return await self._discover_queries(
            _build_queries(customer_game), limit, skip_external_ids
        )

    async def discover_seed_accounts(
        self,
        query_text: str,
        limit: int,
        *,
        page_cursors: dict[str, str] | None = None,
        skip_external_ids: frozenset[str] = frozenset(),
    ) -> Sequence[AccountSeedBundle]:
        return await self._discover_queries(
            [query_text], limit, skip_external_ids
        )

    async def _discover_queries(
        self,
        queries: Sequence[str],
        limit: int,
        skip_external_ids: frozenset[str] = frozenset(),
    ) -> Sequence[AccountSeedBundle]:
        bundles: list[AccountSeedBundle] = []
        seen_channel_ids: set[str] = set(skip_external_ids)

        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers=_SCRAPE_HEADERS,
            follow_redirects=True,
        ) as client:
            # Phase 1: scrape channel IDs — paced to look like natural browsing
            #   4–6 searches at a time, 2–5s between each, 30–90s between groups
            all_channel_ids: list[str] = []
            batch_size = random.randint(4, 6)
            for i, query in enumerate(queries):
                if i > 0 and i % batch_size == 0:
                    pause = random.uniform(30, 90)
                    log.info("Scrape batch done — pausing %.0fs", pause)
                    await asyncio.sleep(pause)
                    batch_size = random.randint(4, 6)
                elif i > 0:
                    await asyncio.sleep(random.uniform(2, 5))

                log.info("YouTube scrape search: %r", query)
                try:
                    ids = await self._scrape_channel_ids(
                        client, query, max_results=15
                    )
                except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                    log.warning("Skipping YouTube query %r: %s", query, exc)
                    continue
                new_ids = [c for c in ids if c not in seen_channel_ids]
                seen_channel_ids.update(new_ids)
                all_channel_ids.extend(new_ids)
                log.info(
                    "YouTube scrape %r → %d new channel(s)",
                    query,
                    len(new_ids),
                )

            # Phase 1b: scrape About pages — paced, 2–5s between each
            about_data: dict[str, dict[str, Any]] = {}
            for channel_id in all_channel_ids[:limit]:
                await asyncio.sleep(random.uniform(2, 5))
                about_data[channel_id] = await self._scrape_about_page(
                    client, channel_id
                )

            # Phase 2: enrich via V3 API — no artificial delays, use quota freely
            for batch in chunks(all_channel_ids[:limit], 50):
                if len(bundles) >= limit:
                    break
                try:
                    channels = await self._fetch_channels(client, batch)
                    uploads_map = {
                        cid: _uploads_playlist_id(ch)
                        for cid, ch in channels.items()
                    }
                    playlist_items = await self._fetch_uploads_for_channels(
                        client, uploads_map
                    )
                    video_details = await self._fetch_video_details(
                        client, _playlist_video_ids(playlist_items)
                    )
                except (httpx.HTTPError, ValueError) as exc:
                    log.warning("Enrichment batch failed: %s", exc)
                    continue

                for channel_id in batch:
                    bundle = _bundle_from_records(
                        channel=channels.get(channel_id),
                        uploads=_enrich_uploads(
                            playlist_items.get(channel_id, []), video_details
                        ),
                        about=about_data.get(channel_id),
                    )
                    if bundle is not None:
                        log.info(
                            "YouTube channel accepted: %s (%s)",
                            bundle.account.display_name_current,
                            bundle.account.canonical_url,
                        )
                        bundles.append(bundle)
                    if len(bundles) >= limit:
                        break

        return bundles

    async def _scrape_channel_ids(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        max_results: int = 15,
    ) -> list[str]:
        """Discover channel IDs by scraping YouTube search HTML — no API key needed."""
        response = await client.get(
            YOUTUBE_SEARCH_URL,
            params={"search_query": query, "sp": CHANNEL_FILTER},
        )
        response.raise_for_status()
        data = _extract_initial_data(response.text)
        channel_ids: list[str] = []
        for renderer in _iter_renderers(data, "channelRenderer"):
            channel_id = str(renderer.get("channelId", "")).strip()
            if channel_id and channel_id not in channel_ids:
                channel_ids.append(channel_id)
                if len(channel_ids) >= max_results:
                    break
        return channel_ids

    async def _scrape_about_page(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
    ) -> dict[str, Any]:
        """Scrape the channel About page for full description, social links, and country.

        Returns a dict with keys: full_description, social_links, country.
        All values may be None/empty if the page structure has changed or the
        request fails — callers must treat this data as best-effort.
        """
        result: dict[str, Any] = {
            "full_description": None,
            "social_links": [],
            "country": None,
        }
        try:
            response = await client.get(
                f"https://www.youtube.com/channel/{channel_id}/about",
            )
            response.raise_for_status()
            data = _extract_initial_data(response.text)
        except Exception as exc:
            log.warning("About page scrape failed for %s: %s", channel_id, exc)
            return result

        # New structure (2025): aboutChannelViewModel for description/country
        for vm in _iter_renderers(data, "aboutChannelViewModel"):
            desc = str(vm.get("description") or "").strip()
            result["full_description"] = desc or None
            country = str(vm.get("country") or "").strip()
            result["country"] = country or None
            break  # only need the first match

        # New structure (2025): channelExternalLinkViewModel — one per social link
        for vm in _iter_renderers(data, "channelExternalLinkViewModel"):
            link = _extract_external_link(vm)
            if link:
                result["social_links"].append(link)

        return result

    async def _fetch_channels(
        self,
        client: httpx.AsyncClient,
        channel_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        if not channel_ids:
            return {}
        response = await client.get(
            f"{_YT_API_BASE}/channels",
            params={
                "part": "snippet,statistics,contentDetails,brandingSettings",
                "id": ",".join(channel_ids),
                "key": self._api_key,
            },
        )
        response.raise_for_status()
        body = response.json()
        rows: dict[str, dict[str, Any]] = {}
        for item in as_list(body.get("items")):
            if not isinstance(item, dict):
                continue
            channel_id = str(item.get("id", "")).strip()
            if channel_id:
                rows[channel_id] = item
        return rows

    async def _fetch_uploads_for_channels(
        self,
        client: httpx.AsyncClient,
        uploads_map: dict[str, str | None],
    ) -> dict[str, list[dict[str, Any]]]:
        rows: dict[str, list[dict[str, Any]]] = {}

        async def fetch_uploads(channel_id: str, playlist_id: str) -> None:
            try:
                response = await client.get(
                    f"{_YT_API_BASE}/playlistItems",
                    params={
                        "part": "snippet,contentDetails",
                        "playlistId": playlist_id,
                        "maxResults": 5,
                        "key": self._api_key,
                    },
                )
                response.raise_for_status()
                body = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                log.warning(
                    "Skipping YouTube uploads for channel %s playlist %s: %s",
                    channel_id,
                    playlist_id,
                    exc,
                )
                rows[channel_id] = []
                return

            rows[channel_id] = [
                item
                for item in as_list(body.get("items"))
                if isinstance(item, dict)
            ]

        await asyncio.gather(
            *(
                fetch_uploads(channel_id, playlist_id)
                for channel_id, playlist_id in uploads_map.items()
                if playlist_id
            )
        )
        return rows

    async def _fetch_video_details(
        self,
        client: httpx.AsyncClient,
        video_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        if not video_ids:
            return {}
        rows: dict[str, dict[str, Any]] = {}
        for chunk in chunks(video_ids, 50):
            try:
                response = await client.get(
                    f"{_YT_API_BASE}/videos",
                    params={
                        "part": "snippet,statistics",
                        "id": ",".join(chunk),
                        "key": self._api_key,
                    },
                )
                response.raise_for_status()
                body = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                log.warning(
                    "Skipping YouTube video stats chunk %s: %s", chunk, exc
                )
                continue
            for item in as_list(body.get("items")):
                if not isinstance(item, dict):
                    continue
                video_id = str(item.get("id", "")).strip()
                if video_id:
                    rows[video_id] = item
        return rows


def _build_queries(customer_game: CustomerGame) -> list[str]:
    """Build simple search queries from the customer game name."""
    name = customer_game.name.strip()
    if not name:
        return []
    return [
        f"{name} gameplay",
        f"{name} review",
        f"{name} lets play",
    ]


def _bundle_from_records(
    *,
    channel: Mapping[str, object] | None,
    uploads: Sequence[Mapping[str, object]],
    about: dict[str, Any] | None = None,
) -> AccountSeedBundle | None:
    if not channel:
        return None
    channel_id = str(channel.get("id", "")).strip()
    snippet = channel.get("snippet")
    channel_statistics = channel.get("statistics")
    branding_value = _mapping_value(channel.get("brandingSettings"), "channel")
    branding = branding_value if isinstance(branding_value, Mapping) else {}
    if not channel_id or not isinstance(snippet, dict):
        return None

    display_name = str(snippet.get("title", "")).strip()
    if not display_name:
        return None
    if display_name.endswith(" - Topic"):
        return None

    subscriber_count = optional_int(
        _mapping_value(channel_statistics, "subscriberCount")
    )
    if subscriber_count is not None and subscriber_count < 100:
        return None

    now = datetime.now(UTC)
    fetched_at = now.isoformat()
    expires_at = (now + timedelta(days=14)).isoformat()
    description = str(snippet.get("description") or "").strip() or None
    thumbnails = snippet.get("thumbnails")
    avatar_url = _best_thumbnail_url(thumbnails)
    custom_url = str(snippet.get("customUrl") or "").strip() or None
    uploads_playlist_id = _uploads_playlist_id(channel)
    channel_created_at = str(snippet.get("publishedAt") or "").strip() or None
    country = (
        str(
            (about or {}).get("country") or branding.get("country") or ""
        ).strip()
        or None
    )
    last_upload_at = None

    content_samples: list[ContentSampleSeed] = []
    for position, upload in enumerate(uploads):
        sample = _upload_to_sample(
            upload,
            position_rank=position,
            fetched_at=fetched_at,
            expires_at=expires_at,
        )
        if sample is None:
            continue
        content_samples.append(sample)
        if last_upload_at is None:
            last_upload_at = sample.published_at
    view_counts = [
        sample.engagement_count
        for sample in content_samples
        if sample.engagement_count is not None
    ]

    # Channel-level language from the channel snippet (rarely populated by YouTube).
    # Fallback to video audio languages is handled in the facets layer.
    default_language = (
        str(snippet.get("defaultLanguage") or "").strip() or None
    )

    # Use the fullest description available for email extraction
    about_description = (about or {}).get("full_description")
    richest_description = about_description or description
    contact_points: list[ContactPointSeed] = [
        ContactPointSeed(
            contact_type=ContactType.EMAIL,
            contact_value=email,
            source_kind="channel_description",
            source_url=f"https://www.youtube.com/channel/{channel_id}/about",
        )
        for email in extract_emails(richest_description)
    ]
    for _link_title, link_url in (about or {}).get("social_links", []):
        contact_points.append(
            ContactPointSeed(
                contact_type=ContactType.SOCIAL_LINK,
                contact_value=link_url,
                source_kind="channel_about",
                source_url=f"https://www.youtube.com/channel/{channel_id}/about",
            )
        )

    return AccountSeedBundle(
        account=SourceAccountSeed(
            external_id=channel_id,
            handle_current=custom_url or channel_id,
            display_name_current=display_name,
            canonical_url=f"https://www.youtube.com/channel/{channel_id}",
        ),
        platform_profile=YouTubeChannelSeed(
            channel_id=channel_id,
            handle=custom_url,
            display_name=display_name,
            description=description,
            subscriber_count=subscriber_count,
            video_count=optional_int(
                _mapping_value(channel_statistics, "videoCount")
            ),
            recent_avg_views=mean_int(view_counts),
            recent_median_views=median_int(view_counts),
            uploads_last_30d=count_recent_timestamps(
                [sample.published_at for sample in content_samples],
                days=30,
                now=now,
            ),
            default_language=default_language,
            country=country,
            channel_created_at=channel_created_at,
            avatar_url=avatar_url,
            uploads_playlist_id=uploads_playlist_id,
            last_upload_at=last_upload_at,
            fetched_at=fetched_at,
            expires_at=expires_at,
            raw_payload_json=dict(channel),
        ),
        content_samples=tuple(content_samples),
        contact_points=tuple(contact_points),
    )


def _upload_to_sample(
    upload: Mapping[str, object],
    *,
    position_rank: int,
    fetched_at: str,
    expires_at: str,
) -> ContentSampleSeed | None:
    content_details = upload.get("contentDetails")
    snippet = upload.get("snippet")
    video_details = upload.get("video_details")
    if not isinstance(content_details, dict) or not isinstance(snippet, dict):
        return None
    video_id = str(content_details.get("videoId", "")).strip()
    title = str(snippet.get("title", "")).strip()
    if not video_id or not title:
        return None
    detail_statistics = _mapping_value(video_details, "statistics")
    detail_snippet = _mapping_value(video_details, "snippet")
    return ContentSampleSeed(
        external_content_id=video_id,
        content_type="video",
        title_or_text=title,
        body_text=(
            str(_mapping_value(detail_snippet, "description") or "").strip()
            or str(snippet.get("description") or "").strip()
            or None
        ),
        url=f"https://www.youtube.com/watch?v={video_id}",
        thumbnail_url=_best_thumbnail_url(snippet.get("thumbnails")),
        published_at=str(snippet.get("publishedAt") or "").strip() or None,
        engagement_count=optional_int(
            _mapping_value(detail_statistics, "viewCount")
        ),
        language=(
            str(
                _mapping_value(detail_snippet, "defaultAudioLanguage") or ""
            ).strip()
            or str(
                _mapping_value(detail_snippet, "defaultLanguage") or ""
            ).strip()
            or None
        ),
        position_rank=position_rank,
        fetched_at=fetched_at,
        expires_at=expires_at,
        raw_payload_json={
            "playlist_item": dict(upload),
            "video_details": (
                dict(video_details) if isinstance(video_details, Mapping) else {}
            ),
        },
    )


def _best_thumbnail_url(thumbnails: object) -> str | None:
    if not isinstance(thumbnails, Mapping):
        return None
    for key in ("high", "medium", "default"):
        value = thumbnails.get(key)
        if isinstance(value, Mapping):
            url = str(value.get("url", "")).strip()
            if url:
                return url
    return None


def _uploads_playlist_id(channel: Mapping[str, object]) -> str | None:
    content_details = channel.get("contentDetails")
    if not isinstance(content_details, Mapping):
        return None
    related_playlists = content_details.get("relatedPlaylists")
    if not isinstance(related_playlists, Mapping):
        return None
    uploads = str(related_playlists.get("uploads", "")).strip()
    return uploads or None


def _mapping_value(mapping: object, key: str) -> object | None:
    if not isinstance(mapping, Mapping):
        return None
    return mapping.get(key)


def _extract_external_link(vm: dict[str, Any]) -> tuple[str, str] | None:
    """Extract (title, url) from a ``channelExternalLinkViewModel`` node.

    YouTube's About page (2025 structure) wraps each social link in one of these.
    The real URL is buried inside ``commandRuns``; the display URL in ``link.content``
    is a fallback.
    """
    title = str((vm.get("title") or {}).get("content") or "").strip()
    link_node = vm.get("link") or {}
    command_runs = link_node.get("commandRuns") or []
    if command_runs and isinstance(command_runs[0], dict):
        raw_url = (
            command_runs[0]
            .get("onTap", {})
            .get("innertubeCommand", {})
            .get("commandMetadata", {})
            .get("webCommandMetadata", {})
            .get("url", "")
        )
    else:
        display = str(link_node.get("content") or "").strip()
        raw_url = f"https://{display}" if display else ""

    if not raw_url:
        return None
    if "youtube.com/redirect" in raw_url:
        qs = parse_qs(urlparse(raw_url).query)
        real_url = next(iter(qs.get("q", [])), raw_url)
    else:
        real_url = raw_url
    return (title, real_url) if real_url else None


def _extract_social_links(links: object) -> list[tuple[str, str]]:
    """Extract (title, url) pairs from a YouTube About page primaryLinks list.

    YouTube wraps external URLs in redirect links of the form:
    ``https://www.youtube.com/redirect?...&q=https%3A%2F%2Ftwitter.com%2F...``
    This helper unwraps the ``q`` parameter to return the real URL.
    """
    if not isinstance(links, list):
        return []
    result: list[tuple[str, str]] = []
    for link in links:
        if not isinstance(link, dict):
            continue
        title_node = link.get("title", {})
        title = str(title_node.get("simpleText") or "").strip() or "".join(
            r.get("text", "")
            for r in title_node.get("runs", [])
            if isinstance(r, dict)
        )
        raw_url = str(
            _mapping_value(
                _mapping_value(link.get("navigationEndpoint"), "urlEndpoint"),
                "url",
            )
            or ""
        ).strip()
        if not raw_url:
            continue
        # Unwrap YouTube redirect
        if "youtube.com/redirect" in raw_url:
            qs = parse_qs(urlparse(raw_url).query)
            real_url = next(iter(qs.get("q", [])), raw_url)
        else:
            real_url = raw_url
        if real_url:
            result.append((title, real_url))
    return result


def _playlist_video_ids(
    uploads_by_channel: dict[str, list[dict[str, Any]]],
) -> list[str]:
    seen: set[str] = set()
    video_ids: list[str] = []
    for uploads in uploads_by_channel.values():
        for upload in uploads:
            video_id = str(
                _mapping_value(
                    _mapping_value(upload, "contentDetails"), "videoId"
                )
                or ""
            ).strip()
            if not video_id or video_id in seen:
                continue
            seen.add(video_id)
            video_ids.append(video_id)
    return video_ids


def _enrich_uploads(
    uploads: Sequence[Mapping[str, object]],
    video_details: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for upload in uploads:
        upload_dict = dict(upload)
        video_id = str(
            _mapping_value(_mapping_value(upload, "contentDetails"), "videoId")
            or ""
        ).strip()
        if video_id and video_id in video_details:
            upload_dict["video_details"] = video_details[video_id]
        enriched.append(upload_dict)
    return enriched
