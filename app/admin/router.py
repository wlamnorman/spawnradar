"""Admin routes — restricted to is_admin users."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import require_admin
from app.auth.models import User
from app.auth.repository import UserRepository
from app.billing.repository import SubscriptionRepository
from app.dependencies import (
    get_game_repo,
    get_subscription_repo,
    get_templates,
    get_user_repo,
)
from app.games.repository import GameRepository

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    user: User = Depends(require_admin),
    templates: Jinja2Templates = Depends(get_templates),
    user_repo: UserRepository = Depends(get_user_repo),
    game_repo: GameRepository = Depends(get_game_repo),
    sub_repo: SubscriptionRepository = Depends(get_subscription_repo),
) -> HTMLResponse:
    """Admin overview: all users, their games and subscription tiers."""
    users = user_repo.list_all()
    # Build per-user stats
    rows = []
    for u in users:
        games = game_repo.list_by_user(u.user_id)
        sub = sub_repo.get_by_user(u.user_id)
        rows.append({"user": u, "games": games, "subscription": sub})

    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {"user": user, "rows": rows},
    )
