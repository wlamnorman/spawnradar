from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.url_policy import public_url


def test_public_url_uses_configured_base_url(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("BASE_URL", "https://spawnradar.com")

    settings = create_app().state.settings

    assert public_url(settings, "/auth/google/callback") == (
        "https://spawnradar.com/auth/google/callback"
    )
    assert public_url(settings, "pricing") == (
        "https://spawnradar.com/pricing"
    )


def test_canonical_redirect_preserves_path_and_query(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("BASE_URL", "https://spawnradar.com")
    monkeypatch.setenv("RESEND_API_KEY", "")
    app = create_app()

    with TestClient(app, base_url="https://www.spawnradar.com") as client:
        response = client.get(
            "/auth/login?next=%2Fgames",
            follow_redirects=False,
        )

    assert response.status_code == 308
    assert (
        response.headers["location"]
        == "https://spawnradar.com/auth/login?next=%2Fgames"
    )


def test_localhost_does_not_redirect_www_alias(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("RESEND_API_KEY", "")
    app = create_app()

    with TestClient(app, base_url="http://www.localhost:8000") as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 200
