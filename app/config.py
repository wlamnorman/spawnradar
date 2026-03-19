"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """All runtime configuration for Spawnradar.

    Loaded from environment variables with sensible defaults.
    """

    db_path: str
    secret_key: str
    stripe_secret_key: str
    stripe_webhook_secret: str
    stripe_starter_price_id: str
    stripe_pro_price_id: str
    base_url: str
    resend_api_key: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    email_from: str
    dev_auto_login: bool
    youtube_api_key: str
    anthropic_api_key: str
    youtube_cache_dir: str  # empty string = disabled

    @classmethod
    def from_env(cls) -> Settings:
        """Load settings from environment, falling back to .env file if present."""
        # Attempt to load .env file if python-dotenv is installed
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

        return cls(
            db_path=os.environ.get("DB_PATH", "data/spawnradar.sqlite3"),
            secret_key=os.environ.get(
                "SECRET_KEY", "dev-secret-key-change-in-production"
            ),
            stripe_secret_key=os.environ.get("STRIPE_SECRET_KEY", ""),
            stripe_webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
            stripe_starter_price_id=os.environ.get(
                "STRIPE_STARTER_PRICE_ID", ""
            ),
            stripe_pro_price_id=os.environ.get("STRIPE_PRO_PRICE_ID", ""),
            base_url=os.environ.get("BASE_URL", "http://localhost:8000"),
            resend_api_key=os.environ.get("RESEND_API_KEY", ""),
            smtp_host=os.environ.get("SMTP_HOST", ""),
            smtp_port=int(os.environ.get("SMTP_PORT", "587")),
            smtp_user=os.environ.get("SMTP_USER", ""),
            smtp_password=os.environ.get("SMTP_PASSWORD", ""),
            email_from=os.environ.get("EMAIL_FROM", "noreply@spawnradar.app"),
            dev_auto_login=os.environ.get("DEV_AUTO_LOGIN", "").strip().lower()
            in {"1", "true", "yes", "on"},
            youtube_api_key=os.environ.get("YOUTUBE_API_KEY", ""),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            youtube_cache_dir=os.environ.get("YOUTUBE_CACHE_DIR", "data/yt_cache"),
        )
