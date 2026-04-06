"""Session cookie helpers shared by auth routes and guest creation."""

from __future__ import annotations

from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request
from starlette.responses import Response

from app.config import Settings


class AnonymousSessionMiddleware(BaseHTTPMiddleware):
    """Set the session cookie for newly created guest actors.

    ``get_or_create_guest_actor`` stores the new session ID on
    ``request.state.new_session_id``.  FastAPI's ``Response`` dependency
    injection does **not** propagate cookies into ``TemplateResponse`` /
    ``HTMLResponse`` returns, so a middleware is needed to reliably set
    the cookie on the actual response.
    """

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self._secure = settings.base_url.startswith("https://")

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        new_session_id = getattr(request.state, "new_session_id", None)
        if new_session_id is not None:
            response.set_cookie(
                key="session_id",
                value=new_session_id,
                httponly=True,
                secure=self._secure,
                samesite="lax",
                max_age=60 * 60 * 24 * 30,
            )
        return response


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
