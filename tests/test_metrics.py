"""Tests for durable business metrics and Prometheus export."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import get_connection
from app.main import create_app
from app.metrics.definitions import GAMES_CREATED


def test_metrics_endpoint_returns_prometheus_text(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "metrics.sqlite3"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    with TestClient(create_app(), raise_server_exceptions=True) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# HELP spawnradar_accounts_created_total" in response.text
    assert "# DEFINITION spawnradar_accounts_created_total" in response.text


def test_metrics_record_auth_and_game_lifecycle_counters(
    auth_service, game_service, metrics_service
):
    user = auth_service.register("metrics@example.com", "password123")
    auth_service.login("metrics@example.com", "password123")

    game = game_service.create_game(
        user_id=user.user_id,
        name="Metrics Game",
        summary="A browser tactics game for metrics coverage.",
        description="A browser tactics game for metrics coverage.",
        website_url=None,
        igdb_genre_ids=[12, 24],  # Strategy, Tactical
    )
    duplicate = game_service.duplicate_game(game.customer_game_id, user.user_id)
    game_service.delete_game(duplicate.customer_game_id, user.user_id)

    metrics = metrics_service.render_prometheus()

    assert "spawnradar_accounts_created_total 1.000000" in metrics
    assert "spawnradar_sessions_started_total 1.000000" in metrics
    assert "spawnradar_games_created_total 1.000000" in metrics
    assert "spawnradar_games_duplicated_total 1.000000" in metrics
    assert "spawnradar_games_deleted_total 1.000000" in metrics


def test_metrics_reconcile_subscription_endings(
    auth_service, billing_service, db_path, metrics_service, sub_repo
):
    paid_user = auth_service.register("paid-ended@example.com", "password123")

    import uuid

    from app.billing.models import Tier
    sub_repo.create(str(uuid.uuid4()), paid_user.user_id, Tier.INDIE)

    sub_repo.update_from_paddle(
        paid_user.user_id,
        paddle_subscription_id="sub_paid_ended",
        status="canceled",
        current_period_end="2026-03-01T00:00:00+00:00",
    )

    first_render = metrics_service.render_prometheus()
    second_render = metrics_service.render_prometheus()

    assert (
        'spawnradar_paid_access_ended_total{reason="canceled"} 1.000000'
        in first_render
    )
    assert (
        'spawnradar_paid_access_ended_total{reason="canceled"} 1.000000'
        in second_render
    )


def test_metrics_derive_time_to_first_metrics(
    auth_service, db_path, metrics_service
):
    user = auth_service.register("timing@example.com", "password123")
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE metric_events
            SET occurred_at = ?
            WHERE metric_key = 'accounts_created' AND user_id = ?
            """,
            ("2026-03-01T00:00:00+00:00", user.user_id),
        )

    metrics_service.record_event(
        GAMES_CREATED,
        user_id=user.user_id,
        occurred_at="2026-03-01T12:00:00+00:00",
    )

    metrics = metrics_service.render_prometheus()

    assert (
        "spawnradar_time_to_first_game_created_hours_avg 12.000000" in metrics
    )
    assert (
        "spawnradar_time_to_first_game_created_hours_p50 12.000000" in metrics
    )
