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
        "Find the right creators, communities, and outreach opportunities"
        in response.text
    )
    assert 'href="/pricing"' in response.text


def test_pricing_renders_only_starter_and_pro(monkeypatch, tmp_path):
    with _make_client(monkeypatch, tmp_path) as client:
        response = client.get("/pricing")

    assert response.status_code == 200
    assert "Starter" in response.text
    assert "Pro" in response.text
    assert "Free" not in response.text
