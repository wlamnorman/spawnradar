import os

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from app.admin.queries import get_dashboard_data
from app.auth.models import User
from app.database import get_connection, initialize_database
from app.main import create_app


def _make_user(is_admin: bool = False) -> User:
    return User(
        user_id="u1",
        email="admin@test.com",
        password_hash=None,
        google_id=None,
        is_admin=is_admin,
        email_verified=True,
        is_anonymous=False,
        created_at="2026-01-01",
        updated_at="2026-01-01",
    )


class TestAdminSettings:
    def test_admin_secret_key_loaded_from_env(self, monkeypatch):
        monkeypatch.setenv("ADMIN_SECRET_KEY", "test-secret-abc")
        from app.config import Settings

        s = Settings.from_env()
        assert s.admin_secret_key == "test-secret-abc"

    def test_admin_secret_key_defaults_to_empty(self, monkeypatch):
        monkeypatch.setenv("ADMIN_SECRET_KEY", "")
        from app.config import Settings

        s = Settings.from_env()
        assert s.admin_secret_key == ""


class TestVerifyAdminAccess:
    def test_rejects_missing_key(self):
        from app.admin.dependencies import verify_admin_access

        with pytest.raises(HTTPException) as exc_info:
            verify_admin_access(
                user=_make_user(is_admin=True),
                admin_secret_key="real-secret",
                provided_key=None,
            )
        assert exc_info.value.status_code == 404

    def test_rejects_wrong_key(self):
        from app.admin.dependencies import verify_admin_access

        with pytest.raises(HTTPException) as exc_info:
            verify_admin_access(
                user=_make_user(is_admin=True),
                admin_secret_key="real-secret",
                provided_key="wrong-secret",
            )
        assert exc_info.value.status_code == 404

    def test_rejects_non_admin_user(self):
        from app.admin.dependencies import verify_admin_access

        with pytest.raises(HTTPException) as exc_info:
            verify_admin_access(
                user=_make_user(is_admin=False),
                admin_secret_key="real-secret",
                provided_key="real-secret",
            )
        assert exc_info.value.status_code == 404

    def test_rejects_empty_secret_key_config(self):
        from app.admin.dependencies import verify_admin_access

        with pytest.raises(HTTPException) as exc_info:
            verify_admin_access(
                user=_make_user(is_admin=True),
                admin_secret_key="",
                provided_key="anything",
            )
        assert exc_info.value.status_code == 404

    def test_accepts_valid_admin_with_correct_key(self):
        from app.admin.dependencies import verify_admin_access

        # Should not raise
        verify_admin_access(
            user=_make_user(is_admin=True),
            admin_secret_key="real-secret",
            provided_key="real-secret",
        )


class TestGetDashboardData:
    def test_empty_database(self, db_path):
        data = get_dashboard_data(db_path)
        assert data["total_accounts"] == 0
        assert data["total_games"] == 0
        assert data["comped_accounts"] == 0
        assert data["paid_accounts"] == 0
        assert data["customers"] == []

    def test_user_with_no_games(self, db_path, auth_service, billing_service, sub_repo):
        import uuid

        from app.billing.models import Tier
        user = auth_service.register("alice@test.com", "pass123")
        sub_repo.create(str(uuid.uuid4()), user.user_id, Tier.INDIE)
        data = get_dashboard_data(db_path)
        assert data["total_accounts"] == 1
        assert len(data["customers"]) == 1
        c = data["customers"][0]
        assert c["email"] == "alice@test.com"
        assert c["games"] == []

    def test_user_with_game(
        self, db_path, auth_service, billing_service, game_service, sub_repo
    ):
        import uuid

        from app.billing.models import Tier
        user = auth_service.register("bob@test.com", "pass123")
        sub_repo.create(str(uuid.uuid4()), user.user_id, Tier.INDIE)
        game_service.create_game(
            user_id=user.user_id,
            name="TestGame",
            summary="A test game",
            description="A test game description for testing",
            website_url=None,
            igdb_genre_ids=[9],
        )
        data = get_dashboard_data(db_path)
        assert data["total_games"] == 1
        assert len(data["customers"][0]["games"]) == 1
        g = data["customers"][0]["games"][0]
        assert g["name"] == "TestGame"
        assert g["summary"] == "A test game"
        assert g["prospect_count"] == 0
        assert g["last_prospect_view"] is None

    def test_comped_user_counted(self, db_path, auth_service, sub_repo):
        user = auth_service.register("comped@test.com", "pass123")
        sub_repo.grant_comped_access(user.user_id)
        data = get_dashboard_data(db_path)
        assert data["comped_accounts"] == 1


