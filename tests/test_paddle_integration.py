"""Soft Paddle integration checks.

These tests run with the normal suite, but external Paddle failures are treated as
warnings plus skips so sandbox/CDN issues do not block local development.
"""

from __future__ import annotations

import re
import warnings

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def _warn_and_skip(message: str, exc: Exception | None = None) -> None:
    details = f"{message}: {exc}" if exc is not None else message
    warnings.warn(details, stacklevel=2)
    pytest.skip(message)


def _make_client(monkeypatch, tmp_path) -> TestClient:
    db_path = str(tmp_path / "paddle-integration.sqlite3")
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("PADDLE_API_KEY", "test_api_key")
    monkeypatch.setenv(
        "PADDLE_CLIENT_SIDE_TOKEN", "test_123456789012345678901234567"
    )
    monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("PADDLE_INDIE_PRICE_ID", "pri_test_indie")
    monkeypatch.setenv("PADDLE_ENVIRONMENT", "sandbox")
    monkeypatch.delenv("DEV_AUTO_LOGIN", raising=False)
    monkeypatch.setenv("RESEND_API_KEY", "")
    app = create_app()
    return TestClient(app)


def _csrf_token(client: TestClient, path: str) -> str:
    response = client.get(path)
    match = re.search(r'name="csrf-token" content="([^"]+)"', response.text)
    assert match is not None
    return match.group(1)


def _post_form(
    client: TestClient,
    *,
    get_path: str,
    post_path: str,
    data: dict[str, str],
    follow_redirects: bool = True,
):
    payload = dict(data)
    payload["csrf_token"] = _csrf_token(client, get_path)
    return client.post(
        post_path, data=payload, follow_redirects=follow_redirects
    )


def test_billing_pay_page_embeds_paddle_checkout_context(
    monkeypatch, tmp_path
):
    with _make_client(monkeypatch, tmp_path) as client:
        _post_form(
            client,
            get_path="/auth/register",
            post_path="/auth/register",
            data={"email": "billing@example.com", "password": "password123"},
            follow_redirects=False,
        )
        response = client.get("/billing/pay")

    assert response.status_code == 200
    assert "https://cdn.paddle.com/paddle/v2/paddle.js" in response.text
    assert "pri_test_indie" in response.text
    assert "test_123456789012345678901234567" in response.text
    assert "billing-pay.js" in response.text


def test_paddle_cdn_script_is_reachable_softly():
    try:
        response = httpx.get(
            "https://cdn.paddle.com/paddle/v2/paddle.js",
            timeout=5.0,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        _warn_and_skip("Paddle CDN was unreachable during this test run", exc)
        return

    if response.status_code != 200:
        _warn_and_skip(
            f"Paddle CDN returned {response.status_code} during this test run"
        )
        return

    if "Paddle" not in response.text:
        _warn_and_skip(
            "Paddle CDN responded, but the script content looked unexpected"
        )
        return

    assert "Paddle" in response.text
