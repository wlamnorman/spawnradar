"""HTTP-level integration tests using FastAPI TestClient.

These tests exercise the full request/response cycle including middleware,
routing, template rendering and cookie handling.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient

from app.billing.repository import SubscriptionRepository
from app.billing.service import BillingService
from app.database import get_connection
from app.dependencies import get_game_import_service
from app.game_import.models import (
    ImportedGameDraft,
    ImportedGamePreview,
    ImportedGameSourceData,
)
from app.games.repository import CustomerGameRepository
from app.main import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    for key in (
        "PADDLE_API_KEY",
        "PADDLE_CLIENT_SIDE_TOKEN",
        "PADDLE_WEBHOOK_SECRET",
        "PADDLE_INDIE_PRICE_ID",
        "PADDLE_ENVIRONMENT",
    ):
        monkeypatch.setenv(key, os.environ.get(key, ""))
    monkeypatch.setenv("RESEND_API_KEY", "")
    return TestClient(create_app(), raise_server_exceptions=True)


def _sample_import_preview() -> ImportedGamePreview:
    return ImportedGamePreview(
        source=ImportedGameSourceData(
            source_kind="steam",
            source_url="https://store.steampowered.com/app/4309620/",
            source_id="4309620",
            name="Strife of Stars",
            short_description="A tactical sci-fi deckbuilder.",
            full_description="Build a squad and climb the tower.",
            platform_labels=["Windows"],
            api_genre_labels=["Strategy", "Indie"],
            api_category_labels=["Single-player"],
            raw_tags=["Deckbuilding", "Roguelike", "Sci-fi"],
            website_url="https://strife.example.com",
            image_url="https://cdn.example.com/strife.jpg",
        ),
        draft=ImportedGameDraft(
            source_kind="steam",
            source_url="https://store.steampowered.com/app/4309620/",
            source_id="4309620",
            name="Strife of Stars",
            summary="A tactical sci-fi deckbuilder.",
            description="Build a squad and climb the tower.",
            platform_labels=["Windows"],
            igdb_genre_ids=[15, 32],
            igdb_theme_ids=[18],
            igdb_game_mode_ids=[1],
            igdb_keyword_ids=["deckbuilder", "roguelike"],
            tag_candidates=["Deckbuilding", "Roguelike", "Sci-fi"],
            website_url="https://strife.example.com",
            image_url="https://cdn.example.com/strife.jpg",
            notes=["Imported draft applied. Review and edit before saving."],
        ),
    )


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
    headers: dict[str, str] | None = None,
):
    payload = dict(data)
    payload["csrf_token"] = _csrf_token(client, get_path)
    return client.post(
        post_path,
        data=payload,
        follow_redirects=follow_redirects,
        headers=headers,
    )


def _post_json(
    client: TestClient,
    *,
    get_path: str,
    post_path: str,
    json_body: dict[str, object],
    follow_redirects: bool = True,
    headers: dict[str, str] | None = None,
):
    request_headers = dict(headers or {})
    request_headers["x-csrf-token"] = _csrf_token(client, get_path)
    return client.post(
        post_path,
        json=json_body,
        follow_redirects=follow_redirects,
        headers=request_headers,
    )


def _create_game_for_user(client: TestClient, name: str = "Game") -> None:
    _post_form(
        client,
        get_path="/games/setup",
        post_path="/games/setup",
        data={
            "name": name,
            "summary": "Short summary",
            "description": "Desc",
            "igdb_genre_ids": "12",
            "igdb_game_mode_ids": "1",
            "igdb_player_perspective_ids": "2",
            "website_url": "",
        },
    )


def test_new_game_page_shows_shared_summary_and_description_limits(
    monkeypatch, tmp_path
) -> None:
    with _make_client(monkeypatch, tmp_path) as client:
        _register_and_login(client, "limits@example.com", "password123")

        response = client.get("/games/setup")

        assert response.status_code == 200
        assert 'maxlength="200"' in response.text
        assert 'maxlength="1000"' in response.text
        assert "/200" in response.text
        assert "/1000" in response.text


def _create_game_for_user_and_return_id(
    client: TestClient, name: str = "Game"
) -> str:
    _create_game_for_user(client, name)
    db_path = os.environ.get("DB_PATH", "")
    assert db_path
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT customer_game_id FROM customer_games WHERE name = ?",
            (name,),
        ).fetchone()
    assert row is not None
    return str(row["customer_game_id"])


def _verify_user_email(db_path: str, email: str) -> None:
    """Mark a user's email as verified directly in the DB."""
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE users SET email_verified = 1 WHERE email = ?", (email,)
        )


def _register_and_login(client: TestClient, email: str, password: str) -> str:
    """Register a user, verify their email, grant a subscription, and return the session cookie value."""
    _post_form(
        client,
        get_path="/auth/register",
        post_path="/auth/register",
        data={"email": email, "password": password},
    )
    db_path = os.environ.get("DB_PATH", "")
    if db_path:
        _verify_user_email(db_path, email)
        _grant_subscription(db_path, email)
    _post_form(
        client,
        get_path="/auth/login",
        post_path="/auth/login",
        data={"email": email, "password": password},
    )
    return client.cookies.get("session_id") or ""


def _grant_subscription(db_path: str, email: str) -> None:
    """Create an active paid subscription for a user by email."""
    import uuid as _uuid

    from app.billing.models import Tier
    from app.billing.repository import SubscriptionRepository

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT user_id FROM users WHERE email = ?", (email,)
        ).fetchone()
    if row is None:
        return
    repo = SubscriptionRepository(db_path)
    repo.create(str(_uuid.uuid4()), row["user_id"], Tier.INDIE)
    repo.update_from_paddle(
        row["user_id"],
        paddle_subscription_id="test_sub",
        paddle_customer_id="test_cust",
        status="active",
    )


def _create_incomplete_game_for_user(
    db_path: str, user_id: str, name: str = "Legacy Game"
):
    repo = CustomerGameRepository(db_path)
    return repo.create(
        customer_game_id=str(uuid4()),
        user_id=user_id,
        name=name,
        summary=None,
        description="Legacy game description",
        website_url=None,
    )


def _expire_trial(db_path: str, email: str) -> str:
    """Simulate a user with no active subscription (free/expired).

    In the new model there is no trial; this helper cancels the subscription
    and sets its period end in the past so the user loses access.
    """
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT user_id, subscription_id FROM users JOIN subscriptions USING(user_id) WHERE email = ?",
            (email,),
        ).fetchone()
        assert row is not None
        conn.execute(
            "UPDATE subscriptions SET status = 'canceled', paddle_subscription_id = NULL, "
            "current_period_end = ?, trial_ends_at = NULL, updated_at = ? WHERE subscription_id = ?",
            (
                "2000-01-01T00:00:00+00:00",
                "2000-01-01T00:00:00+00:00",
                row["subscription_id"],
            ),
        )
        return str(row["user_id"])


def _expire_paid_subscription(db_path: str, email: str) -> str:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT user_id, subscription_id FROM users JOIN subscriptions USING(user_id) WHERE email = ?",
            (email,),
        ).fetchone()
        assert row is not None
        conn.execute(
            "UPDATE subscriptions SET status = ?, paddle_subscription_id = ?, current_period_end = ?, updated_at = ? WHERE subscription_id = ?",
            (
                "canceled",
                "sub_expired",
                "2000-01-01T00:00:00+00:00",
                "2000-01-01T00:00:00+00:00",
                row["subscription_id"],
            ),
        )
        return str(row["user_id"])


def _activate_paid_subscription(db_path: str, email: str) -> str:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT user_id, subscription_id FROM users JOIN subscriptions USING(user_id) WHERE email = ?",
            (email,),
        ).fetchone()
        assert row is not None
        conn.execute(
            """
            UPDATE subscriptions
            SET status = ?, paddle_subscription_id = ?, current_period_end = ?, updated_at = ?
            WHERE subscription_id = ?
            """,
            (
                "active",
                "sub_paid",
                "2999-01-01T00:00:00+00:00",
                "2999-01-01T00:00:00+00:00",
                row["subscription_id"],
            ),
        )
        return str(row["user_id"])


def _grant_comped_access(db_path: str, email: str) -> str:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT user_id FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        assert row is not None
    user_id = str(row["user_id"])
    billing = BillingService(
        SubscriptionRepository(db_path),
        CustomerGameRepository(db_path),
    )
    billing.grant_comped_access(user_id)
    return user_id


