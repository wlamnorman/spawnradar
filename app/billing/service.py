"""Billing business logic: tier limits, Stripe checkout, webhook handling.

The Stripe integration degrades gracefully: if STRIPE_SECRET_KEY is not set,
checkout and portal operations return an error message rather than crashing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.billing.models import TIER_LIMITS, TRIAL_DAYS, Subscription, Tier
from app.billing.repository import SubscriptionRepository
from app.games.repository import GameRepository


class BillingService:
    """Manages subscriptions and enforces tier limits."""

    def __init__(
        self,
        sub_repo: SubscriptionRepository,
        game_repo: GameRepository,
        stripe_secret_key: str = "",
        stripe_starter_price_id: str = "",
        stripe_pro_price_id: str = "",
        base_url: str = "http://localhost:8000",
    ) -> None:
        self._subs = sub_repo
        self._games = game_repo
        self._stripe_key = stripe_secret_key
        self._starter_price = stripe_starter_price_id
        self._pro_price = stripe_pro_price_id
        self._base_url = base_url

    @property
    def stripe_enabled(self) -> bool:
        """Return True if Stripe is configured."""
        return bool(self._stripe_key)

    def get_or_create_subscription(self, user_id: str) -> Subscription:
        """Return the user's subscription, creating a Starter trial if absent."""
        sub = self._subs.get_by_user(user_id)
        if sub is not None:
            return sub
        sub_id = str(uuid.uuid4())
        return self._subs.create(
            sub_id, user_id, Tier.STARTER, trial_days=TRIAL_DAYS
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

    def create_checkout_session(self, user_id: str, tier: str) -> str:
        """Create a Stripe Checkout session and return its URL.

        Returns an empty string if Stripe is not configured.
        """
        if not self.stripe_enabled:
            return ""

        import stripe  # type: ignore

        stripe.api_key = self._stripe_key

        price_id = (
            self._starter_price if tier == "starter" else self._pro_price
        )
        if not price_id:
            return ""

        sub = self.get_or_create_subscription(user_id)
        customer_id = sub.stripe_customer_id

        params: dict = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": f"{self._base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{self._base_url}/billing",
            "metadata": {"user_id": user_id},
        }
        if tier == "starter":
            params["subscription_data"] = {"trial_period_days": TRIAL_DAYS}
        if customer_id:
            params["customer"] = customer_id

        session = stripe.checkout.Session.create(**params)
        return session.url or ""

    def create_portal_session(self, user_id: str) -> str:
        """Create a Stripe Customer Portal session and return its URL."""
        if not self.stripe_enabled:
            return ""

        import stripe  # type: ignore

        stripe.api_key = self._stripe_key

        sub = self.get_or_create_subscription(user_id)
        if not sub.stripe_customer_id:
            return ""

        session = stripe.billing_portal.Session.create(
            customer=sub.stripe_customer_id,
            return_url=f"{self._base_url}/billing",
        )
        return session.url or ""

    def handle_stripe_webhook(
        self, payload: bytes, sig_header: str, webhook_secret: str
    ) -> None:
        """Process an incoming Stripe webhook event.

        Updates the local subscription record based on the event type.
        """
        if not self.stripe_enabled:
            return

        import stripe  # type: ignore

        stripe.api_key = self._stripe_key

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
        except Exception as exc:
            if exc.__class__.__name__ == "SignatureVerificationError":
                raise ValueError("Invalid Stripe webhook signature.") from exc
            raise

        event_type = event["type"]
        data_obj = event["data"]["object"]

        if event_type in (
            "customer.subscription.created",
            "customer.subscription.updated",
        ):
            self._sync_subscription(data_obj)
        elif event_type == "customer.subscription.deleted":
            self._cancel_subscription(data_obj)

    def _sync_subscription(self, stripe_sub: dict) -> None:
        """Update local subscription from a Stripe subscription object."""
        customer_id = stripe_sub.get("customer")
        sub_id = stripe_sub.get("id")
        status = stripe_sub.get("status", "active")
        period_end = stripe_sub.get("current_period_end")
        period_end_iso = self._utc_timestamp_to_iso(period_end)

        # Determine tier from price ID
        items = stripe_sub.get("items", {}).get("data", [])
        tier = Tier.STARTER
        for item in items:
            price_id = item.get("price", {}).get("id", "")
            if price_id == self._starter_price:
                tier = Tier.STARTER
            elif price_id == self._pro_price:
                tier = Tier.PRO

        # Find user by Stripe customer ID
        user_id = self._find_user_by_customer(customer_id)
        if user_id is None:
            # Try metadata
            metadata = stripe_sub.get("metadata", {})
            user_id = metadata.get("user_id")
        if user_id is None:
            return

        self._subs.update_from_stripe(
            user_id,
            stripe_customer_id=customer_id,
            stripe_subscription_id=sub_id,
            tier=tier,
            status=status,
            current_period_end=period_end_iso,
        )

    def _cancel_subscription(self, stripe_sub: dict) -> None:
        """Mark local subscription as cancelled."""
        customer_id = stripe_sub.get("customer")
        user_id = self._find_user_by_customer(customer_id)
        if user_id is None:
            return
        self._subs.update_from_stripe(
            user_id, status="cancelled", tier=Tier.STARTER
        )

    def _find_user_by_customer(self, customer_id: str | None) -> str | None:
        """Look up a user_id by their Stripe customer ID."""
        if not customer_id:
            return None
        from app.database import get_connection

        # Access db_path via sub_repo
        db_path = self._subs._db_path  # type: ignore[attr-defined]
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT user_id FROM subscriptions WHERE stripe_customer_id = ? LIMIT 1",
                (customer_id,),
            ).fetchone()
        return row["user_id"] if row else None

    @staticmethod
    def _utc_timestamp_to_iso(timestamp: object) -> str | None:
        """Convert a Stripe UTC epoch timestamp to an ISO-8601 string."""
        if not isinstance(timestamp, int) or timestamp <= 0:
            return None
        return datetime.fromtimestamp(timestamp, UTC).isoformat()
