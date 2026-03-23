"""Billing business logic: Paddle checkout, portal and webhook handling."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx

from app.billing.models import (
    DISCOVERY_RUNS_PER_DAY,
    DISCOVERY_RUNS_PER_HOUR,
    EXPIRED_LIMITS,
    TIER_LIMITS,
    TRIAL_DAYS,
    TRIAL_LIMITS,
    Subscription,
    Tier,
)
from app.billing.repository import (
    DiscoveryRunRepository,
    SubscriptionRepository,
)
from app.games.repository import GameRepository

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


@dataclass(frozen=True)
class DiscoveryUsageWindow:
    used: int
    limit: int
    remaining: int
    next_available_at: str | None = None


@dataclass(frozen=True)
class DiscoveryRunStatus:
    can_run: bool
    blocked_by: str | None
    account_state: str
    as_of: str
    hourly: DiscoveryUsageWindow
    daily: DiscoveryUsageWindow
    monthly: DiscoveryUsageWindow
    run_id: str | None = None

    @property
    def is_trial(self) -> bool:
        return self.account_state == "trial"

    @property
    def message(self) -> str:
        if self.blocked_by == "billing":
            return (
                "Discovery is unavailable for this account. "
                "Reactivate billing to continue."
            )
        if self.blocked_by == "month":
            if self.is_trial:
                return (
                    f"You've used all {self.monthly.limit} trial discovery runs "
                    "for this month."
                )
            return (
                f"You've reached your {self.monthly.limit} discovery runs "
                "for this month."
            )
        if self.blocked_by == "day":
            return _limit_message(
                "today",
                self.daily.next_available_at,
                _normalize_now(datetime.fromisoformat(self.as_of)),
            )
        if self.blocked_by == "hour":
            return _limit_message(
                "this hour",
                self.hourly.next_available_at,
                _normalize_now(datetime.fromisoformat(self.as_of)),
            )
        if self.is_trial:
            return (
                "Trial discovery is ready. "
                f"{self.monthly.remaining} of {self.monthly.limit} run"
                f"{'s' if self.monthly.limit != 1 else ''} left this month."
            )
        return (
            "Discovery is ready. "
            f"{self.hourly.remaining} hourly run"
            f"{'s' if self.hourly.remaining != 1 else ''} left, "
            f"{self.daily.remaining} daily run"
            f"{'s' if self.daily.remaining != 1 else ''} left, "
            f"{self.monthly.remaining} this month."
        )

    def as_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("run_id", None)
        payload["message"] = self.message
        return payload


class BillingService:
    """Manages subscriptions and enforces tier limits."""

    def __init__(
        self,
        sub_repo: SubscriptionRepository,
        game_repo: GameRepository,
        discovery_run_repo: DiscoveryRunRepository | None = None,
        metrics_service: MetricsService | None = None,
        paddle_api_key: str = "",
        paddle_client_side_token: str = "",
        paddle_indie_price_id: str = "",
        paddle_environment: str = "sandbox",
        base_url: str = "http://localhost:8000",
    ) -> None:
        self._subs = sub_repo
        self._games = game_repo
        self._discovery_runs = discovery_run_repo
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

    def get_or_create_subscription(self, user_id: str) -> Subscription:
        """Return the user's subscription, creating an Indie trial if absent."""
        sub = self._subs.get_by_user(user_id)
        if sub is not None:
            return sub
        sub = self._subs.create(
            str(uuid.uuid4()), user_id, Tier.INDIE, trial_days=TRIAL_DAYS
        )
        if self._metrics is not None:
            self._metrics.record_trial_started(sub)
        return sub

    def check_game_limit(self, user_id: str) -> bool:
        sub = self.get_or_create_subscription(user_id)
        limit = self._get_limits(sub)["games"]
        current = self._games.count_by_user(user_id)
        return current < limit

    def get_prospects_limit(self, user_id: str) -> int:
        sub = self.get_or_create_subscription(user_id)
        return self._get_limits(sub)["prospects_per_run"]

    def get_discovery_runs_limit(self, user_id: str) -> int:
        sub = self.get_or_create_subscription(user_id)
        return self._get_limits(sub)["discovery_runs_per_month"]

    def get_discovery_runs_used_this_month(
        self, user_id: str, *, now: datetime | None = None
    ) -> int:
        status = self.get_discovery_run_status(user_id, now=now)
        return status.monthly.used

    def get_discovery_run_status(
        self, user_id: str, *, now: datetime | None = None
    ) -> DiscoveryRunStatus:
        current_time = _normalize_now(now)
        sub = self.get_or_create_subscription(user_id)
        monthly_limit = self._get_limits(sub)["discovery_runs_per_month"]
        account_state = _discovery_account_state(sub)
        if monthly_limit <= 0:
            empty = DiscoveryUsageWindow(used=0, limit=0, remaining=0)
            return DiscoveryRunStatus(
                can_run=False,
                blocked_by="billing",
                account_state=account_state,
                as_of=current_time.isoformat(),
                hourly=empty,
                daily=empty,
                monthly=empty,
            )

        if self._discovery_runs is None:
            monthly = DiscoveryUsageWindow(
                used=0,
                limit=monthly_limit,
                remaining=monthly_limit,
            )
            unlimited = DiscoveryUsageWindow(
                used=0,
                limit=min(DISCOVERY_RUNS_PER_HOUR, monthly_limit),
                remaining=min(DISCOVERY_RUNS_PER_HOUR, monthly_limit),
            )
            daily = DiscoveryUsageWindow(
                used=0,
                limit=min(DISCOVERY_RUNS_PER_DAY, monthly_limit),
                remaining=min(DISCOVERY_RUNS_PER_DAY, monthly_limit),
            )
            return DiscoveryRunStatus(
                can_run=True,
                blocked_by=None,
                account_state=account_state,
                as_of=current_time.isoformat(),
                hourly=unlimited,
                daily=daily,
                monthly=monthly,
            )

        daily_window_start = current_time - timedelta(days=1)
        month_window_start = _month_start(current_time)

        recent_day_runs = self._discovery_runs.list_created_at_for_user_since(
            user_id, daily_window_start.isoformat()
        )
        month_used = self._discovery_runs.count_for_user_since(
            user_id, month_window_start.isoformat()
        )

        hourly = _window_usage(
            recent_day_runs,
            current_time=current_time,
            window=timedelta(hours=1),
            limit=min(DISCOVERY_RUNS_PER_HOUR, monthly_limit),
        )
        daily = _window_usage(
            recent_day_runs,
            current_time=current_time,
            window=timedelta(days=1),
            limit=min(DISCOVERY_RUNS_PER_DAY, monthly_limit),
        )
        monthly = DiscoveryUsageWindow(
            used=month_used,
            limit=monthly_limit,
            remaining=max(0, monthly_limit - month_used),
            next_available_at=_next_month_start(current_time).isoformat()
            if month_used >= monthly_limit
            else None,
        )

        if monthly.used >= monthly.limit:
            return DiscoveryRunStatus(
                can_run=False,
                blocked_by="month",
                account_state=account_state,
                as_of=current_time.isoformat(),
                hourly=hourly,
                daily=daily,
                monthly=monthly,
            )

        if daily.used >= daily.limit:
            return DiscoveryRunStatus(
                can_run=False,
                blocked_by="day",
                account_state=account_state,
                as_of=current_time.isoformat(),
                hourly=hourly,
                daily=daily,
                monthly=monthly,
            )

        if hourly.used >= hourly.limit:
            return DiscoveryRunStatus(
                can_run=False,
                blocked_by="hour",
                account_state=account_state,
                as_of=current_time.isoformat(),
                hourly=hourly,
                daily=daily,
                monthly=monthly,
            )

        return DiscoveryRunStatus(
            can_run=True,
            blocked_by=None,
            account_state=account_state,
            as_of=current_time.isoformat(),
            hourly=hourly,
            daily=daily,
            monthly=monthly,
        )

    def record_discovery_run(
        self, user_id: str, game_id: str, *, now: datetime | None = None
    ) -> DiscoveryRunStatus:
        current_time = _normalize_now(now)
        status = self.get_discovery_run_status(user_id, now=current_time)

        if not status.can_run:
            raise ValueError(status.message)

        if self._discovery_runs is None:
            raise ValueError("Discovery run tracking is not configured.")

        run_id = str(uuid.uuid4())
        self._discovery_runs.create(
            run_id,
            user_id,
            game_id,
            created_at=current_time.isoformat(),
        )
        if self._metrics is not None:
            self._metrics.record_discovery_run_started(
                run_id,
                user_id,
                game_id,
                started_at=current_time.isoformat(),
            )
        return replace(
            self.get_discovery_run_status(user_id, now=current_time),
            run_id=run_id,
        )

    def grant_comped_access(self, user_id: str) -> Subscription | None:
        """Grant complimentary full access without a Paddle subscription."""
        return self._subs.grant_comped_access(user_id, Tier.INDIE)

    def _get_limits(self, sub: Subscription) -> dict[str, int]:
        if sub.has_access:
            return TIER_LIMITS[sub.effective_tier]
        if sub.is_trialing:
            return TRIAL_LIMITS
        return EXPIRED_LIMITS

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

        sub = self.get_or_create_subscription(user_id)
        if not sub.paddle_customer_id:
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
            "subscription.trialing",
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
    allowed = {"active", "trialing", "past_due", "paused", "canceled"}
    return normalized if normalized in allowed else "active"


