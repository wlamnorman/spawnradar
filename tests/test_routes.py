"""HTTP-level integration tests using FastAPI TestClient.

These tests exercise the full request/response cycle including middleware,
routing, template rendering, and cookie handling.
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
from app.games.repository import GameRepository
from app.games.tags import TagProfile
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
    monkeypatch.setenv("SMTP_HOST", "")
    return TestClient(create_app(), raise_server_exceptions=True)


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
        get_path="/games/new",
        post_path="/games",
        data={
            "name": name,
            "summary": "Short summary",
            "description": "Desc",
            "genre_tags": "tag",
            "audience_tags": "aud",
            "genre_primary_tags": "tag",
            "genre_secondary_tags": "",
            "audience_primary_tags": "",
            "audience_secondary_tags": "",
            "mechanics_primary_tags": "",
            "mechanics_secondary_tags": "",
            "tone_primary_tags": "",
            "tone_secondary_tags": "",
            "website_url": "",
        },
    )


def _verify_user_email(db_path: str, email: str) -> None:
    """Mark a user's email as verified directly in the DB."""
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE users SET email_verified = 1 WHERE email = ?", (email,)
        )


def _register_and_login(client: TestClient, email: str, password: str) -> str:
    """Register a user, verify their email, and return the session cookie value."""
    _post_form(
        client,
        get_path="/auth/register",
        post_path="/auth/register",
        data={"email": email, "password": password},
    )
    db_path = os.environ.get("DB_PATH", "")
    if db_path:
        _verify_user_email(db_path, email)
    _post_form(
        client,
        get_path="/auth/login",
        post_path="/auth/login",
        data={"email": email, "password": password},
    )
    return client.cookies.get("session_id") or ""


def _create_incomplete_game_for_user(
    db_path: str, user_id: str, name: str = "Legacy Game"
):
    repo = GameRepository(db_path)
    return repo.create(
        game_id=str(uuid4()),
        user_id=user_id,
        name=name,
        summary=None,
        description="Legacy game description",
        genre_tags=[],
        audience_tags=[],
        genre_tag_profile=TagProfile.empty(),
        audience_tag_profile=TagProfile.empty(),
        mechanics_tag_profile=TagProfile.empty(),
        tone_tag_profile=TagProfile.empty(),
        platform_tags=["browser"],
        website_url=None,
    )


def _expire_trial(db_path: str, email: str) -> str:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT user_id, subscription_id FROM users JOIN subscriptions USING(user_id) WHERE email = ?",
            (email,),
        ).fetchone()
        assert row is not None
        conn.execute(
            "UPDATE subscriptions SET trial_ends_at = ?, updated_at = ? WHERE subscription_id = ?",
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


def _insert_prospect(db_path: str, **kwargs) -> str:
    import uuid
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    prospect_id = kwargs.get("prospect_id", str(uuid.uuid4()))
    with get_connection(db_path) as conn:
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
                kwargs.get("platform", "youtube"),
                kwargs.get("handle", "testhandle"),
                kwargs.get("display_name", "Test Creator"),
                kwargs.get("profile_url"),
                kwargs.get("contact_channel"),
                kwargs.get("contact_value"),
                kwargs.get("audience_size"),
                kwargs.get("engagement_rate"),
                kwargs.get("description"),
                json.dumps(kwargs.get("raw_data", {})),
                now,
                now,
            ),
        )
    return str(prospect_id)


def _insert_draft_item(
    db_path: str, game_id: str, prospect_id: str, **kwargs
) -> str:
    import uuid
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    draft_item_id = kwargs.get("draft_item_id", str(uuid.uuid4()))
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO draft_items
                (draft_item_id, game_id, prospect_id, template_id, subject_line,
                 body_text, status, priority_score, fit_summary, score_breakdown,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft_item_id,
                game_id,
                prospect_id,
                kwargs.get("template_id"),
                kwargs.get("subject_line"),
                kwargs.get("body_text", "Hello"),
                kwargs.get("status", "queued"),
                kwargs.get("priority_score", 0.5),
                kwargs.get("fit_summary", "Good fit"),
                json.dumps(kwargs.get("score_breakdown", {})),
                now,
                now,
            ),
        )
    return str(draft_item_id)