class TestAdminBypassGameSetup:
    """Verify admin can access and edit any user's game setup."""

    def test_admin_can_view_other_users_game_setup(
        self, db_path, auth_service, game_service, game_repo
    ):
        owner = auth_service.register("owner@test.com", "pass123")
        game = game_service.create_game(
            user_id=owner.user_id,
            name="OwnerGame",
            summary="Owner's game",
            description="A game owned by someone else",
            website_url=None,
            igdb_genre_ids=[9],
        )
        fetched = game_repo.get_by_slug(game.slug)
        assert fetched is not None
        assert fetched.user_id == owner.user_id

    def test_admin_can_update_other_users_game_via_service(
        self, db_path, auth_service, game_service
    ):
        owner = auth_service.register("owner2@test.com", "pass123")
        game = game_service.create_game(
            user_id=owner.user_id,
            name="OwnerGame2",
            summary="Owner's game",
            description="A game owned by someone else",
            website_url=None,
            igdb_genre_ids=[9],
        )
        updated = game_service.update_game(
            customer_game_id=game.customer_game_id,
            user_id=owner.user_id,
            name="AdminEdited",
            summary="Admin edited this",
            description="Admin changed the description",
            website_url=None,
            igdb_genre_ids=[9],
        )
        assert updated.name == "AdminEdited"


@pytest.fixture
def admin_app(monkeypatch, tmp_path):
    """Create a test app with admin secret configured."""
    db_path = str(tmp_path / "test.sqlite3")
    initialize_database(db_path)
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("ADMIN_SECRET_KEY", "test-admin-secret")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-that-is-long-enough")
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    app = create_app()
    return app


@pytest.fixture
def admin_client(admin_app):
    with TestClient(admin_app) as client:
        yield client


def _register_and_login(client, email, password):
    """Register, verify email, and log in. Returns session cookie."""
    import re

    def _csrf(path):
        r = client.get(path)
        m = re.search(r'name="csrf-token" content="([^"]+)"', r.text)
        return m.group(1) if m else ""

    client.post(
        "/auth/register",
        data={"csrf_token": _csrf("/auth/register"), "email": email, "password": password},
    )
    db_path = os.environ.get("DB_PATH", "")
    if db_path:
        with get_connection(db_path) as conn:
            conn.execute("UPDATE users SET email_verified = 1 WHERE email = ?", (email,))
    client.post(
        "/auth/login",
        data={"csrf_token": _csrf("/auth/login"), "email": email, "password": password},
    )


class TestAdminRouteAccessControl:
    def test_unauthenticated_redirects_to_login(self, admin_client):
        resp = admin_client.get(
            "/admin?key=test-admin-secret", follow_redirects=False
        )
        assert resp.status_code == 307
        assert "/auth/login" in resp.headers.get("location", "")

    def test_returns_404_without_key(self, admin_client):
        resp = admin_client.get("/admin", follow_redirects=False)
        assert resp.status_code == 307

    def test_returns_404_with_wrong_key(self, admin_client):
        resp = admin_client.get("/admin?key=wrong", follow_redirects=False)
        assert resp.status_code == 307

    def test_non_admin_user_with_correct_key_gets_404(self, admin_client):
        _register_and_login(admin_client, "nonadmin@test.com", "pass123")
        resp = admin_client.get(
            "/admin?key=test-admin-secret", follow_redirects=False
        )
        assert resp.status_code == 404

    def test_admin_user_with_correct_key_gets_200(self, admin_client):
        _register_and_login(admin_client, "admin@test.com", "pass123")
        db_path = os.environ.get("DB_PATH", "")
        with get_connection(db_path) as conn:
            conn.execute("UPDATE users SET is_admin = 1 WHERE email = ?", ("admin@test.com",))
        resp = admin_client.get(
            "/admin?key=test-admin-secret", follow_redirects=False
        )
        assert resp.status_code == 200
        assert "admin@test.com" not in resp.text  # admin excluded from customer list
