"""Admin dashboard routes."""

from __future__ import annotations

import json
from datetime import UTC, datetime

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

    # Compute trial_days_left for each customer and parse game JSON fields
    now = datetime.now(UTC)
    for customer in data["customers"]:
        trial_days_left = None
        if customer["trial_ends_at"] and customer["sub_status"] == "active":
            try:
                ends = datetime.fromisoformat(customer["trial_ends_at"])
                delta = ends - now
                trial_days_left = max(0, delta.days)
            except (ValueError, TypeError):
                pass
        customer["trial_days_left"] = trial_days_left

        for game in customer["games"]:
            game["platforms_list"] = json.loads(game["platforms"] or "[]")

    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {"user": user, **data},
    )
