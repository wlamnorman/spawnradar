"""Shared Twitch Helix HTTP helpers with bounded rate-limit backoff."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

log = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY_SECONDS = 1.0
_MAX_DELAY_SECONDS = 30.0
_JITTER_SECONDS = 0.25


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

    Retries 429 responses with backoff, and can refresh auth once on 401
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
