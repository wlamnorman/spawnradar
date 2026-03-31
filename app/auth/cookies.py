"""Session cookie helpers shared by auth routes and anonymous user creation."""

from __future__ import annotations

from starlette.responses import Response

from app.config import Settings


def use_secure_cookies(settings: Settings) -> bool:
    """Return True if the base URL is HTTPS (production)."""
    return settings.base_url.startswith("https://")


def set_session_cookie(
    response: Response,
    session_id: str,
    settings: Settings,
) -> None:
    """Set the session_id cookie on *response*."""
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        secure=use_secure_cookies(settings),
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    """Remove the session_id cookie."""
    response.delete_cookie(
        key="session_id",
        httponly=True,
        secure=use_secure_cookies(settings),
        samesite="lax",
    )
