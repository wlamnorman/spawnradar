from __future__ import annotations

import pytest

from app.config import ConfigError, Settings


def test_settings_reject_partial_paddle_configuration(monkeypatch):
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("PADDLE_CLIENT_SIDE_TOKEN", "test_token")
    monkeypatch.setenv("PADDLE_API_KEY", "")
    monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "")
    monkeypatch.setenv("PADDLE_INDIE_PRICE_ID", "")
    monkeypatch.setenv("PADDLE_ENVIRONMENT", "")

    with pytest.raises(ConfigError, match="Paddle configuration is partial"):
        Settings.from_env()


def test_settings_reject_default_secret_key_for_non_local_base_url(
    monkeypatch,
):
    monkeypatch.setenv("BASE_URL", "https://spawnradar.com")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("SECRET_KEY", "dev-secret-key-change-in-production")
    for key in (
        "PADDLE_API_KEY",
        "PADDLE_CLIENT_SIDE_TOKEN",
        "PADDLE_WEBHOOK_SECRET",
        "PADDLE_INDIE_PRICE_ID",
        "PADDLE_ENVIRONMENT",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ConfigError, match="SECRET_KEY"):
        Settings.from_env()


def test_settings_allow_default_secret_key_for_local_base_url(monkeypatch):
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("SECRET_KEY", "dev-secret-key-change-in-production")
    for key in (
        "PADDLE_API_KEY",
        "PADDLE_CLIENT_SIDE_TOKEN",
        "PADDLE_WEBHOOK_SECRET",
        "PADDLE_INDIE_PRICE_ID",
        "PADDLE_ENVIRONMENT",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings.from_env()
    assert settings.base_url == "http://localhost:8000"


def test_settings_reject_invalid_log_level(monkeypatch):
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("LOG_LEVEL", "TRACE")

    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        Settings.from_env()


def test_settings_reject_partial_twitch_configuration(monkeypatch):
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("TWITCH_CLIENT_ID", "twitch-client")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "")

    with pytest.raises(ConfigError, match="TWITCH_CLIENT_ID"):
        Settings.from_env()


def test_settings_load_creator_index_scope_options(monkeypatch):
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv(
        "CREATOR_INDEX_GAME_NAMES", "Strife Of Stars, WikiQuests "
    )
    monkeypatch.setenv("CREATOR_INDEX_BOOTSTRAP_ENABLED", "0")

    settings = Settings.from_env()

    assert settings.creator_index_game_names == (
        "Strife Of Stars",
        "WikiQuests",
    )
    assert settings.creator_index_bootstrap_enabled is False
    assert settings.creator_index_twitch_min_live_viewers == 10
    assert settings.creator_index_twitch_min_followers == 0
    assert settings.creator_index_customer_game_twitch_probe_limit == 10
