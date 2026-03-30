"""Tests for the public landing and pricing pages."""

from fastapi.testclient import TestClient

from app.main import create_app


def _make_client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "marketing.sqlite3"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("RESEND_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    app = create_app()
    return TestClient(app)


def test_root_renders_public_landing_page(monkeypatch, tmp_path):
    with _make_client(monkeypatch, tmp_path) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert (
        "Build a tailored creator outreach list for your game in minutes."
        in " ".join(response.text.split())
    )
    assert 'href="/pricing"' in response.text
    assert "/static/favicon/site.webmanifest?v=" in response.text
    assert 'href="/static/favicon/favicon.svg"' in response.text
    assert "/static/favicon/favicon-96x96.png?v=" in response.text
    assert "/static/style.css?v=" in response.text
    assert 'href="/terms"' in response.text
    assert 'href="/privacy"' in response.text
    assert 'href="/refunds"' in response.text
    assert "https://bsky.app/profile/spawnradar.com" in response.text
    assert "https://discord.gg/XwGbqFHy" in response.text
    assert "mailto:contact@spawnradar.com" in response.text


def test_pricing_renders_single_offer(monkeypatch, tmp_path):
    with _make_client(monkeypatch, tmp_path) as client:
        response = client.get("/pricing")

    text = " ".join(response.text.split())
    assert response.status_code == 200
    assert "One plan for efficient game outreach." in text
    assert "Start 3-day trial" in text
    assert "Studio" not in text
    assert "Questions before subscribing?" in text
    assert "Manage up to" in text
    assert "active games" in text
    assert "Browse unlimited creator matches" in text
    assert "Reusable message templates and outreach assets" not in text
    assert "29" in text
    assert "$29" in text
