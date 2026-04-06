"""Public legal and policy pages required for verification and billing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates

from app.dependencies import get_templates
from app.ownership.dependencies import get_ownership_context
from app.ownership.service import OwnershipContext

router = APIRouter()


@router.get("/terms")
async def terms_page(
    request: Request,
    ownership: OwnershipContext = Depends(get_ownership_context),
    templates: Jinja2Templates = Depends(get_templates),
):
    return templates.TemplateResponse(
        request,
        "legal/terms.html",
        {"user": ownership.actor},
    )


@router.get("/privacy")
async def privacy_page(
    request: Request,
    ownership: OwnershipContext = Depends(get_ownership_context),
    templates: Jinja2Templates = Depends(get_templates),
):
    return templates.TemplateResponse(
        request,
        "legal/privacy.html",
        {"user": ownership.actor},
    )


@router.get("/refunds")
async def refunds_page(
    request: Request,
    ownership: OwnershipContext = Depends(get_ownership_context),
    templates: Jinja2Templates = Depends(get_templates),
):
    return templates.TemplateResponse(
        request,
        "legal/refunds.html",
        {"user": ownership.actor},
    )
