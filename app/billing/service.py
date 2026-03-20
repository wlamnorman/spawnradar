"""Billing business logic: tier limits, Lemon Squeezy checkout, webhook handling.

The Lemon Squeezy integration degrades gracefully: if LEMONSQUEEZY_API_KEY is
not set, checkout and portal operations return an empty string rather than
crashing.

Webhook signature verification: HMAC-SHA256 of the raw request body, compared
against the X-Signature header value.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid

import httpx

from app.billing.models import TIER_LIMITS, TRIAL_DAYS, Subscription, Tier
from app.billing.repository import SubscriptionRepository
from app.games.repository import GameRepository

log = logging.getLogger(__name__)

_LS_API_BASE = "https://api.lemonsqueezy.com/v1"

# Lemon Squeezy status → our internal status
_LS_STATUS_MAP: dict[str, str] = {
    "on_trial": "trialing",
    "active": "active",
    "past_due": "past_due",
    "unpaid": "past_due",
    "cancelled": "cancelled",
    "expired": "cancelled",
    "paused": "paused",
}


class BillingService:
    """Manages subscriptions and enforces tier limits."""

    def __init__(
        self,
        sub_repo: SubscriptionRepository,
        game_repo: GameRepository,
        ls_api_key: str = "",
        ls_store_id: str = "",
        ls_starter_variant_id: str = "",
        ls_pro_variant_id: str = "",
        base_url: str = "http://localhost:8000",
    ) -> None:
        self._subs = sub_repo
        self._games = game_repo
        self._api_key = ls_api_key
        self._store_id = ls_store_id
        self._starter_variant = ls_starter_variant_id
        self._pro_variant = ls_pro_variant_id
        self._base_url = base_url

    @property
    def ls_enabled(self) -> bool:
        """Return True if Lemon Squeezy is configured."""
        return bool(self._api_key)

    # ------------------------------------------------------------------
    # Subscription access
    # ------------------------------------------------------------------

    def get_or_create_subscription(self, user_id: str) -> Subscription:
        """Return the user's subscription, creating a Starter trial if absent."""
        sub = self._subs.get_by_user(user_id)
        if sub is not None:
            return sub
        return self._subs.create(
            str(uuid.uuid4()), user_id, Tier.STARTER, trial_days=TRIAL_DAYS
        )

    def check_game_limit(self, user_id: str) -> bool:
        """Return True if the user can create another game under their plan."""
        sub = self.get_or_create_subscription(user_id)
        limit = TIER_LIMITS[sub.effective_tier]["games"]
        current = self._games.count_by_user(user_id)
        return current < limit

    def get_prospects_limit(self, user_id: str) -> int:
        """Return how many prospects the user can discover per ingestion run."""
        sub = self.get_or_create_subscription(user_id)
        return TIER_LIMITS[sub.effective_tier]["prospects_per_run"]

    # ------------------------------------------------------------------
    # Lemon Squeezy API calls
    # ------------------------------------------------------------------

    async def create_checkout_url(self, user_id: str, tier: str) -> str:
        """Create a Lemon Squeezy checkout and return its URL.

        Returns an empty string if Lemon Squeezy is not configured or if
        variant / store IDs are missing.
        """
        if not self.ls_enabled:
            return ""

        variant_id = (
            self._starter_variant if tier == "starter" else self._pro_variant
        )
        if not variant_id or not self._store_id:
            return ""

        payload = {
            "data": {
                "type": "checkouts",
                "attributes": {
                    "checkout_data": {
                        "custom": {"user_id": user_id},
                    },
                    "product_options": {
                        "redirect_url": f"{self._base_url}/billing/success",
                    },
                },
                "relationships": {
                    "store": {"data": {"type": "stores", "id": self._store_id}},
                    "variant": {"data": {"type": "variants", "id": variant_id}},
                },
            }
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{_LS_API_BASE}/checkouts",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        return data["data"]["attributes"].get("url", "")

    async def get_portal_url(self, user_id: str) -> str:
        """Return the Lemon Squeezy customer portal URL for the user.

        Returns an empty string if the user has no LS subscription yet.
        """
        if not self.ls_enabled:
            return ""

        sub = self.get_or_create_subscription(user_id)
        if not sub.ls_subscription_id:
            return ""

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_LS_API_BASE}/subscriptions/{sub.ls_subscription_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        urls = data["data"]["attributes"].get("urls", {})
        return urls.get("customer_portal", "")

    # ------------------------------------------------------------------
    # Webhook handling
    # ------------------------------------------------------------------

    def handle_webhook(
        self, payload: bytes, signature: str, webhook_secret: str
    ) -> None:
        """Process an incoming Lemon Squeezy webhook event."""
        if not self.ls_enabled:
            return

        if not self._verify_signature(payload, signature, webhook_secret):
            raise ValueError("Invalid Lemon Squeezy webhook signature.")

        event = json.loads(payload)
        event_name = event.get("meta", {}).get("event_name", "")

        if event_name in (
            "subscription_created",
            "subscription_updated",
            "subscription_resumed",
            "subscription_unpaused",
            "subscription_paused",
        ):
            self._sync_subscription(event)
        elif event_name in ("subscription_cancelled", "subscription_expired"):
            self._cancel_subscription(event)

    def _sync_subscription(self, event: dict) -> None:  # type: ignore[type-arg]
        """Update local subscription from a Lemon Squeezy subscription event."""
        meta = event.get("meta", {})
        data = event.get("data", {})
        attrs = data.get("attributes", {})

        ls_sub_id = str(data.get("id", ""))
        ls_customer_id = str(attrs.get("customer_id", ""))
        ls_status = attrs.get("status", "active")
        status = _LS_STATUS_MAP.get(ls_status, "active")
        variant_id = str(attrs.get("variant_id", ""))
        renews_at = attrs.get("renews_at")

        tier = Tier.PRO if variant_id == self._pro_variant else Tier.STARTER

        user_id = self._resolve_user_id(meta, ls_customer_id)
        if not user_id:
            return

        self._subs.update_from_ls(
            user_id,
            ls_customer_id=ls_customer_id,
            ls_subscription_id=ls_sub_id,
            tier=tier,
            status=status,
            current_period_end=renews_at,
        )

    def _cancel_subscription(self, event: dict) -> None:  # type: ignore[type-arg]
        """Mark a subscription as cancelled and revert tier to Starter."""
        meta = event.get("meta", {})
        attrs = event.get("data", {}).get("attributes", {})
        ls_customer_id = str(attrs.get("customer_id", ""))

        user_id = self._resolve_user_id(meta, ls_customer_id)
        if not user_id:
            return

        self._subs.update_from_ls(user_id, status="cancelled", tier=Tier.STARTER)

    def _resolve_user_id(self, meta: dict, ls_customer_id: str) -> str | None:  # type: ignore[type-arg]
        """Return a user_id from webhook metadata or a customer-ID lookup."""
        user_id: str | None = meta.get("custom_data", {}).get("user_id")
        if not user_id:
            sub = self._subs.get_by_ls_customer(ls_customer_id)
            if sub:
                user_id = sub.user_id
        if not user_id:
            log.warning(
                "LS webhook: could not resolve user for customer %s", ls_customer_id
            )
        return user_id

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _verify_signature(
        self, payload: bytes, signature: str, secret: str
    ) -> bool:
        """Verify an HMAC-SHA256 webhook signature from Lemon Squeezy."""
        expected = hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
        }
