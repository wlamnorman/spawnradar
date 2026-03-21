"""Billing routes: checkout, portal, and webhook handling."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import require_user
from app.auth.models import User
from app.billing.service import BillingService
from app.dependencies import get_billing_service, get_templates

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("")
async def billing_root_redirect() -> RedirectResponse:
    """Keep old plan links working by redirecting to the public pricing page."""
    return RedirectResponse(url="/pricing", status_code=303)


@router.get("/pricing")
async def billing_pricing_redirect() -> RedirectResponse:
    """Keep legacy pricing links working by redirecting to /pricing."""
    return RedirectResponse(url="/pricing", status_code=303)


@router.get("/checkout/{tier}")
async def legacy_checkout_redirect(tier: str) -> RedirectResponse:
    """Redirect legacy checkout links to the dedicated Paddle payment page."""
    if tier not in ("indie", "studio"):
        raise HTTPException(status_code=400, detail="Invalid tier.")
    return RedirectResponse(url="/billing/pay", status_code=303)


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
    sub = billing.get_or_create_subscription(user.user_id)
    if sub.has_access:
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
) -> RedirectResponse:
    """Handle post-checkout redirect from Paddle.

    Paddle appends ?_ptxn=<transaction_id> to this URL. We use it to
    eagerly sync the subscription so the user sees active status immediately
    rather than waiting for the webhook to arrive.
    """
    transaction_id = request.query_params.get("_ptxn", "")
    await billing.sync_from_transaction(user.user_id, transaction_id)
    return RedirectResponse(url="/games", status_code=303)


@router.get("/portal")
async def customer_portal(
    request: Request,
    user: User = Depends(require_user),
    billing: BillingService = Depends(get_billing_service),
) -> RedirectResponse:
    """Redirect to a temporary Paddle customer portal session."""
    if not billing.portal_enabled:
        raise HTTPException(status_code=503, detail="Billing is not configured.")

    url = await billing.get_portal_url(user.user_id)
    if not url:
        raise HTTPException(status_code=400, detail="No billing account found.")

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
