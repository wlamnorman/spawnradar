"""Twitch enrichment module for the creator index.

Extracted from ``app.creator_index.adapters.twitch`` to allow reuse outside
the discovery pipeline.  All Helix / GQL call patterns, concurrency guards,
and error-handling are preserved exactly as they were in the adapter.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from app.creator_index.adapters.base import (
    AccountSeedBundle,
    ContactPointSeed,
    ContactType,
    ContentSampleSeed,
    ObservedGameSeed,
    SourceAccountSeed,
    TwitchProfileSeed,
)
from app.creator_index.adapters.common import (
    as_list,
    chunks,
    collect_text_contacts,
    count_recent_timestamps,
    extract_emails,
    mean_int,
    median_int,
    optional_int,
)
from app.creator_index.adapters.youtube_scraping import (
    YT_SCRAPE_HEADERS as _YT_SCRAPE_HEADERS,
)
from app.creator_index.adapters.youtube_scraping import (
    extract_initial_data as _yt_extract_initial_data,
)
from app.creator_index.adapters.youtube_scraping import (
    iter_renderers as _yt_iter_renderers,
)
from app.creator_index.twitch_http import twitch_request_json

_TWITCH_API_BASE = "https://api.twitch.tv/helix"
_TWITCH_AUTH_URL = "https://id.twitch.tv/oauth2/token"
_HEADERS = {
    "User-Agent": "SpawnRadar/1.0 (+https://spawnradar.com)",
    "Accept": "application/json",
}
_CLIP_FETCH_CONCURRENCY = 5
_VIDEO_FETCH_CONCURRENCY = 5
_CLIP_LOOKBACK_DAYS = 730  # ~2 years
_MAX_CONTENT_SAMPLES_PER_ACCOUNT = 5
_TWITCH_GQL_URL = "https://gql.twitch.tv/gql"
_TWITCH_GQL_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
_GQL_CHANNEL_QUERY = (
    "query ChannelExtra($login: String!) {"
    " user(login: $login) {"
    "  login"
    "  panels { id ... on DefaultPanel { description linkURL } }"
    "  channel { socialMedias { name url } }"
    " }"
    "}"
)
_GQL_PANEL_BATCH_SIZE = 35  # Twitch GQL allows up to ~35 ops per request
_YT_SCRAPE_CONCURRENCY = 3

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TwitchUser:
    user_id: str
    login: str
    display_name: str
    description: str | None
    profile_image_url: str | None


@dataclass(frozen=True)
class TwitchStreamRecord:
    user_id: str
    game_id: str | None
    game_name: str | None
    title: str | None
    tags: tuple[str, ...]
    viewer_count: int | None
    language: str | None
    started_at: str | None


@dataclass(frozen=True)
class TwitchChannelInfoRecord:
    broadcaster_id: str
    broadcaster_language: str | None
    title: str | None
    game_id: str | None
    game_name: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True)
class TwitchVideoRecord:
    video_id: str
    title: str
    description: str | None
    thumbnail_url: str | None
    created_at: str | None
    view_count: int | None
    url: str | None
    stream_id: str | None
    language: str | None
    game_id: str | None
    game_name: str | None
    video_type: str | None
    duration: str | None


@dataclass(frozen=True)
class TwitchClipRecord:
    clip_id: str
    broadcaster_id: str
    game_id: str
    title: str
    view_count: int | None
    created_at: str | None
    thumbnail_url: str | None
    url: str | None
    language: str | None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _clean_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _tags(value: object) -> tuple[str, ...]:
    return tuple(
        item.strip()
        for item in as_list(value)
        if isinstance(item, str) and item.strip()
    )


def _parse_user(item: Mapping[str, object]) -> TwitchUser | None:
    user_id = _clean_str(item.get("id"))
    login = _clean_str(item.get("login"))
    display_name = _clean_str(item.get("display_name"))
    if user_id is None or login is None or display_name is None:
        return None
    return TwitchUser(
        user_id=user_id,
        login=login,
        display_name=display_name,
        description=_clean_str(item.get("description")),
        profile_image_url=_clean_str(item.get("profile_image_url")),
    )


def _parse_stream_record(
    item: Mapping[str, object],
) -> TwitchStreamRecord | None:
    user_id = _clean_str(item.get("user_id"))
    if user_id is None:
        return None
    return TwitchStreamRecord(
        user_id=user_id,
        game_id=_clean_str(item.get("game_id")),
        game_name=_clean_str(item.get("game_name")),
        title=_clean_str(item.get("title")),
        tags=_tags(item.get("tags")),
        viewer_count=optional_int(item.get("viewer_count")),
        language=_clean_str(item.get("language")),
        started_at=_clean_str(item.get("started_at")),
    )


def _parse_channel_info_record(
    item: Mapping[str, object],
) -> TwitchChannelInfoRecord | None:
    broadcaster_id = _clean_str(item.get("broadcaster_id"))
    if broadcaster_id is None:
        return None
    return TwitchChannelInfoRecord(
        broadcaster_id=broadcaster_id,
        broadcaster_language=_clean_str(item.get("broadcaster_language")),
        title=_clean_str(item.get("title")),
        game_id=_clean_str(item.get("game_id")),
        game_name=_clean_str(item.get("game_name")),
        tags=_tags(item.get("tags")),
    )


def _parse_video_record(
    item: Mapping[str, object],
) -> TwitchVideoRecord | None:
    video_id = _clean_str(item.get("id"))
    title = _clean_str(item.get("title"))
    if video_id is None or title is None:
        return None
    return TwitchVideoRecord(
        video_id=video_id,
        title=title,
        description=_clean_str(item.get("description")),
        thumbnail_url=_clean_str(item.get("thumbnail_url")),
        created_at=_clean_str(item.get("created_at")),
        view_count=optional_int(item.get("view_count")),
        url=_clean_str(item.get("url")),
        stream_id=_clean_str(item.get("stream_id")),
        language=_clean_str(item.get("language")),
        game_id=_clean_str(item.get("game_id")),
        game_name=_clean_str(item.get("game_name")),
        video_type=_clean_str(item.get("type")),
        duration=_clean_str(item.get("duration")),
    )


def _parse_clip_record(
    item: Mapping[str, object],
) -> TwitchClipRecord | None:
    clip_id = _clean_str(item.get("id"))
    game_id = _clean_str(item.get("game_id"))
    title = _clean_str(item.get("title"))
    broadcaster_id = _clean_str(item.get("broadcaster_id"))
    if (
        clip_id is None
        or game_id is None
        or title is None
        or broadcaster_id is None
    ):
        return None
    return TwitchClipRecord(
        clip_id=clip_id,
        broadcaster_id=broadcaster_id,
        game_id=game_id,
        title=title,
        view_count=optional_int(item.get("view_count")),
        created_at=_clean_str(item.get("created_at")),
        thumbnail_url=_clean_str(item.get("thumbnail_url")),
        url=_clean_str(item.get("url")),
        language=_clean_str(item.get("language")),
    )


# ---------------------------------------------------------------------------
# Standalone helpers
# ---------------------------------------------------------------------------


_SOCIAL_LINK_DOMAINS = (
    "twitter.com/",
    "x.com/",
    "instagram.com/",
    "tiktok.com/",
    "bsky.app/",
    "youtube.com/",
    "youtu.be/",
)


def _extract_panel_contacts(
    panels: Sequence[dict],
    login: str,
    seen_emails: set[str],
    seen_discord: set[str],
) -> list[ContactPointSeed]:
    """Extract email, Discord, and social-link contact points from GQL panel data.

    Mutates *seen_emails* and *seen_discord* for cumulative deduplication
    across all contact sources in the bundle.
    """
    contacts: list[ContactPointSeed] = []
    source_url = f"https://www.twitch.tv/{login}"
    seen_socials: set[str] = set()

    for panel in panels:
        if not isinstance(panel, dict):
            continue

        description = panel.get("description") or ""
        link_url = panel.get("linkURL") or ""
        combined_text = f"{description} {link_url}"

        contacts.extend(
            collect_text_contacts(
                combined_text,
                source_kind="channel_panel",
                source_url=source_url,
                seen_emails=seen_emails,
                seen_discord=seen_discord,
            )
        )

        # Persist social links (X/Twitter, Instagram, Bluesky, YouTube)
        if link_url:
            link_lower = link_url.lower()
            if (
                any(d in link_lower for d in _SOCIAL_LINK_DOMAINS)
                and link_lower not in seen_socials
            ):
                seen_socials.add(link_lower)
                contacts.append(
                    ContactPointSeed(
                        contact_type=ContactType.SOCIAL_LINK,
                        contact_value=link_url,
                        source_kind="channel_social",
                        source_url=source_url,
                    )
                )
    return contacts


def _video_to_sample(
    *,
    login: str,
    video: TwitchVideoRecord,
    position_rank: int,
    fetched_at: str,
    expires_at: str,
) -> ContentSampleSeed | None:
    video_id = video.video_id
    title = video.title
    if not video_id or not title:
        return None
    return ContentSampleSeed(
        external_content_id=video_id,
        content_type="vod",
        title_or_text=title,
        body_text=video.description,
        url=video.url or f"https://www.twitch.tv/videos/{video_id}",
        thumbnail_url=video.thumbnail_url,
        published_at=video.created_at,
        engagement_count=video.view_count,
        language=video.language,
        position_rank=position_rank,
        fetched_at=fetched_at,
        expires_at=expires_at,
    )


def _infer_account_type(
    description: str | None, title: str | None, tags: Sequence[str]
) -> str:
    haystack = " ".join(
        part for part in [description or "", title or "", *tags] if part
    ).lower()
    if any(
        marker in haystack
        for marker in ("developer", "devlog", "gamedev", "indiedev")
    ):
        return "developer"
    return "creator"


def _append_observed_game(
    games_played: list[str],
    observed_games: list[ObservedGameSeed],
    *,
    game_name: str | None,
    game_id: str | None,
) -> None:
    if not game_name:
        return
    game_name_key = game_name.strip().lower()
    if not game_name_key:
        return
    if game_name_key not in {existing.lower() for existing in games_played}:
        games_played.append(game_name)
    if any(
        existing.game_name.strip().lower() == game_name_key
        and existing.platform_game_id == game_id
        for existing in observed_games
    ):
        return
    observed_games.append(
        ObservedGameSeed(
            game_name=game_name,
            platform_game_id=game_id,
        )
    )


def bundle_from_records(
    *,
    user: TwitchUser,
    channel_info: TwitchChannelInfoRecord | None,
    stream: TwitchStreamRecord | None,
    videos: Sequence[TwitchVideoRecord],
    clips: Sequence[TwitchClipRecord] = (),
    clip_game_names: dict[str, str] | None = None,
    follower_total: int | None,
    panels: Sequence[dict] = (),
    youtube_emails: Sequence[str] = (),
    clip_cursor: str | None = None,
    clips_exhausted: bool = False,
) -> AccountSeedBundle | None:
    """Assemble a full :class:`AccountSeedBundle` from enrichment data.

    This is the public counterpart of the former ``_bundle_from_records`` in
    ``twitch.py``.  It takes a :class:`TwitchUser` instead of a search-channel
    record so it can be used without running a search query first.
    """
    broadcaster_id = user.user_id
    login = user.login.strip().lower()
    display_name = user.display_name.strip() or login
    if not broadcaster_id or not login or not display_name:
        return None

    now = datetime.now(UTC)
    fetched_at = now.isoformat()
    expires_at = (now + timedelta(days=14)).isoformat()
    description = user.description
    avatar_url = user.profile_image_url
    language = (stream.language if stream is not None else None) or (
        channel_info.broadcaster_language if channel_info is not None else None
    )
    last_live_at = stream.started_at if stream is not None else None
    account_type = _infer_account_type(
        description,
        (stream.title if stream is not None else None)
        or (channel_info.title if channel_info is not None else None),
        (stream.tags if stream is not None else ())
        or (channel_info.tags if channel_info is not None else ()),
    )

    games_played: list[str] = []
    observed_games: list[ObservedGameSeed] = []
    for game_name, game_id in (
        (
            stream.game_name if stream is not None else None,
            stream.game_id if stream is not None else None,
        ),
        (
            channel_info.game_name if channel_info is not None else None,
            channel_info.game_id if channel_info is not None else None,
        ),
    ):
        _append_observed_game(
            games_played,
            observed_games,
            game_name=game_name,
            game_id=game_id,
        )

    for video in videos:
        _append_observed_game(
            games_played,
            observed_games,
            game_name=video.game_name,
            game_id=video.game_id,
        )

    resolved_names = clip_game_names or {}
    for clip in clips:
        clip_game_name = resolved_names.get(clip.game_id)
        if clip_game_name:
            _append_observed_game(
                games_played,
                observed_games,
                game_name=clip_game_name,
                game_id=clip.game_id,
            )

    content_samples_list: list[ContentSampleSeed] = []
    for position, video in enumerate(
        videos[:_MAX_CONTENT_SAMPLES_PER_ACCOUNT]
    ):
        sample = _video_to_sample(
            login=login,
            video=video,
            position_rank=position,
            fetched_at=fetched_at,
            expires_at=expires_at,
        )
        if sample is not None:
            content_samples_list.append(sample)
    content_samples = tuple(content_samples_list)

    # -- Contact points (cumulative dedup via shared seen-sets) --
    about_url = f"https://www.twitch.tv/{login}/about"
    seen_emails: set[str] = set()
    seen_discord: set[str] = set()
    contact_points_list: list[ContactPointSeed] = []

    # 1. Profile description
    contact_points_list.extend(
        collect_text_contacts(
            description,
            source_kind="profile_description",
            source_url=about_url,
            seen_emails=seen_emails,
            seen_discord=seen_discord,
        )
    )

    # 2. VOD descriptions
    for video in videos:
        contact_points_list.extend(
            collect_text_contacts(
                video.description,
                source_kind="video_description",
                source_url=video.url,
                seen_emails=seen_emails,
                seen_discord=seen_discord,
            )
        )

    # 3. Channel panels + social links
    contact_points_list.extend(
        _extract_panel_contacts(list(panels), login, seen_emails, seen_discord)
    )

    # 4. YouTube about page (cross-platform fallback)
    for email in youtube_emails:
        if email not in seen_emails:
            seen_emails.add(email)
            contact_points_list.append(
                ContactPointSeed(
                    contact_type=ContactType.EMAIL,
                    contact_value=email,
                    source_kind="youtube_about",
                    source_url=None,
                )
            )

    contact_points = tuple(contact_points_list)
    vod_view_counts = [
        sample.engagement_count
        for sample in content_samples
        if sample.engagement_count is not None
    ]

    return AccountSeedBundle(
        account=SourceAccountSeed(
            external_id=broadcaster_id,
            handle_current=login,
            display_name_current=display_name,
            canonical_url=f"https://www.twitch.tv/{login}",
            account_type=account_type,
        ),
        platform_profile=TwitchProfileSeed(
            broadcaster_id=broadcaster_id,
            login=login,
            display_name=display_name,
            description=description,
            followers_count=follower_total,
            viewer_count=stream.viewer_count if stream is not None else None,
            recent_avg_live_viewers=None,
            recent_median_live_viewers=None,
            recent_avg_vod_views=mean_int(vod_view_counts),
            recent_median_vod_views=median_int(vod_view_counts),
            streams_last_30d=count_recent_timestamps(
                [sample.published_at for sample in content_samples],
                days=30,
                now=now,
            ),
            language=language,
            games_played=tuple(games_played),
            avatar_url=avatar_url,
            last_live_at=last_live_at,
            fetched_at=fetched_at,
            expires_at=expires_at,
            clip_cursor=clip_cursor,
            clips_exhausted=clips_exhausted,
        ),
        content_samples=content_samples,
        contact_points=contact_points,
        observed_games=tuple(observed_games),
    )


# ---------------------------------------------------------------------------
# TwitchEnrichment class
# ---------------------------------------------------------------------------


class TwitchEnrichment:
    """Twitch Helix / GQL enrichment client.

    Manages its own OAuth token and provides methods for fetching user data,
    channel info, clips, followers, panels, and YouTube email scraping.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        timeout: float = 20.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout

    async def _fetch_app_access_token(self, client: httpx.AsyncClient) -> str:
        payload = await twitch_request_json(
            client,
            "POST",
            _TWITCH_AUTH_URL,
            params={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            },
        )
        token = str(payload.get("access_token", "")).strip()
        if not token:
            raise ValueError(
                "Twitch app access token missing from OAuth response."
            )
        return token

    async def _auth_headers(self, client: httpx.AsyncClient) -> dict[str, str]:
        access_token = await self._fetch_app_access_token(client)
        return {
            **_HEADERS,
            "Authorization": f"Bearer {access_token}",
            "Client-Id": self._client_id,
        }

    # -- Helix endpoints ----------------------------------------------------

    async def fetch_users(
        self,
        broadcaster_ids: list[str],
        client: httpx.AsyncClient | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, TwitchUser]:
        """Fetch Twitch users by broadcaster ID."""

        async def _run(
            c: httpx.AsyncClient, h: dict[str, str]
        ) -> dict[str, TwitchUser]:
            async def refresh_headers() -> dict[str, str]:
                nonlocal h
                h = await self._auth_headers(c)
                return h

            rows: dict[str, TwitchUser] = {}
            for chunk in chunks([bid for bid in broadcaster_ids if bid], 100):
                params = tuple(
                    ("id", broadcaster_id) for broadcaster_id in chunk
                )
                try:
                    body = await twitch_request_json(
                        c,
                        "GET",
                        f"{_TWITCH_API_BASE}/users",
                        params=params,
                        headers=h,
                        refresh_headers=refresh_headers,
                    )
                except (httpx.HTTPError, ValueError) as exc:
                    log.warning(
                        "Skipping Twitch users chunk %s: %s", chunk, exc
                    )
                    continue
                for item in as_list(body.get("data")):
                    if not isinstance(item, dict):
                        continue
                    user = _parse_user(item)
                    if user is not None:
                        rows[user.user_id] = user
            return rows

        if client is not None and headers is not None:
            return await _run(client, headers)
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=_HEADERS
        ) as c:
            h = await self._auth_headers(c)
            return await _run(c, h)

    async def fetch_channel_info(
        self,
        broadcaster_ids: list[str],
        client: httpx.AsyncClient | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, TwitchChannelInfoRecord]:
        """Fetch channel info for broadcaster IDs."""

        async def _run(
            c: httpx.AsyncClient, h: dict[str, str]
        ) -> dict[str, TwitchChannelInfoRecord]:
            async def refresh_headers() -> dict[str, str]:
                nonlocal h
                h = await self._auth_headers(c)
                return h

            rows: dict[str, TwitchChannelInfoRecord] = {}
            for chunk in chunks([bid for bid in broadcaster_ids if bid], 100):
                params = tuple(
                    ("broadcaster_id", broadcaster_id)
                    for broadcaster_id in chunk
                )
                try:
                    body = await twitch_request_json(
                        c,
                        "GET",
                        f"{_TWITCH_API_BASE}/channels",
                        params=params,
                        headers=h,
                        refresh_headers=refresh_headers,
                    )
                except (httpx.HTTPError, ValueError) as exc:
                    log.warning(
                        "Skipping Twitch channel info chunk %s: %s", chunk, exc
                    )
                    continue
                for item in as_list(body.get("data")):
                    if not isinstance(item, dict):
                        continue
                    channel_info = _parse_channel_info_record(item)
                    if channel_info is not None:
                        rows[channel_info.broadcaster_id] = channel_info
            return rows

        if client is not None and headers is not None:
            return await _run(client, headers)
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=_HEADERS
        ) as c:
            h = await self._auth_headers(c)
            return await _run(c, h)

    async def fetch_streams(
        self,
        broadcaster_ids: list[str],
        client: httpx.AsyncClient | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, TwitchStreamRecord]:
        """Fetch current live stream state for broadcaster IDs."""

        async def _run(
            c: httpx.AsyncClient, h: dict[str, str]
        ) -> dict[str, TwitchStreamRecord]:
            async def refresh_headers() -> dict[str, str]:
                nonlocal h
                h = await self._auth_headers(c)
                return h

            rows: dict[str, TwitchStreamRecord] = {}
            for chunk in chunks([bid for bid in broadcaster_ids if bid], 100):
                params = tuple(
                    ("user_id", broadcaster_id) for broadcaster_id in chunk
                )
                try:
                    body = await twitch_request_json(
                        c,
                        "GET",
                        f"{_TWITCH_API_BASE}/streams",
                        params=params,
                        headers=h,
                        refresh_headers=refresh_headers,
                    )
                except (httpx.HTTPError, ValueError) as exc:
                    log.warning(
                        "Skipping Twitch streams chunk %s: %s", chunk, exc
                    )
                    continue
                for item in as_list(body.get("data")):
                    if not isinstance(item, dict):
                        continue
                    stream = _parse_stream_record(item)
                    if stream is not None:
                        rows[stream.user_id] = stream
            return rows

        if client is not None and headers is not None:
            return await _run(client, headers)
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=_HEADERS
        ) as c:
            h = await self._auth_headers(c)
            return await _run(c, h)

    async def fetch_videos_for_users(
        self,
        broadcaster_ids: list[str],
        *,
        limit_per_user: int = _MAX_CONTENT_SAMPLES_PER_ACCOUNT,
        client: httpx.AsyncClient | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, list[TwitchVideoRecord]]:
        """Fetch recent archived videos for broadcaster IDs."""

        async def _run(
            c: httpx.AsyncClient, h: dict[str, str]
        ) -> dict[str, list[TwitchVideoRecord]]:
            async def refresh_headers() -> dict[str, str]:
                nonlocal h
                h = await self._auth_headers(c)
                return h

            rows: dict[str, list[TwitchVideoRecord]] = {}
            semaphore = asyncio.Semaphore(_VIDEO_FETCH_CONCURRENCY)
            page_size = max(1, min(limit_per_user, 100))

            async def fetch_user_videos(broadcaster_id: str) -> None:
                async with semaphore:
                    try:
                        body = await twitch_request_json(
                            c,
                            "GET",
                            f"{_TWITCH_API_BASE}/videos",
                            params={
                                "user_id": broadcaster_id,
                                "type": "archive",
                                "sort": "time",
                                "first": page_size,
                            },
                            headers=h,
                            refresh_headers=refresh_headers,
                        )
                    except (httpx.HTTPError, ValueError) as exc:
                        log.warning(
                            "Skipping Twitch videos for %s: %s",
                            broadcaster_id,
                            exc,
                        )
                        rows[broadcaster_id] = []
                        return

                    videos: list[TwitchVideoRecord] = []
                    for item in as_list(body.get("data")):
                        if not isinstance(item, dict):
                            continue
                        video = _parse_video_record(item)
                        if video is not None:
                            videos.append(video)
                    rows[broadcaster_id] = videos

            await asyncio.gather(
                *(
                    fetch_user_videos(broadcaster_id)
                    for broadcaster_id in sorted({*broadcaster_ids})
                    if broadcaster_id
                )
            )
            return rows

        if client is not None and headers is not None:
            return await _run(client, headers)
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=_HEADERS
        ) as c:
            h = await self._auth_headers(c)
            return await _run(c, h)

    async def fetch_clips_for_users(
        self,
        broadcaster_ids: list[str],
        client: httpx.AsyncClient | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, list[TwitchClipRecord]]:
        """Fetch clips for broadcaster IDs with Semaphore(5) and 730-day lookback."""

        async def _run(
            c: httpx.AsyncClient, h: dict[str, str]
        ) -> dict[str, list[TwitchClipRecord]]:
            async def refresh_headers() -> dict[str, str]:
                nonlocal h
                h = await self._auth_headers(c)
                return h

            semaphore = asyncio.Semaphore(_CLIP_FETCH_CONCURRENCY)
            rows: dict[str, list[TwitchClipRecord]] = {}
            now = datetime.now(UTC)
            started_at = (now - timedelta(days=_CLIP_LOOKBACK_DAYS)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

            async def fetch_user_clips(broadcaster_id: str) -> None:
                async with semaphore:
                    clips: list[TwitchClipRecord] = []
                    cursor: str | None = None
                    # Fetch up to 2 pages (200 clips max) to stay within rate budget
                    for _ in range(2):
                        params: dict[str, str | int] = {
                            "broadcaster_id": broadcaster_id,
                            "first": 100,
                            "started_at": started_at,
                        }
                        if cursor:
                            params["after"] = cursor
                        try:
                            body = await twitch_request_json(
                                c,
                                "GET",
                                f"{_TWITCH_API_BASE}/clips",
                                params=params,
                                headers=h,
                                refresh_headers=refresh_headers,
                            )
                        except (httpx.HTTPError, ValueError) as exc:
                            log.warning(
                                "Skipping Twitch clips for %s: %s",
                                broadcaster_id,
                                exc,
                            )
                            break
                        for item in as_list(body.get("data")):
                            if isinstance(item, dict):
                                clip = _parse_clip_record(item)
                                if clip is not None:
                                    clips.append(clip)
                        pagination = body.get("pagination")
                        cursor = (
                            pagination.get("cursor")
                            if isinstance(pagination, dict)
                            else None
                        )
                        if not cursor:
                            break
                    rows[broadcaster_id] = clips

            await asyncio.gather(
                *(
                    fetch_user_clips(broadcaster_id)
                    for broadcaster_id in sorted({*broadcaster_ids})
                )
            )
            return rows

        if client is not None and headers is not None:
            return await _run(client, headers)
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=_HEADERS
        ) as c:
            h = await self._auth_headers(c)
            return await _run(c, h)

    async def fetch_follower_totals(
        self,
        broadcaster_ids: list[str],
        client: httpx.AsyncClient | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, int]:
        """Fetch follower counts for broadcaster IDs."""

        async def _run(
            c: httpx.AsyncClient, h: dict[str, str]
        ) -> dict[str, int]:
            async def refresh_headers() -> dict[str, str]:
                nonlocal h
                h = await self._auth_headers(c)
                return h

            follower_totals: dict[str, int] = {}

            async def fetch_total(broadcaster_id: str) -> None:
                try:
                    body = await twitch_request_json(
                        c,
                        "GET",
                        f"{_TWITCH_API_BASE}/channels/followers",
                        params={"broadcaster_id": broadcaster_id, "first": 1},
                        headers=h,
                        refresh_headers=refresh_headers,
                    )
                except (httpx.HTTPError, ValueError):
                    return

                if not isinstance(body, Mapping):
                    return
                total = optional_int(body.get("total"))
                if total is not None:
                    follower_totals[broadcaster_id] = total

            await asyncio.gather(
                *(
                    fetch_total(broadcaster_id)
                    for broadcaster_id in sorted({*broadcaster_ids})
                )
            )
            return follower_totals

        if client is not None and headers is not None:
            return await _run(client, headers)
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=_HEADERS
        ) as c:
            h = await self._auth_headers(c)
            return await _run(c, h)

    async def fetch_panels(
        self,
        logins: list[str],
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, list[dict]]:
        """Fetch channel panels and social links via Twitch GQL.

        Returns ``{login: [panel_dict, ...]}``.  Social media entries are
        normalised into the same shape as panels (with ``linkURL``) so
        downstream contact extraction works uniformly.
        """

        async def _run(c: httpx.AsyncClient) -> dict[str, list[dict]]:
            if not logins:
                return {}
            results: dict[str, list[dict]] = {login: [] for login in logins}

            unique_logins = sorted({*logins})
            for batch_start in range(
                0, len(unique_logins), _GQL_PANEL_BATCH_SIZE
            ):
                batch = unique_logins[
                    batch_start : batch_start + _GQL_PANEL_BATCH_SIZE
                ]
                payload = [
                    {
                        "operationName": "ChannelExtra",
                        "variables": {"login": login},
                        "query": _GQL_CHANNEL_QUERY,
                    }
                    for login in batch
                ]
                try:
                    resp = await c.post(
                        _TWITCH_GQL_URL,
                        json=payload,
                        headers={
                            "Client-ID": _TWITCH_GQL_CLIENT_ID,
                            "Content-Type": "application/json",
                        },
                    )
                    resp.raise_for_status()
                    responses = resp.json()
                    if not isinstance(responses, list):
                        continue
                    for item in responses:
                        if not isinstance(item, dict):
                            continue
                        user = (item.get("data") or {}).get("user")
                        if not isinstance(user, dict):
                            continue
                        login_key = (
                            str(user.get("login") or "").strip().lower()
                        )
                        if not login_key:
                            continue

                        combined: list[dict] = []
                        panels_data = user.get("panels")
                        if isinstance(panels_data, list):
                            combined.extend(panels_data)

                        # Normalise social media entries into panel-like dicts
                        channel = user.get("channel")
                        if isinstance(channel, dict):
                            for sm in channel.get("socialMedias") or []:
                                if isinstance(sm, dict) and sm.get("url"):
                                    combined.append(
                                        {
                                            "description": None,
                                            "linkURL": sm["url"],
                                        }
                                    )

                        results[login_key] = combined
                except Exception as exc:
                    log.debug(
                        "GQL channel-extra fetch failed for batch of %d: %s",
                        len(batch),
                        exc,
                    )
            return results

        if client is not None:
            return await _run(client)
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=_HEADERS
        ) as c:
            return await _run(c)

    async def scrape_youtube_emails(
        self,
        panels_by_login: dict[str, list[dict]],
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, list[str]]:
        """Scrape YouTube about pages for emails when Twitch data has none.

        For each login whose panels contain a YouTube social link but no
        email, fetch the YouTube channel page and extract emails from the
        about description.  Returns ``{login: [email, ...]}``.
        """

        async def _run(c: httpx.AsyncClient) -> dict[str, list[str]]:
            # Build {login: youtube_url} for channels that lack email in panels
            targets: dict[str, str] = {}
            for login, panels in panels_by_login.items():
                has_email = any(
                    extract_emails(p.get("description") or "")
                    for p in panels
                    if isinstance(p, dict)
                )
                if has_email:
                    continue
                for panel in panels:
                    if not isinstance(panel, dict):
                        continue
                    link = panel.get("linkURL") or ""
                    if "youtube.com/" in link or "youtu.be/" in link:
                        targets[login] = link
                        break

            if not targets:
                return {}

            semaphore = asyncio.Semaphore(_YT_SCRAPE_CONCURRENCY)
            results: dict[str, list[str]] = {}

            async def scrape(login: str, yt_url: str) -> None:
                async with semaphore:
                    try:
                        # Normalise to www.youtube.com so consent cookies apply
                        url = yt_url.split("?")[0]  # strip tracking params
                        url = url.replace("http://", "https://")
                        url = url.replace(
                            "https://youtube.com/", "https://www.youtube.com/"
                        )
                        resp = await c.get(
                            url,
                            headers=_YT_SCRAPE_HEADERS,
                            follow_redirects=True,
                        )
                        resp.raise_for_status()
                        data = _yt_extract_initial_data(resp.text)
                        for vm in _yt_iter_renderers(
                            data, "aboutChannelViewModel"
                        ):
                            desc = str(vm.get("description") or "")
                            emails = extract_emails(desc)
                            if emails:
                                results[login] = emails
                            break
                    except Exception as exc:
                        log.debug(
                            "YouTube email scrape failed for %s (%s): %s",
                            login,
                            yt_url,
                            exc,
                        )

            await asyncio.gather(
                *(scrape(login, url) for login, url in targets.items())
            )
            return results

        if client is not None:
            return await _run(client)
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=_HEADERS
        ) as c:
            return await _run(c)

    async def resolve_game_names(
        self,
        game_ids: set[str],
        client: httpx.AsyncClient | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Resolve Twitch game IDs to display names via GET /helix/games."""

        async def _run(
            c: httpx.AsyncClient, h: dict[str, str]
        ) -> dict[str, str]:
            async def refresh_headers() -> dict[str, str]:
                nonlocal h
                h = await self._auth_headers(c)
                return h

            if not game_ids:
                return {}
            names: dict[str, str] = {}
            for chunk in chunks(sorted(game_ids), 100):
                params = tuple(("id", gid) for gid in chunk)
                try:
                    body = await twitch_request_json(
                        c,
                        "GET",
                        f"{_TWITCH_API_BASE}/games",
                        params=params,
                        headers=h,
                        refresh_headers=refresh_headers,
                    )
                except (httpx.HTTPError, ValueError) as exc:
                    log.warning("Skipping game name resolution chunk: %s", exc)
                    continue
                for item in as_list(body.get("data")):
                    if isinstance(item, dict):
                        gid = _clean_str(item.get("id"))
                        name = _clean_str(item.get("name"))
                        if gid and name:
                            names[gid] = name
            return names

        if client is not None and headers is not None:
            return await _run(client, headers)
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=_HEADERS
        ) as c:
            h = await self._auth_headers(c)
            return await _run(c, h)

    def extract_panel_contacts(
        self,
        panels: list[dict],
        login: str,
        seen_emails: set[str] | None = None,
        seen_discord: set[str] | None = None,
    ) -> list[ContactPointSeed]:
        """Extract contact points from panel data."""
        return _extract_panel_contacts(
            panels,
            login,
            seen_emails if seen_emails is not None else set(),
            seen_discord if seen_discord is not None else set(),
        )

    # -- High-level orchestrator --------------------------------------------

    async def enrich_broadcaster(
        self,
        broadcaster_id: str,
        *,
        skip_contacts: bool = False,
    ) -> AccountSeedBundle | None:
        """Orchestrate full enrichment for a single broadcaster ID.

        Fetches user, channel info, clips, followers, and optionally panels
        plus contacts.  Returns an :class:`AccountSeedBundle` or ``None`` if
        the user could not be resolved.
        """
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=_HEADERS
        ) as client:
            auth = await self._auth_headers(client)

            users_by_id = await self.fetch_users(
                [broadcaster_id], client=client, headers=auth
            )
            user = users_by_id.get(broadcaster_id)
            if user is None:
                return None

            login = user.login.strip().lower()

            (
                channels_by_id,
                streams_by_id,
                videos_by_user,
                clips_by_user,
                followers,
            ) = await asyncio.gather(
                self.fetch_channel_info(
                    [broadcaster_id], client=client, headers=auth
                ),
                self.fetch_streams(
                    [broadcaster_id], client=client, headers=auth
                ),
                self.fetch_videos_for_users(
                    [broadcaster_id], client=client, headers=auth
                ),
                self.fetch_clips_for_users(
                    [broadcaster_id], client=client, headers=auth
                ),
                self.fetch_follower_totals(
                    [broadcaster_id], client=client, headers=auth
                ),
            )

            # Resolve clip game names
            all_clip_game_ids: set[str] = set()
            for user_clips in clips_by_user.values():
                for clip in user_clips:
                    all_clip_game_ids.add(clip.game_id)
            try:
                clip_game_names = await self.resolve_game_names(
                    all_clip_game_ids, client=client, headers=auth
                )
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("Clip game name resolution failed: %s", exc)
                clip_game_names = {}

            panels_by_login: dict[str, list[dict]] = {}
            yt_emails_by_login: dict[str, list[str]] = {}
            if not skip_contacts:
                panels_by_login = await self.fetch_panels(
                    [login], client=client
                )
                yt_emails_by_login = await self.scrape_youtube_emails(
                    panels_by_login, client=client
                )

            return bundle_from_records(
                user=user,
                channel_info=channels_by_id.get(broadcaster_id),
                stream=streams_by_id.get(broadcaster_id),
                videos=videos_by_user.get(broadcaster_id, []),
                clips=clips_by_user.get(broadcaster_id, []),
                clip_game_names=clip_game_names,
                follower_total=followers.get(broadcaster_id),
                panels=panels_by_login.get(login, []),
                youtube_emails=yt_emails_by_login.get(login, []),
            )

    async def deepen_broadcaster_clips(
        self,
        broadcaster_id: str,
        *,
        cursor: str | None,
    ) -> tuple[list[ObservedGameSeed], str | None, bool]:
        """Fetch one additional page of clips for a known broadcaster.

        Uses a stored pagination *cursor* to resume where the last
        enrichment left off.  Returns ``(new_games, next_cursor,
        exhausted)`` — the caller persists new games and updates the
        cursor state.

        This is a lightweight enrichment pass: 1 API call for clips +
        1 for game name resolution (if new game IDs found).
        """
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=_HEADERS
        ) as client:
            auth = await self._auth_headers(client)

            now = datetime.now(UTC)
            started_at = (now - timedelta(days=_CLIP_LOOKBACK_DAYS)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            params: dict[str, str | int] = {
                "broadcaster_id": broadcaster_id,
                "first": 100,
                "started_at": started_at,
            }
            if cursor:
                params["after"] = cursor

            try:
                body = await twitch_request_json(
                    client,
                    "GET",
                    f"{_TWITCH_API_BASE}/clips",
                    params=params,
                    headers=auth,
                )
            except (httpx.HTTPError, ValueError) as exc:
                log.warning(
                    "Clip deepening failed for %s: %s", broadcaster_id, exc,
                )
                return [], cursor, False

            clips: list[TwitchClipRecord] = []
            for item in as_list(body.get("data")):
                if isinstance(item, dict):
                    clip = _parse_clip_record(item)
                    if clip is not None:
                        clips.append(clip)

            pagination = body.get("pagination")
            next_cursor = (
                pagination.get("cursor")
                if isinstance(pagination, dict)
                else None
            )
            exhausted = not next_cursor or len(clips) < 100

            # Resolve game IDs to names
            game_ids = {
                clip.game_id for clip in clips
                if clip.game_id and clip.game_id != "0"
            }
            game_names: dict[str, str] = {}
            if game_ids:
                game_names = await self.resolve_game_names(
                    game_ids, client=client, headers=auth,
                )

            # Build ObservedGameSeed list
            observed: list[ObservedGameSeed] = []
            seen_keys: set[str] = set()
            for clip in clips:
                if not clip.game_id or clip.game_id == "0":
                    continue
                game_name = game_names.get(clip.game_id)
                if not game_name:
                    continue
                key = game_name.lower()
                if key not in seen_keys:
                    seen_keys.add(key)
                    observed.append(
                        ObservedGameSeed(
                            game_name=game_name,
                            platform_game_id=clip.game_id,
                        )
                    )

            log.debug(
                "Clip deepening for %s: %d clips, %d new games, exhausted=%s",
                broadcaster_id, len(clips), len(observed), exhausted,
            )
            return observed, next_cursor, exhausted
