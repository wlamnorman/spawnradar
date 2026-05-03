from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.twitch.http import TwitchAppAuth, twitch_request_json


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
    with patch("app.twitch.http.asyncio.sleep", sleep):
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
    with patch("app.twitch.http.asyncio.sleep", sleep):
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


@pytest.mark.anyio
async def test_twitch_app_auth_caches_token_until_expiry():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            request=request,
            json={"access_token": "cached-token", "expires_in": 3600},
        )

    auth = TwitchAppAuth(client_id="cid", client_secret="secret")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        headers_one = await auth.auth_headers(client)
        headers_two = await auth.auth_headers(client)

    assert calls == 1
    assert headers_one["Authorization"] == "Bearer cached-token"
    assert headers_two["Authorization"] == "Bearer cached-token"
    assert headers_one["Client-ID"] == "cid"


@pytest.mark.anyio
async def test_twitch_app_auth_force_refreshes_token():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        token = "first-token" if calls == 1 else "second-token"
        return httpx.Response(
            200,
            request=request,
            json={"access_token": token, "expires_in": 3600},
        )

    auth = TwitchAppAuth(client_id="cid", client_secret="secret")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        first = await auth.auth_headers(client)
        second = await auth.auth_headers(client, force_refresh=True)

    assert calls == 2
    assert first["Authorization"] == "Bearer first-token"
    assert second["Authorization"] == "Bearer second-token"
