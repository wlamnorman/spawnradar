"""Tests for registration, empty-dashboard flow and dev login."""

import re

from fastapi.testclient import TestClient

from app.database import get_connection
from app.main import create_app


def _verify_user_email(db_path: str, email: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE users SET email_verified = 1 WHERE email = ?", (email,)
        )


def _make_client(monkeypatch, tmp_path) -> TestClient:
    db_path = str(tmp_path / "games-flow.sqlite3")
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("DEV_AUTO_LOGIN", raising=False)
    for key in (
        "PADDLE_API_KEY",
        "PADDLE_CLIENT_SIDE_TOKEN",
        "PADDLE_WEBHOOK_SECRET",
        "PADDLE_INDIE_PRICE_ID",
        "PADDLE_ENVIRONMENT",
        "RESEND_API_KEY",
    ):
        monkeypatch.setenv(key, "")
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


def test_register_redirects_to_verify_pending(monkeypatch, tmp_path):
    with _make_client(monkeypatch, tmp_path) as client:
        response = _post_form(
            client,
            get_path="/auth/register",
            post_path="/auth/register",
            data={"email": "new@example.com", "password": "password123"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/verify-pending"


def test_empty_trial_dashboard_shows_add_card(monkeypatch, tmp_path):
    db_path = str(tmp_path / "games-flow.sqlite3")
    with _make_client(monkeypatch, tmp_path) as client:
        _post_form(
            client,
            get_path="/auth/register",
            post_path="/auth/register",
            data={"email": "blank@example.com", "password": "password123"},
            follow_redirects=False,
        )
        _verify_user_email(db_path, "blank@example.com")
        response = client.get("/games")

    assert response.status_code == 200
    assert response.text.count('href="/games/setup"') == 1
    assert response.text.count("Locked during trial") == 2
    assert response.text.count("Add Game") == 3
    assert "Add game to get started!" not in response.text
    assert "game-card-add" in response.text


def test_dashboard_game_cards_include_run_discovery_action(
    monkeypatch, tmp_path
):
    db_path = str(tmp_path / "games-flow.sqlite3")
    with _make_client(monkeypatch, tmp_path) as client:
        _post_form(
            client,
            get_path="/auth/register",
            post_path="/auth/register",
            data={"email": "runner@example.com", "password": "password123"},
            follow_redirects=False,
        )
        _verify_user_email(db_path, "runner@example.com")
        _post_form(
            client,
            get_path="/games/setup",
            post_path="/games/setup",
            data={
                "name": "Orbit Drift",
                "summary": "Arcade racing across collapsing star lanes.",
                "description": "A longer internal description that should not appear on the dashboard card.",
                "platforms": "pc",
                "igdb_genre_ids": "10",
                "similar_game_names": "Slay the Spire",
                "website_url": "",
            },
            follow_redirects=False,
        )
        response = client.get("/games")

    assert response.status_code == 200
    assert "Discover creators" in response.text
    assert "/prospects" in response.text
    assert "Arcade racing across collapsing star lanes." in response.text
    assert "PC / Steam" in response.text
    # Similar games are no longer shown on the dashboard card
    assert "Slay the Spire" not in response.text
    assert (
        "A longer internal description that should not appear on the dashboard card."
        not in response.text
    )
    assert response.text.count("Locked during trial") == 2
    assert 'href="/games/setup"' not in response.text
    assert response.text.count("Add Game") == 2


def test_create_game_redirects_to_dashboard(monkeypatch, tmp_path):
    db_path = str(tmp_path / "games-flow.sqlite3")
    with _make_client(monkeypatch, tmp_path) as client:
        _post_form(
            client,
            get_path="/auth/register",
            post_path="/auth/register",
            data={"email": "flow@example.com", "password": "password123"},
            follow_redirects=False,
        )
        _verify_user_email(db_path, "flow@example.com")
        setup_page = client.get("/games/setup")
        response = _post_form(
            client,
            get_path="/games/setup",
            post_path="/games/setup",
            data={
                "name": "Orbit Drift",
                "summary": "Arcade racing across collapsing star lanes.",
                "description": "Arcade racing across collapsing star lanes.",
                "igdb_genre_ids": "10",
                "website_url": "orbitdrift.example",
            },
            follow_redirects=False,
        )

    assert setup_page.status_code == 200
    assert response.status_code == 303
    assert response.headers["location"] == "/games"


def test_pricing_page_shows_single_subscription_offer(monkeypatch, tmp_path):
    with _make_client(monkeypatch, tmp_path) as client:
        _post_form(
            client,
            get_path="/auth/register",
            post_path="/auth/register",
            data={"email": "plans@example.com", "password": "password123"},
            follow_redirects=False,
        )
        response = client.get("/pricing")

    assert response.status_code == 200
    assert "One plan for efficient game outreach." in response.text
    assert "Browse unlimited creator matches" in response.text
    assert "Billing unavailable" in response.text
    assert "Studio" not in response.text


def test_billing_root_unauthenticated_redirects_to_login(
    monkeypatch, tmp_path
):
    with _make_client(monkeypatch, tmp_path) as client:
        response = client.get("/billing", follow_redirects=False)

    assert response.status_code in (302, 303, 307)


def test_dev_login_redirects_to_login_when_disabled(monkeypatch, tmp_path):
    with _make_client(monkeypatch, tmp_path) as client:
        response = client.get("/auth/dev-login", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_dev_login_creates_session_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "dev-login.sqlite3"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DEV_AUTO_LOGIN", "1")
    monkeypatch.setenv("RESEND_API_KEY", "")
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/auth/dev-login", follow_redirects=False)
        home_response = client.get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "session_id" in response.cookies
    assert home_response.status_code == 200
    assert "My Account" in home_response.text
