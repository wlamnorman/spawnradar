"""Tests for registration, empty-dashboard flow, and dev login."""

import json
import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.database import get_connection
from app.main import create_app


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
    ):
        monkeypatch.setenv(key, "")
    app = create_app()
    return TestClient(app)


def test_register_redirects_to_games(monkeypatch, tmp_path):
    with _make_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/auth/register",
            data={"email": "new@example.com", "password": "password123"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/games"


def test_empty_dashboard_shows_plain_add_game_card(monkeypatch, tmp_path):
    with _make_client(monkeypatch, tmp_path) as client:
        client.post(
            "/auth/register",
            data={"email": "blank@example.com", "password": "password123"},
            follow_redirects=False,
        )
        response = client.get("/games")

    assert response.status_code == 200
    assert 'href="/games/new"' in response.text
    assert "Add game to get started!" not in response.text


def test_create_game_redirects_to_setup(monkeypatch, tmp_path):
    with _make_client(monkeypatch, tmp_path) as client:
        client.post(
            "/auth/register",
            data={"email": "flow@example.com", "password": "password123"},
            follow_redirects=False,
        )
        new_page = client.get("/games/new")
        response = client.post(
            "/games",
            data={
                "name": "Orbit Drift",
                "description": "Arcade racing across collapsing star lanes.",
                "genre_tags": "racing, arcade",
                "audience_tags": "speedrunners, arcade fans",
                "platform_tags": "browser",
                "website_url": "orbitdrift.example",
            },
            follow_redirects=False,
        )
        setup_response = client.get(response.headers["location"])

    assert new_page.status_code == 200
    assert "Discovery schedule" not in new_page.text
    assert "Automatic discovery runs in the background" not in new_page.text
    assert response.status_code == 303
    assert response.headers["location"].endswith("/setup")
    assert "Orbit Drift — Settings" in setup_response.text
    assert "Discovery schedule" not in setup_response.text
    assert (
        "Automatic discovery runs in the background" not in setup_response.text
    )
    assert "Onboarding wizard" not in setup_response.text


def test_pricing_page_shows_single_subscription_offer(monkeypatch, tmp_path):
    with _make_client(monkeypatch, tmp_path) as client:
        client.post(
            "/auth/register",
            data={"email": "plans@example.com", "password": "password123"},
            follow_redirects=False,
        )
        response = client.get("/pricing")

    assert response.status_code == 200
    assert "Simple pricing for tailored game outreach." in response.text
    assert "3-day trial" in response.text
    assert "Billing unavailable" in response.text
    assert "Studio" not in response.text


def test_billing_root_redirects_to_pricing(monkeypatch, tmp_path):
    with _make_client(monkeypatch, tmp_path) as client:
        response = client.get("/billing", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/pricing"


def test_dev_login_redirects_to_login_when_disabled(monkeypatch, tmp_path):
    with _make_client(monkeypatch, tmp_path) as client:
        response = client.get("/auth/dev-login", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_dev_login_creates_session_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "dev-login.sqlite3"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DEV_AUTO_LOGIN", "1")
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/auth/dev-login", follow_redirects=False)
        home_response = client.get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "session_id" in response.cookies
    assert home_response.status_code == 200
    assert "dev@spawnradar.local" in home_response.text


def test_queue_page_shows_expanded_thumbnails_and_visible_score_snapshot(
    monkeypatch, tmp_path
):
    db_path = str(tmp_path / "queue-ui.sqlite3")
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("DEV_AUTO_LOGIN", raising=False)
    app = create_app()

    with TestClient(app) as client:
        client.post(
            "/auth/register",
            data={"email": "queue@example.com", "password": "password123"},
            follow_redirects=False,
        )
        client.post(
            "/games",
            data={
                "name": "Star Tactician",
                "description": "Fleet battles in deep space.",
                "genre_tags": "strategy, tactics",
                "audience_tags": "strategy fans",
                "platform_tags": "pc",
                "website_url": "startactician.example",
            },
            follow_redirects=False,
        )

        with get_connection(db_path) as conn:
            game = conn.execute(
                "SELECT game_id, slug FROM games ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            now = datetime.now(UTC).isoformat()
            prospect_id = str(uuid.uuid4())
            draft_item_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO prospects
                    (prospect_id, platform, handle, display_name, profile_url,
                     contact_channel, contact_value, audience_size, engagement_rate,
                     description, raw_data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prospect_id,
                    "youtube",
                    "roguelikerabbit",
                    "RogueLikeRabbit",
                    "https://youtube.example/roguelikerabbit",
                    "email",
                    "rogue@example.com",
                    2600,
                    0.06,
                    "Covers indie roguelikes.",
                    json.dumps(
                        {
                            "avatar_url": "https://img.example.com/avatar.jpg",
                            "recent_video_thumbnails": [
                                f"https://img.example.com/thumb-{i}.jpg"
                                for i in range(1, 7)
                            ],
                        }
                    ),
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO draft_items
                    (draft_item_id, game_id, prospect_id, body_text, status,
                     priority_score, fit_summary, score_breakdown,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_item_id,
                    game["game_id"],
                    prospect_id,
                    "Hi RogueLikeRabbit,\n\nI'd love to share Star Tactician with you.",
                    "queued",
                    0.7,
                    "Strong match for strategy players.",
                    json.dumps(
                        {
                            "genre_fit": 0.92,
                            "audience_fit": 0.88,
                            "platform_fit": 1.0,
                            "contactability": 0.75,
                            "audience_size_score": 0.63,
                            "why_selected": "Audience and format align strongly with the game's target players.",
                            "reasons": [
                                "Contact channel available: reddit_post",
                                "Contact value present: https://reddit.example/post",
                                "Recent uploads feature adjacent tactics games.",
                            ],
                        }
                    ),
                    now,
                    now,
                ),
            )

        response = client.get(f"/games/{game['slug']}/queue")

    assert response.status_code == 200
    assert response.text.count('class="video-thumbnail"') == 6
    assert "score-dim-card" in response.text
    assert 'class="queue-insights"' in response.text
    assert "Quick take" in response.text
    assert "Detailed rationale" in response.text
    assert "Contact channel available: reddit_post" not in response.text
    assert (
        "Contact value present: https://reddit.example/post"
        not in response.text
    )
    assert "<summary>Score breakdown</summary>" not in response.text
    assert '<details class="message-accordion">' in response.text
    assert "<summary>Message draft</summary>" in response.text
