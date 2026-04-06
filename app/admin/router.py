"""Admin dashboard routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.admin.dependencies import require_admin
from app.admin.queries import get_dashboard_data
from app.auth.models import User
from app.config import Settings
from app.dependencies import get_settings, get_templates

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
        {"user": user, **data},
    )
