"""Twitch stream discovery — Twitch category lookup plus paginated live crawl.

Discovers live Twitch broadcasters for a given Twitch category and extracts
YouTube cross-reference hints from channel descriptions. Category lookup from
an IGDB game name happens one layer up in ``app.creator_index.service``.

Reference: https://dev.twitch.tv/docs/api/reference
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import httpx

from app.creator_index.twitch_http import twitch_request_json

log = logging.getLogger(__name__)
_HELIX_BASE = "https://api.twitch.tv/helix"
_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_PAGE_SIZE = 100  # Fetch up to Twitch's per-request maximum on each page.
_STREAMS_MAX_FILTER_VALUES = 100


@dataclass(frozen=True)
class TwitchStream:
    user_id: str
    user_login: str | None
    user_name: str | None
    twitch_game_id: str
    stream_title: str | None
    viewer_count: int | None
    language: str | None


@dataclass(frozen=True)
class TwitchPagination:
    """Opaque Twitch cursor for fetching the next page of live streams."""

    cursor: str | None = None


@dataclass(frozen=True)
class TwitchStreamsPage:
    """One parsed page from ``GET /helix/streams`` for a single game/category.

    https://dev.twitch.tv/docs/api/reference#get-streams
    Gets a list of all streams. The list is in descending order by the
    number of viewers watching the stream. Because viewers come and go
    during a stream, it’s possible to find duplicate or missing streams
    in the list as you page through the results.
    """

    data: tuple[TwitchStream, ...]
    pagination: TwitchPagination


@dataclass(frozen=True)
class TwitchChannel:
    broadcaster_id: str
    broadcaster_login: str | None
    broadcaster_name: str | None
    broadcaster_language: str | None
    description: str | None
    title: str | None
    twitch_game_id: str | None
    game_name: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True)
class TwitchChannelsPage:
    """Parsed response body from ``GET /helix/channels``."""

    data: tuple[TwitchChannel, ...]


@dataclass(frozen=True)
class TwitchCategory:
    category_id: str
    name: str
    box_art_url: str | None


@dataclass(frozen=True)
class TwitchCategorySearchPage:
    """Parsed response body from ``GET /helix/search/categories``."""

    data: tuple[TwitchCategory, ...]
    pagination: TwitchPagination


@dataclass(frozen=True)
class TwitchGame:
    twitch_game_id: str
    name: str
    box_art_url: str | None
    igdb_game_id: str | None


@dataclass(frozen=True)
class TwitchGamesPage:
    """Parsed response body from ``GET /helix/games``."""

    data: tuple[TwitchGame, ...]


class TwitchStreamClient:
    """Minimal Twitch Helix HTTP client. Builds its own OAuth token.

    SourceRuntime has no .twitch attribute — only twitch_client_id /
    twitch_client_secret.
    """

    def __init__(self, *, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None

    @classmethod
    def from_runtime(cls, runtime: object) -> TwitchStreamClient:
        return cls(
            client_id=runtime.twitch_client_id,  # type: ignore[attr-defined]
            client_secret=runtime.twitch_client_secret,  # type: ignore[attr-defined]
        )

    async def _ensure_token(self, http: httpx.AsyncClient) -> str:
        if self._token:
            return self._token
        body = await twitch_request_json(
            http,
            "POST",
            _TOKEN_URL,
            params={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            },
        )
        self._token = body["access_token"]
        if not isinstance(self._token, str):
            raise ValueError(
                "Twitch token response did not include access_token."
            )
        return self._token

    async def _authorized_headers(
        self,
        http: httpx.AsyncClient,
        *,
        force_refresh: bool = False,
    ) -> dict[str, str]:
        if force_refresh:
            self._token = None
        token = await self._ensure_token(http)
        return {
            "Client-ID": self._client_id,
            "Authorization": f"Bearer {token}",
        }

    async def get_streams(
        self,
        *,
        user_ids: Sequence[str] = (),
        user_logins: Sequence[str] = (),
        game_ids: Sequence[str] = (),
        languages: Sequence[str] = (),
        stream_type: Literal["all", "live"] = "all",
        first: int = _PAGE_SIZE,
        before: str | None = None,
        after: str | None = None,
    ) -> TwitchStreamsPage:
        """Fetch one page from ``GET /helix/streams`` with optional filters."""
        async with httpx.AsyncClient(timeout=20) as http:
            headers = await self._authorized_headers(http)

            async def refresh_headers() -> dict[str, str]:
                nonlocal headers
                headers = await self._authorized_headers(
                    http, force_refresh=True
                )
                return headers

            body = await twitch_request_json(
                http,
                "GET",
                f"{_HELIX_BASE}/streams",
                headers=headers,
                params=_build_streams_query_params(
                    user_ids=user_ids,
                    user_logins=user_logins,
                    game_ids=game_ids,
                    languages=languages,
                    stream_type=stream_type,
                    first=first,
                    before=before,
                    after=after,
                ),
                refresh_headers=refresh_headers,
            )
        return _parse_streams_page(body)

    async def get_channel_info(
        self, broadcaster_ids: list[str]
    ) -> TwitchChannelsPage:
        if not broadcaster_ids:
            return TwitchChannelsPage(data=())
        async with httpx.AsyncClient(timeout=20) as http:
            headers = await self._authorized_headers(http)

            async def refresh_headers() -> dict[str, str]:
                nonlocal headers
                headers = await self._authorized_headers(
                    http, force_refresh=True
                )
                return headers

            body = await twitch_request_json(
                http,
                "GET",
                f"{_HELIX_BASE}/channels",
                headers=headers,
                params=[
                    ("broadcaster_id", uid) for uid in broadcaster_ids[:100]
                ],
                refresh_headers=refresh_headers,
            )
        return _parse_channels_page(body)

    async def search_categories(
        self,
        *,
        query: str,
        first: int = 20,
        after: str | None = None,
    ) -> TwitchCategorySearchPage:
        """Search Twitch categories by name via ``GET /helix/search/categories``.

        Reference: https://dev.twitch.tv/docs/api/reference#search-categories
        """
        async with httpx.AsyncClient(timeout=20) as http:
            headers = await self._authorized_headers(http)

            async def refresh_headers() -> dict[str, str]:
                nonlocal headers
                headers = await self._authorized_headers(
                    http, force_refresh=True
                )
                return headers

            body = await twitch_request_json(
                http,
                "GET",
                f"{_HELIX_BASE}/search/categories",
                headers=headers,
                params=_build_category_search_query_params(
                    query=query,
                    first=first,
                    after=after,
                ),
                refresh_headers=refresh_headers,
            )
        return _parse_category_search_page(body)

    async def get_games(
        self,
        *,
        twitch_game_ids: Sequence[str] = (),
        names: Sequence[str] = (),
        igdb_game_ids: Sequence[int] = (),
    ) -> TwitchGamesPage:
        """Fetch Twitch games/categories via ``GET /helix/games``."""
        async with httpx.AsyncClient(timeout=20) as http:
            headers = await self._authorized_headers(http)

            async def refresh_headers() -> dict[str, str]:
                nonlocal headers
                headers = await self._authorized_headers(
                    http, force_refresh=True
                )
                return headers

            body = await twitch_request_json(
                http,
                "GET",
                f"{_HELIX_BASE}/games",
                headers=headers,
                params=_build_games_query_params(
                    twitch_game_ids=twitch_game_ids,
                    names=names,
                    igdb_game_ids=igdb_game_ids,
                ),
                refresh_headers=refresh_headers,
            )
        return _parse_games_page(body)


def _parse_streams_page(payload: object) -> TwitchStreamsPage:
    if not isinstance(payload, dict):
        raise ValueError("Twitch streams response was not an object.")

    raw_data = payload.get("data", [])
    if not isinstance(raw_data, list):
        raise ValueError("Twitch streams response data was not a list.")

    streams: list[TwitchStream] = []
    for item in raw_data:
        if not isinstance(item, dict):
            continue
        user_id = item.get("user_id")
        twitch_game_id = item.get("game_id")
        if not isinstance(user_id, str) or not isinstance(twitch_game_id, str):
            continue
        streams.append(
            TwitchStream(
                user_id=user_id,
                user_login=item.get("user_login")
                if isinstance(item.get("user_login"), str)
                else None,
                user_name=item.get("user_name")
                if isinstance(item.get("user_name"), str)
                else None,
                twitch_game_id=twitch_game_id,
                stream_title=item.get("title")
                if isinstance(item.get("title"), str)
                else None,
                viewer_count=item.get("viewer_count")
                if isinstance(item.get("viewer_count"), int)
                else None,
                language=item.get("language")
                if isinstance(item.get("language"), str)
                else None,
            )
        )

    raw_pagination = payload.get("pagination", {})
    cursor = None
    if isinstance(raw_pagination, dict) and isinstance(
        raw_pagination.get("cursor"), str
    ):
        cursor = raw_pagination["cursor"]

    return TwitchStreamsPage(
        data=tuple(streams),
        pagination=TwitchPagination(cursor=cursor),
    )


def _parse_channels_page(payload: object) -> TwitchChannelsPage:
    if not isinstance(payload, dict):
        raise ValueError("Twitch channels response was not an object.")

    raw_data = payload.get("data", [])
    if not isinstance(raw_data, list):
        raise ValueError("Twitch channels response data was not a list.")

    channels: list[TwitchChannel] = []
    for item in raw_data:
        if not isinstance(item, dict):
            continue
        broadcaster_id = item.get("broadcaster_id")
        if not isinstance(broadcaster_id, str):
            continue
        channels.append(
            TwitchChannel(
                broadcaster_id=broadcaster_id,
                broadcaster_login=item.get("broadcaster_login")
                if isinstance(item.get("broadcaster_login"), str)
                else None,
                broadcaster_name=item.get("broadcaster_name")
                if isinstance(item.get("broadcaster_name"), str)
                else None,
                broadcaster_language=item.get("broadcaster_language")
                if isinstance(item.get("broadcaster_language"), str)
                else None,
                description=item.get("description")
                if isinstance(item.get("description"), str)
                else None,
                title=item.get("title")
                if isinstance(item.get("title"), str)
                else None,
                twitch_game_id=item.get("game_id")
                if isinstance(item.get("game_id"), str)
                else None,
                game_name=item.get("game_name")
                if isinstance(item.get("game_name"), str)
                else None,
                tags=tuple(
                    tag.strip()
                    for tag in item.get("tags", [])
                    if isinstance(tag, str) and tag.strip()
                )
                if isinstance(item.get("tags"), list)
                else (),
            )
        )

    return TwitchChannelsPage(data=tuple(channels))


def _parse_category_search_page(payload: object) -> TwitchCategorySearchPage:
    if not isinstance(payload, dict):
        raise ValueError("Twitch category search response was not an object.")

    raw_data = payload.get("data", [])
    if not isinstance(raw_data, list):
        raise ValueError(
            "Twitch category search response data was not a list."
        )

    categories: list[TwitchCategory] = []
    for item in raw_data:
        if not isinstance(item, dict):
            continue
        category_id = item.get("id")
        name = item.get("name")
        if not isinstance(category_id, str) or not isinstance(name, str):
            continue
        categories.append(
            TwitchCategory(
                category_id=category_id,
                name=name,
                box_art_url=item.get("box_art_url")
                if isinstance(item.get("box_art_url"), str)
                else None,
            )
        )

    raw_pagination = payload.get("pagination", {})
    cursor = None
    if isinstance(raw_pagination, dict) and isinstance(
        raw_pagination.get("cursor"), str
    ):
        cursor = raw_pagination["cursor"]

    return TwitchCategorySearchPage(
        data=tuple(categories),
        pagination=TwitchPagination(cursor=cursor),
    )


def _parse_games_page(payload: object) -> TwitchGamesPage:
    if not isinstance(payload, dict):
        raise ValueError("Twitch games response was not an object.")

    raw_data = payload.get("data", [])
    if not isinstance(raw_data, list):
        raise ValueError("Twitch games response data was not a list.")

    games: list[TwitchGame] = []
    for item in raw_data:
        if not isinstance(item, dict):
            continue
        twitch_game_id = item.get("id")
        name = item.get("name")
        if not isinstance(twitch_game_id, str) or not isinstance(name, str):
            continue
        games.append(
            TwitchGame(
                twitch_game_id=twitch_game_id,
                name=name,
                box_art_url=item.get("box_art_url")
                if isinstance(item.get("box_art_url"), str)
                else None,
                igdb_game_id=item.get("igdb_id")
                if isinstance(item.get("igdb_id"), str)
                else None,
            )
        )
    return TwitchGamesPage(data=tuple(games))


def _build_streams_query_params(
    *,
    user_ids: Sequence[str] = (),
    user_logins: Sequence[str] = (),
    game_ids: Sequence[str] = (),
    languages: Sequence[str] = (),
    stream_type: Literal["all", "live"] = "all",
    first: int = _PAGE_SIZE,
    before: str | None = None,
    after: str | None = None,
) -> tuple[tuple[str, str], ...]:
    """Build validated query params for ``GET /helix/streams``."""
    if not 1 <= first <= _PAGE_SIZE:
        raise ValueError(f"first must be between 1 and {_PAGE_SIZE}.")
    if before and after:
        raise ValueError("before and after may not both be set.")
    if stream_type not in {"all", "live"}:
        raise ValueError("stream_type must be 'all' or 'live'.")

    params: list[tuple[str, str]] = [("first", str(first))]
    if stream_type != "all":
        params.append(("type", stream_type))

    params.extend(_repeated_param("user_id", user_ids))
    params.extend(_repeated_param("user_login", user_logins))
    params.extend(_repeated_param("game_id", game_ids))
    params.extend(_repeated_param("language", languages))

    if before:
        params.append(("before", before))
    if after:
        params.append(("after", after))
    return tuple(params)


def _build_games_query_params(
    *,
    twitch_game_ids: Sequence[str] = (),
    names: Sequence[str] = (),
    igdb_game_ids: Sequence[int] = (),
) -> tuple[tuple[str, str], ...]:
    params: list[tuple[str, str]] = []
    params.extend(_repeated_param("id", twitch_game_ids))
    params.extend(_repeated_param("name", names))
    params.extend(
        _repeated_param(
            "igdb_id", tuple(str(game_id) for game_id in igdb_game_ids)
        )
    )
    if not params:
        raise ValueError(
            "At least one of twitch_game_ids, names, or igdb_game_ids is required."
        )
    return tuple(params)


def _build_category_search_query_params(
    *,
    query: str,
    first: int = 20,
    after: str | None = None,
) -> tuple[tuple[str, str], ...]:
    cleaned_query = query.strip()
    if not cleaned_query:
        raise ValueError("query is required.")
    if not 1 <= first <= _PAGE_SIZE:
        raise ValueError(f"first must be between 1 and {_PAGE_SIZE}.")

    params: list[tuple[str, str]] = [
        ("query", cleaned_query),
        ("first", str(first)),
    ]
    if after:
        params.append(("after", after))
    return tuple(params)


def _repeated_param(key: str, values: Sequence[str]) -> list[tuple[str, str]]:
    cleaned_values = [value.strip() for value in values if value.strip()]
    if len(cleaned_values) > _STREAMS_MAX_FILTER_VALUES:
        raise ValueError(
            f"{key} supports at most {_STREAMS_MAX_FILTER_VALUES} values."
        )
    return [(key, value) for value in cleaned_values]
