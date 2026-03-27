"""Twitch Helix adapter for the background creator index."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from app.creator_index.adapters.base import (
    AccountSeedAdapter,
    AccountSeedBundle,
    ContactPointSeed,
    ContentSampleSeed,
    ObservedGameSeed,
    SourceAccountSeed,
    TwitchProfileSeed,
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
from app.creator_index.twitch_http import twitch_request_json
from app.games.models import CustomerGame
from app.igdb.taxonomy import IGDBGenre, IGDBTheme
from app.runtime import SourceRuntime

_TWITCH_API_BASE = "https://api.twitch.tv/helix"
_TWITCH_AUTH_URL = "https://id.twitch.tv/oauth2/token"
_HEADERS = {
    "User-Agent": "SpawnRadar/1.0 (+https://spawnradar.com)",
    "Accept": "application/json",
}
_VIDEO_FETCH_CONCURRENCY = 5
_CLIP_FETCH_CONCURRENCY = 5
_CLIP_LOOKBACK_DAYS = 730  # ~2 years
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TwitchSearchChannel:
    broadcaster_id: str
    broadcaster_login: str
    display_name: str
    title: str | None
    thumbnail_url: str | None
    broadcaster_language: str | None
    game_id: str | None
    game_name: str | None
    tags: tuple[str, ...]
    is_live: bool
    started_at: str | None


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


class TwitchAccountAdapter(AccountSeedAdapter):
    """Discover Twitch channels and recent VODs for the local creator index."""

    platform = "twitch"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout_seconds

    @classmethod
    def build(cls, runtime: SourceRuntime) -> TwitchAccountAdapter:
        if not runtime.twitch_client_id or not runtime.twitch_client_secret:
            raise ValueError(
                "Twitch source-index adapter requires Twitch API credentials."
            )
        return cls(runtime.twitch_client_id, runtime.twitch_client_secret)

    async def discover_game_accounts(
        self,
        customer_game: CustomerGame,
        limit: int,
        *,
        page_cursors: dict[str, str] | None = None,
        skip_external_ids: frozenset[str] = frozenset(),
    ) -> Sequence[AccountSeedBundle]:
        return await self._discover_queries(
            _build_queries(customer_game),
            limit,
            page_cursors=page_cursors,
            skip_external_ids=skip_external_ids,
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
            [query_text],
            limit,
            page_cursors=page_cursors,
            skip_external_ids=skip_external_ids,
        )

    async def _discover_queries(
        self,
        queries: Sequence[str],
        limit: int,
        *,
        page_cursors: dict[str, str] | None = None,
        skip_external_ids: frozenset[str] = frozenset(),
    ) -> Sequence[AccountSeedBundle]:
        cursors = page_cursors if page_cursors is not None else {}
        bundles: list[AccountSeedBundle] = []
        seen_ids: set[str] = set(skip_external_ids)

        async with httpx.AsyncClient(
            timeout=self._timeout, headers=_HEADERS
        ) as client:
            access_token = await self._fetch_app_access_token(client)
            auth_headers = {
                **_HEADERS,
                "Authorization": f"Bearer {access_token}",
                "Client-Id": self._client_id,
            }

            for query_text in queries:
                if len(bundles) >= limit:
                    break

                cursor_key = f"search:{query_text}"
                try:
                    channels, next_cursor = await self._search_channels(
                        client,
                        auth_headers,
                        query_text,
                        first=min(10, max(5, limit)),
                        cursor=cursors.get(cursor_key),
                    )
                    if next_cursor:
                        cursors[cursor_key] = next_cursor
                    else:
                        cursors.pop(cursor_key, None)

                    fresh_channels = []
                    for channel in channels:
                        broadcaster_id = channel.broadcaster_id
                        if not broadcaster_id or broadcaster_id in seen_ids:
                            continue
                        seen_ids.add(broadcaster_id)
                        fresh_channels.append(channel)
                        if len(fresh_channels) + len(bundles) >= limit:
                            break

                    if not fresh_channels:
                        skipped_existing = len(channels)
                        log.info(
                            "Twitch query %r yielded no fresh channels (raw=%d skipped_existing_or_invalid=%d)",
                            query_text,
                            len(channels),
                            skipped_existing,
                        )
                        continue

                    broadcaster_ids = [
                        item.broadcaster_id for item in fresh_channels
                    ]
                    (
                        users_by_id,
                        channels_by_id,
                        streams_by_user,
                        videos_by_user,
                        followers,
                    ) = await asyncio.gather(
                        self._fetch_users(
                            client, auth_headers, broadcaster_ids
                        ),
                        self._fetch_channel_info(
                            client, auth_headers, broadcaster_ids
                        ),
                        self._fetch_streams(
                            client, auth_headers, broadcaster_ids
                        ),
                        self._fetch_videos_for_users(
                            client, auth_headers, broadcaster_ids
                        ),
                        self._fetch_follower_totals(
                            client, auth_headers, broadcaster_ids
                        ),
                    )
                except (httpx.HTTPError, ValueError) as exc:
                    log.warning(
                        "Skipping Twitch query %s due to API error: %s",
                        query_text,
                        exc,
                    )
                    cursors.pop(cursor_key, None)
                    continue

                bundles_before_query = len(bundles)
                for channel in fresh_channels:
                    broadcaster_id = channel.broadcaster_id
                    bundle = _bundle_from_records(
                        channel=channel,
                        user=users_by_id.get(broadcaster_id),
                        channel_info=channels_by_id.get(broadcaster_id),
                        stream=streams_by_user.get(broadcaster_id),
                        videos=videos_by_user.get(broadcaster_id, []),
                        follower_total=followers.get(broadcaster_id),
                    )
                    if bundle is not None:
                        bundles.append(bundle)
                    if len(bundles) >= limit:
                        break
                log.info(
                    "Twitch query %r: raw_channels=%d fresh_channels=%d bundles_added=%d total_bundles=%d limit=%d",
                    query_text,
                    len(channels),
                    len(fresh_channels),
                    len(bundles) - bundles_before_query,
                    len(bundles),
                    limit,
                )

        return bundles

    async def fetch_accounts_by_ids(
        self,
        broadcaster_ids: list[str],
    ) -> Sequence[AccountSeedBundle]:
        """Fetch full profiles for known broadcaster IDs and return bundles."""
        if not broadcaster_ids:
            return []

        bundles: list[AccountSeedBundle] = []
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=_HEADERS
        ) as client:
            access_token = await self._fetch_app_access_token(client)
            auth_headers = {
                **_HEADERS,
                "Authorization": f"Bearer {access_token}",
                "Client-Id": self._client_id,
            }

            for chunk in chunks(broadcaster_ids, 100):
                try:
                    (
                        users_by_id,
                        channels_by_id,
                        streams_by_user,
                        videos_by_user,
                        followers,
                    ) = await asyncio.gather(
                        self._fetch_users(client, auth_headers, chunk),
                        self._fetch_channel_info(
                            client, auth_headers, chunk
                        ),
                        self._fetch_streams(client, auth_headers, chunk),
                        self._fetch_videos_for_users(
                            client, auth_headers, chunk
                        ),
                        self._fetch_follower_totals(
                            client, auth_headers, chunk
                        ),
                    )
                except (httpx.HTTPError, ValueError) as exc:
                    log.warning(
                        "Skipping chunk of %d IDs due to API error: %s",
                        len(chunk),
                        exc,
                    )
                    continue

                bundles_before_chunk = len(bundles)
                for bid in chunk:
                    user = users_by_id.get(bid)
                    if user is None:
                        continue
                    channel = TwitchSearchChannel(
                        broadcaster_id=bid,
                        broadcaster_login=user.login,
                        display_name=user.display_name,
                        title=user.description,
                        thumbnail_url=user.profile_image_url,
                        broadcaster_language=None,
                        game_id=None,
                        game_name=None,
                        tags=(),
                        is_live=False,
                        started_at=None,
                    )
                    bundle = _bundle_from_records(
                        channel=channel,
                        user=user,
                        channel_info=channels_by_id.get(bid),
                        stream=streams_by_user.get(bid),
                        videos=videos_by_user.get(bid, []),
                        follower_total=followers.get(bid),
                    )
                    if bundle is not None:
                        bundles.append(bundle)
                log.info(
                    "Fetched Twitch account chunk: requested=%d users=%d channels=%d live_streams=%d video_sets=%d followers=%d bundles_added=%d",
                    len(chunk),
                    len(users_by_id),
                    len(channels_by_id),
                    len(streams_by_user),
                    len(videos_by_user),
                    len(followers),
                    len(bundles) - bundles_before_chunk,
                )
        return bundles

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

    async def _search_channels(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        query: str,
        *,
        first: int,
        cursor: str | None = None,
    ) -> tuple[list[TwitchSearchChannel], str | None]:
        params: dict[str, str | int] = {"query": query, "first": first}
        if cursor:
            params["after"] = cursor
        body = await twitch_request_json(
            client,
            "GET",
            f"{_TWITCH_API_BASE}/search/channels",
            params=params,
            headers=headers,
        )
        pagination = body.get("pagination")
        next_cursor = (
            pagination.get("cursor") if isinstance(pagination, dict) else None
        )
        rows = [
            _parse_search_channel(item)
            for item in as_list(body.get("data"))
            if isinstance(item, dict)
        ]
        rows = [row for row in rows if row is not None]
        return rows, str(next_cursor).strip() if next_cursor else None

    async def _fetch_users(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        broadcaster_ids: list[str],
    ) -> dict[str, TwitchUser]:
        rows: dict[str, TwitchUser] = {}
        for chunk in chunks([bid for bid in broadcaster_ids if bid], 100):
            params = tuple(("id", broadcaster_id) for broadcaster_id in chunk)
            try:
                body = await twitch_request_json(
                    client,
                    "GET",
                    f"{_TWITCH_API_BASE}/users",
                    params=params,
                    headers=headers,
                )
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("Skipping Twitch users chunk %s: %s", chunk, exc)
                continue
            for item in as_list(body.get("data")):
                if not isinstance(item, dict):
                    continue
                user = _parse_user(item)
                if user is not None:
                    rows[user.user_id] = user
        return rows

    async def _fetch_streams(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        broadcaster_ids: list[str],
    ) -> dict[str, TwitchStreamRecord]:
        rows: dict[str, TwitchStreamRecord] = {}
        for chunk in chunks([bid for bid in broadcaster_ids if bid], 100):
            params = tuple(
                ("user_id", broadcaster_id) for broadcaster_id in chunk
            )
            try:
                body = await twitch_request_json(
                    client,
                    "GET",
                    f"{_TWITCH_API_BASE}/streams",
                    params=params,
                    headers=headers,
                )
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("Skipping Twitch streams chunk %s: %s", chunk, exc)
                continue
            for item in as_list(body.get("data")):
                if not isinstance(item, dict):
                    continue
                stream = _parse_stream_record(item)
                if stream is not None:
                    rows[stream.user_id] = stream
        return rows

    async def _fetch_channel_info(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        broadcaster_ids: list[str],
    ) -> dict[str, TwitchChannelInfoRecord]:
        rows: dict[str, TwitchChannelInfoRecord] = {}
        for chunk in chunks([bid for bid in broadcaster_ids if bid], 100):
            params = tuple(
                ("broadcaster_id", broadcaster_id)
                for broadcaster_id in chunk
            )
            try:
                body = await twitch_request_json(
                    client,
                    "GET",
                    f"{_TWITCH_API_BASE}/channels",
                    params=params,
                    headers=headers,
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

    async def _fetch_videos_for_users(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        broadcaster_ids: list[str],
    ) -> dict[str, list[TwitchVideoRecord]]:
        semaphore = asyncio.Semaphore(_VIDEO_FETCH_CONCURRENCY)
        rows: dict[str, list[TwitchVideoRecord]] = {}

        async def fetch_user_videos(broadcaster_id: str) -> None:
            async with semaphore:
                try:
                    body = await twitch_request_json(
                        client,
                        "GET",
                        f"{_TWITCH_API_BASE}/videos",
                        params={
                            "user_id": broadcaster_id,
                            "first": 20,
                            "period": "month",
                            "sort": "time",
                        },
                        headers=headers,
                    )
                except (httpx.HTTPError, ValueError) as exc:
                    log.warning(
                        "Skipping Twitch videos for %s: %s",
                        broadcaster_id,
                        exc,
                    )
                    rows[broadcaster_id] = []
                    return
                rows[broadcaster_id] = [
                    video
                    for item in as_list(body.get("data"))
                    if isinstance(item, dict)
                    for video in [_parse_video_record(item)]
                    if video is not None
                ]

        await asyncio.gather(
            *(
                fetch_user_videos(broadcaster_id)
                for broadcaster_id in sorted({*broadcaster_ids})
            )
        )
        return rows

    async def _fetch_follower_totals(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        broadcaster_ids: list[str],
    ) -> dict[str, int]:
        follower_totals: dict[str, int] = {}

        async def fetch_total(broadcaster_id: str) -> None:
            try:
                body = await twitch_request_json(
                    client,
                    "GET",
                    f"{_TWITCH_API_BASE}/channels/followers",
                    params={"broadcaster_id": broadcaster_id, "first": 1},
                    headers=headers,
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

    async def _fetch_clips_for_users(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        broadcaster_ids: list[str],
    ) -> dict[str, list[TwitchClipRecord]]:
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
                            client,
                            "GET",
                            f"{_TWITCH_API_BASE}/clips",
                            params=params,
                            headers=headers,
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

    async def _resolve_game_names(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        game_ids: set[str],
    ) -> dict[str, str]:
        """Resolve Twitch game IDs to display names via GET /helix/games."""
        if not game_ids:
            return {}
        names: dict[str, str] = {}
        for chunk in chunks(sorted(game_ids), 100):
            params = tuple(("id", gid) for gid in chunk)
            try:
                body = await twitch_request_json(
                    client,
                    "GET",
                    f"{_TWITCH_API_BASE}/games",
                    params=params,
                    headers=headers,
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


def _build_queries(customer_game: CustomerGame) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        queries.append(cleaned)

    add(customer_game.name)

    genre_labels = IGDBGenre.labels_for_ids(customer_game.igdb_genre_ids)
    for label in genre_labels:
        add(label)

    # If a game has no genre tags locally, fall back to a few bare theme labels.
    if len(queries) == 1:
        theme_labels = IGDBTheme.labels_for_ids(customer_game.igdb_theme_ids)
        for label in theme_labels[:3]:
            add(label)

    return queries


def _bundle_from_records(
    *,
    channel: TwitchSearchChannel,
    user: TwitchUser | None,
    channel_info: TwitchChannelInfoRecord | None,
    stream: TwitchStreamRecord | None,
    videos: Sequence[TwitchVideoRecord],
    clips: Sequence[TwitchClipRecord] = (),
    clip_game_names: dict[str, str] | None = None,
    follower_total: int | None,
) -> AccountSeedBundle | None:
    broadcaster_id = channel.broadcaster_id
    login = channel.broadcaster_login.strip().lower()
    display_name = channel.display_name.strip() or login
    if not broadcaster_id or not login or not display_name:
        return None

    now = datetime.now(UTC)
    fetched_at = now.isoformat()
    expires_at = (now + timedelta(days=14)).isoformat()
    description = user.description if user is not None else None
    avatar_url = (
        user.profile_image_url if user is not None else None
    ) or channel.thumbnail_url
    language = (
        (stream.language if stream is not None else None)
        or (
            channel_info.broadcaster_language
            if channel_info is not None
            else None
        )
        or channel.broadcaster_language
    )
    last_live_at = (stream.started_at if stream is not None else None) or (
        channel.started_at
    )
    account_type = _infer_account_type(
        description,
        (stream.title if stream is not None else None)
        or (channel_info.title if channel_info is not None else None)
        or channel.title,
        (stream.tags if stream is not None else ())
        or (channel_info.tags if channel_info is not None else ())
        or channel.tags,
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
        (channel.game_name, channel.game_id),
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
    for position, video in enumerate(videos):
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

    contact_points = tuple(
        ContactPointSeed(
            contact_type="email",
            contact_value=email,
            source_kind="profile_description",
            source_url=f"https://www.twitch.tv/{login}/about",
        )
        for email in extract_emails(description)
    )
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
        ),
        content_samples=content_samples,
        contact_points=contact_points,
        observed_games=tuple(observed_games),
    )


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


def _parse_search_channel(
    item: Mapping[str, object],
) -> TwitchSearchChannel | None:
    broadcaster_id = _clean_str(item.get("id"))
    broadcaster_login = _clean_str(item.get("broadcaster_login"))
    display_name = _clean_str(item.get("display_name"))
    if broadcaster_id is None or broadcaster_login is None or display_name is None:
        return None
    return TwitchSearchChannel(
        broadcaster_id=broadcaster_id,
        broadcaster_login=broadcaster_login,
        display_name=display_name,
        title=_clean_str(item.get("title")),
        thumbnail_url=_clean_str(item.get("thumbnail_url")),
        broadcaster_language=_clean_str(item.get("broadcaster_language")),
        game_id=_clean_str(item.get("game_id")),
        game_name=_clean_str(item.get("game_name")),
        tags=_tags(item.get("tags")),
        is_live=bool(item.get("is_live")),
        started_at=_clean_str(item.get("started_at")),
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
    if clip_id is None or game_id is None or title is None or broadcaster_id is None:
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
