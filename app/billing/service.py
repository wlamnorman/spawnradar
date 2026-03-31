"""Billing business logic: Paddle checkout, portal and webhook handling."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from app.billing.models import (
    FREE_LIMITS,
    TIER_LIMITS,
    Subscription,
    Tier,
)
from app.billing.repository import SubscriptionRepository
from app.games.repository import CustomerGameRepository

if TYPE_CHECKING:
    from app.metrics.service import MetricsService

log = logging.getLogger(__name__)

_PADDLE_API_BASE = "https://api.paddle.com"
_ALLOWED_PADDLE_ENVIRONMENTS = {"sandbox", "production"}


@dataclass(frozen=True)
class CheckoutContext:
    price_id: str
    client_side_token: str
    environment: str
    success_url: str
    customer_email: str | None
    custom_data: dict[str, str]


class BillingService:
    """Manages subscriptions and enforces tier limits."""

    def __init__(
        self,
        sub_repo: SubscriptionRepository,
        customer_game_repo: CustomerGameRepository,
        metrics_service: MetricsService | None = None,
        paddle_api_key: str = "",
        paddle_client_side_token: str = "",
        paddle_indie_price_id: str = "",
        paddle_environment: str = "sandbox",
        base_url: str = "http://localhost:8000",
    ) -> None:
        self._subs = sub_repo
        self._customer_games = customer_game_repo
        self._metrics = metrics_service
        self._api_key = paddle_api_key
        self._client_side_token = paddle_client_side_token
        self._indie_price_id = paddle_indie_price_id
        self._environment = _normalize_environment(
            paddle_environment, paddle_client_side_token
        )
        self._base_url = base_url.rstrip("/")

    @property
    def checkout_enabled(self) -> bool:
        """Return True if Paddle checkout is configured."""
        return bool(self._client_side_token and self._indie_price_id)

    @property
    def portal_enabled(self) -> bool:
        """Return True if backend Paddle API features are configured."""
        return bool(self._api_key)

    def get_subscription(self, user_id: str) -> Subscription | None:
        """Return the user's subscription, or None if they have no subscription row."""
        return self._subs.get_by_user(user_id)

    def check_game_limit(self, user_id: str) -> bool:
        sub = self.get_subscription(user_id)
        limit = self._get_limits(sub)["games"]
        current = self._customer_games.count_by_user(user_id)
        return current < limit

    def grant_comped_access(self, user_id: str) -> Subscription | None:
        """Grant complimentary full access without a Paddle subscription."""
        return self._subs.grant_comped_access(user_id, Tier.INDIE)

    def _get_limits(self, sub: Subscription | None) -> dict[str, int]:
        if sub is not None and sub.has_access:
            return TIER_LIMITS[sub.effective_tier]
        return FREE_LIMITS

    def checkout_context(
        self, user_id: str, customer_email: str | None = None
    ) -> CheckoutContext:
        """Build client-side Paddle checkout settings for the single plan."""
        if not self.checkout_enabled:
            raise ValueError("Paddle checkout is not configured.")

        return CheckoutContext(
            price_id=self._indie_price_id,
            client_side_token=self._client_side_token,
            environment=self._environment,
            success_url=f"{self._base_url}/billing/success",
            customer_email=customer_email,
            custom_data={"user_id": user_id},
        )

    async def sync_from_transaction(
        self, user_id: str, transaction_id: str
    ) -> None:
        """Eagerly activate a subscription from a Paddle transaction ID.

        Called immediately on the checkout success redirect so the user sees
        their active subscription without waiting for the webhook.
        Does nothing if the Paddle API is not configured or the call fails.
        """
        if not self.portal_enabled or not transaction_id:
            return

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{_PADDLE_API_BASE}/transactions/{transaction_id}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json().get("data", {})

            subscription_id = _as_str(data.get("subscription_id"))
            customer_id = _as_str(data.get("customer_id"))
            if not subscription_id:
                return

            # Fetch the subscription to get current period and status.
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{_PADDLE_API_BASE}/subscriptions/{subscription_id}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                sub_data = resp.json().get("data", {})

            status = _normalize_status(
                _as_str(sub_data.get("status"), "active")
            )
            current_period_end = _extract_period_end(sub_data)
            tier = self._tier_from_subscription(sub_data)

            before = self._subs.get_by_user(user_id)
            self._subs.update_from_paddle(
                user_id,
                paddle_customer_id=customer_id,
                paddle_subscription_id=subscription_id,
                tier=tier,
                status=status,
                current_period_end=current_period_end,
            )
            if self._metrics is not None:
                self._metrics.record_subscription_transition(
                    before,
                    self._subs.get_by_user(user_id),
                )
        except Exception:
            log.warning(
                "Could not eagerly sync subscription from transaction %s; "
                "webhook will update it shortly.",
                transaction_id,
            )

    async def get_portal_url(self, user_id: str) -> str:
        """Create a short-lived Paddle customer portal URL."""
        if not self.portal_enabled:
            return ""

        sub = self.get_subscription(user_id)
        if sub is None or not sub.paddle_customer_id:
            return ""

        payload = {
            "subscription_ids": [sub.paddle_subscription_id]
            if sub.paddle_subscription_id
            else [],
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{_PADDLE_API_BASE}/customers/{sub.paddle_customer_id}/portal-sessions",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        return (
            data.get("data", {})
            .get("urls", {})
            .get("general", {})
            .get("overview", "")
        )

    def handle_webhook(
        self, payload: bytes, signature: str, webhook_secret: str
    ) -> None:
        """Process an incoming Paddle webhook event."""
        if not webhook_secret:
            return

        if not self._verify_signature(payload, signature, webhook_secret):
            raise ValueError("Invalid Paddle webhook signature.")

        event = json.loads(payload)
        event_type = str(event.get("event_type", ""))

        if event_type in {
            "subscription.created",
            "subscription.updated",
            "subscription.activated",
            "subscription.resumed",
            "subscription.paused",
            "subscription.past_due",
        }:
            self._sync_subscription(event)
        elif event_type == "subscription.canceled":
            self._cancel_subscription(event)

    def _sync_subscription(self, event: dict[str, Any]) -> None:
        data = _as_dict(event.get("data"))
        custom_data = _as_dict(data.get("custom_data"))

        paddle_subscription_id = _as_str(data.get("id"))
        paddle_customer_id = _as_str(data.get("customer_id"))
        status = _normalize_status(_as_str(data.get("status"), "active"))
        current_period_end = _extract_period_end(data)
        tier = self._tier_from_subscription(data)

        user_id = self._resolve_user_id(custom_data, paddle_customer_id)
        if not user_id:
            return

        before = self._subs.get_by_user(user_id)
        self._subs.update_from_paddle(
            user_id,
            paddle_customer_id=paddle_customer_id,
            paddle_subscription_id=paddle_subscription_id,
            tier=tier,
            status=status,
            current_period_end=current_period_end,
        )
        if self._metrics is not None:
            self._metrics.record_subscription_transition(
                before,
                self._subs.get_by_user(user_id),
            )

    def _cancel_subscription(self, event: dict[str, Any]) -> None:
        data = _as_dict(event.get("data"))
        custom_data = _as_dict(data.get("custom_data"))
        paddle_customer_id = _as_str(data.get("customer_id"))

        user_id = self._resolve_user_id(custom_data, paddle_customer_id)
        if not user_id:
            return

        before = self._subs.get_by_user(user_id)
        self._subs.update_from_paddle(
            user_id,
            status="canceled",
            tier=Tier.INDIE,
        )
        if self._metrics is not None:
            self._metrics.record_subscription_transition(
                before,
                self._subs.get_by_user(user_id),
            )

    def _resolve_user_id(
        self, custom_data: dict[str, Any], paddle_customer_id: str
    ) -> str | None:
        user_id = _as_str(custom_data.get("user_id"))
        if not user_id and paddle_customer_id:
            sub = self._subs.get_by_paddle_customer(paddle_customer_id)
            if sub:
                user_id = sub.user_id
        if not user_id:
            log.warning(
                "Paddle webhook: could not resolve user for customer %s",
                paddle_customer_id,
            )
        return user_id or None

    def _tier_from_subscription(self, data: dict[str, Any]) -> Tier:
        for item in _as_list(data.get("items")):
            item_dict = _as_dict(item)
            price = _as_dict(item_dict.get("price"))
            price_id = _as_str(price.get("id"))
            if price_id == self._indie_price_id:
                return Tier.INDIE
            if price_id:
                log.info(
                    "Paddle webhook: treating unknown price %s as indie",
                    price_id,
                )
        return Tier.INDIE

    def _verify_signature(
        self, payload: bytes, signature: str, secret: str
    ) -> bool:
        if not signature or not secret:
            return False

        timestamp = ""
        signatures: list[str] = []
        for part in signature.split(";"):
            key, _, value = part.partition("=")
            if key == "ts":
                timestamp = value
            elif key == "h1" and value:
                signatures.append(value)

        if not timestamp or not signatures:
            return False

        try:
            ts = int(timestamp)
        except ValueError:
            return False

        if abs(int(time.time()) - ts) > 300:
            return False

        signed_payload = timestamp.encode() + b":" + payload
        expected = hmac.new(
            secret.encode(), signed_payload, hashlib.sha256
        ).hexdigest()
        return any(
            hmac.compare_digest(expected, candidate)
            for candidate in signatures
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }


def _normalize_environment(value: str, client_side_token: str) -> str:
    normalized = value.strip().lower()
    if normalized in _ALLOWED_PADDLE_ENVIRONMENTS:
        return normalized
    if client_side_token.startswith("test_"):
        return "sandbox"
    return "production"


def _normalize_status(value: str) -> str:
    normalized = value.lower().replace(" ", "_")
    allowed = {"active", "past_due", "paused", "canceled"}
    return normalized if normalized in allowed else "active"


def _extract_period_end(data: dict[str, Any]) -> str | None:
    period = _as_dict(data.get("current_billing_period"))
    period_end = _as_str(period.get("ends_at"))
    if period_end:
        return period_end
    return _as_str(data.get("next_billed_at")) or None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default
