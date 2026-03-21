"""HTTP-level integration tests using FastAPI TestClient.

These tests exercise the full request/response cycle including middleware,
routing, template rendering, and cookie handling.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any, cast

from fastapi.testclient import TestClient

from app.billing.repository import SubscriptionRepository
from app.billing.service import BillingService
from app.database import get_connection
from app.games.repository import GameRepository
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
    return TestClient(create_app(), raise_server_exceptions=True)


def _register_and_login(client: TestClient, email: str, password: str) -> str:
    """Register a user and return the session cookie value."""
    client.post("/auth/register", data={"email": email, "password": password})
    client.post("/auth/login", data={"email": email, "password": password})
    return client.cookies.get("session_id") or ""


def _signed_paddle_webhook(payload: dict[str, object], secret: str) -> tuple[bytes, str]:
    encoded = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    signed = timestamp.encode() + b":" + encoded
    signature = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return encoded, f"ts={timestamp};h1={signature}"


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

    def test_blog_post_templates_returns_200(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/blog/creator-outreach-message-templates")
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
            resp = client.get("/blog/creator-outreach-message-templates")
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

    def test_robots_txt_disallows_admin(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/robots.txt")
        assert "Disallow: /admin" in resp.text

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
        assert "creator-outreach-message-templates" in resp.text

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
        assert "handled in line with Paddle's Buyer Terms and Refund Policy" in normalized_refunds
        assert "Eligible buyers may request a refund within 14 days of the transaction" in normalized_refunds

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
            resp = client.post(
                "/auth/register",
                data={"email": "new@example.com", "password": "password123"},
            )
        assert resp.status_code in (200, 302, 303)

    def test_login_sets_session_cookie(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            client.post(
                "/auth/register",
                data={"email": "cookie@example.com", "password": "testpass"},
            )
            client.post(
                "/auth/login",
                data={"email": "cookie@example.com", "password": "testpass"},
            )
        assert "session_id" in client.cookies

    def test_login_with_wrong_password_shows_error(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            client.post(
                "/auth/register",
                data={"email": "wrong@example.com", "password": "correct"},
            )
            resp = client.post(
                "/auth/login",
                data={"email": "wrong@example.com", "password": "notcorrect"},
                follow_redirects=False,
            )
        assert resp.status_code in (200, 302, 303, 400)

    def test_logout_clears_session_cookie(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            client.post(
                "/auth/register",
                data={"email": "logout@example.com", "password": "testpass"},
            )
            client.post(
                "/auth/login",
                data={"email": "logout@example.com", "password": "testpass"},
            )
            assert "session_id" in client.cookies
            client.post("/auth/logout")
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
            client.post(
                "/auth/register",
                data={"email": "dup@example.com", "password": "pass1"},
            )
            resp = client.post(
                "/auth/register",
                data={"email": "dup@example.com", "password": "pass2"},
            )
        assert resp.status_code in (200, 400)


    def test_forgot_password_redirects_even_when_email_send_fails(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            client.post(
                "/auth/register",
                data={"email": "reset@example.com", "password": "testpass"},
            )

            def broken_send(message):
                raise RuntimeError("email provider rejected sender")

            app_state = cast(Any, client.app).state
            app_state.email_service.send = broken_send

            resp = client.post(
                "/auth/forgot-password",
                data={"email": "reset@example.com"},
                follow_redirects=False,
            )

        assert resp.status_code == 303
        assert resp.headers["location"] == "/auth/forgot-password?sent=1"


# ---------------------------------------------------------------------------
# Discovery routes
# ---------------------------------------------------------------------------


class TestDiscoveryRoutes:
    def test_run_ingestion_tracks_and_limits_each_user_independently(
        self, monkeypatch, tmp_path
    ):
        async def fake_run_ingestion(*args, **kwargs):
            return {"discovered": 0, "scored": 0, "imported": 0}

        from app.billing.service import TRIAL_LIMITS

        monkeypatch.setitem(TRIAL_LIMITS, "discovery_runs_per_month", 6)
        monkeypatch.setattr(
            "app.ingestion.pipeline.run_ingestion", fake_run_ingestion
        )

        db_path = tmp_path / "test.sqlite3"

        def create_game(client: TestClient, game_name: str) -> str:
            response = client.post(
                "/games",
                data={
                    "name": game_name,
                    "description": f"{game_name} description",
                    "genre_tags": "strategy",
                    "audience_tags": "strategy fans",
                    "platform_tags": "browser",
                    "website_url": "",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303

            with get_connection(str(db_path)) as conn:
                row = conn.execute(
                    """
                    SELECT game_id
                    FROM games
                    WHERE name = ?
                    """,
                    (game_name,),
                ).fetchone()

            assert row is not None
            return str(row["game_id"])

        def count_runs_by_email() -> dict[str, int]:
            with get_connection(str(db_path)) as conn:
                rows = conn.execute(
                    """
                    SELECT users.email, COUNT(discovery_runs.run_id) AS run_count
                    FROM users
                    LEFT JOIN discovery_runs
                        ON discovery_runs.user_id = users.user_id
                    GROUP BY users.user_id
                    ORDER BY users.email
                    """
                ).fetchall()
            return {str(row["email"]): int(row["run_count"]) for row in rows}

        with _make_client(monkeypatch, tmp_path) as user_one_client, _make_client(
            monkeypatch, tmp_path
        ) as user_two_client, _make_client(monkeypatch, tmp_path) as user_three_client:
            _register_and_login(user_one_client, "user1@example.com", "testpass")
            _register_and_login(user_two_client, "user2@example.com", "testpass")
            _register_and_login(
                user_three_client, "user3@example.com", "testpass"
            )

            user_one_game_id = create_game(user_one_client, "User One Game")
            user_two_game_id = create_game(user_two_client, "User Two Game")
            create_game(user_three_client, "User Three Game")

            for expected_used in range(1, 6):
                response = user_one_client.post(
                    f"/api/games/{user_one_game_id}/run-ingestion"
                )
                assert response.status_code == 200
                assert response.json()["usage"] == {
                    "used": expected_used,
                    "limit": 6,
                    "remaining": 6 - expected_used,
                }

            assert count_runs_by_email() == {
                "user1@example.com": 5,
                "user2@example.com": 0,
                "user3@example.com": 0,
            }

            for expected_used in range(1, 6):
                response = user_two_client.post(
                    f"/api/games/{user_two_game_id}/run-ingestion"
                )
                assert response.status_code == 200
                assert response.json()["usage"] == {
                    "used": expected_used,
                    "limit": 6,
                    "remaining": 6 - expected_used,
                }

            assert count_runs_by_email() == {
                "user1@example.com": 5,
                "user2@example.com": 5,
                "user3@example.com": 0,
            }

            within_limit = user_one_client.post(
                f"/api/games/{user_one_game_id}/run-ingestion"
            )
            assert within_limit.status_code == 200
            assert within_limit.json()["usage"] == {
                "used": 6,
                "limit": 6,
                "remaining": 0,
            }

            limited = user_one_client.post(
                f"/api/games/{user_one_game_id}/run-ingestion"
            )

            assert limited.status_code == 429
            assert (
                limited.json()["detail"]
                == "You've reached your 6 discovery runs for this month."
            )

            other_user_still_allowed = user_two_client.post(
                f"/api/games/{user_two_game_id}/run-ingestion"
            )
            assert other_user_still_allowed.status_code == 200
            assert other_user_still_allowed.json()["usage"] == {
                "used": 6,
                "limit": 6,
                "remaining": 0,
            }

        assert count_runs_by_email() == {
            "user1@example.com": 6,
            "user2@example.com": 6,
            "user3@example.com": 0,
        }


# ---------------------------------------------------------------------------
# Billing routes
# ---------------------------------------------------------------------------


class TestBillingRoutes:
    def test_billing_root_redirects_to_pricing(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/billing", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/pricing"

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
            client.post(
                "/auth/register",
                data={"email": "pay@example.com", "password": "testpass"},
            )
            client.post(
                "/auth/login",
                data={"email": "pay@example.com", "password": "testpass"},
            )
            resp = client.get(
                "/billing/pay", follow_redirects=False
            )
        assert resp.status_code == 503

    def test_checkout_returns_400_for_invalid_tier(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("PADDLE_CLIENT_SIDE_TOKEN", "test_token")
        with _make_client(monkeypatch, tmp_path) as client:
            client.post(
                "/auth/register",
                data={"email": "tier@example.com", "password": "testpass"},
            )
            client.post(
                "/auth/login",
                data={"email": "tier@example.com", "password": "testpass"},
            )
            resp = client.get(
                "/billing/checkout/enterprise", follow_redirects=False
            )
        assert resp.status_code == 400

    def test_portal_returns_503_when_paddle_not_configured(
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
            client.post(
                "/auth/register",
                data={"email": "portal@example.com", "password": "testpass"},
            )
            client.post(
                "/auth/login",
                data={"email": "portal@example.com", "password": "testpass"},
            )
            resp = client.get("/billing/portal", follow_redirects=False)
        assert resp.status_code == 503

    def test_webhook_returns_400_on_bad_signature(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PADDLE_API_KEY", "test_api_key")
        monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "whsec_fake")
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

    def test_webhook_ends_trial_and_marks_user_as_paid(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "whsec_test")
        db_path = tmp_path / "test.sqlite3"

        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "paid@example.com", "testpass")

            before = client.get("/games")
            assert before.status_code == 200
            assert "<strong>Trial:</strong>" in before.text
            assert "Activate subscription" in before.text

            with get_connection(str(db_path)) as conn:
                user_row = conn.execute(
                    "SELECT user_id FROM users WHERE email = ?",
                    ("paid@example.com",),
                ).fetchone()

            assert user_row is not None
            user_id = user_row["user_id"]

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

            after = client.get("/games")

        assert after.status_code == 200
        assert "<strong>Trial:</strong>" not in after.text
        assert "Activate subscription" not in after.text

        with get_connection(str(db_path)) as conn:
            sub_row = conn.execute(
                "SELECT tier, status, paddle_customer_id, paddle_subscription_id FROM subscriptions LIMIT 1"
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
            resp = client.get(
                "/billing/pay", follow_redirects=False
            )
        assert resp.status_code in (302, 303, 307)

    def test_pay_redirects_to_games_when_already_subscribed(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("PADDLE_CLIENT_SIDE_TOKEN", "test_token")
        monkeypatch.setenv("PADDLE_INDIE_PRICE_ID", "pri_indie")
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            client.post(
                "/auth/register",
                data={"email": "sub@example.com", "password": "testpass"},
            )
            client.post(
                "/auth/login",
                data={"email": "sub@example.com", "password": "testpass"},
            )

            with get_connection(db) as conn:
                row = conn.execute(
                    "SELECT user_id FROM users WHERE email = ?",
                    ("sub@example.com",),
                ).fetchone()
            user_id = row["user_id"]

            sub_repo = SubscriptionRepository(db)
            billing = BillingService(sub_repo, GameRepository(db))
            billing.get_or_create_subscription(user_id)
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
        monkeypatch.setenv("PADDLE_CLIENT_SIDE_TOKEN", "test_token")
        monkeypatch.setenv("PADDLE_INDIE_PRICE_ID", "pri_indie")
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            client.post(
                "/auth/register",
                data={"email": "comp@example.com", "password": "testpass"},
            )
            client.post(
                "/auth/login",
                data={"email": "comp@example.com", "password": "testpass"},
            )

            with get_connection(db) as conn:
                row = conn.execute(
                    "SELECT user_id FROM users WHERE email = ?",
                    ("comp@example.com",),
                ).fetchone()
            user_id = row["user_id"]

            sub_repo = SubscriptionRepository(db)
            billing = BillingService(sub_repo, GameRepository(db))
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