def _signed_paddle_webhook(
    payload: dict[str, object], secret: str
) -> tuple[bytes, str]:
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
        assert (
            "handled in line with Paddle's Buyer Terms and Refund Policy"
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
        monkeypatch.setenv("SMTP_HOST", "")
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

    def test_http_requests_redirect_to_https_when_public_base_url_is_https(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "test.sqlite3"))
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("BASE_URL", "https://spawnradar.com")
        monkeypatch.setenv("RESEND_API_KEY", "")
        monkeypatch.setenv("SMTP_HOST", "")

        with TestClient(create_app()) as client:
            response = client.get("/", follow_redirects=False)

        assert response.status_code == 307
        assert response.headers["location"].startswith("https://testserver/")

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
                "/games",
                data={
                    "name": "CSRF Test",
                    "description": "A test game",
                    "genre_tags": "strategy",
                    "audience_tags": "strategy fans",
                    "platform_tags": "browser",
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
                get_path="/games/new",
                post_path="/games",
                data={
                    "name": "Missing Summary",
                    "summary": "",
                    "description": "A test game",
                    "genre_tags": "strategy",
                    "genre_primary_tags": "strategy",
                    "audience_tags": "strategy fans",
                    "platform_tags": "browser",
                    "website_url": "",
                },
                follow_redirects=False,
            )

        assert response.status_code == 400
        assert "Game summary is required." in response.text

    def test_create_game_requires_primary_genre_tag(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "missing-primary@example.com", "testpass"
            )
            response = _post_form(
                client,
                get_path="/games/new",
                post_path="/games",
                data={
                    "name": "Missing Primary",
                    "summary": "A short summary",
                    "description": "A test game",
                    "genre_tags": "",
                    "genre_primary_tags": "",
                    "audience_tags": "strategy fans",
                    "platform_tags": "browser",
                    "website_url": "",
                },
                follow_redirects=False,
            )

        assert response.status_code == 400
        assert "At least one primary genre tag is required." in response.text

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
# Creator signup routes
# ---------------------------------------------------------------------------


class TestCreatorSignupRoutes:
    def test_creator_signup_honeypot_skips_persistence_and_email(
        self, monkeypatch, tmp_path
    ):
        db_path = tmp_path / "test.sqlite3"

        with _make_client(monkeypatch, tmp_path) as client:
            sent_messages: list[object] = []
            app_state = cast(Any, client.app).state
            app_state.email_service.send = sent_messages.append

            response = _post_form(
                client,
                get_path="/creators",
                post_path="/creators/signup",
                data={
                    "display_name": "Spam Bot",
                    "email": "spam@example.com",
                    "company": "Definitely real company",
                },
                follow_redirects=False,
            )

        assert response.status_code == 303
        assert response.headers["location"] == "/creators/thanks"
        assert sent_messages == []

        with get_connection(str(db_path)) as conn:
            signups = conn.execute(
                "SELECT COUNT(*) AS count FROM creator_signups"
            ).fetchone()

        assert signups is not None
        assert int(signups["count"]) == 0

    def test_creator_signup_rate_limits_per_ip_without_revealing_it(
        self, monkeypatch, tmp_path
    ):
        db_path = tmp_path / "test.sqlite3"
        headers = {"x-forwarded-for": "203.0.113.10"}

        with _make_client(monkeypatch, tmp_path) as client:
            sent_messages: list[object] = []
            app_state = cast(Any, client.app).state
            app_state.email_service.send = sent_messages.append

            for index in range(3):
                response = _post_form(
                    client,
                    get_path="/creators",
                    post_path="/creators/signup",
                    data={
                        "display_name": f"Creator {index}",
                        "email": f"creator{index}@example.com",
                    },
                    headers=headers,
                    follow_redirects=False,
                )
                assert response.status_code == 303
                assert response.headers["location"] == "/creators/thanks"

            blocked = _post_form(
                client,
                get_path="/creators",
                post_path="/creators/signup",
                data={
                    "display_name": "Creator 4",
                    "email": "creator4@example.com",
                },
                headers=headers,
                follow_redirects=False,
            )

        assert blocked.status_code == 303
        assert blocked.headers["location"] == "/creators/thanks"
        assert len(sent_messages) == 3

        with get_connection(str(db_path)) as conn:
            signups = conn.execute(
                "SELECT COUNT(*) AS count FROM creator_signups"
            ).fetchone()
            attempts = conn.execute(
                "SELECT COUNT(*) AS count FROM request_rate_limits WHERE scope = 'creator_signup'"
            ).fetchone()

        assert signups is not None
        assert attempts is not None
        assert int(signups["count"]) == 3
        assert int(attempts["count"]) == 3


