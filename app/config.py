"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from app.email.service import DEFAULT_FROM_ADDRESS

_DEV_SECRET_KEY = "dev-secret-key-change-in-production"


class ConfigError(ValueError):
    """Raised when required environment configuration is missing or invalid."""


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


def _env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """All runtime configuration for Spawnradar.

    Loaded from environment variables with sensible defaults.
    """

    db_path: str
    log_level: str
    secret_key: str
    paddle_api_key: str
    paddle_client_side_token: str
    paddle_webhook_secret: str
    paddle_indie_price_id: str
    paddle_environment: str
    base_url: str
    resend_api_key: str
    email_from: str
    google_client_id: str
    google_client_secret: str
    twitch_client_id: str
    twitch_client_secret: str
    dev_auto_login: bool
    youtube_api_key: str
    anthropic_api_key: str
    youtube_cache_dir: str

    @property
    def uses_https(self) -> bool:
        return self.base_url.startswith("https://")

    @property
    def is_local_base_url(self) -> bool:
        parsed = urlparse(self.base_url)
        host = parsed.hostname or ""
        return host in {"localhost", "127.0.0.1"}

    def validate(self) -> Settings:
        if not self.secret_key:
            raise ConfigError("SECRET_KEY must be set.")
        if self.secret_key == _DEV_SECRET_KEY and not self.is_local_base_url:
            raise ConfigError("SECRET_KEY must be set to a non-default value outside local development.")

        if not self.base_url:
            raise ConfigError("BASE_URL must be set.")
        parsed_base = urlparse(self.base_url)
        if parsed_base.scheme not in {"http", "https"} or not parsed_base.netloc:
            raise ConfigError("BASE_URL must be a valid absolute http(s) URL.")

        if not self.log_level:
            raise ConfigError("LOG_LEVEL must be set.")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigError(
                "LOG_LEVEL must be one of DEBUG, INFO, WARNING, ERROR, or CRITICAL."
            )

        if self.paddle_environment and self.paddle_environment not in {"sandbox", "production"}:
            raise ConfigError("PADDLE_ENVIRONMENT must be either 'sandbox' or 'production'.")

        paddle_values = [
            self.paddle_api_key,
            self.paddle_client_side_token,
            self.paddle_webhook_secret,
            self.paddle_indie_price_id,
            self.paddle_environment,
        ]
        if any(paddle_values) and not all(paddle_values):
            raise ConfigError(
                "Paddle configuration is partial. Set PADDLE_API_KEY, PADDLE_CLIENT_SIDE_TOKEN, "
                "PADDLE_WEBHOOK_SECRET, PADDLE_INDIE_PRICE_ID, and PADDLE_ENVIRONMENT together."
            )

        if bool(self.google_client_id) != bool(self.google_client_secret):
            raise ConfigError(
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must either both be set or both be empty."
            )

        if bool(self.twitch_client_id) != bool(self.twitch_client_secret):
            raise ConfigError(
                "TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET must either both be set or both be empty."
            )

        return self

    @classmethod
    def from_env(cls) -> Settings:
        """Load and validate settings from environment variables."""
        _load_dotenv()

        settings = cls(
            db_path=_env_str("DB_PATH", "data/spawnradar.sqlite3"),
            log_level=_env_str("LOG_LEVEL", "INFO").upper(),
            secret_key=_env_str("SECRET_KEY", _DEV_SECRET_KEY),
            paddle_api_key=_env_str("PADDLE_API_KEY"),
            paddle_client_side_token=_env_str("PADDLE_CLIENT_SIDE_TOKEN"),
            paddle_webhook_secret=_env_str("PADDLE_WEBHOOK_SECRET"),
            paddle_indie_price_id=_env_str("PADDLE_INDIE_PRICE_ID"),
            paddle_environment=_env_str("PADDLE_ENVIRONMENT"),
            base_url=_env_str("BASE_URL", "http://localhost:8000"),
            resend_api_key=_env_str("RESEND_API_KEY"),
            email_from=DEFAULT_FROM_ADDRESS,
            google_client_id=_env_str("GOOGLE_CLIENT_ID"),
            google_client_secret=_env_str("GOOGLE_CLIENT_SECRET"),
            twitch_client_id=_env_str("TWITCH_CLIENT_ID"),
            twitch_client_secret=_env_str("TWITCH_CLIENT_SECRET"),
            dev_auto_login=_env_bool("DEV_AUTO_LOGIN"),
            youtube_api_key=_env_str("YOUTUBE_API_KEY"),
            anthropic_api_key=_env_str("ANTHROPIC_API_KEY"),
            youtube_cache_dir="data/yt_cache",
        )
        return settings.validate()
