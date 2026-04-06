"""Billing routes: checkout, portal and webhook handling."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import require_user
from app.auth.models import User
from app.billing.models import TIER_PRICES, Tier
from app.billing.service import BillingService
from app.dependencies import get_billing_service, get_templates

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("")
async def billing_page(
    request: Request,
    user: User = Depends(require_user),
    billing: BillingService = Depends(get_billing_service),
    templates: Jinja2Templates = Depends(get_templates),
):
    """Billing management page for active subscribers."""
    sub = billing.get_subscription(user.user_id)
    if sub is None or not sub.has_subscription:
        return RedirectResponse(url="/pricing", status_code=303)
    return templates.TemplateResponse(
        request,
        "billing/manage.html",
        {
            "user": user,
            "subscription": sub,
            "portal_enabled": billing.portal_enabled,
            "indie_price": TIER_PRICES[Tier.INDIE],
        },
    )


@router.get("/pay")
async def pay(
    request: Request,
    tier: str | None = None,
    user: User = Depends(require_user),
    billing: BillingService = Depends(get_billing_service),
    templates: Jinja2Templates = Depends(get_templates),
):
    """Render the dedicated Paddle payment-link page for the single plan."""
    if tier not in (None, "indie", "studio"):
        raise HTTPException(status_code=400, detail="Invalid tier.")
    sub = billing.get_subscription(user.user_id)
    if sub is not None and sub.has_access:
        return RedirectResponse(url="/games", status_code=303)

    if not billing.checkout_enabled:
        raise HTTPException(
            status_code=503,
            detail=(
                "Billing is not configured. Set PADDLE_CLIENT_SIDE_TOKEN "
                "and PADDLE_INDIE_PRICE_ID."
            ),
        )

    try:
        checkout = billing.checkout_context(user.user_id, user.email)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return templates.TemplateResponse(
        request,
        "billing/pay.html",
        {
            "user": user,
            "price_id": checkout.price_id,
            "paddle_client_side_token": checkout.client_side_token,
            "paddle_environment": checkout.environment,
            "success_url": checkout.success_url,
            "customer_email": checkout.customer_email,
            "custom_data": checkout.custom_data,
        },
    )


@router.get("/success")
async def checkout_success(
    request: Request,
    user: User = Depends(require_user),
    billing: BillingService = Depends(get_billing_service),
    templates: Jinja2Templates = Depends(get_templates),
):
    """Handle post-checkout redirect from Paddle.

    Renders a polling page that waits for the webhook to activate the
    subscription, then redirects to /billing automatically.
    """
    transaction_id = request.query_params.get("_ptxn", "")
    await billing.sync_from_transaction(user.user_id, transaction_id)
    sub = billing.get_subscription(user.user_id)
    if sub is not None and sub.has_subscription:
        return RedirectResponse(url="/billing", status_code=303)
    return templates.TemplateResponse(
        request, "billing/success.html", {"user": user}
    )


@router.get("/status")
async def subscription_status(
    user: User = Depends(require_user),
    billing: BillingService = Depends(get_billing_service),
):
    """JSON endpoint polled by the success page to detect webhook activation."""
    sub = billing.get_subscription(user.user_id)
    return JSONResponse({"active": sub is not None and sub.has_subscription})


@router.get("/portal")
async def customer_portal(
    request: Request,
    user: User = Depends(require_user),
    billing: BillingService = Depends(get_billing_service),
    templates: Jinja2Templates = Depends(get_templates),
):
    """Redirect to a temporary Paddle customer portal session."""
    sub = billing.get_subscription(user.user_id)

    def _billing_page(error: str):
        return templates.TemplateResponse(
            request,
            "billing/manage.html",
            {
                "user": user,
                "subscription": sub,
                "portal_enabled": billing.portal_enabled,
                "error": error,
                "indie_price": TIER_PRICES[Tier.INDIE],
            },
            status_code=502,
        )

    if not billing.portal_enabled:
        return _billing_page("Billing portal is not configured.")

    try:
        url = await billing.get_portal_url(user.user_id)
    except httpx.HTTPStatusError:
        return _billing_page(
            "Could not open the billing portal. Please email contact@spawnradar.com."
        )
    if not url:
        return _billing_page("No billing account found for your user.")

    return RedirectResponse(url=url, status_code=303)


@router.post("/webhook")
async def paddle_webhook(
    request: Request,
    billing: BillingService = Depends(get_billing_service),
) -> JSONResponse:
    """Handle incoming Paddle webhook events."""
    payload = await request.body()
    signature = request.headers.get("Paddle-Signature", "")
    settings = request.app.state.settings

    try:
        billing.handle_webhook(
            payload, signature, settings.paddle_webhook_secret
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse({"received": True})