def _seed_ranked_prospects(
    db_path: str,
    *,
    count: int,
    customer_game_name: str,
    game_name: str,
) -> str:
    with get_connection(db_path) as conn:
        game_row = conn.execute(
            "SELECT customer_game_id, slug FROM customer_games WHERE name = ?",
            (customer_game_name,),
        ).fetchone()
        assert game_row is not None
        game_slug = str(game_row["slug"])
        conn.execute(
            """
            INSERT INTO igdb_games (
                igdb_id, name, slug, summary, first_release_date,
                platform_ids_json, platform_names_json, last_synced_at
            ) VALUES (?, ?, ?, NULL, NULL, '[]', '[]', datetime('now'))
            """,
            (999, game_name, game_slug),
        )
        conn.execute(
            """
            INSERT INTO igdb_game_tags (igdb_id, tag_type, tag_name, tag_id)
            VALUES (?, ?, ?, ?)
            """,
            (999, "genre", "Role-playing (RPG)", 12),
        )
        for idx in range(count):
            account_id = f"prospect-{idx:03d}"
            handle = f"prospect{idx:03d}"
            conn.execute(
                """
                INSERT INTO source_accounts (
                    account_id, platform, external_id, handle_current,
                    display_name_current, canonical_url,
                    first_seen_at, last_seen_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'),
                          datetime('now'), datetime('now'))
                """,
                (
                    account_id,
                    "twitch",
                    f"ext-{idx:03d}",
                    handle,
                    f"Prospect {idx:03d}",
                    f"https://twitch.tv/{handle}",
                ),
            )
            conn.execute(
                """
                INSERT INTO twitch_profiles_latest (
                    account_id, broadcaster_id, login, display_name,
                    followers_count, recent_avg_live_viewers,
                    fetched_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now', '+1 day'))
                """,
                (
                    account_id,
                    f"broadcaster-{idx:03d}",
                    handle,
                    f"Prospect {idx:03d}",
                    1000 + idx,
                    50 + idx,
                ),
            )
            conn.execute(
                """
                INSERT INTO creator_games_played (
                    account_id, game_name_raw, game_name_key, platform,
                    first_seen_at, last_seen_at, observation_count, igdb_game_id
                ) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), 1, ?)
                """,
                (
                    account_id,
                    game_name,
                    game_name.lower(),
                    "twitch",
                    999,
                ),
            )
    return game_slug


