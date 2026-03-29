from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.creator_index.twitch_http import twitch_request_json


@pytest.mark.anyio
async def test_twitch_request_json_retries_rate_limit_and_honors_retry_after():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "2"},
                request=request,
                json={"error": "Too Many Requests"},
            )
        return httpx.Response(200, request=request, json={"ok": True})

    sleep = AsyncMock()
    with patch("app.creator_index.twitch_http.asyncio.sleep", sleep):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            body = await twitch_request_json(
                client, "GET", "https://example.test/streams"
            )

    assert body == {"ok": True}
    assert calls == 2
    sleep.assert_awaited_once_with(2.0)


@pytest.mark.anyio
async def test_twitch_request_json_raises_non_rate_limit_errors_without_retry():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, request=request, json={"error": "bad"})

    sleep = AsyncMock()
    with patch("app.creator_index.twitch_http.asyncio.sleep", sleep):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await twitch_request_json(
                    client, "GET", "https://example.test/streams"
                )

    assert calls == 1
    sleep.assert_not_awaited()


@pytest.mark.anyio
async def test_twitch_request_json_refreshes_auth_once_on_401():
    calls = 0
    refreshed = AsyncMock(return_value={"Authorization": "Bearer fresh"})

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        auth = request.headers.get("Authorization")
        if auth == "Bearer stale":
            return httpx.Response(
                401, request=request, json={"error": "token expired"}
            )
        return httpx.Response(200, request=request, json={"ok": True})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        body = await twitch_request_json(
            client,
            "GET",
            "https://example.test/streams",
            headers={"Authorization": "Bearer stale"},
            refresh_headers=refreshed,
        )

    assert body == {"ok": True}
    assert calls == 2
    refreshed.assert_awaited_once()
