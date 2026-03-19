"""FastAPI dependencies for authentication."""
from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, Request

from app.auth.models import User
from app.auth.service import AuthService


def _get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


async def get_current_user(
    request: Request,
    session_id: str | None = Cookie(default=None),
    auth_service: AuthService = Depends(_get_auth_service),
) -> User | None:
    """Return the authenticated user from the session cookie, or None."""
    if session_id is None:
        return None
    return auth_service.get_user_for_session(session_id)


async def require_user(
    request: Request,
    session_id: str | None = Cookie(default=None),
    auth_service: AuthService = Depends(_get_auth_service),
) -> User:
    """FastAPI dependency that enforces authentication.

    Redirects to /auth/login for browser requests.
    Raises HTTP 401 for API/JSON requests.
    """
    if session_id is None:
        return _reject(request)

    user = auth_service.get_user_for_session(session_id)
    if user is None:
        return _reject(request)
    return user


async def require_admin(user: User = Depends(require_user)) -> User:
    """FastAPI dependency that requires the user to be an admin."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


def _reject(request: Request):
    """Redirect or raise 401 depending on the Accept header."""
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        raise HTTPException(status_code=401, detail="Authentication required.")
    # For HTML browser requests, redirect to login page
    raise HTTPException(
        status_code=307,
        headers={"Location": f"/auth/login?next={request.url.path}"},
    )
