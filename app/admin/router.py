"""Admin dashboard routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.admin.dependencies import require_admin
from app.admin.queries import get_dashboard_data
from app.auth.models import User
from app.bluesky_posts.repository import BlueskyPostDraftRepository
from app.bluesky_posts.service import BlueskyDraftService
from app.config import Settings
from app.dependencies import (
    get_bluesky_draft_repo,
    get_bluesky_draft_service,
    get_settings,
    get_templates,
)
from app.security import require_csrf_form

router = APIRouter()


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    user: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Render the admin dashboard."""
    data = get_dashboard_data(settings.db_path)

    # Parse game JSON fields for each workspace card.
    for workspace in data["workspaces"]:
        for game in workspace["games"]:
            game["platforms_list"] = json.loads(game["platforms"] or "[]")

    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "user": user,
            "admin_key": request.query_params.get("key", ""),
            **data,
        },
    )


@router.get("/admin/bluesky-posts", response_class=HTMLResponse)
def admin_bluesky_posts(
    request: Request,
    user: User = Depends(require_admin),
    repo: BlueskyPostDraftRepository = Depends(get_bluesky_draft_repo),
    templates: Jinja2Templates = Depends(get_templates),
) -> HTMLResponse:
    """Render the internal Bluesky draft review queue."""
    drafts = repo.list_queue()
    games = request.app.state.customer_game_repo
    draft_cards = []
    for draft in drafts:
        game = games.get_by_id(draft.customer_game_id)
        if game is None:
            continue
        draft_cards.append({"draft": draft, "game": game})

    return templates.TemplateResponse(
        request,
        "admin/bluesky_posts.html",
        {
            "user": user,
            "admin_key": request.query_params.get("key", ""),
            "draft_cards": draft_cards,
        },
    )


@router.post("/admin/bluesky-posts/{draft_id}")
def admin_bluesky_posts_update(
    draft_id: str,
    request: Request,
    body: str = Form(default=""),
    action: str = Form(default="save"),
    user: User = Depends(require_admin),
    service: BlueskyDraftService = Depends(get_bluesky_draft_service),
    _csrf: None = Depends(require_csrf_form),
) -> RedirectResponse:
    """Apply admin edits or status transitions to a Bluesky draft."""
    status_by_action = {
        "save": "draft",
        "approve": "approved",
        "reject": "rejected",
    }
    service.review_draft(
        draft_id,
        body=body,
        status=status_by_action.get(action, "draft"),
    )
    key = request.query_params.get("key", "")
    return RedirectResponse(
        url=f"/admin/bluesky-posts?key={key}",
        status_code=303,
    )
