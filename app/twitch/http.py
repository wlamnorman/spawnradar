"""Shared Twitch Helix HTTP helpers with bounded rate-limit backoff."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

log = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY_SECONDS = 1.0
_MAX_DELAY_SECONDS = 30.0
_JITTER_SECONDS = 0.25
_TWITCH_AUTH_URL = "https://id.twitch.tv/oauth2/token"
_TOKEN_REFRESH_MARGIN_SECONDS = 60


def _parse_retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


def _compute_retry_delay_seconds(
    response: httpx.Response | None,
    *,
    attempt: int,
) -> float:
    if response is not None:
        retry_after = _parse_retry_after_seconds(
            response.headers.get("Retry-After")
        )
        if retry_after is not None:
            return min(_MAX_DELAY_SECONDS, retry_after)
    backoff = min(
        _MAX_DELAY_SECONDS,
        _BASE_DELAY_SECONDS * (2 ** max(0, attempt - 1)),
    )
    return backoff + random.uniform(0.0, _JITTER_SECONDS)


class TwitchAppAuth:
    """Shared Twitch app-access-token provider for Helix and IGDB clients."""

    def __init__(self, *, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    def _token_is_fresh(self) -> bool:
        if self._token is None or self._token_expires_at is None:
            return False
        refresh_at = self._token_expires_at - timedelta(
            seconds=_TOKEN_REFRESH_MARGIN_SECONDS
        )
        return refresh_at > datetime.now(UTC)

    async def access_token(
        self,
        client: httpx.AsyncClient,
        *,
        force_refresh: bool = False,
    ) -> str:
        if force_refresh:
            self._token = None
            self._token_expires_at = None
        if self._token_is_fresh():
            assert self._token is not None
            return self._token

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
        expires_in = payload.get("expires_in")
        expires_in_seconds = (
            int(expires_in) if isinstance(expires_in, int | float) else 0
        )
        self._token = token
        self._token_expires_at = datetime.now(UTC) + timedelta(
            seconds=max(0, expires_in_seconds)
        )
        return token

    async def auth_headers(
        self,
        client: httpx.AsyncClient,
        *,
        force_refresh: bool = False,
        extra_headers: Mapping[str, str] | None = None,
        client_id_header_name: str = "Client-ID",
    ) -> dict[str, str]:
        token = await self.access_token(client, force_refresh=force_refresh)
        headers = dict(extra_headers or {})
        headers[client_id_header_name] = self._client_id
        headers["Authorization"] = f"Bearer {token}"
        return headers


async def twitch_request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Any = None,
    refresh_headers: Callable[[], Awaitable[Mapping[str, str] | None]]
    | None = None,
) -> Any:
    """Make a Twitch API request with bounded retry/backoff.

    Retries 429 responses with backoff and can refresh auth once on 401
    when a ``refresh_headers`` callback is provided.
    """
    last_exc: httpx.HTTPError | None = None
    request_headers = headers
    refreshed_auth = False
    for attempt in range(1, _MAX_RETRIES + 2):
        response: httpx.Response | None = None
        try:
            response = await client.request(
                method,
                url,
                headers=request_headers,
                params=params,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            response = exc.response
            if (
                response.status_code == 401
                and refresh_headers is not None
                and not refreshed_auth
            ):
                refreshed_auth = True
                request_headers = await refresh_headers()
                log.info(
                    "Twitch %s %s → 401, refreshing auth and retrying once",
                    method,
                    url.split("?")[0].split("/")[-1],
                )
                continue
            if response.status_code != 429 or attempt > _MAX_RETRIES:
                raise
            last_exc = exc
        except httpx.HTTPError as exc:
            if attempt > _MAX_RETRIES:
                raise
            last_exc = exc
        delay = _compute_retry_delay_seconds(response, attempt=attempt)
        status = (
            response.status_code if response is not None else "network error"
        )
        log.info(
            "Twitch %s %s → %s, retrying in %.1fs (attempt %d/%d)",
            method,
            url.split("?")[0].split("/")[-1],
            status,
            delay,
            attempt,
            _MAX_RETRIES + 1,
        )
        await asyncio.sleep(delay)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Unreachable Twitch request retry state.")
