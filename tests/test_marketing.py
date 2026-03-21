"""Tests for the public landing and pricing pages."""

from fastapi.testclient import TestClient

from app.main import create_app


def _make_client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "marketing.sqlite3"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    app = create_app()
    return TestClient(app)


def test_root_renders_public_landing_page(monkeypatch, tmp_path):
    with _make_client(monkeypatch, tmp_path) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert (
        "Find the best creators, communities, and outreach targets for your game."
        in " ".join(response.text.split())
    )
    assert 'href="/pricing"' in response.text
    assert 'href="/static/favicon/site.webmanifest"' in response.text
    assert 'href="/static/favicon/favicon.svg"' in response.text
    assert 'src="/static/favicon/favicon-96x96.png"' in response.text
    assert 'href="/terms"' in response.text
    assert 'href="/privacy"' in response.text
    assert 'href="/refunds"' in response.text
    assert "mailto:contact@spawnradar.com" in response.text


def test_pricing_renders_single_offer(monkeypatch, tmp_path):
    with _make_client(monkeypatch, tmp_path) as client:
        response = client.get("/pricing")

    assert response.status_code == 200
    assert "One plan for research-driven game outreach." in response.text
    assert "Start 3-day trial" in response.text
    assert "Studio" not in response.text
    assert "Questions before subscribing?" in response.text
    assert "Manage up to" in response.text
    assert "20" in response.text
    assert "$20" in response.text
