"""FastAPI dependencies for ownership context resolution."""

from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, Request

from app.dependencies import get_ownership_service
from app.ownership.service import OwnershipContext, OwnershipService


async def get_ownership_context(
    session_id: str | None = Cookie(default=None),
    ownership_service: OwnershipService = Depends(get_ownership_service),
) -> OwnershipContext:
    """Return the current ownership context for the request session."""
    return ownership_service.get_context_for_session(session_id)


async def require_ownership_context(
    context: OwnershipContext = Depends(get_ownership_context),
) -> OwnershipContext:
    """Require an existing actor-backed ownership context."""
    if context.actor is not None:
        return context
    raise HTTPException(status_code=307, headers={"Location": "/games"})


async def get_or_create_guest_ownership_context(
    request: Request,
    context: OwnershipContext = Depends(get_ownership_context),
    ownership_service: OwnershipService = Depends(get_ownership_service),
) -> OwnershipContext:
    """Return the current context, creating a guest on meaningful writes."""
    if context.actor is not None:
        return context
    context, session = ownership_service.create_guest_context(
        first_path=request.url.path,
        first_referrer=request.headers.get("referer"),
        first_user_agent=request.headers.get("user-agent"),
    )
    request.state.new_session_id = session.session_id
    return context
