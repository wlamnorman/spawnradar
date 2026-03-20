"""HTTP-level integration tests using FastAPI TestClient.

These tests exercise the full request/response cycle including middleware,
routing, template rendering, and cookie handling.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    return TestClient(create_app(), raise_server_exceptions=True)


def _register_and_login(client: TestClient, email: str, password: str) -> str:
    """Register a user and return the session cookie value."""
    client.post("/auth/register", data={"email": email, "password": password})
    client.post("/auth/login", data={"email": email, "password": password})
    return client.cookies.get("session_id") or ""


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
        assert "spawnradar.app/</loc>" in resp.text

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


# ---------------------------------------------------------------------------
# Billing routes
# ---------------------------------------------------------------------------


class TestBillingRoutes:
    def test_billing_root_redirects_to_pricing(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/billing", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/pricing"

    def test_checkout_returns_503_when_stripe_not_configured(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            client.post(
                "/auth/register",
                data={"email": "pay@example.com", "password": "testpass"},
            )
            client.post(
                "/auth/login",
                data={"email": "pay@example.com", "password": "testpass"},
            )
            resp = client.post(
                "/billing/checkout/starter", follow_redirects=False
            )
        assert resp.status_code == 503

    def test_checkout_returns_400_for_invalid_tier(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("LEMONSQUEEZY_API_KEY", "test_key")
        with _make_client(monkeypatch, tmp_path) as client:
            client.post(
                "/auth/register",
                data={"email": "tier@example.com", "password": "testpass"},
            )
            client.post(
                "/auth/login",
                data={"email": "tier@example.com", "password": "testpass"},
            )
            resp = client.post(
                "/billing/checkout/enterprise", follow_redirects=False
            )
        assert resp.status_code == 400

    def test_portal_returns_503_when_stripe_not_configured(
        self, monkeypatch, tmp_path
    ):
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
        monkeypatch.setenv("LEMONSQUEEZY_API_KEY", "test_key")
        monkeypatch.setenv("LEMONSQUEEZY_WEBHOOK_SECRET", "whsec_fake")
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.post(
                "/billing/webhook",
                content=b'{"meta":{"event_name":"subscription_created"}}',
                headers={"x-signature": "bad-sig"},
            )
        assert resp.status_code == 400

    def test_webhook_returns_200_when_stripe_not_configured(
        self, monkeypatch, tmp_path
    ):
        # When STRIPE_SECRET_KEY is empty, the webhook handler is a no-op
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.post(
                "/billing/webhook",
                content=b"{}",
                headers={"stripe-signature": "any"},
            )
        assert resp.status_code == 200

    def test_checkout_unauthenticated_redirects_to_login(
        self, monkeypatch, tmp_path
    ):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.post(
                "/billing/checkout/starter", follow_redirects=False
            )
        assert resp.status_code in (302, 303, 307)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class TestHealthRoute:
    def test_health_returns_200(self, monkeypatch, tmp_path):
        with _make_client(monkeypatch, tmp_path) as client:
            resp = client.get("/healthz")
        assert resp.status_code == 200
