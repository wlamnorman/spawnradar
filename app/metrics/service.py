"""High-level business metrics recording and Prometheus rendering."""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from statistics import mean
from typing import TYPE_CHECKING, TypeVar

from app.billing.models import Subscription
from app.metrics.definitions import (
    ACCOUNTS_CREATED,
    COUNTER_METRICS,
    DISCOVERY_RUNS_COMPLETED,
    GAMES_CREATED,
    GAMES_DELETED,
    GAMES_DUPLICATED,
    PAID_ACCESS_ENDED,
    PAID_SUBSCRIPTIONS_STARTED,
    PROSPECT_PAGES_VIEWED,
    SESSIONS_STARTED,
    TIME_TO_FIRST_GAME_CREATED,
    TIMING_METRICS,
    TRIALS_EXPIRED_WITHOUT_CONVERSION,
    TRIALS_STARTED,
    CounterMetricDefinition,
)
from app.metrics.repository import MetricEvent, MetricsRepository

if TYPE_CHECKING:
    from app.billing.repository import SubscriptionRepository

log = logging.getLogger(__name__)
T = TypeVar("T")


class MetricsService:
    """Record durable business metrics and export them as Prometheus text."""

    def __init__(
        self,
        repo: MetricsRepository,
        subscription_repo: SubscriptionRepository,
    ) -> None:
        self._repo = repo
        self._subscriptions = subscription_repo

    def record_event(
        self,
        metric: CounterMetricDefinition,
        *,
        user_id: str | None = None,
        customer_game_id: str | None = None,
        occurred_at: str,
        value: float = 1.0,
        dedupe_key: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> bool:
        """Record a counter event using the canonical metric definition."""
        return self._repo.record_metric_event(
            metric.key,
            user_id=user_id,
            customer_game_id=customer_game_id,
            occurred_at=occurred_at,
            value=value,
            dedupe_key=dedupe_key,
            metadata=metadata,
        )

    def record_account_created(self, user_id: str, occurred_at: str) -> bool:
        return self._best_effort(
            ACCOUNTS_CREATED.key,
            False,
            lambda: self.record_event(
                ACCOUNTS_CREATED,
                user_id=user_id,
                occurred_at=occurred_at,
            ),
        )

    def record_session_started(self, user_id: str, occurred_at: str) -> bool:
        return self._best_effort(
            SESSIONS_STARTED.key,
            False,
            lambda: self.record_event(
                SESSIONS_STARTED,
                user_id=user_id,
                occurred_at=occurred_at,
            ),
        )

    def record_trial_started(self, subscription: Subscription) -> bool:
        return self._best_effort(
            TRIALS_STARTED.key,
            False,
            lambda: self.record_event(
                TRIALS_STARTED,
                user_id=subscription.user_id,
                occurred_at=subscription.created_at,
                dedupe_key=f"trial_started:{subscription.subscription_id}",
            ),
        )

    def record_paid_subscription_started(
        self, subscription: Subscription
    ) -> bool:
        if not subscription.paddle_subscription_id:
            return False
        return self._best_effort(
            PAID_SUBSCRIPTIONS_STARTED.key,
            False,
            lambda: self.record_event(
                PAID_SUBSCRIPTIONS_STARTED,
                user_id=subscription.user_id,
                occurred_at=subscription.updated_at,
                dedupe_key=(
                    "paid_subscription_started:"
                    f"{subscription.paddle_subscription_id}"
                ),
            ),
        )

    def record_paid_access_ended(
        self,
        subscription: Subscription,
        *,
        reason: str,
        occurred_at: str,
    ) -> bool:
        if not subscription.paddle_subscription_id:
            return False
        dedupe_anchor = (
            subscription.current_period_end
            or subscription.updated_at
            or occurred_at
        )
        return self._best_effort(
            PAID_ACCESS_ENDED.key,
            False,
            lambda: self.record_event(
                PAID_ACCESS_ENDED,
                user_id=subscription.user_id,
                occurred_at=occurred_at,
                dedupe_key=(
                    "paid_access_ended:"
                    f"{subscription.paddle_subscription_id}:{reason}:{dedupe_anchor}"
                ),
                metadata={"reason": reason},
            ),
        )

    def record_trial_expired_without_conversion(
        self,
        *,
        subscription_id: str,
        user_id: str,
        occurred_at: str,
    ) -> bool:
        return self._best_effort(
            TRIALS_EXPIRED_WITHOUT_CONVERSION.key,
            False,
            lambda: self.record_event(
                TRIALS_EXPIRED_WITHOUT_CONVERSION,
                user_id=user_id,
                occurred_at=occurred_at,
                dedupe_key=(
                    "trial_expired_without_conversion:"
                    f"{subscription_id}:{occurred_at}"
                ),
            ),
        )

    def record_game_created(
        self,
        *,
        user_id: str,
        customer_game_id: str | None = None,
        occurred_at: str,
    ) -> bool:
        return self._best_effort(
            GAMES_CREATED.key,
            False,
            lambda: self.record_event(
                GAMES_CREATED,
                user_id=user_id,
                customer_game_id=customer_game_id,
                occurred_at=occurred_at,
            ),
        )

    def record_game_deleted(
        self,
        *,
        user_id: str,
        customer_game_id: str | None = None,
        occurred_at: str,
    ) -> bool:
        return self._best_effort(
            GAMES_DELETED.key,
            False,
            lambda: self.record_event(
                GAMES_DELETED,
                user_id=user_id,
                customer_game_id=customer_game_id,
                occurred_at=occurred_at,
            ),
        )

    def record_game_duplicated(
        self,
        *,
        user_id: str,
        customer_game_id: str | None = None,
        occurred_at: str,
    ) -> bool:
        return self._best_effort(
            GAMES_DUPLICATED.key,
            False,
            lambda: self.record_event(
                GAMES_DUPLICATED,
                user_id=user_id,
                customer_game_id=customer_game_id,
                occurred_at=occurred_at,
            ),
        )

    def record_discovery_run_completed(
        self,
        *,
        customer_game_id: str,
        creators_found: int,
    ) -> bool:
        """Record one completed discovery run for a game."""
        return self._best_effort(
            DISCOVERY_RUNS_COMPLETED.key,
            False,
            lambda: self.record_event(
                DISCOVERY_RUNS_COMPLETED,
                customer_game_id=customer_game_id,
                occurred_at=datetime.now(UTC).isoformat(),
                value=float(creators_found),
            ),
        )

    def record_prospect_page_viewed(
        self,
        *,
        user_id: str,
        customer_game_id: str,
    ) -> bool:
        """Record one prospect page view."""
        return self._best_effort(
            PROSPECT_PAGES_VIEWED.key,
            False,
            lambda: self.record_event(
                PROSPECT_PAGES_VIEWED,
                user_id=user_id,
                customer_game_id=customer_game_id,
                occurred_at=datetime.now(UTC).isoformat(),
            ),
        )

    def record_subscription_transition(
        self,
        before: Subscription | None,
        after: Subscription | None,
    ) -> None:
        if after is None:
            return
        if after.paddle_subscription_id and (
            before is None
            or before.paddle_subscription_id != after.paddle_subscription_id
        ):
            self.record_paid_subscription_started(after)
        if before is None:
            return
        if before.has_access and not after.has_access:
            self.record_paid_access_ended(
                after,
                reason=_paid_access_end_reason(after),
                occurred_at=_paid_access_end_occurred_at(after),
            )

    def render_prometheus(self) -> str:
        """Render metrics in Prometheus text exposition format."""
        self._reconcile_subscription_metrics()

        lines: list[str] = []
        event_totals = self._repo.metric_totals()
        paid_access_events = self._repo.list_metric_events(
            PAID_ACCESS_ENDED.key
        )

        for metric in COUNTER_METRICS:
            lines.extend(
                self._render_counter_metric(
                    metric, event_totals, paid_access_events
                )
            )
        lines.extend(self._render_time_to_first_metrics())
        return "\n".join(lines) + "\n"

    def _render_counter_metric(
        self,
        metric: CounterMetricDefinition,
        event_totals: dict[str, float],
        paid_access_events: list[MetricEvent],
    ) -> list[str]:
        lines = [
            f"# HELP {metric.prometheus_name} {metric.help_text}",
            f"# TYPE {metric.prometheus_name} counter",
            f"# DEFINITION {metric.prometheus_name} {metric.definition}",
        ]
        if metric is PAID_ACCESS_ENDED:
            totals_by_reason: dict[str, float] = defaultdict(float)
            for event in paid_access_events:
                reason = _normalize_reason(
                    str(event.metadata.get("reason", "other"))
                )
                totals_by_reason[reason] += event.value
            for reason in ("canceled", "past_due", "paused", "other"):
                value = totals_by_reason.get(reason, 0.0)
                lines.append(
                    f'{metric.prometheus_name}{{reason="{reason}"}} {value:.6f}'
                )
            return lines

        lines.append(
            f"{metric.prometheus_name} {event_totals.get(metric.key, 0.0):.6f}"
        )
        return lines

    def _render_time_to_first_metrics(self) -> list[str]:
        lines: list[str] = []
        account_times = {
            user_id: _parse_timestamp(timestamp)
            for user_id, timestamp in self._repo.first_metric_time_by_user(
                ACCOUNTS_CREATED.key
            ).items()
        }
        first_game_times = {
            user_id: _parse_timestamp(timestamp)
            for user_id, timestamp in self._repo.first_metric_time_by_user(
                GAMES_CREATED.key
            ).items()
        }
        values_by_key = {
            TIME_TO_FIRST_GAME_CREATED.key: _durations_in_hours(
                account_times,
                first_game_times,
            ),
        }

        for definition in TIMING_METRICS:
            values = values_by_key[definition.key]
            avg_value = mean(values) if values else math.nan
            p50_value = _percentile(values, 50) if values else math.nan
            p90_value = _percentile(values, 90) if values else math.nan

            for metric_name, value, suffix in (
                (definition.avg_name, avg_value, "average"),
                (definition.p50_name, p50_value, "50th percentile"),
                (definition.p90_name, p90_value, "90th percentile"),
            ):
                lines.append(f"# HELP {metric_name} {definition.help_text}")
                lines.append(f"# TYPE {metric_name} gauge")
                lines.append(
                    f"# DEFINITION {metric_name} {definition.definition} Exported as the {suffix}."
                )
                lines.append(f"{metric_name} {_format_float(value)}")
        return lines

    def _reconcile_subscription_metrics(self) -> None:
        # Trial expiry and canceled-access loss are time-based transitions, so they
        # need lazy reconciliation in addition to webhook/write-path recording.
        now = datetime.now(UTC)
        for subscription in self._subscriptions.list_all():
            trial_end = _parse_optional_timestamp(subscription.trial_ends_at)
            if trial_end is not None and trial_end <= now:
                converted_before_expiry = (
                    self._repo.has_metric_event_for_user_before(
                        PAID_SUBSCRIPTIONS_STARTED.key,
                        subscription.user_id,
                        subscription.trial_ends_at or trial_end.isoformat(),
                    )
                )
                if not converted_before_expiry:
                    self.record_trial_expired_without_conversion(
                        subscription_id=subscription.subscription_id,
                        user_id=subscription.user_id,
                        occurred_at=trial_end.isoformat(),
                    )

            if not subscription.paddle_subscription_id:
                continue
            if subscription.has_access:
                continue

            reason = _paid_access_end_reason(subscription)
            occurred_at = _paid_access_end_occurred_at(subscription)
            if _parse_timestamp(occurred_at) > now:
                continue
            self.record_paid_access_ended(
                subscription,
                reason=reason,
                occurred_at=occurred_at,
            )

    def _best_effort(
        self, operation: str, default: T, fn: Callable[[], T]
    ) -> T:
        try:
            return fn()
        except Exception:
            log.warning(
                "Metrics write failed during %s.", operation, exc_info=True
            )
            return default


def _durations_in_hours(
    starts: dict[str, datetime], ends: dict[str, datetime]
) -> list[float]:
    values: list[float] = []
    for user_id, start in starts.items():
        end = ends.get(user_id)
        if end is None or end < start:
            continue
        values.append((end - start).total_seconds() / 3600)
    return values


def _parse_timestamp(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _parse_optional_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return _parse_timestamp(value)


def _percentile(values: list[float], percentile: float) -> float:
    sorted_values = sorted(values)
    if not sorted_values:
        return math.nan
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (percentile / 100)
    lower_index = math.floor(rank)
    upper_index = math.ceil(rank)
    lower_value = sorted_values[lower_index]
    upper_value = sorted_values[upper_index]
    if lower_index == upper_index:
        return lower_value
    return lower_value + (upper_value - lower_value) * (rank - lower_index)


def _paid_access_end_reason(subscription: Subscription) -> str:
    return _normalize_reason(subscription.status)


def _normalize_reason(reason: str) -> str:
    if reason in {"canceled", "past_due", "paused"}:
        return reason
    return "other"


def _paid_access_end_occurred_at(subscription: Subscription) -> str:
    if subscription.status == "canceled" and subscription.current_period_end:
        return subscription.current_period_end
    return subscription.updated_at


def _format_float(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    return f"{value:.6f}"
