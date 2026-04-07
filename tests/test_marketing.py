"""Tests for the public landing and pricing pages."""

from fastapi.testclient import TestClient

from app.database import get_connection
from app.main import create_app


def _make_client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "marketing.sqlite3"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("RESEND_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    app = create_app()
    return TestClient(app)


def test_root_renders_public_landing_page(monkeypatch, tmp_path):
    db_path = str(tmp_path / "marketing.sqlite3")
    with _make_client(monkeypatch, tmp_path) as client:
        with get_connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO source_accounts (
                    account_id, platform, external_id, handle_current,
                    display_name_current, canonical_url, account_type, status,
                    first_seen_at, last_seen_at, created_at, updated_at
                ) VALUES
                    ('creator-1', 'twitch', 'ext-1', 'creator1', 'Creator One',
                     'https://twitch.tv/creator1', 'creator', 'active',
                     datetime('now'), datetime('now'), datetime('now'), datetime('now')),
                    ('creator-2', 'youtube', 'ext-2', 'creator2', 'Creator Two',
                     'https://youtube.com/@creator2', 'creator', 'active',
                     datetime('now'), datetime('now'), datetime('now'), datetime('now')),
                    ('developer-1', 'twitch', 'ext-3', 'dev1', 'Dev One',
                     'https://twitch.tv/dev1', 'developer', 'active',
                     datetime('now'), datetime('now'), datetime('now'), datetime('now'))
                """
            )
        response = client.get("/")

    text = " ".join(response.text.split())
    assert response.status_code == 200
    assert (
        "Start efficient creator outreach tailored to your game within minutes."
        in text
    )
    assert 'href="/pricing"' in response.text
    assert "/static/favicon/site.webmanifest?v=" in response.text
    assert 'href="/static/favicon/favicon.svg"' in response.text
    assert "/static/favicon/favicon-96x96.png?v=" in response.text
    assert "/static/style.css?v=" in response.text
    assert "<strong>2</strong>" in response.text
    assert (
        "active creators with analyzed game interests and contact info"
        in text
    )
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
    assert "subscribe" in text.lower()
    assert "Studio" not in text
    assert "Questions before subscribing?" in text
    assert "Manage up to" in text
    assert "active games" in text
    assert "Browse unlimited creator matches" in text
    assert "Reusable message templates and outreach assets" not in text
    assert "19" in text
    assert "$19" in text
