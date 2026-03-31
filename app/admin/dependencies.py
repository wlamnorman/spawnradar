"""FastAPI dependencies for admin access control."""

from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Query, Request

from app.auth.dependencies import require_verified_user
from app.auth.models import User
from app.config import Settings
from app.dependencies import get_settings


def verify_admin_access(
    *,
    user: User,
    admin_secret_key: str,
    provided_key: str | None,
) -> None:
    """Raise 404 unless user is admin AND provided key matches.

    Uses constant-time comparison to prevent timing attacks.
    Returns 404 (not 403) to avoid revealing the route exists.
    """
    if not admin_secret_key:
        raise HTTPException(status_code=404)
    if not provided_key:
        raise HTTPException(status_code=404)
    if not hmac.compare_digest(admin_secret_key, provided_key):
        raise HTTPException(status_code=404)
    if not user.is_admin:
        raise HTTPException(status_code=404)


async def require_admin(
    request: Request,
    key: str | None = Query(default=None),
    user: User = Depends(require_verified_user),
    settings: Settings = Depends(get_settings),
) -> User:
    """FastAPI dependency: dual-gate admin access (secret key + is_admin)."""
    verify_admin_access(
        user=user,
        admin_secret_key=settings.admin_secret_key,
        provided_key=key,
    )
    return user