def _extract_period_end(data: dict[str, Any]) -> str | None:
    period = _as_dict(data.get("current_billing_period"))
    period_end = _as_str(period.get("ends_at"))
    if period_end:
        return period_end
    return _as_str(data.get("next_billed_at")) or None


def _month_start(now: datetime | None = None) -> datetime:
    current = _normalize_now(now)
    return current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month_start(now: datetime) -> datetime:
    if now.month == 12:
        return now.replace(
            year=now.year + 1,
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    return now.replace(
        month=now.month + 1,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def _normalize_now(now: datetime | None) -> datetime:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        return current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


def _discovery_account_state(sub: Subscription) -> str:
    if sub.is_trialing:
        return "trial"
    if sub.has_access:
        return "paid"
    return "inactive"


def _window_usage(
    timestamps: list[datetime],
    *,
    current_time: datetime,
    window: timedelta,
    limit: int,
) -> DiscoveryUsageWindow:
    relevant = [
        _normalize_now(timestamp)
        for timestamp in timestamps
        if _normalize_now(timestamp) >= current_time - window
    ]
    used = len(relevant)
    next_available_at: str | None = None
    if limit > 0 and used >= limit:
        boundary = relevant[used - limit] + window
        next_available_at = boundary.isoformat()

    return DiscoveryUsageWindow(
        used=used,
        limit=limit,
        remaining=max(0, limit - used),
        next_available_at=next_available_at,
    )


def _limit_message(
    label: str,
    next_available_at: str | None,
    current_time: datetime,
) -> str:
    if not next_available_at:
        return f"You've reached the discovery limit for {label}."

    available_at = _normalize_now(datetime.fromisoformat(next_available_at))
    wait = max(timedelta(0), available_at - current_time)
    return (
        f"You've reached the discovery limit for {label}. "
        f"Try again in about {_format_wait(wait)}."
    )


def _format_wait(delta: timedelta) -> str:
    total_seconds = max(1, int(delta.total_seconds()))
    minutes = (total_seconds + 59) // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"

    hours = minutes // 60
    remaining_minutes = minutes % 60
    if remaining_minutes == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return (
        f"{hours} hour{'s' if hours != 1 else ''} "
        f"{remaining_minutes} minute{'s' if remaining_minutes != 1 else ''}"
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default
