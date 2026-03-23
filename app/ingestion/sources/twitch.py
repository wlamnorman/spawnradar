"""Twitch creator discovery via the Helix API."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Collection, Mapping
from dataclasses import replace
from typing import Any

import httpx

from app.games.models import Game
from app.ingestion.base import CandidateRecord, CandidateSource, SourceRuntime
from app.ingestion.query_builder import TaggedQuery, build_tagged_queries
from app.ingestion.raw_data import TwitchChannelData
from app.ingestion.registry import Source, register

_TWITCH_API_BASE = "https://api.twitch.tv/helix"
_TWITCH_AUTH_URL = "https://id.twitch.tv/oauth2/token"
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_HEADERS = {
    "User-Agent": "SpawnRadar/1.0 (+https://spawnradar.com)",
    "Accept": "application/json",
}
_MIN_VIEWER_COUNT = 3
_FOLLOWER_FETCH_CONCURRENCY = 8

log = logging.getLogger(__name__)

_DEV_KEYWORDS = (
    "developer",
    "devlog",
    "gamedev",
    "game dev",
    "indiedev",
    "indie dev",
    "software and game development",
)


@register(Source.TWITCH)
class TwitchSource(CandidateSource):
    """Discover live Twitch channels relevant to a game's tags."""

    platform = "twitch"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        delay_seconds: float = 0.25,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._delay = delay_seconds
        self._timeout = timeout_seconds

    @classmethod
    def build(cls, runtime: SourceRuntime) -> TwitchSource:
        if not runtime.twitch_client_id or not runtime.twitch_client_secret:
            raise ValueError(
                "Twitch source requires TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET."
            )
        return cls(runtime.twitch_client_id, runtime.twitch_client_secret)

    async def discover(
        self,
        game: Game,
        limit: int,
        *,
        run_index: int = 0,
        excluded_handles: Collection[str] | None = None,
        page_cursors: dict[str, str] | None = None,
    ) -> list[CandidateRecord]:
        queries = _build_queries(game, run_index)
        seen_handles = {handle.lower() for handle in (excluded_handles or ())}
        candidates: list[CandidateRecord] = []
        collect_target = min(limit * (4 if run_index else 2), 120)
        cursors = page_cursors if page_cursors is not None else {}

        async with httpx.AsyncClient(
            timeout=self._timeout, headers=_HEADERS
        ) as client:
            access_token = await self._fetch_app_access_token(client)
            auth_headers = {
                **_HEADERS,
                "Authorization": f"Bearer {access_token}",
                "Client-Id": self._client_id,
            }

            search_results: list[tuple[dict[str, Any], TaggedQuery]] = []
            for i, tagged_query in enumerate(queries):
                if len(search_results) >= collect_target:
                    break

                cursor_key = f"search:{tagged_query.text}"
                try:
                    batch, next_cursor = await self._search_channels(
                        client,
                        auth_headers,
                        tagged_query,
                        min(limit, 20),
                        cursor=cursors.get(cursor_key),
                    )
                except Exception:
                    continue

                if next_cursor:
                    cursors[cursor_key] = next_cursor
                else:
                    cursors.pop(cursor_key, None)

                for channel in batch:
                    handle = (
                        str(channel.get("broadcaster_login", ""))
                        .strip()
                        .lower()
                    )
                    if not handle or handle in seen_handles:
                        continue
                    seen_handles.add(handle)
                    search_results.append((channel, tagged_query))
                    if len(search_results) >= collect_target:
                        break

                if i < len(queries) - 1:
                    await asyncio.sleep(self._delay)

            candidates = await self._enrich_results(
                client, auth_headers, search_results
            )

        return candidates[:limit]

    async def _fetch_app_access_token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            _TWITCH_AUTH_URL,
            params={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            },
        )
        response.raise_for_status()
        payload = response.json()
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
        tagged_query: TaggedQuery,
        limit: int,
        *,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        params: dict[str, str | int | bool] = {
            "query": tagged_query.text,
            "live_only": True,
            "first": limit,
        }
        if cursor:
            params["after"] = cursor

        response = await client.get(
            f"{_TWITCH_API_BASE}/search/channels",
            params=params,
            headers=headers,
        )
        response.raise_for_status()
        body = response.json()
        pagination = body.get("pagination")
        next_cursor = (
            pagination.get("cursor") if isinstance(pagination, dict) else None
        )
        records = [
            item
            for item in _as_list(body.get("data"))
            if isinstance(item, dict)
        ]
        return records, str(next_cursor).strip() if next_cursor else None

    async def _enrich_results(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        search_results: list[tuple[dict[str, Any], TaggedQuery]],
    ) -> list[CandidateRecord]:
        if not search_results:
            return []

        broadcaster_ids = [
            str(result[0].get("id", "")).strip() for result in search_results
        ]
        users_by_id = await self._fetch_users(client, headers, broadcaster_ids)
        streams_by_user = await self._fetch_streams(
            client, headers, broadcaster_ids
        )

        candidate_rows: list[tuple[str, CandidateRecord]] = []
        for channel, tagged_query in search_results:
            broadcaster_id = str(channel.get("id", "")).strip()
            candidate = _candidate_from_search_result(
                channel,
                users_by_id.get(broadcaster_id),
                streams_by_user.get(broadcaster_id),
                tagged_query,
            )
            if candidate is not None:
                candidate_rows.append((broadcaster_id, candidate))

        follower_totals = await self._fetch_follower_totals(
            client,
            headers,
            [broadcaster_id for broadcaster_id, _candidate in candidate_rows],
        )

        return [
            _with_follower_count(
                candidate, follower_totals.get(broadcaster_id)
            )
            for broadcaster_id, candidate in candidate_rows
        ]

    async def _fetch_users(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        broadcaster_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for chunk in _chunks([bid for bid in broadcaster_ids if bid], 100):
            params = tuple(("id", bid) for bid in chunk)
            response = await client.get(
                f"{_TWITCH_API_BASE}/users",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            body = response.json()
            for item in _as_list(body.get("data")):
                if not isinstance(item, dict):
                    continue
                user_id = str(item.get("id", "")).strip()
                if user_id:
                    rows[user_id] = item
        return rows

    async def _fetch_streams(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        broadcaster_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for chunk in _chunks([bid for bid in broadcaster_ids if bid], 100):
            params = tuple(("user_id", bid) for bid in chunk)
            response = await client.get(
                f"{_TWITCH_API_BASE}/streams",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            body = response.json()
            for item in _as_list(body.get("data")):
                if not isinstance(item, dict):
                    continue
                user_id = str(item.get("user_id", "")).strip()
                if user_id:
                    rows[user_id] = item
        return rows

    async def _fetch_follower_totals(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        broadcaster_ids: list[str],
    ) -> dict[str, int]:
        """Return Twitch follower totals keyed by broadcaster ID.

        Helix's Get Channel Followers endpoint returns the aggregate ``total``
        even when the caller lacks moderator-level follower visibility. We use
        that public total to enrich cards, but discovery still succeeds if
        Twitch tightens the behavior or any request fails.
        """
        follower_totals: dict[str, int] = {}
        semaphore = asyncio.Semaphore(_FOLLOWER_FETCH_CONCURRENCY)

        async def fetch_total(broadcaster_id: str) -> None:
            async with semaphore:
                try:
                    response = await client.get(
                        f"{_TWITCH_API_BASE}/channels/followers",
                        params={"broadcaster_id": broadcaster_id, "first": 1},
                        headers=headers,
                    )
                    response.raise_for_status()
                    body = response.json()
                except (httpx.HTTPError, ValueError) as exc:
                    log.debug(
                        "Skipping Twitch follower enrichment for %s: %s",
                        broadcaster_id,
                        exc,
                    )
                    return

            if not isinstance(body, Mapping):
                return

            total = _optional_int(body.get("total"))
            if total is not None:
                follower_totals[broadcaster_id] = total

        await asyncio.gather(
            *(
                fetch_total(broadcaster_id)
                for broadcaster_id in sorted(
                    {bid for bid in broadcaster_ids if bid}
                )
            )
        )
        return follower_totals


def _build_queries(game: Game, run_index: int = 0) -> list[TaggedQuery]:
    return build_tagged_queries(
        game,
        suffixes=("games", "streamer", "indie"),
        prefixes=("indie",),
        game_name_suffixes=("demo", "playtest"),
        run_index=run_index,
    )


def _candidate_from_search_result(
    channel: Mapping[str, object],
    user: Mapping[str, object] | None,
    stream: Mapping[str, object] | None,
    tagged_query: TaggedQuery,
) -> CandidateRecord | None:
    broadcaster_id = str(channel.get("id", "")).strip()
    login = str(channel.get("broadcaster_login", "")).strip().lower()
    if not broadcaster_id or not login:
        return None

    user = user or {}
    stream = stream or {}

    display_name = str(
        channel.get("display_name") or user.get("display_name") or login
    ).strip()
    description = str(user.get("description", "")).strip() or None
    title = (
        str(stream.get("title") or channel.get("title") or "").strip() or None
    )
    game_id = (
        str(stream.get("game_id") or channel.get("game_id") or "").strip()
        or None
    )
    game_name = (
        str(stream.get("game_name") or channel.get("game_name") or "").strip()
        or None
    )
    language = (
        str(
            stream.get("language") or channel.get("broadcaster_language") or ""
        ).strip()
        or None
    )
    started_at = (
        str(
            stream.get("started_at") or channel.get("started_at") or ""
        ).strip()
        or None
    )
    tags = _string_list(stream.get("tags") or channel.get("tags"))
    viewer_count = _optional_int(stream.get("viewer_count"))
    if viewer_count is None or viewer_count < _MIN_VIEWER_COUNT:
        return None
    avatar_url = (
        str(
            user.get("profile_image_url") or channel.get("thumbnail_url") or ""
        ).strip()
        or None
    )
    preview_thumbnail = _normalize_thumbnail(
        str(
            stream.get("thumbnail_url") or channel.get("thumbnail_url") or ""
        ).strip()
        or None
    )

    contact_channel = "twitch_dm"
    contact_value = login
    if description:
        email_match = _EMAIL_RE.search(description)
        if email_match is not None:
            contact_channel = "email"
            contact_value = email_match.group(0)

    tags_context = tagged_query.source_tags
    raw_data = TwitchChannelData(
        broadcaster_id=broadcaster_id,
        broadcaster_login=login,
        query=tagged_query.text,
        game_id=game_id,
        game_name=game_name,
        stream_title=title,
        is_live=bool(stream or channel.get("is_live")),
        started_at=started_at,
        viewer_count=viewer_count,
        broadcaster_language=language,
        tags=tags,
        avatar_url=avatar_url,
        recent_video_thumbnails=[preview_thumbnail]
        if preview_thumbnail
        else [],
        source_genre_tag=tags_context.genre,
        source_mechanics_tag=tags_context.mechanics,
        source_vibe_tag=tags_context.vibe,
    ).model_dump()

    text_signals = _text_signals(title, description, game_name, tags)
    prospect_type = _infer_prospect_type(
        display_name, description, title, game_name, tags
    )

    summary_bits = [bit for bit in (title, description) if bit]
    summary = " ".join(summary_bits).strip() or None

    return CandidateRecord(
        platform="twitch",
        handle=login,
        display_name=display_name,
        profile_url=f"https://www.twitch.tv/{login}",
        contact_channel=contact_channel,
        contact_value=contact_value,
        audience_size=viewer_count,
        engagement_rate=None,
        description=summary[:500] if summary else None,
        raw_data=raw_data,
        last_active_days=0,
        text_signals=text_signals,
        prospect_type=prospect_type,
    )


def _text_signals(
    title: str | None,
    description: str | None,
    game_name: str | None,
    tags: list[str],
) -> list[str]:
    values = [title, description]
    if game_name:
        values.append(f"Streaming {game_name}")
    values.extend(tags[:4])
    seen: set[str] = set()
    signals: list[str] = []
    for value in values:
        if not value:
            continue
        cleaned = str(value).strip()
        lowered = cleaned.lower()
        if not cleaned or lowered in seen:
            continue
        seen.add(lowered)
        signals.append(cleaned)
    return signals


def _infer_prospect_type(
    display_name: str,
    description: str | None,
    title: str | None,
    game_name: str | None,
    tags: list[str],
) -> str:
    haystack = " ".join(
        part
        for part in [
            display_name,
            description,
            title,
            game_name,
            " ".join(tags),
        ]
        if part
    ).lower()
    if any(keyword in haystack for keyword in _DEV_KEYWORDS):
        return "developer"
    return "creator"


def _normalize_thumbnail(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace("{width}", "640").replace("{height}", "360")


def _with_follower_count(
    candidate: CandidateRecord, follower_count: int | None
) -> CandidateRecord:
    if follower_count is None:
        return candidate
    return replace(
        candidate,
        raw_data={**candidate.raw_data, "followers_count": follower_count},
    )


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
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


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
