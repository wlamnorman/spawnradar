"""Admin routes — restricted to is_admin users."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import require_admin
from app.auth.models import User
from app.auth.repository import UserRepository
from app.billing.repository import SubscriptionRepository
from app.games.repository import GameRepository

router = APIRouter(prefix="/admin", tags=["admin"])


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    user: User = Depends(require_admin),
) -> HTMLResponse:
    """Admin overview: all users, their games and subscription tiers."""
    db_path = request.app.state.settings.db_path
    user_repo = UserRepository(db_path)
    game_repo = GameRepository(db_path)
    sub_repo = SubscriptionRepository(db_path)

    users = user_repo.list_all()
    # Build per-user stats
    rows = []
    for u in users:
        games = game_repo.list_by_user(u.user_id)
        sub = sub_repo.get_by_user(u.user_id)
        rows.append({"user": u, "games": games, "subscription": sub})

    tpl = _templates(request)
    return tpl.TemplateResponse(
        request,
        "admin/dashboard.html",
        {"user": user, "rows": rows},
    )
