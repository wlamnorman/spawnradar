"""Billing routes: checkout, portal, and webhook handling."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.auth.dependencies import require_user
from app.auth.models import User
from app.billing.service import BillingService

router = APIRouter(prefix="/billing", tags=["billing"])


def _billing_service(request: Request) -> BillingService:
    return request.app.state.billing_service


@router.get("")
async def billing_root_redirect() -> RedirectResponse:
    """Keep old plan links working by redirecting to the public pricing page."""
    return RedirectResponse(url="/pricing", status_code=303)


@router.get("/pricing")
async def billing_pricing_redirect() -> RedirectResponse:
    """Keep legacy pricing links working by redirecting to /pricing."""
    return RedirectResponse(url="/pricing", status_code=303)


# ---------------------------------------------------------------------------
# Lemon Squeezy checkout
# ---------------------------------------------------------------------------


@router.post("/checkout/{tier}")
async def checkout(
    tier: str,
    request: Request,
    user: User = Depends(require_user),
) -> RedirectResponse:
    """Start a Lemon Squeezy checkout session for the given tier."""
    if tier not in ("starter", "pro"):
        raise HTTPException(status_code=400, detail="Invalid tier.")

    billing = _billing_service(request)
    if not billing.ls_enabled:
        raise HTTPException(
            status_code=503,
            detail="Billing is not configured. Set LEMONSQUEEZY_API_KEY.",
        )

    url = await billing.create_checkout_url(user.user_id, tier)
    if not url:
        raise HTTPException(
            status_code=503, detail="Could not create checkout session."
        )

    return RedirectResponse(url=url, status_code=303)


# ---------------------------------------------------------------------------
# Checkout success
# ---------------------------------------------------------------------------


@router.get("/success")
async def checkout_success(
    request: Request,
    user: User = Depends(require_user),
) -> RedirectResponse:
    """Handle post-checkout redirect from Lemon Squeezy."""
    return RedirectResponse(url="/games", status_code=303)


# ---------------------------------------------------------------------------
# Customer portal
# ---------------------------------------------------------------------------


@router.get("/portal")
async def customer_portal(
    request: Request,
    user: User = Depends(require_user),
) -> RedirectResponse:
    """Redirect to the Lemon Squeezy customer portal for subscription management."""
    billing = _billing_service(request)
    if not billing.ls_enabled:
        raise HTTPException(
            status_code=503,
            detail="Billing is not configured.",
        )

    url = await billing.get_portal_url(user.user_id)
    if not url:
        raise HTTPException(
            status_code=400, detail="No billing account found."
        )

    return RedirectResponse(url=url, status_code=303)


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


@router.post("/webhook")
async def ls_webhook(request: Request) -> JSONResponse:
    """Handle incoming Lemon Squeezy webhook events."""
    payload = await request.body()
    signature = request.headers.get("x-signature", "")

    billing = _billing_service(request)
    settings = request.app.state.settings

    try:
        billing.handle_webhook(
            payload, signature, settings.ls_webhook_secret
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse({"received": True})
