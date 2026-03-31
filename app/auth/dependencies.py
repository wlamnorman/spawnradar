"""FastAPI dependencies for authentication."""

from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, Request, Response

from app.auth.cookies import set_session_cookie
from app.auth.models import User
from app.auth.service import AuthService
from app.billing.service import BillingService
from app.config import Settings
from app.dependencies import get_auth_service, get_billing_service, get_settings


async def get_current_user(
    session_id: str | None = Cookie(default=None),
    auth_service: AuthService = Depends(get_auth_service),
) -> User | None:
    """Return the authenticated user from the session cookie, or None."""
    if session_id is None:
        return None
    return auth_service.get_user_for_session(session_id)


async def require_user(
    request: Request,
    session_id: str | None = Cookie(default=None),
    auth_service: AuthService = Depends(get_auth_service),
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


async def require_verified_user(
    user: User = Depends(require_user),
) -> User:
    """Require an authenticated user with a verified email address."""
    if not user.email_verified:
        raise HTTPException(
            status_code=307,
            headers={"Location": "/auth/verify-pending"},
        )
    return user


async def require_product_access(
    request: Request,
    user: User = Depends(require_verified_user),
    billing_service: BillingService = Depends(get_billing_service),
) -> User:
    """Require an authenticated user with a verified email and active product access."""
    sub = billing_service.get_subscription(user.user_id)
    if sub is not None and sub.has_access:
        return user

    accept = request.headers.get("accept", "")
    if request.url.path.startswith("/api/") or "application/json" in accept:
        raise HTTPException(
            status_code=402, detail="Active subscription required."
        )

    raise HTTPException(status_code=307, headers={"Location": "/pricing"})


async def require_user_or_anonymous(
    request: Request,
    response: Response,
    session_id: str | None = Cookie(default=None),
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> User:
    """Return the current user, creating an anonymous user if no valid session.

    Unlike require_user (which redirects to login), this creates a cookie-based
    anonymous identity on the spot. The cookie is set on the response so
    subsequent requests are associated with the same user.
    """
    if session_id:
        user = auth_service.get_user_for_session(session_id)
        if user is not None:
            return user
    # No valid session — create anonymous user and set cookie
    user, session = auth_service.create_anonymous_user()
    set_session_cookie(response, session.session_id, settings)
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
