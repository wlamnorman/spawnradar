"""Tests for durable business metrics and Prometheus export."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.database import get_connection
from app.ingestion.base import CandidateRecord
from app.ingestion.pipeline import run_ingestion
from app.ingestion.registry import Source
from app.ingestion.sources.bluesky import BlueskySource
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
        genre_tags_raw="strategy, tactics",
        platform_tags=["browser"],
        website_url=None,
    )
    game_service.add_template(
        game.game_id,
        user.user_id,
        name="Pitch",
        channel="email",
        subject_template="Hello {{creator_name}}",
        body_template="Hi {{creator_name}} from {{game_name}}",
    )
    duplicate = game_service.duplicate_game(game.game_id, user.user_id)
    game_service.delete_game(duplicate.game_id, user.user_id)

    metrics = metrics_service.render_prometheus()

    assert "spawnradar_accounts_created_total 1.000000" in metrics
    assert "spawnradar_sessions_started_total 1.000000" in metrics
    assert "spawnradar_games_created_total 1.000000" in metrics
    assert "spawnradar_message_templates_created_total 1.000000" in metrics
    assert "spawnradar_games_duplicated_total 1.000000" in metrics
    assert "spawnradar_games_deleted_total 1.000000" in metrics


def test_metrics_record_discovery_distributions_and_scores(
    monkeypatch,
    billing_service,
    db_path,
    game_service,
    metrics_service,
    registered_user,
):
    game = game_service.create_game(
        user_id=registered_user.user_id,
        name="Discovery Metrics",
        summary="Test game for discovery metrics.",
        description="Test game for discovery metrics.",
        genre_tags_raw="strategy, tactics",
        platform_tags=["pc"],
        website_url=None,
    )
    game = replace(game, discovery_sources=[Source.BLUESKY])

    async def fake_discover(
        self,
        game,
        limit,
        *,
        run_index=0,
        excluded_handles=None,
        page_cursors=None,
    ):
        del self, game, limit, run_index, excluded_handles, page_cursors
        return [
            CandidateRecord(
                platform="bluesky",
                handle="strong-fit",
                display_name="Strong Fit",
                profile_url="https://bsky.app/profile/strong-fit",
                contact_channel="email",
                contact_value="strong@example.com",
                audience_size=1200,
                engagement_rate=0.02,
                description="Strong match for strategy players.",
                raw_data={"query": "strategy"},
                last_active_days=1,
                text_signals=["Turn-based tactics for PC players."],
                prospect_type="creator",
            ),
            CandidateRecord(
                platform="bluesky",
                handle="weak-fit",
                display_name="Weak Fit",
                profile_url="https://bsky.app/profile/weak-fit",
                contact_channel="email",
                contact_value="weak@example.com",
                audience_size=50,
                engagement_rate=0.01,
                description="Unrelated lifestyle creator.",
                raw_data={"query": "strategy"},
                last_active_days=30,
                text_signals=["Daily lifestyle updates."],
                prospect_type="creator",
            ),
        ]

    def fake_score_prospect(game, prospect, **kwargs):
        del game, kwargs
        is_strong = prospect.handle == "strong-fit"
        return SimpleNamespace(
            final_score=0.86 if is_strong else 0.12,
            genre_fit=0.9 if is_strong else 0.1,
            vibe_fit=0.85 if is_strong else 0.1,
            format_fit=0.8 if is_strong else 0.2,
            activity_score=0.75 if is_strong else 0.1,
            platform_fit=0.8 if is_strong else 0.1,
            contactability=0.9 if is_strong else 0.2,
            audience_size_score=0.4 if is_strong else 0.1,
            fit_summary="Strong fit" if is_strong else "Weak fit",
            why_selected="selected",
            reasons=[],
        )

    monkeypatch.setattr(BlueskySource, "discover", fake_discover)
    monkeypatch.setattr(
        "app.ingestion.pipeline.score_prospect", fake_score_prospect
    )

    status = billing_service.record_discovery_run(
        registered_user.user_id,
        game.game_id,
        now=datetime(2026, 3, 21, 12, 0, tzinfo=UTC),
    )
    summary = asyncio.run(
        run_ingestion(
            game,
            db_path,
            limit_per_source=5,
            run_id=status.run_id,
            metrics_service=metrics_service,
        )
    )

    assert summary == {"discovered": 2, "scored": 2, "imported": 1}

    metrics = metrics_service.render_prometheus()

    assert "spawnradar_discovery_runs_started_total 1.000000" in metrics
    assert "spawnradar_discovery_runs_completed_total 1.000000" in metrics
    assert "spawnradar_discovery_runs_no_prospects_total 0.000000" in metrics
    assert "spawnradar_prospects_discovered_total 2.000000" in metrics
    assert "spawnradar_prospects_scored_total 2.000000" in metrics
    assert "spawnradar_prospects_queued_total 1.000000" in metrics
    assert (
        'spawnradar_discovery_run_prospects_discovered_bucket{le="3"} 1'
        in metrics
    )
    assert "spawnradar_prospect_score_scored_count 2" in metrics
    assert "spawnradar_prospect_score_queued_count 1" in metrics


def test_metrics_reconcile_subscription_endings_and_trial_expiry(
    auth_service, billing_service, db_path, metrics_service, sub_repo
):
    expired_trial_user = auth_service.register(
        "trial-expired@example.com", "password123"
    )
    paid_user = auth_service.register("paid-ended@example.com", "password123")

    trial_sub = billing_service.get_or_create_subscription(
        expired_trial_user.user_id
    )
    billing_service.get_or_create_subscription(paid_user.user_id)

    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE subscriptions
            SET trial_ends_at = ?, updated_at = ?
            WHERE subscription_id = ?
            """,
            (
                "2026-03-01T00:00:00+00:00",
                "2026-03-01T00:00:00+00:00",
                trial_sub.subscription_id,
            ),
        )

    sub_repo.update_from_paddle(
        paid_user.user_id,
        paddle_subscription_id="sub_paid_ended",
        status="canceled",
        current_period_end="2026-03-01T00:00:00+00:00",
    )

    first_render = metrics_service.render_prometheus()
    second_render = metrics_service.render_prometheus()

    assert (
        "spawnradar_trials_expired_without_conversion_total 1.000000"
        in first_render
    )
    assert (
        'spawnradar_paid_access_ended_total{reason="canceled"} 1.000000'
        in first_render
    )
    assert (
        "spawnradar_trials_expired_without_conversion_total 1.000000"
        in second_render
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
    metrics_service.record_discovery_run_started(
        "run-1",
        user.user_id,
        "game-1",
        started_at="2026-03-02T00:00:00+00:00",
    )

    metrics = metrics_service.render_prometheus()

    assert (
        "spawnradar_time_to_first_game_created_hours_avg 12.000000" in metrics
    )
    assert (
        "spawnradar_time_to_first_game_created_hours_p50 12.000000" in metrics
    )
    assert (
        "spawnradar_time_to_first_discovery_run_hours_avg 24.000000" in metrics
    )
