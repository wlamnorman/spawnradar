"""Twitch enrichment module for the creator index.

Extracted from ``app.creator_index.adapters.twitch`` to allow reuse outside
the discovery pipeline.  All Helix / GQL call patterns, concurrency guards,
and error-handling are preserved exactly as they were in the adapter.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import httpx

from app.creator_index.adapters.base import (
    AccountSeedBundle,
    ContactPointSeed,
    ObservedGameSeed,
)
from app.creator_index.adapters.common import (
    as_list,
    chunks,
    extract_emails,
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
from app.creator_index.twitch_bundle import (
    _extract_panel_contacts,
)
from app.creator_index.twitch_bundle import (
    _infer_account_type as _infer_account_type,  # noqa: F401
)
from app.creator_index.twitch_bundle import (
    bundle_from_records as bundle_from_records,  # noqa: F401
)
from app.creator_index.twitch_http import twitch_request_json

# -- Backward-compatible re-exports ------------------------------------------
from app.creator_index.twitch_records import (  # noqa: F401
    TwitchChannelInfoRecord,
    TwitchClipRecord,
    TwitchStreamRecord,
    TwitchUser,
    TwitchVideoRecord,
    _clean_str,
    _parse_channel_info_record,
    _parse_clip_record,
    _parse_stream_record,
    _parse_user,
    _parse_video_record,
)

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
        exhausted)`` --- the caller persists new games and updates the
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
