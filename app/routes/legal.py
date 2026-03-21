"""Public legal and policy pages required for verification and billing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.dependencies import get_templates

router = APIRouter()


@router.get("/terms")
async def terms_page(
    request: Request,
    user: User | None = Depends(get_current_user),
    templates: Jinja2Templates = Depends(get_templates),
):
    return templates.TemplateResponse(request, "legal/terms.html", {"user": user})


@router.get("/privacy")
async def privacy_page(
    request: Request,
    user: User | None = Depends(get_current_user),
    templates: Jinja2Templates = Depends(get_templates),
):
    return templates.TemplateResponse(request, "legal/privacy.html", {"user": user})


@router.get("/refunds")
async def refunds_page(
    request: Request,
    user: User | None = Depends(get_current_user),
    templates: Jinja2Templates = Depends(get_templates),
):
    return templates.TemplateResponse(request, "legal/refunds.html", {"user": user})