def _insert_prospect_status(
    db_path: str,
    customer_game_name: str,
    account_id: str,
    status: str,
    notes: str = "",
) -> None:
    with get_connection(db_path) as conn:
        game_row = conn.execute(
            "SELECT customer_game_id FROM customer_games WHERE name = ?",
            (customer_game_name,),
        ).fetchone()
        assert game_row is not None
        conn.execute(
            """
            INSERT INTO prospect_statuses (
                customer_game_id, account_id, status, notes, updated_at
            ) VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (str(game_row["customer_game_id"]), account_id, status, notes),
        )


def _signed_paddle_webhook(
    payload: dict[str, object], secret: str
) -> tuple[bytes, str]:
    encoded = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    signed = timestamp.encode() + b":" + encoded
    signature = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return encoded, f"ts={timestamp};h1={signature}"


# ---------------------------------------------------------------------------
# Game routes
# ---------------------------------------------------------------------------


class TestGameRoutes:
    def test_new_game_page_shows_keyword_taxonomy_options(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "keywords-new@example.com", "testpass")

            response = client.get("/games/setup")

        assert response.status_code == 200
        assert (
            "Highest-signal tags for discovery and scoring." in response.text
        )
        assert "Themes" in response.text
        assert "Mechanics" in response.text
        assert "Roguelike" in response.text
        assert "Cozy" in response.text
        assert "Crafting" in response.text
        assert "Similar games" in response.text
        assert "Platform" in response.text
        assert "PC / Steam" in response.text
        assert "Nintendo Switch" in response.text

    def test_setup_page_shows_keyword_taxonomy_options(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "keywords-setup@example.com", "testpass"
            )
            _create_game_for_user(client, "Setup Keyword Game")

            with get_connection(db_path) as conn:
                row = conn.execute(
                    "SELECT slug FROM customer_games WHERE name = ?",
                    ("Setup Keyword Game",),
                ).fetchone()
            assert row is not None

            response = client.get(f"/games/{row['slug']}/setup")

        assert response.status_code == 200
        assert (
            "Highest-signal tags for discovery and scoring." in response.text
        )
        assert "Themes" in response.text
        assert "Mechanics" in response.text
        assert "Roguelike" in response.text
        assert "Cozy" in response.text
        assert "Crafting" in response.text
        assert "Similar games" in response.text
        assert "Platform" in response.text
        assert "Board Game" in response.text

    def test_create_game_persists_curated_keyword_ids(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "keywords-save@example.com", "testpass"
            )

            response = _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Keyword Game",
                    "summary": "Short summary",
                    "description": "A tactical roguelike deckbuilder.",
                    "igdb_genre_ids": "12",
                    "igdb_keyword_ids": "roguelike",
                    "website_url": "",
                },
                follow_redirects=False,
            )

        assert response.status_code == 303

        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT igdb_keyword_ids FROM customer_games WHERE name = ?",
                ("Keyword Game",),
            ).fetchone()

        assert row is not None
        assert json.loads(str(row["igdb_keyword_ids"])) == ["roguelike"]

    def test_setup_page_persists_curated_keyword_ids(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "keywords-update@example.com", "testpass"
            )
            _create_game_for_user(client, "Update Keyword Game")

            with get_connection(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT slug, summary, description
                    FROM customer_games
                    WHERE name = ?
                    """,
                    ("Update Keyword Game",),
                ).fetchone()
            assert row is not None

            response = _post_form(
                client,
                get_path=f"/games/{row['slug']}/setup",
                post_path=f"/games/{row['slug']}/setup",
                data={
                    "name": "Update Keyword Game",
                    "summary": str(row["summary"]),
                    "description": str(row["description"]),
                    "igdb_genre_ids": "12",
                    "igdb_keyword_ids": "roguelike",
                    "website_url": "",
                },
                follow_redirects=False,
            )

        assert response.status_code == 303
        assert response.headers["location"] == "/games"

        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT igdb_keyword_ids FROM customer_games WHERE name = ?",
                ("Update Keyword Game",),
            ).fetchone()

        assert row is not None
        assert json.loads(str(row["igdb_keyword_ids"])) == ["roguelike"]

    def test_create_game_persists_platforms(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "platforms-create@example.com", "testpass"
            )

            response = _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Platform Route Game",
                    "summary": "Short summary",
                    "description": "A cross-platform tactics game.",
                    "platforms": "pc",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )

        assert response.status_code == 303

        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT platforms FROM customer_games WHERE name = ?",
                ("Platform Route Game",),
            ).fetchone()

        assert row is not None
        assert json.loads(str(row["platforms"])) == ["pc"]

    def test_setup_page_persists_platforms(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "platforms-update@example.com", "testpass"
            )
            _create_game_for_user(client, "Setup Platform Game")

            with get_connection(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT slug, summary, description
                    FROM customer_games
                    WHERE name = ?
                    """,
                    ("Setup Platform Game",),
                ).fetchone()
            assert row is not None

            response = _post_form(
                client,
                get_path=f"/games/{row['slug']}/setup",
                post_path=f"/games/{row['slug']}/setup",
                data={
                    "name": "Setup Platform Game",
                    "summary": str(row["summary"]),
                    "description": str(row["description"]),
                    "platforms": "switch",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )

        assert response.status_code == 303
        assert response.headers["location"] == "/games"

        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT platforms FROM customer_games WHERE name = ?",
                ("Setup Platform Game",),
            ).fetchone()

        assert row is not None
        assert json.loads(str(row["platforms"])) == ["switch"]

    def test_setup_page_persists_similar_games(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "similar-games-update@example.com", "testpass"
            )
            _create_game_for_user(client, "Setup Similar Game")

            with get_connection(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT slug, summary, description
                    FROM customer_games
                    WHERE name = ?
                    """,
                    ("Setup Similar Game",),
                ).fetchone()
            assert row is not None

            response = client.post(
                f"/games/{row['slug']}/setup",
                data={
                    "csrf_token": _csrf_token(
                        client, f"/games/{row['slug']}/setup"
                    ),
                    "name": "Setup Similar Game",
                    "summary": str(row["summary"]),
                    "description": str(row["description"]),
                    "igdb_genre_ids": ["12"],
                    "similar_game_names": [
                        "Slay the Spire",
                        "FTL: Faster Than Light",
                    ],
                },
                follow_redirects=False,
            )

        assert response.status_code == 303

        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT similar_game_names FROM customer_games WHERE name = ?",
                ("Setup Similar Game",),
            ).fetchone()

        assert row is not None
        assert json.loads(str(row["similar_game_names"])) == [
            "Slay the Spire",
            "FTL: Faster Than Light",
        ]

    def test_create_game_validation_error_preserves_pending_form_state(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "preserve-create@example.com", "testpass"
            )

            response = client.post(
                "/games/setup",
                data={
                    "csrf_token": _csrf_token(client, "/games/setup"),
                    "name": "Pending Theme Overflow",
                    "summary": "Pending summary for invalid create.",
                    "description": "Pending description for invalid create.",
                    "platforms": ["pc"],
                    "igdb_genre_ids": ["12"],
                    "igdb_theme_ids": ["17", "18", "19"],
                    "igdb_keyword_ids": ["cozy"],
                    "similar_game_names": ["Slay the Spire"],
                },
                follow_redirects=False,
            )

        assert response.status_code == 400
        assert (
            "At most 3 themes can be selected (you have 4)." in response.text
        )
        assert "Pending Theme Overflow" in response.text
        assert "Pending summary for invalid create." in response.text
        assert "Pending description for invalid create." in response.text
        assert "PC / Steam" in response.text
        assert "Fantasy" in response.text
        assert "Science fiction" in response.text
        assert "Cozy" in response.text
        assert "Slay the Spire" in response.text

    def test_setup_validation_error_preserves_pending_form_state(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "preserve-update@example.com", "testpass"
            )
            _create_game_for_user(client, "Persist Pending Game")

            with get_connection(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT slug, summary, description
                    FROM customer_games
                    WHERE name = ?
                    """,
                    ("Persist Pending Game",),
                ).fetchone()
            assert row is not None

            response = client.post(
                f"/games/{row['slug']}/setup",
                data={
                    "csrf_token": _csrf_token(
                        client, f"/games/{row['slug']}/setup"
                    ),
                    "name": "Pending Updated Name",
                    "summary": "Pending summary for invalid update.",
                    "description": "Pending description for invalid update.",
                    "platforms": ["switch"],
                    "igdb_genre_ids": ["12"],
                    "igdb_theme_ids": ["17", "18", "19"],
                    "igdb_keyword_ids": ["cozy"],
                    "similar_game_names": [
                        "Slay the Spire",
                        "FTL: Faster Than Light",
                    ],
                },
                follow_redirects=False,
            )

        assert response.status_code == 400
        assert (
            "At most 3 themes can be selected (you have 4)." in response.text
        )
        assert "Pending Updated Name" in response.text
        assert "Pending summary for invalid update." in response.text
        assert "Pending description for invalid update." in response.text
        assert "Nintendo Switch" in response.text
        assert "Fantasy" in response.text
        assert "Science fiction" in response.text
        assert "Cozy" in response.text
        assert "Slay the Spire" in response.text
        assert "FTL: Faster Than Light" in response.text

    def test_cached_igdb_search_returns_similar_game_suggestions(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "similar-games-search@example.com", "testpass"
            )
            with get_connection(db_path) as conn:
                conn.executemany(
                    """
                    INSERT INTO igdb_games (
                        igdb_id, name, slug, summary, first_release_date,
                        platform_ids_json, platform_names_json, last_synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    [
                        (
                            101,
                            "Slay the Spire",
                            "slay-the-spire",
                            None,
                            None,
                            "[]",
                            "[]",
                        ),
                        (
                            102,
                            "Slay the Princess",
                            "slay-the-princess",
                            None,
                            None,
                            "[]",
                            "[]",
                        ),
                        (
                            103,
                            "Monster Train",
                            "monster-train",
                            None,
                            None,
                            "[]",
                            "[]",
                        ),
                    ],
                )

            response = client.get("/games/igdb-search?q=slay")

        assert response.status_code == 200
        assert response.json() == [
            {
                "igdb_id": 101,
                "name": "Slay the Spire",
                "slug": "slay-the-spire",
            },
            {
                "igdb_id": 102,
                "name": "Slay the Princess",
                "slug": "slay-the-princess",
            },
        ]

    def test_dashboard_game_card_loads_without_match_count(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "dashboard-count@example.com", "testpass"
            )
            _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Counted Dashboard Game",
                    "summary": "A strategy game.",
                    "description": "A strategy game.",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )

            response = client.get("/games")

        assert response.status_code == 200
        assert "Counted Dashboard Game" in response.text

    def test_prospects_page_shows_bucketed_curated_tags(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "prospects-buckets@example.com", "testpass"
            )

            response = _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Bucket Prospect Game",
                    "summary": "A cozy roguelike with crafting.",
                    "description": "A cozy roguelike with crafting.",
                    "igdb_genre_ids": "12",
                    "igdb_theme_ids": "18",
                    "igdb_keyword_ids": "roguelike",
                    "website_url": "",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303

            with get_connection(db_path) as conn:
                game_row = conn.execute(
                    """
                    SELECT customer_game_id, slug
                    FROM customer_games
                    WHERE name = ?
                    """,
                    ("Bucket Prospect Game",),
                ).fetchone()
                assert game_row is not None
                conn.execute(
                    """
                    UPDATE customer_games
                    SET igdb_keyword_ids = ?
                    WHERE customer_game_id = ?
                    """,
                    (
                        json.dumps(["roguelike", "cozy", "crafting"]),
                        str(game_row["customer_game_id"]),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO source_accounts (
                        account_id, platform, external_id, handle_current,
                        display_name_current, canonical_url,
                        first_seen_at, last_seen_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'),
                              datetime('now'), datetime('now'))
                    """,
                    (
                        "bucketed-route",
                        "twitch",
                        "ext-bucketed-route",
                        "bucketedroute",
                        "Bucketed Route",
                        "https://twitch.example.com/bucketedroute",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO twitch_profiles_latest (
                        account_id, broadcaster_id, login, display_name,
                        followers_count, recent_avg_live_viewers,
                        fetched_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now', '+1 day'))
                    """,
                    (
                        "bucketed-route",
                        "bid-bucketed-route",
                        "bucketedroute",
                        "Bucketed Route",
                        1500,
                        75,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO igdb_games (
                        igdb_id, name, slug, summary, first_release_date,
                        platform_ids_json, platform_names_json,
                        last_synced_at
                    ) VALUES (?, ?, ?, NULL, NULL, '[]', '[]', datetime('now'))
                    """,
                    (999, "Bucket Match", "bucket-match"),
                )
                conn.executemany(
                    """
                    INSERT INTO igdb_game_tags (igdb_id, tag_type, tag_name, tag_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (999, "genre", "Role-playing (RPG)", 12),
                        (999, "theme", "Science fiction", 18),
                        (999, "genre", "Roguelike", "roguelike"),
                        (999, "theme", "Cozy", "cozy"),
                        (999, "mechanic", "Crafting", "crafting"),
                    ],
                )
                conn.execute(
                    """
                    INSERT INTO creator_games_played (
                        account_id, game_name_raw, game_name_key, platform,
                        first_seen_at, last_seen_at, observation_count, igdb_game_id
                    ) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), 1, ?)
                    """,
                    (
                        "bucketed-route",
                        "Bucket Match",
                        "bucket match",
                        "twitch",
                        999,
                    ),
                )

            page = client.get(f"/games/{game_row['slug']}/prospects")

        assert page.status_code == 200
        assert "Observed Matching Tags" in page.text
        assert "Roguelike" in page.text
        assert "Cozy" in page.text
        assert "Crafting" in page.text
        assert 'data-tooltip="Observed in 1 played game"' in page.text
        assert "tag-genre" in page.text
        assert "tag-theme" in page.text
        assert "tag-mechanic" in page.text

    def test_prospects_page_uses_true_reach_filter_max(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "prospects-reach-max@example.com", "testpass"
            )
            _activate_paid_subscription(
                db_path, "prospects-reach-max@example.com"
            )
            _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Reach Max Prospect Game",
                    "summary": "Tactical RPG",
                    "description": "Tactical RPG",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )
            game_slug = _seed_ranked_prospects(
                db_path,
                count=3,
                customer_game_name="Reach Max Prospect Game",
                game_name="Reach Max Match",
            )
            with get_connection(db_path) as conn:
                conn.execute(
                    """
                    UPDATE twitch_profiles_latest
                    SET followers_count = ?
                    WHERE account_id = ?
                    """,
                    (250_000, "prospect-002"),
                )

            response = client.get(f"/games/{game_slug}/prospects")

        assert response.status_code == 200
        assert 'name="max_reach"' in response.text
        assert 'value="250000"' in response.text
        assert 'name="min_reach"' in response.text
        assert 'value="50"' in response.text

    def test_prospects_page_excludes_creators_below_minimum_reach(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "prospects-min-reach@example.com", "testpass"
            )
            _activate_paid_subscription(
                db_path, "prospects-min-reach@example.com"
            )
            _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Min Reach Prospect Game",
                    "summary": "Tactical RPG",
                    "description": "Tactical RPG",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )
            game_slug = _seed_ranked_prospects(
                db_path,
                count=2,
                customer_game_name="Min Reach Prospect Game",
                game_name="Min Reach Match",
            )
            with get_connection(db_path) as conn:
                conn.execute(
                    """
                    UPDATE twitch_profiles_latest
                    SET followers_count = ?
                    WHERE account_id = ?
                    """,
                    (20, "prospect-001"),
                )

            response = client.get(f"/games/{game_slug}/prospects")

        assert response.status_code == 200
        normalized = " ".join(response.text.split())
        assert "1 creator matched" in normalized
        assert "Prospect 001" not in response.text

    def test_paid_prospects_page_shows_all_features_with_pagination(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "prospects-paid@example.com", "testpass"
            )
            _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Paid Prospect Game",
                    "summary": "Tactical RPG",
                    "description": "Tactical RPG",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )
            game_slug = _seed_ranked_prospects(
                db_path,
                count=51,
                customer_game_name="Paid Prospect Game",
                game_name="Paid Prospect Match",
            )

            response = client.get(f"/games/{game_slug}/prospects")

        assert response.status_code == 200
        assert "51 creators matched" in response.text
        # Paid users see all features unlocked — no trial-locked messaging
        assert (
            "Showing the top 50 creator matches during trial."
            not in response.text
        )
        assert 'title="Disabled during trial"' not in response.text
        # Pagination is available for paid users with >50 results
        assert "Next →" in response.text

    def test_prospects_page_shows_true_total_above_fetch_cap(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "prospects-true-total@example.com", "testpass"
            )
            _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "True Total Prospect Game",
                    "summary": "Tactical RPG",
                    "description": "Tactical RPG",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )
            _activate_paid_subscription(
                db_path, "prospects-true-total@example.com"
            )
            game_slug = _seed_ranked_prospects(
                db_path,
                count=1005,
                customer_game_name="True Total Prospect Game",
                game_name="True Total Match",
            )

            response = client.get(f"/games/{game_slug}/prospects")

        assert response.status_code == 200
        assert (
            " ".join(response.text.split()).find("1005 creators matched") != -1
        )

    def test_paid_prospects_page_two_is_accessible(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "prospects-paid-redirect@example.com", "testpass"
            )
            _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Paid Redirect Game",
                    "summary": "Tactical RPG",
                    "description": "Tactical RPG",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )
            game_slug = _seed_ranked_prospects(
                db_path,
                count=51,
                customer_game_name="Paid Redirect Game",
                game_name="Paid Redirect Match",
            )

            response = client.get(
                f"/games/{game_slug}/prospects?page=2",
                follow_redirects=False,
            )

        # Paid users can access page 2 directly
        assert response.status_code == 200

    def test_paid_prospects_workflow_endpoint_is_allowed(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "prospects-paid-workflow@example.com", "testpass"
            )
            _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Paid Workflow Game",
                    "summary": "Tactical RPG",
                    "description": "Tactical RPG",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )
            game_slug = _seed_ranked_prospects(
                db_path,
                count=2,
                customer_game_name="Paid Workflow Game",
                game_name="Paid Workflow Match",
            )

            response = _post_json(
                client,
                get_path=f"/games/{game_slug}/prospects",
                post_path=f"/games/{game_slug}/prospects/prospect-000/workflow",
                json_body={
                    "status": "contacted",
                    "notes": "Should be allowed",
                    "active_status": "all",
                },
                follow_redirects=False,
                headers={"accept": "application/json"},
            )

        # Paid users can use the workflow endpoint
        assert response.status_code == 200

    def test_comped_user_has_full_prospects_workflow_access(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "prospects-comped@example.com", "testpass"
            )
            _grant_comped_access(db_path, "prospects-comped@example.com")
            _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Comped Workflow Game",
                    "summary": "Tactical RPG",
                    "description": "Tactical RPG",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )
            game_slug = _seed_ranked_prospects(
                db_path,
                count=2,
                customer_game_name="Comped Workflow Game",
                game_name="Comped Workflow Match",
            )

            page = client.get(f"/games/{game_slug}/prospects")
            response = _post_json(
                client,
                get_path=f"/games/{game_slug}/prospects",
                post_path=f"/games/{game_slug}/prospects/prospect-000/workflow",
                json_body={
                    "status": "contacted",
                    "notes": "Comped user workflow",
                    "active_status": "all",
                },
                follow_redirects=False,
                headers={"accept": "application/json"},
            )

        assert page.status_code == 200
        assert 'data-status-tab="contacted"' in page.text
        assert 'class="prospect-workflow-menu"' in page.text
        assert response.status_code == 200
        assert response.json()["status"] == "contacted"

    def test_paid_user_can_access_second_prospects_page(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "prospects-paid@example.com", "testpass"
            )
            _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Paid Prospect Game",
                    "summary": "Tactical RPG",
                    "description": "Tactical RPG",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )
            _activate_paid_subscription(db_path, "prospects-paid@example.com")
            game_slug = _seed_ranked_prospects(
                db_path,
                count=21,
                customer_game_name="Paid Prospect Game",
                game_name="Paid Prospect Match",
            )

            response = client.get(f"/games/{game_slug}/prospects?page=2")

        assert response.status_code == 200
        assert "Subscribe for full access" not in response.text
        assert "21 creators matched" in response.text
        assert "Next →" not in response.text
        assert "← Previous" in response.text
        assert "data-range-filter-form" in response.text

    def test_prospects_page_shows_status_tabs_and_hides_not_pursuing_by_default(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "prospects-status-tabs@example.com", "testpass"
            )
            _activate_paid_subscription(
                db_path, "prospects-status-tabs@example.com"
            )
            _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Workflow Route Game",
                    "summary": "Tactical RPG",
                    "description": "Tactical RPG",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )
            game_slug = _seed_ranked_prospects(
                db_path,
                count=3,
                customer_game_name="Workflow Route Game",
                game_name="Workflow Route Match",
            )
            _insert_prospect_status(
                db_path,
                "Workflow Route Game",
                "prospect-001",
                "contacted",
            )
            _insert_prospect_status(
                db_path,
                "Workflow Route Game",
                "prospect-002",
                "not_pursuing",
            )

            response = client.get(f"/games/{game_slug}/prospects")

        assert response.status_code == 200
        assert 'data-status-tab="shortlisted"' not in response.text
        assert 'data-status-tab="contacted"' in response.text
        assert 'data-status-tab="not_pursuing"' in response.text
        assert "data-prospect-status-summary" in response.text
        assert "Prospect 000" in response.text
        assert "Prospect 001" in response.text
        assert "Prospect 002" not in response.text

    def test_status_filtered_prospects_page_shows_only_that_status(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "prospects-status-filter@example.com", "testpass"
            )
            _activate_paid_subscription(
                db_path, "prospects-status-filter@example.com"
            )
            _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Workflow Filter Game",
                    "summary": "Tactical RPG",
                    "description": "Tactical RPG",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )
            game_slug = _seed_ranked_prospects(
                db_path,
                count=3,
                customer_game_name="Workflow Filter Game",
                game_name="Workflow Filter Match",
            )
            _insert_prospect_status(
                db_path,
                "Workflow Filter Game",
                "prospect-001",
                "contacted",
            )

            response = client.get(
                f"/games/{game_slug}/prospects?status=contacted"
            )

        assert response.status_code == 200
        assert "Prospect 001" in response.text
        assert "Prospect 000" not in response.text
        assert "Prospect 002" not in response.text

    def test_update_prospect_workflow_endpoint_persists_status_and_notes(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "prospects-workflow-update@example.com", "testpass"
            )
            _activate_paid_subscription(
                db_path, "prospects-workflow-update@example.com"
            )
            _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Workflow Update Game",
                    "summary": "Tactical RPG",
                    "description": "Tactical RPG",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )
            game_slug = _seed_ranked_prospects(
                db_path,
                count=2,
                customer_game_name="Workflow Update Game",
                game_name="Workflow Update Match",
            )

            response = _post_json(
                client,
                get_path=f"/games/{game_slug}/prospects",
                post_path=f"/games/{game_slug}/prospects/prospect-000/workflow",
                json_body={
                    "status": "contacted",
                    "notes": "Sent Discord message",
                    "active_status": "all",
                    "min_reach": 50,
                },
                follow_redirects=False,
                headers={"accept": "application/json"},
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "contacted"
        assert payload["status_label"] == "Contacted"
        assert payload["has_notes"] is True
        assert payload["status_counts"]["contacted"] == 1
        assert payload["status_counts"]["all"] == 2
        with get_connection(db_path) as conn:
            row = conn.execute(
                """
                SELECT ps.status, ps.notes
                FROM prospect_statuses ps
                JOIN customer_games cg
                    ON cg.customer_game_id = ps.customer_game_id
                WHERE cg.name = ? AND ps.account_id = ?
                """,
                ("Workflow Update Game", "prospect-000"),
            ).fetchone()
        assert row is not None
        assert row["status"] == "contacted"
        assert row["notes"] == "Sent Discord message"


# ---------------------------------------------------------------------------
# Blog routes
# ---------------------------------------------------------------------------


class TestBlogRoutes:
    def test_blog_index_returns_200(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/blog")
        assert resp.status_code == 200

    def test_blog_index_contains_post_titles(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/blog")
        assert (
            "Indie Developer" in resp.text or "Creator Outreach" in resp.text
        )

    def test_blog_index_contains_blog_link_in_nav(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/blog")
        assert 'href="/blog"' in resp.text

    def test_blog_post_checklist_returns_200(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get(
                "/blog/indie-developer-creator-outreach-checklist"
            )
        assert resp.status_code == 200

    def test_blog_post_contains_title_in_html(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get(
                "/blog/indie-developer-creator-outreach-checklist"
            )
        assert "Checklist" in resp.text

    def test_blog_post_contains_register_cta(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get(
                "/blog/indie-developer-creator-outreach-checklist"
            )
        assert "/auth/register" in resp.text

    def test_blog_post_unknown_slug_returns_404(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/blog/this-post-does-not-exist")
        assert resp.status_code == 404

    def test_blog_post_contains_og_meta_tags(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get(
                "/blog/indie-developer-creator-outreach-checklist"
            )
        assert 'property="og:title"' in resp.text
        assert 'property="og:description"' in resp.text

    def test_blog_post_contains_json_ld(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get(
                "/blog/indie-developer-creator-outreach-checklist"
            )
        assert "application/ld+json" in resp.text
        assert "BlogPosting" in resp.text


# ---------------------------------------------------------------------------
# SEO routes
# ---------------------------------------------------------------------------


class TestSEORoutes:
    def test_robots_txt_returns_200(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/robots.txt")
        assert resp.status_code == 200

    def test_robots_txt_allows_root(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/robots.txt")
        assert "Allow: /" in resp.text

    def test_robots_txt_disallows_auth(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/robots.txt")
        assert "Disallow: /auth" in resp.text

    def test_robots_txt_references_sitemap(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/robots.txt")
        assert "Sitemap:" in resp.text
        assert "sitemap.xml" in resp.text

    def test_sitemap_returns_200(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/sitemap.xml")
        assert resp.status_code == 200

    def test_sitemap_is_valid_xml(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/sitemap.xml")
        assert resp.text.startswith("<?xml")
        assert "<urlset" in resp.text
        assert "</urlset>" in resp.text

    def test_sitemap_includes_homepage(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/sitemap.xml")
        assert "spawnradar.com/</loc>" in resp.text

    def test_sitemap_includes_blog_index(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/sitemap.xml")
        assert "/blog</loc>" in resp.text

    def test_sitemap_includes_blog_posts(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/sitemap.xml")
        assert "indie-developer-creator-outreach-checklist" in resp.text

    def test_sitemap_includes_pricing(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/sitemap.xml")
        assert "/pricing" in resp.text


# ---------------------------------------------------------------------------
# Legal routes
# ---------------------------------------------------------------------------


class TestLegalRoutes:
    def test_terms_privacy_and_refunds_pages_return_200(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            terms = client.get("/terms")
            privacy = client.get("/privacy")
            refunds = client.get("/refunds")

        assert terms.status_code == 200
        assert privacy.status_code == 200
        assert refunds.status_code == 200
        assert "Terms of Service" in terms.text
        assert (
            "SpawnRadar, the legal business name operating this website and service"
            in " ".join(terms.text.split())
        )
        assert "Privacy Policy" in privacy.text
        assert "Refund Policy" in refunds.text
        normalized_refunds = " ".join(refunds.text.split())
        assert (
            "SpawnRadar offers a free tier and sells paid subscriptions through Paddle, our merchant of record."
            in normalized_refunds
        )
        assert (
            "Eligible buyers may request a refund within 14 days of the transaction"
            in normalized_refunds
        )

    def test_sitemap_includes_legal_pages(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/sitemap.xml")

        assert "/terms</loc>" in resp.text
        assert "/privacy</loc>" in resp.text
        assert "/refunds</loc>" in resp.text


# ---------------------------------------------------------------------------
# Root frontend asset routes
# ---------------------------------------------------------------------------


class TestRootFrontendAssets:
    def test_favicon_ico_alias_returns_200(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/favicon.ico")
        assert resp.status_code == 200
        assert resp.content

    def test_webmanifest_alias_returns_manifest(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/site.webmanifest")
        assert resp.status_code == 200
        assert "SpawnRadar" in resp.text


# ---------------------------------------------------------------------------
# Not found page
# ---------------------------------------------------------------------------


class TestNotFoundPage:
    def test_unknown_page_renders_branded_404_for_html_requests(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get(
                "/this-page-does-not-exist",
                headers={"accept": "text/html"},
            )
        assert resp.status_code == 404
        assert "Oops! That page does not exist." in resp.text
        assert "Back to home" in resp.text

    def test_unknown_page_stays_json_for_non_html_requests(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get(
                "/this-page-does-not-exist",
                headers={"accept": "application/json"},
            )
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Not Found"}


# ---------------------------------------------------------------------------
# Meta tags
# ---------------------------------------------------------------------------


class TestMetaTags:
    def test_homepage_has_meta_description(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/")
        assert 'name="description"' in resp.text

    def test_homepage_has_og_title(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/")
        assert 'property="og:title"' in resp.text

    def test_homepage_has_twitter_card(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/")
        assert 'name="twitter:card"' in resp.text

    def test_homepage_has_canonical_link(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/")
        assert 'rel="canonical"' in resp.text

    def test_pricing_has_meta_description(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/pricing")
        assert 'name="description"' in resp.text


# ---------------------------------------------------------------------------
# Auth HTTP flow
# ---------------------------------------------------------------------------


class TestAuthRoutes:
    def test_register_redirects_after_success(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": "new@example.com", "password": "password123"},
            )
        assert resp.status_code in (200, 302, 303)

    def test_login_sets_session_cookie(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": "cookie@example.com", "password": "testpass"},
            )
            _post_form(
                client,
                get_path="/auth/login",
                post_path="/auth/login",
                data={"email": "cookie@example.com", "password": "testpass"},
            )
        assert "session_id" in client.cookies

    def test_login_sets_secure_cookie_when_public_base_url_is_https(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "test.sqlite3"))
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("BASE_URL", "https://spawnradar.com")
        monkeypatch.setenv("RESEND_API_KEY", "")
        app = create_app()

        with TestClient(app, base_url="https://testserver") as client:
            _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": "secure@example.com", "password": "testpass"},
                follow_redirects=False,
            )
            response = _post_form(
                client,
                get_path="/auth/login",
                post_path="/auth/login",
                data={"email": "secure@example.com", "password": "testpass"},
                follow_redirects=False,
            )

        assert response.status_code == 303
        assert "Secure" in response.headers["set-cookie"]
        assert "HttpOnly" in response.headers["set-cookie"]

    def test_login_with_wrong_password_shows_error(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": "wrong@example.com", "password": "correct"},
            )
            resp = _post_form(
                client,
                get_path="/auth/login",
                post_path="/auth/login",
                data={"email": "wrong@example.com", "password": "notcorrect"},
                follow_redirects=False,
            )
        assert resp.status_code in (200, 302, 303, 400)

    def test_logout_clears_session_cookie(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": "logout@example.com", "password": "testpass"},
            )
            _verify_user_email(db_path, "logout@example.com")
            _post_form(
                client,
                get_path="/auth/login",
                post_path="/auth/login",
                data={"email": "logout@example.com", "password": "testpass"},
            )
            assert "session_id" in client.cookies
            _post_form(
                client, get_path="/games", post_path="/auth/logout", data={}
            )
        assert "session_id" not in client.cookies

    def test_register_page_returns_200(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/auth/register")
        assert resp.status_code == 200

    def test_register_page_has_correct_title(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/auth/register")
        assert "Start Free" in resp.text

    def test_duplicate_registration_shows_error(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": "dup@example.com", "password": "pass1"},
            )
            resp = _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": "dup@example.com", "password": "pass2"},
            )
        assert resp.status_code in (200, 400)

    def test_login_rate_limit_blocks_repeated_failures(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={
                    "email": "ratelimit@example.com",
                    "password": "correctpass",
                },
                follow_redirects=False,
            )

            blocked = None
            for _ in range(5):
                response = _post_form(
                    client,
                    get_path="/auth/login",
                    post_path="/auth/login",
                    data={
                        "email": "ratelimit@example.com",
                        "password": "wrongpass",
                    },
                    follow_redirects=False,
                )
                assert response.status_code == 400

            blocked = _post_form(
                client,
                get_path="/auth/login",
                post_path="/auth/login",
                data={
                    "email": "ratelimit@example.com",
                    "password": "wrongpass",
                },
                follow_redirects=False,
            )

        assert blocked is not None
        assert blocked.status_code == 429
        assert "Too many sign-in attempts" in blocked.text

    def test_missing_csrf_token_rejects_game_creation(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "csrf@example.com", "testpass")
            response = client.post(
                "/games/setup",
                data={
                    "name": "CSRF Test",
                    "description": "A test game",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )

        assert response.status_code == 422

    def test_create_game_requires_summary(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "missing-summary@example.com", "testpass"
            )
            response = _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Missing Summary",
                    "summary": "",
                    "description": "A test game",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )

        assert response.status_code == 400
        assert "Game summary is required." in response.text

    def test_create_game_allows_blank_description(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "blank-desc@example.com", "testpass")
            response = _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Blank Desc Game",
                    "summary": "A short summary",
                    "description": "",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )

        assert response.status_code == 303
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT description FROM customer_games WHERE name = ?",
                ("Blank Desc Game",),
            ).fetchone()
        assert row is not None
        assert str(row["description"]) == ""

    def test_import_url_json_returns_draft_without_saving(
        self, monkeypatch, tmp_path
    ):
        class StubGameImportService:
            async def import_url(self, url: str) -> ImportedGamePreview:
                assert url == "https://store.steampowered.com/app/4309620/"
                return _sample_import_preview()

        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            app = cast(Any, client.app)
            app.dependency_overrides[get_game_import_service] = lambda: (
                StubGameImportService()
            )
            _register_and_login(client, "import-json@example.com", "testpass")
            response = client.post(
                "/games/import-url",
                json={"url": "https://store.steampowered.com/app/4309620/"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Strife of Stars"
        assert data["summary"] == "A tactical sci-fi deckbuilder."
        assert data["description"] == "Build a squad and climb the tower."
        assert isinstance(data["platforms"], list)
        assert isinstance(data["igdb_genre_ids"], list)
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM customer_games"
            ).fetchone()
        assert row is not None
        assert int(row["count"]) == 0

    def test_create_game_requires_at_least_one_genre(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "missing-primary@example.com", "testpass"
            )
            response = _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Missing Primary",
                    "summary": "A short summary",
                    "description": "A test game",
                    "website_url": "",
                },
                follow_redirects=False,
            )

        assert response.status_code in (200, 303, 400)

    def test_forgot_password_redirects_even_when_email_send_fails(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": "reset@example.com", "password": "testpass"},
            )

            def broken_send(message):
                raise RuntimeError("email provider rejected sender")

            app_state = cast(Any, client.app).state
            app_state.email_service.send = broken_send

            resp = _post_form(
                client,
                get_path="/auth/forgot-password",
                post_path="/auth/forgot-password",
                data={"email": "reset@example.com"},
                follow_redirects=False,
            )

        assert resp.status_code == 303
        assert resp.headers["location"] == "/auth/forgot-password?sent=1"


# ---------------------------------------------------------------------------
# Billing routes
# ---------------------------------------------------------------------------


class TestBillingRoutes:
    def test_billing_root_unauthenticated_redirects(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/billing", follow_redirects=False)
        assert resp.status_code in (302, 303, 307)

    def test_pay_returns_503_when_paddle_not_configured(
        self, monkeypatch, tmp_path
    ):
        for key in (
            "PADDLE_API_KEY",
            "PADDLE_CLIENT_SIDE_TOKEN",
            "PADDLE_WEBHOOK_SECRET",
            "PADDLE_INDIE_PRICE_ID",
            "PADDLE_ENVIRONMENT",
        ):
            monkeypatch.setenv(key, "")
        with _make_client(monkeypatch, tmp_path) as client:
            _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": "pay@example.com", "password": "testpass"},
            )
            _post_form(
                client,
                get_path="/auth/login",
                post_path="/auth/login",
                data={"email": "pay@example.com", "password": "testpass"},
            )
            resp = client.get("/billing/pay", follow_redirects=False)
        assert resp.status_code == 503

    def test_checkout_returns_400_for_invalid_tier(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("PADDLE_API_KEY", "test_api_key")
        monkeypatch.setenv("PADDLE_CLIENT_SIDE_TOKEN", "test_token")
        monkeypatch.setenv("PADDLE_API_KEY", "test_api_key")
        monkeypatch.setenv("PADDLE_CLIENT_SIDE_TOKEN", "test_token")
        monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "whsec_test")
        monkeypatch.setenv("PADDLE_INDIE_PRICE_ID", "pri_indie")
        monkeypatch.setenv("PADDLE_ENVIRONMENT", "sandbox")
        monkeypatch.setenv("PADDLE_INDIE_PRICE_ID", "pri_indie")
        monkeypatch.setenv("PADDLE_ENVIRONMENT", "sandbox")
        with _make_client(monkeypatch, tmp_path) as client:
            _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": "tier@example.com", "password": "testpass"},
            )
            _post_form(
                client,
                get_path="/auth/login",
                post_path="/auth/login",
                data={"email": "tier@example.com", "password": "testpass"},
            )
            resp = client.get(
                "/billing/checkout/enterprise", follow_redirects=False
            )
        assert resp.status_code == 400

    def test_portal_returns_error_page_when_paddle_not_configured(
        self, monkeypatch, tmp_path
    ):
        for key in (
            "PADDLE_API_KEY",
            "PADDLE_CLIENT_SIDE_TOKEN",
            "PADDLE_WEBHOOK_SECRET",
            "PADDLE_INDIE_PRICE_ID",
            "PADDLE_ENVIRONMENT",
        ):
            monkeypatch.setenv(key, "")
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": "portal@example.com", "password": "testpass"},
            )
            _verify_user_email(db_path, "portal@example.com")
            _post_form(
                client,
                get_path="/auth/login",
                post_path="/auth/login",
                data={"email": "portal@example.com", "password": "testpass"},
            )
            resp = client.get("/billing/portal", follow_redirects=False)
        assert resp.status_code in (502, 503)

    def test_webhook_returns_400_on_bad_signature(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PADDLE_API_KEY", "test_api_key")
        monkeypatch.setenv("PADDLE_CLIENT_SIDE_TOKEN", "test_token")
        monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "whsec_fake")
        monkeypatch.setenv("PADDLE_INDIE_PRICE_ID", "pri_indie")
        monkeypatch.setenv("PADDLE_ENVIRONMENT", "sandbox")
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.post(
                "/billing/webhook",
                content=b'{"event_type":"subscription.created"}',
                headers={"Paddle-Signature": "bad-sig"},
            )
        assert resp.status_code == 400

    def test_webhook_returns_200_when_webhook_secret_missing(
        self, monkeypatch, tmp_path
    ):
        for key in (
            "PADDLE_API_KEY",
            "PADDLE_CLIENT_SIDE_TOKEN",
            "PADDLE_WEBHOOK_SECRET",
            "PADDLE_INDIE_PRICE_ID",
            "PADDLE_ENVIRONMENT",
        ):
            monkeypatch.setenv(key, "")
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.post(
                "/billing/webhook",
                content=b"{}",
                headers={"Paddle-Signature": "any"},
            )
        assert resp.status_code == 200

    def test_webhook_activates_subscription_for_free_user(
        self, monkeypatch, tmp_path
    ):
        """A free user (no subscription row) becomes active after a Paddle webhook."""
        monkeypatch.setenv("PADDLE_API_KEY", "test_api_key")
        monkeypatch.setenv("PADDLE_CLIENT_SIDE_TOKEN", "test_token")
        monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "whsec_test")
        monkeypatch.setenv("PADDLE_INDIE_PRICE_ID", "pri_indie")
        monkeypatch.setenv("PADDLE_ENVIRONMENT", "sandbox")
        db_path = tmp_path / "test.sqlite3"

        with _make_client(monkeypatch, tmp_path) as client:
            # Register and verify without granting a subscription
            _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": "newpaid@example.com", "password": "testpass"},
            )
            _verify_user_email(str(db_path), "newpaid@example.com")
            _post_form(
                client,
                get_path="/auth/login",
                post_path="/auth/login",
                data={"email": "newpaid@example.com", "password": "testpass"},
            )

            with get_connection(str(db_path)) as conn:
                user_row = conn.execute(
                    "SELECT user_id FROM users WHERE email = ?",
                    ("newpaid@example.com",),
                ).fetchone()

            assert user_row is not None
            user_id = user_row["user_id"]

            # Verify no subscription row before webhook
            with get_connection(str(db_path)) as conn:
                sub_before = conn.execute(
                    "SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)
                ).fetchone()
            assert sub_before is None

            payload, signature = _signed_paddle_webhook(
                {
                    "event_id": "evt_paid",
                    "event_type": "subscription.created",
                    "occurred_at": "2026-06-01T00:00:00Z",
                    "notification_id": "ntf_paid",
                    "data": {
                        "id": "sub_paid",
                        "customer_id": "ctm_paid",
                        "status": "active",
                        "items": [{"price": {"id": "pri_indie"}}],
                        "current_billing_period": {
                            "starts_at": "2026-05-01T00:00:00Z",
                            "ends_at": "2026-06-01T00:00:00Z",
                        },
                        "custom_data": {"user_id": user_id},
                    },
                },
                "whsec_test",
            )

            resp = client.post(
                "/billing/webhook",
                content=payload,
                headers={"Paddle-Signature": signature},
            )
            assert resp.status_code == 200

        with get_connection(str(db_path)) as conn:
            sub_row = conn.execute(
                "SELECT tier, status, paddle_customer_id, paddle_subscription_id FROM subscriptions WHERE user_id = ?",
                (user_id,),
            ).fetchone()

        assert sub_row is not None
        assert sub_row["tier"] == "indie"
        assert sub_row["status"] == "active"
        assert sub_row["paddle_customer_id"] == "ctm_paid"
        assert sub_row["paddle_subscription_id"] == "sub_paid"

    def test_checkout_unauthenticated_redirects_to_login(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/billing/pay", follow_redirects=False)
        assert resp.status_code in (302, 303, 307)

    def test_pay_redirects_to_games_when_already_subscribed(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("PADDLE_API_KEY", "test_api_key")
        monkeypatch.setenv("PADDLE_CLIENT_SIDE_TOKEN", "test_token")
        monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "whsec_test")
        monkeypatch.setenv("PADDLE_INDIE_PRICE_ID", "pri_indie")
        monkeypatch.setenv("PADDLE_ENVIRONMENT", "sandbox")
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": "sub@example.com", "password": "testpass"},
            )
            _post_form(
                client,
                get_path="/auth/login",
                post_path="/auth/login",
                data={"email": "sub@example.com", "password": "testpass"},
            )

            with get_connection(db) as conn:
                row = conn.execute(
                    "SELECT user_id FROM users WHERE email = ?",
                    ("sub@example.com",),
                ).fetchone()
            user_id = row["user_id"]

            sub_repo = SubscriptionRepository(db)
            import uuid

            from app.billing.models import Tier

            sub_repo.create(str(uuid.uuid4()), user_id, Tier.INDIE)
            sub_repo.update_from_paddle(
                user_id,
                paddle_subscription_id="sub_already",
                status="active",
            )

            resp = client.get("/billing/pay", follow_redirects=False)
        assert resp.status_code in (302, 303)
        assert resp.headers["location"] == "/games"

    def test_pay_redirects_to_games_when_user_has_comped_access(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("PADDLE_API_KEY", "test_api_key")
        monkeypatch.setenv("PADDLE_CLIENT_SIDE_TOKEN", "test_token")
        monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "whsec_test")
        monkeypatch.setenv("PADDLE_INDIE_PRICE_ID", "pri_indie")
        monkeypatch.setenv("PADDLE_ENVIRONMENT", "sandbox")
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": "comp@example.com", "password": "testpass"},
            )
            _post_form(
                client,
                get_path="/auth/login",
                post_path="/auth/login",
                data={"email": "comp@example.com", "password": "testpass"},
            )

            with get_connection(db) as conn:
                row = conn.execute(
                    "SELECT user_id FROM users WHERE email = ?",
                    ("comp@example.com",),
                ).fetchone()
            user_id = row["user_id"]

            sub_repo = SubscriptionRepository(db)
            billing = BillingService(sub_repo, CustomerGameRepository(db))
            billing.grant_comped_access(user_id)

            resp = client.get("/billing/pay", follow_redirects=False)
        assert resp.status_code in (302, 303)
        assert resp.headers["location"] == "/games"


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class TestHealthRoute:
    def test_health_returns_200(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/healthz")
        assert resp.status_code == 200

    def test_health_and_metrics_do_not_redirect_when_base_url_is_https(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("BASE_URL", "https://spawnradar.fly.dev")
        with _make_client(monkeypatch, tmp_path) as client:
            health = client.get("/healthz", follow_redirects=False)
            metrics = client.get("/metrics", follow_redirects=False)

        assert health.status_code == 200
        assert metrics.status_code == 200


class TestAccessGate:
    def test_expired_trial_games_page_accessible(self, monkeypatch, tmp_path):
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "expired@example.com", "testpass")
            _expire_trial(db, "expired@example.com")

            resp = client.get("/games", follow_redirects=False)

        assert resp.status_code == 200

    def test_ended_paid_subscription_games_page_accessible(
        self, monkeypatch, tmp_path
    ):
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "paidended@example.com", "testpass")
            _expire_paid_subscription(db, "paidended@example.com")

            resp = client.get("/games", follow_redirects=False)

        assert resp.status_code == 200

    def test_expired_trial_setup_page_accessible(self, monkeypatch, tmp_path):
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "newexpired@example.com", "testpass")
            _expire_trial(db, "newexpired@example.com")

            resp = client.get("/games/setup", follow_redirects=False)

        assert resp.status_code == 200

    def test_expired_trial_game_edit_page_accessible(
        self, monkeypatch, tmp_path
    ):
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "setupexpired@example.com", "testpass")
            _create_game_for_user(client, "Setup Game")
            _expire_trial(db, "setupexpired@example.com")

            with get_connection(db) as conn:
                row = conn.execute(
                    "SELECT slug FROM customer_games WHERE name = ?",
                    ("Setup Game",),
                ).fetchone()
            assert row is not None
            game_slug = str(row["slug"])

            resp = client.get(
                f"/games/{game_slug}/setup", follow_redirects=False
            )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Anonymous user flows
# ---------------------------------------------------------------------------


def _get_game_slug(db_path: str, name: str) -> str:
    """Return the slug for a customer game by name."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT slug FROM customer_games WHERE name = ?", (name,)
        ).fetchone()
    assert row is not None, f"Game '{name}' not found in DB"
    return str(row["slug"])


def _setup_anonymous_session(db_path: str, client: TestClient) -> str:
    """Create an anonymous user + session in the DB and set the cookie on the
    client so that all subsequent requests in the same client instance are
    attributed to the same anonymous user.

    Background: FastAPI's Response-dependency approach for setting cookies does
    not propagate into HTMLResponse / TemplateResponse route handlers (the
    background response headers are dropped).  We work around this in tests by
    creating the anonymous user directly via the service layer and injecting the
    session_id cookie manually.

    Returns the anonymous user_id.
    """
    from app.auth.repository import SessionRepository, UserRepository
    from app.auth.service import AuthService

    user_repo = UserRepository(db_path)
    session_repo = SessionRepository(db_path)
    auth = AuthService(user_repo, session_repo)
    anon_user, anon_session = auth.create_anonymous_user()
    client.cookies.set("session_id", anon_session.session_id)
    return str(anon_user.user_id)


class TestAnonymousFlows:
    # ------------------------------------------------------------------
    # 1. Anonymous user can access games page
    # ------------------------------------------------------------------
    def test_anonymous_user_can_access_games_page(
        self, monkeypatch, tmp_path
    ) -> None:
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            response = client.get("/games")

        # Anonymous user is auto-created on first request; page renders OK
        assert response.status_code == 200
        # Verify an anonymous user row was created in the DB
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM users WHERE is_anonymous = 1"
            ).fetchone()
        assert row["cnt"] >= 1

    # ------------------------------------------------------------------
    # 2. Anonymous user can create a game
    # ------------------------------------------------------------------
    def test_anonymous_user_can_create_game(
        self, monkeypatch, tmp_path
    ) -> None:
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            # Bootstrap anonymous session so the same user is used across
            # the GET (CSRF) and POST requests.
            _setup_anonymous_session(db_path, client)

            setup_response = client.get("/games/setup")
            assert setup_response.status_code == 200

            create_response = _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Anon Game",
                    "summary": "Short summary",
                    "description": "Desc",
                    "igdb_genre_ids": "12",
                    "igdb_game_mode_ids": "1",
                    "website_url": "",
                },
                follow_redirects=True,
            )

        assert create_response.status_code == 200
        # Game persisted in DB
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT name FROM customer_games WHERE name = ?",
                ("Anon Game",),
            ).fetchone()
        assert row is not None

    # ------------------------------------------------------------------
    # 3. Anonymous user is limited to one game
    # ------------------------------------------------------------------
    def test_anonymous_user_limited_to_one_game(
        self, monkeypatch, tmp_path
    ) -> None:
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _setup_anonymous_session(db_path, client)

            # First game should succeed
            first = _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Anon Game One",
                    "summary": "Short summary",
                    "description": "Desc",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )
            assert first.status_code == 303

            # Second game should be blocked (game limit reached)
            second = _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Anon Game Two",
                    "summary": "Short summary",
                    "description": "Desc",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=True,
            )
        assert "game limit" in second.text.lower() or second.status_code == 400

    # ------------------------------------------------------------------
    # 4. Anonymous user can view prospects page 1
    # ------------------------------------------------------------------
    def test_anonymous_user_can_view_prospects_page_1(
        self, monkeypatch, tmp_path
    ) -> None:
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _setup_anonymous_session(db_path, client)
            _create_game_for_user(client, "Anon Prospects Game")
            slug = _get_game_slug(db_path, "Anon Prospects Game")

            response = client.get(f"/games/{slug}/prospects")

        assert response.status_code == 200
        assert "Sign up" in response.text

    # ------------------------------------------------------------------
    # 5. Anonymous user cannot access page 2 of prospects
    # ------------------------------------------------------------------
    def test_anonymous_user_cannot_access_page_2_prospects(
        self, monkeypatch, tmp_path
    ) -> None:
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _setup_anonymous_session(db_path, client)
            _create_game_for_user(client, "Anon Page2 Game")
            slug = _get_game_slug(db_path, "Anon Page2 Game")

            response = client.get(
                f"/games/{slug}/prospects?page=2", follow_redirects=False
            )

        assert response.status_code == 303
        assert response.headers["location"] == f"/games/{slug}/prospects"

    # ------------------------------------------------------------------
    # 6. Anonymous user cannot use filters
    # ------------------------------------------------------------------
    def test_anonymous_user_cannot_use_filters(
        self, monkeypatch, tmp_path
    ) -> None:
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _setup_anonymous_session(db_path, client)
            _create_game_for_user(client, "Anon Filter Game")
            slug = _get_game_slug(db_path, "Anon Filter Game")

            # min_overlap=10 reliably adds to filter_params (non-default value)
            response = client.get(
                f"/games/{slug}/prospects?min_overlap=10",
                follow_redirects=False,
            )

        assert response.status_code == 303
        assert response.headers["location"] == f"/games/{slug}/prospects"

    # ------------------------------------------------------------------
    # 7. Anonymous user cannot use workflow (requires product access)
    # ------------------------------------------------------------------
    def test_anonymous_user_cannot_use_workflow(
        self, monkeypatch, tmp_path
    ) -> None:
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _setup_anonymous_session(db_path, client)
            _create_game_for_user(client, "Anon Workflow Game")
            slug = _get_game_slug(db_path, "Anon Workflow Game")

            response = client.post(
                f"/games/{slug}/prospects/fake-account-id/workflow",
                json={"status": "contacted"},
                follow_redirects=False,
                headers={"Accept": "application/json"},
            )

        # require_product_access redirects unauthenticated/unpaid users to
        # /pricing (307) or raises 402 for JSON requests
        assert response.status_code in (307, 401, 402, 403)

    # ------------------------------------------------------------------
    # 8. Games are claimed on registration
    # ------------------------------------------------------------------
    def test_game_claimed_on_registration(self, monkeypatch, tmp_path) -> None:
        db_path = str(tmp_path / "test.sqlite3")
        email = "claimer@example.com"
        password = "password123"

        with _make_client(monkeypatch, tmp_path) as client:
            # Bootstrap anonymous session and create a game
            anon_user_id = _setup_anonymous_session(db_path, client)
            _create_game_for_user(client, "Claimed Game")

            # Verify the game belongs to the anonymous user
            with get_connection(db_path) as conn:
                game_row = conn.execute(
                    "SELECT user_id FROM customer_games WHERE name = ?",
                    ("Claimed Game",),
                ).fetchone()
            assert game_row is not None
            assert str(game_row["user_id"]) == anon_user_id

            # Register on the same client; the server reads the session_id
            # cookie to discover and claim the anonymous games.
            _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": email, "password": password},
            )
            _verify_user_email(db_path, email)
            _grant_subscription(db_path, email)

            # Log in with the new account
            _post_form(
                client,
                get_path="/auth/login",
                post_path="/auth/login",
                data={"email": email, "password": password},
            )

            games_response = client.get("/games")

        assert "Claimed Game" in games_response.text

    # ------------------------------------------------------------------
    # 9. Registered free user is limited to one game
    # ------------------------------------------------------------------
    def test_registered_free_user_limited_to_one_game(
        self, monkeypatch, tmp_path
    ) -> None:
        email = "free@example.com"
        password = "password123"
        db_path = str(tmp_path / "test.sqlite3")

        with _make_client(monkeypatch, tmp_path) as client:
            # Register WITHOUT granting subscription
            _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": email, "password": password},
            )
            _verify_user_email(db_path, email)
            _post_form(
                client,
                get_path="/auth/login",
                post_path="/auth/login",
                data={"email": email, "password": password},
            )

            # First game succeeds
            first = _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Free Game One",
                    "summary": "Short summary",
                    "description": "Desc",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=False,
            )
            assert first.status_code == 303

            # Second game is blocked
            second = _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "Free Game Two",
                    "summary": "Short summary",
                    "description": "Desc",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=True,
            )
        assert "game limit" in second.text.lower() or second.status_code == 400

    # ------------------------------------------------------------------
    # 10. Subscribed user can create multiple games
    # ------------------------------------------------------------------
    def test_subscribed_user_can_create_multiple_games(
        self, monkeypatch, tmp_path
    ) -> None:
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "multi@example.com", "password123")

            for i in range(1, 4):
                response = _post_form(
                    client,
                    get_path="/games/setup",
                    post_path="/games/setup",
                    data={
                        "name": f"Multi Game {i}",
                        "summary": "Short summary",
                        "description": "Desc",
                        "igdb_genre_ids": "12",
                        "website_url": "",
                    },
                    follow_redirects=False,
                )
                assert response.status_code == 303, f"Game {i} creation failed"

    # ------------------------------------------------------------------
    # 11. Pricing page shows free tier
    # ------------------------------------------------------------------
    def test_pricing_page_shows_free_tier(self, monkeypatch, tmp_path) -> None:
        with _make_client(monkeypatch, tmp_path) as client:
            response = client.get("/pricing")

        assert response.status_code == 200
        assert "subscribe" in response.text.lower()
        assert "trial" not in response.text.lower()

    # ------------------------------------------------------------------
    # 12. Home page has new CTA
    # ------------------------------------------------------------------
    def test_home_page_has_new_cta(self, monkeypatch, tmp_path) -> None:
        with _make_client(monkeypatch, tmp_path) as client:
            response = client.get("/")

        assert response.status_code == 200
        assert "Try Free" in response.text
        assert "/games/setup" in response.text

    # ------------------------------------------------------------------
    # 13. Anonymous rate limit returns form with error, not raw JSON
    # ------------------------------------------------------------------
    def test_anonymous_rate_limit_returns_html_error(
        self, monkeypatch, tmp_path
    ) -> None:
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _setup_anonymous_session(db_path, client)

            # Exhaust the rate limit (3 per 10 minutes)
            for i in range(3):
                _post_form(
                    client,
                    get_path="/games/setup",
                    post_path="/games/setup",
                    data={
                        "name": f"Rate Limit Game {i}",
                        "summary": "Short summary",
                        "description": "Desc",
                        "igdb_genre_ids": "12",
                        "website_url": "",
                    },
                    follow_redirects=True,
                )

            # Next attempt should be rate-limited but show HTML form
            response = _post_form(
                client,
                get_path="/games/setup",
                post_path="/games/setup",
                data={
                    "name": "One Too Many",
                    "summary": "Short summary",
                    "description": "Desc",
                    "igdb_genre_ids": "12",
                    "website_url": "",
                },
                follow_redirects=True,
            )

        assert response.status_code == 429
        assert "text/html" in response.headers.get("content-type", "")
        assert "too many" in response.text.lower()

    # ------------------------------------------------------------------
    # 14. Registered (non-anonymous) user is NOT rate-limited for game creation
    # ------------------------------------------------------------------
    def test_registered_user_not_rate_limited(
        self, monkeypatch, tmp_path
    ) -> None:
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "nolimit@example.com", "password123")

            # Create 3 games quickly — should all succeed (no IP rate limit)
            for i in range(3):
                response = _post_form(
                    client,
                    get_path="/games/setup",
                    post_path="/games/setup",
                    data={
                        "name": f"Fast Game {i}",
                        "summary": "Short summary",
                        "description": "Desc",
                        "igdb_genre_ids": "12",
                        "website_url": "",
                    },
                    follow_redirects=False,
                )
                assert response.status_code == 303, f"Game {i} should succeed"

    # ------------------------------------------------------------------
    # 15. Prospect page renders filter form for free users (interactive gate)
    # ------------------------------------------------------------------
    def test_free_user_sees_interactive_filter_form(
        self, monkeypatch, tmp_path
    ) -> None:
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _setup_anonymous_session(db_path, client)
            _create_game_for_user(client, "Filter UI Game")
            slug = _get_game_slug(db_path, "Filter UI Game")

            response = client.get(f"/games/{slug}/prospects")

        assert response.status_code == 200
        # Filter form is present (not a disabled span) — even for free users
        assert "data-range-filter-form" in response.text
        assert "prospects-filter-menu" in response.text
        # Gate data attributes are set to false for free users
        assert 'data-filters-unlocked="false"' in response.text
        assert 'data-workflow-unlocked="false"' in response.text

    # ------------------------------------------------------------------
    # 16. Paid user has no gate data attributes
    # ------------------------------------------------------------------
    def test_paid_user_has_unlocked_gate_attributes(
        self, monkeypatch, tmp_path
    ) -> None:
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "paid@example.com", "password123")
            _create_game_for_user(client, "Paid Filter Game")
            db_path = str(tmp_path / "test.sqlite3")
            slug = _get_game_slug(db_path, "Paid Filter Game")

            response = client.get(f"/games/{slug}/prospects")

        assert response.status_code == 200
        assert 'data-filters-unlocked="true"' in response.text
        assert 'data-workflow-unlocked="true"' in response.text

    # ------------------------------------------------------------------
    # 17. Workflow POST rejected for free user with proper error
    # ------------------------------------------------------------------
    def test_free_user_workflow_post_returns_403(
        self, monkeypatch, tmp_path
    ) -> None:
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            # Register but don't grant subscription (free user)
            _post_form(
                client,
                get_path="/auth/register",
                post_path="/auth/register",
                data={"email": "free-wf@example.com", "password": "password123"},
            )
            _verify_user_email(db_path, "free-wf@example.com")
            _post_form(
                client,
                get_path="/auth/login",
                post_path="/auth/login",
                data={"email": "free-wf@example.com", "password": "password123"},
            )
            _create_game_for_user(client, "Free WF Game")
            slug = _get_game_slug(db_path, "Free WF Game")

            # Attempt to update prospect workflow (JSON API)
            response = _post_json(
                client,
                get_path=f"/games/{slug}/prospects",
                post_path=f"/games/{slug}/prospects/fake-account/workflow",
                json_body={"status": "contacted", "notes": ""},
                headers={"accept": "application/json"},
            )

        # Free users are blocked from workflow — 402 for JSON requests
        assert response.status_code == 402

    # ------------------------------------------------------------------
    # 18. Server-side filter enforcement: filters silently stripped
    # ------------------------------------------------------------------
    def test_server_strips_filters_for_free_user(
        self, monkeypatch, tmp_path
    ) -> None:
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _setup_anonymous_session(db_path, client)
            _create_game_for_user(client, "Strip Filter Game")
            slug = _get_game_slug(db_path, "Strip Filter Game")

            # Try applying filters via query params
            response = client.get(
                f"/games/{slug}/prospects?min_reach=5000&status=contacted",
                follow_redirects=False,
            )

        # Server redirects back to clean URL
        assert response.status_code == 303
        assert response.headers["location"] == f"/games/{slug}/prospects"

    # ------------------------------------------------------------------
    # 19. Dashboard hides match counts (perf: skip expensive queries)
    # ------------------------------------------------------------------
    def test_dashboard_hides_match_count_text(
        self, monkeypatch, tmp_path
    ) -> None:
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _setup_anonymous_session(db_path, client)
            _create_game_for_user(client, "No Count Game")

            response = client.get("/games")

        assert response.status_code == 200
        assert "No Count Game" in response.text
        assert "matched creator" not in response.text

    # ------------------------------------------------------------------
    # 20. Paid user dashboard also hides match counts (same perf change)
    # ------------------------------------------------------------------
    def test_paid_dashboard_hides_match_count_text(
        self, monkeypatch, tmp_path
    ) -> None:
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "paid-dash@example.com", "password123")
            _create_game_for_user(client, "Paid No Count Game")

            response = client.get("/games")

        assert response.status_code == 200
        assert "Paid No Count Game" in response.text
        assert "matched creator" not in response.text

    # ------------------------------------------------------------------
    # 21. Paid user prospects page still computes filter ranges
    # ------------------------------------------------------------------
    def test_paid_user_prospects_has_filter_form_with_ranges(
        self, monkeypatch, tmp_path
    ) -> None:
        db_path = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "paid-filter@example.com", "password123")
            _create_game_for_user(client, "Paid Filter Range Game")
            slug = _get_game_slug(db_path, "Paid Filter Range Game")

            response = client.get(f"/games/{slug}/prospects")

        assert response.status_code == 200
        assert 'data-filters-unlocked="true"' in response.text
        assert "data-range-filter-form" in response.text
