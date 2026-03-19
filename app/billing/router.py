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
# Stripe checkout
# ---------------------------------------------------------------------------


@router.post("/checkout/{tier}")
async def checkout(
    tier: str,
    request: Request,
    user: User = Depends(require_user),
) -> RedirectResponse:
    """Start a Stripe Checkout session for the given tier."""
    if tier not in ("starter", "pro"):
        raise HTTPException(status_code=400, detail="Invalid tier.")

    billing = _billing_service(request)
    if not billing.stripe_enabled:
        raise HTTPException(
            status_code=503,
            detail="Billing is not configured. Set STRIPE_SECRET_KEY.",
        )

    url = billing.create_checkout_session(user.user_id, tier)
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
    """Handle post-checkout redirect from Stripe."""
    # Stripe will update the subscription via webhook; just redirect to games
    return RedirectResponse(url="/games", status_code=303)


# ---------------------------------------------------------------------------
# Customer portal
# ---------------------------------------------------------------------------


@router.get("/portal")
async def customer_portal(
    request: Request,
    user: User = Depends(require_user),
) -> RedirectResponse:
    """Redirect to the Stripe Customer Portal for subscription management."""
    billing = _billing_service(request)
    if not billing.stripe_enabled:
        raise HTTPException(
            status_code=503,
            detail="Billing is not configured.",
        )

    url = billing.create_portal_session(user.user_id)
    if not url:
        raise HTTPException(
            status_code=400, detail="No billing account found."
        )

    return RedirectResponse(url=url, status_code=303)


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


@router.post("/webhook")
async def stripe_webhook(request: Request) -> JSONResponse:
    """Handle incoming Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    billing = _billing_service(request)
    settings = request.app.state.settings

    try:
        billing.handle_stripe_webhook(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse({"received": True})