# ---------------------------------------------------------------------------
# Discovery routes
# ---------------------------------------------------------------------------


class TestDiscoveryRoutes:
    def test_queue_page_shows_discovery_limits_and_new_results_copy(
        self, monkeypatch, tmp_path
    ):
        db_path = tmp_path / "test.sqlite3"

        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "queue@example.com", "testpass")
            create_response = _post_form(
                client,
                get_path="/games/new",
                post_path="/games",
                data={
                    "name": "Queue Game",
                    "summary": "Queue Game summary",
                    "description": "Queue Game description",
                    "genre_tags": "strategy",
                    "genre_primary_tags": "strategy",
                    "audience_tags": "strategy fans",
                    "platform_tags": "browser",
                    "website_url": "",
                },
                follow_redirects=False,
            )
            assert create_response.status_code == 303

            with get_connection(str(db_path)) as conn:
                row = conn.execute(
                    "SELECT slug FROM games WHERE name = ?",
                    ("Queue Game",),
                ).fetchone()

            assert row is not None
            response = client.get(f"/games/{row['slug']}/queue")

        assert response.status_code == 200
        assert "discovery-status-global" in response.text

    def test_games_page_marks_incomplete_games_as_discovery_locked(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")

        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "legacylock@example.com", "testpass")
            _create_game_for_user(client, "Ready Game")

            with get_connection(db_path) as conn:
                user_row = conn.execute(
                    "SELECT user_id FROM users WHERE email = ?",
                    ("legacylock@example.com",),
                ).fetchone()
            assert user_row is not None

            _create_incomplete_game_for_user(db_path, str(user_row["user_id"]))

            response = client.get("/games")

        assert response.status_code == 200
        assert "Open Queue" in response.text
        assert (
            "Finish setup before running discovery. Missing summary and primary genre tags."
            in response.text
        )

    def test_queue_page_shows_setup_warning_for_incomplete_game(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")

        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "legacyqueue@example.com", "testpass")

            with get_connection(db_path) as conn:
                user_row = conn.execute(
                    "SELECT user_id FROM users WHERE email = ?",
                    ("legacyqueue@example.com",),
                ).fetchone()
            assert user_row is not None

            game = _create_incomplete_game_for_user(
                db_path, str(user_row["user_id"]), name="Legacy Queue Game"
            )

            response = client.get(f"/games/{game.slug}/queue")

        assert response.status_code == 200
        assert (
            "Finish setup before running discovery. Missing summary and primary genre tags."
            in response.text
        )
        assert 'data-discovery-ready="false"' in response.text

    def test_run_ingestion_rejects_incomplete_game_without_consuming_quota(
        self, monkeypatch, tmp_path
    ):
        db_path = str(tmp_path / "test.sqlite3")

        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "legacyapi@example.com", "testpass")

            with get_connection(db_path) as conn:
                user_row = conn.execute(
                    "SELECT user_id FROM users WHERE email = ?",
                    ("legacyapi@example.com",),
                ).fetchone()
            assert user_row is not None

            game = _create_incomplete_game_for_user(
                db_path, str(user_row["user_id"]), name="Legacy API Game"
            )

            response = _post_json(
                client,
                get_path="/games",
                post_path=f"/api/games/{game.game_id}/run-ingestion",
                json_body={},
                follow_redirects=False,
            )

        assert response.status_code == 409
        assert (
            response.json()["detail"]
            == "Finish setup before running discovery. Missing summary and primary genre tags."
        )

        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM discovery_runs"
            ).fetchone()

        assert row is not None
        assert row["count"] == 0

    def test_run_ingestion_limits_each_user_independently_and_blocks_per_day(
        self, monkeypatch, tmp_path
    ):
        from datetime import UTC, datetime

        async def fake_run_ingestion(*args, **kwargs):
            return {"discovered": 0, "scored": 0, "imported": 0}

        from app.billing.service import TRIAL_LIMITS

        class FrozenDateTime(datetime):
            current = datetime(2026, 3, 21, 12, 0, tzinfo=UTC)

            @classmethod
            def now(cls, tz=None):
                current = cls.current
                if tz is None:
                    return current.replace(tzinfo=None)
                return current.astimezone(tz)

        monkeypatch.setitem(TRIAL_LIMITS, "discovery_runs_per_month", 10)
        monkeypatch.setattr(
            "app.games.router.run_ingestion", fake_run_ingestion
        )
        monkeypatch.setattr("app.billing.service.datetime", FrozenDateTime)

        db_path = tmp_path / "test.sqlite3"

        def create_game(client: TestClient, game_name: str) -> str:
            response = _post_form(
                client,
                get_path="/games/new",
                post_path="/games",
                data={
                    "name": game_name,
                    "summary": f"{game_name} summary",
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

        base = datetime(2026, 3, 21, 12, 0, tzinfo=UTC)
        user_one_schedule = [
            base.replace(hour=8, minute=0),
            base.replace(hour=8, minute=20),
            base.replace(hour=9, minute=30),
            base.replace(hour=9, minute=50),
            base.replace(hour=11, minute=10),
        ]
        user_two_schedule = [
            datetime(2026, 3, 18, 8, 0, tzinfo=UTC),
            datetime(2026, 3, 18, 8, 20, tzinfo=UTC),
            datetime(2026, 3, 18, 9, 30, tzinfo=UTC),
            datetime(2026, 3, 18, 9, 50, tzinfo=UTC),
            datetime(2026, 3, 18, 11, 10, tzinfo=UTC),
        ]

        with (
            _make_client(monkeypatch, tmp_path) as user_one_client,
            _make_client(monkeypatch, tmp_path) as user_two_client,
            _make_client(monkeypatch, tmp_path) as user_three_client,
        ):
            _register_and_login(
                user_one_client, "user1@example.com", "testpass"
            )
            _register_and_login(
                user_two_client, "user2@example.com", "testpass"
            )
            _register_and_login(
                user_three_client, "user3@example.com", "testpass"
            )

            user_one_game_id = create_game(user_one_client, "User One Game")
            user_two_game_id = create_game(user_two_client, "User Two Game")
            create_game(user_three_client, "User Three Game")

            user_one_response = None
            for when in user_one_schedule:
                FrozenDateTime.current = when
                user_one_response = _post_json(
                    user_one_client,
                    get_path="/games",
                    post_path=f"/api/games/{user_one_game_id}/run-ingestion",
                    json_body={},
                )
                assert user_one_response.status_code == 200

            assert user_one_response is not None
            assert count_runs_by_email() == {
                "user1@example.com": 5,
                "user2@example.com": 0,
                "user3@example.com": 0,
            }

            fifth_user_one = user_one_response.json()["usage"]
            assert fifth_user_one["daily"]["used"] == 5
            assert fifth_user_one["can_run"] is False
            assert fifth_user_one["blocked_by"] == "day"

            user_two_response = None
            for when in user_two_schedule:
                FrozenDateTime.current = when
                user_two_response = _post_json(
                    user_two_client,
                    get_path="/games",
                    post_path=f"/api/games/{user_two_game_id}/run-ingestion",
                    json_body={},
                )
                assert user_two_response.status_code == 200

            assert count_runs_by_email() == {
                "user1@example.com": 5,
                "user2@example.com": 5,
                "user3@example.com": 0,
            }

            FrozenDateTime.current = base
            limited = _post_json(
                user_one_client,
                get_path="/games",
                post_path=f"/api/games/{user_one_game_id}/run-ingestion",
                json_body={},
            )

            assert limited.status_code == 429
            assert "today" in limited.json()["detail"]

            other_user_still_allowed = _post_json(
                user_two_client,
                get_path="/games",
                post_path=f"/api/games/{user_two_game_id}/run-ingestion",
                json_body={},
            )
            assert other_user_still_allowed.status_code == 200
            assert (
                other_user_still_allowed.json()["usage"]["monthly"]["used"]
                == 6
            )

        assert count_runs_by_email() == {
            "user1@example.com": 5,
            "user2@example.com": 6,
            "user3@example.com": 0,
        }


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

    def test_webhook_ends_trial_and_marks_user_as_paid(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("PADDLE_API_KEY", "test_api_key")
        monkeypatch.setenv("PADDLE_CLIENT_SIDE_TOKEN", "test_token")
        monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "whsec_test")
        monkeypatch.setenv("PADDLE_INDIE_PRICE_ID", "pri_indie")
        monkeypatch.setenv("PADDLE_ENVIRONMENT", "sandbox")
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
    def test_expired_trial_redirects_games_to_pricing(
        self, monkeypatch, tmp_path
    ):
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "expired@example.com", "testpass")
            _expire_trial(db, "expired@example.com")

            resp = client.get("/games", follow_redirects=False)

        assert resp.status_code == 307
        assert resp.headers["location"] == "/pricing"

    def test_expired_trial_redirects_queue_to_pricing(
        self, monkeypatch, tmp_path
    ):
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "queueexpired@example.com", "testpass")
            _post_form(
                client,
                get_path="/games/new",
                post_path="/games",
                data={
                    "name": "Game",
                    "summary": "Short summary",
                    "description": "Desc",
                    "genre_tags": "tag",
                    "audience_tags": "aud",
                    "genre_primary_tags": "tag",
                    "genre_secondary_tags": "",
                    "audience_primary_tags": "",
                    "audience_secondary_tags": "",
                    "mechanics_primary_tags": "",
                    "mechanics_secondary_tags": "",
                    "tone_primary_tags": "",
                    "tone_secondary_tags": "",
                    "website_url": "",
                },
            )
            _expire_trial(db, "queueexpired@example.com")

            resp = client.get("/games/game/queue", follow_redirects=False)

        assert resp.status_code == 307
        assert resp.headers["location"] == "/pricing"

    def test_expired_trial_blocks_product_api(self, monkeypatch, tmp_path):
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "apiexpired@example.com", "testpass")
            _post_form(
                client,
                get_path="/games/new",
                post_path="/games",
                data={
                    "name": "ApiGame",
                    "summary": "Short summary",
                    "description": "Desc",
                    "genre_tags": "tag",
                    "audience_tags": "aud",
                    "genre_primary_tags": "tag",
                    "genre_secondary_tags": "",
                    "audience_primary_tags": "",
                    "audience_secondary_tags": "",
                    "mechanics_primary_tags": "",
                    "mechanics_secondary_tags": "",
                    "tone_primary_tags": "",
                    "tone_secondary_tags": "",
                    "website_url": "",
                },
            )
            csrf = _csrf_token(client, "/games")
            with get_connection(db) as conn:
                row = conn.execute(
                    "SELECT game_id FROM games WHERE name = ?",
                    ("ApiGame",),
                ).fetchone()
            assert row is not None
            game_id = str(row["game_id"])
            _expire_trial(db, "apiexpired@example.com")

            resp = client.post(
                f"/api/games/{game_id}/run-ingestion",
                json={},
                follow_redirects=False,
                headers={"accept": "application/json", "x-csrf-token": csrf},
            )

        assert resp.status_code == 402
        assert resp.json()["detail"] == "Active subscription required."

    def test_ended_paid_subscription_redirects_games_to_pricing(
        self, monkeypatch, tmp_path
    ):
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "paidended@example.com", "testpass")
            _expire_paid_subscription(db, "paidended@example.com")

            resp = client.get("/games", follow_redirects=False)

        assert resp.status_code == 307
        assert resp.headers["location"] == "/pricing"

    def test_expired_trial_redirects_games_new_to_pricing(
        self, monkeypatch, tmp_path
    ):
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "newexpired@example.com", "testpass")
            _expire_trial(db, "newexpired@example.com")

            resp = client.get("/games/new", follow_redirects=False)

        assert resp.status_code == 307
        assert resp.headers["location"] == "/pricing"

    def test_expired_trial_redirects_setup_to_pricing(
        self, monkeypatch, tmp_path
    ):
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "setupexpired@example.com", "testpass")
            _create_game_for_user(client, "Setup Game")
            _expire_trial(db, "setupexpired@example.com")

            resp = client.get(
                "/games/setup-game/setup", follow_redirects=False
            )

        assert resp.status_code == 307
        assert resp.headers["location"] == "/pricing"

    def test_expired_trial_blocks_queue_api(self, monkeypatch, tmp_path):
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "queueapi@example.com", "testpass")
            _create_game_for_user(client, "Queue API Game")
            with get_connection(db) as conn:
                game_row = conn.execute(
                    "SELECT game_id FROM games WHERE name = ?",
                    ("Queue API Game",),
                ).fetchone()
            assert game_row is not None
            game_id = str(game_row["game_id"])
            _expire_trial(db, "queueapi@example.com")

            resp = client.get(
                f"/api/games/{game_id}/queue",
                headers={"accept": "application/json"},
                follow_redirects=False,
            )

        assert resp.status_code == 402
        assert resp.json()["detail"] == "Active subscription required."

    def test_expired_trial_blocks_draft_action_api(
        self, monkeypatch, tmp_path
    ):
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(client, "draftapi@example.com", "testpass")
            _create_game_for_user(client, "Draft API Game")
            csrf = _csrf_token(client, "/games")
            with get_connection(db) as conn:
                game_row = conn.execute(
                    "SELECT game_id FROM games WHERE name = ?",
                    ("Draft API Game",),
                ).fetchone()
            assert game_row is not None
            game_id = str(game_row["game_id"])
            prospect_id = _insert_prospect(
                db, handle="creatorx", display_name="Creator X"
            )
            draft_item_id = _insert_draft_item(db, game_id, prospect_id)
            _expire_trial(db, "draftapi@example.com")

            resp = client.post(
                f"/api/drafts/{draft_item_id}/action",
                json={"action": "approve"},
                follow_redirects=False,
                headers={"accept": "application/json", "x-csrf-token": csrf},
            )

        assert resp.status_code == 402
        assert resp.json()["detail"] == "Active subscription required."

    def test_ended_paid_subscription_blocks_queue_api(
        self, monkeypatch, tmp_path
    ):
        db = str(tmp_path / "test.sqlite3")
        with _make_client(monkeypatch, tmp_path) as client:
            _register_and_login(
                client, "paidqueueended@example.com", "testpass"
            )
            _create_game_for_user(client, "Paid Queue Game")
            with get_connection(db) as conn:
                game_row = conn.execute(
                    "SELECT game_id FROM games WHERE name = ?",
                    ("Paid Queue Game",),
                ).fetchone()
            assert game_row is not None
            game_id = str(game_row["game_id"])
            _expire_paid_subscription(db, "paidqueueended@example.com")

            resp = client.get(
                f"/api/games/{game_id}/queue",
                headers={"accept": "application/json"},
                follow_redirects=False,
            )

        assert resp.status_code == 402
        assert resp.json()["detail"] == "Active subscription required."
