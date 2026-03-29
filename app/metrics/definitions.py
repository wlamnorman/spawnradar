"""Canonical metric definitions used for durable tracking and export."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CounterMetricDefinition:
    """Definition for an append-only business counter."""

    key: str
    prometheus_name: str
    help_text: str
    definition: str
    label_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class HistogramMetricDefinition:
    """Definition for a histogram exported from durable observations."""

    prometheus_name: str
    help_text: str
    definition: str
    buckets: tuple[float, ...]


@dataclass(frozen=True)
class TimingMetricDefinition:
    """Definition for a derived time-to-first metric family."""

    key: str
    avg_name: str
    p50_name: str
    p90_name: str
    help_text: str
    definition: str


ACCOUNTS_CREATED = CounterMetricDefinition(
    key="accounts_created",
    prometheus_name="spawnradar_accounts_created_total",
    help_text="Total number of SpawnRadar accounts created.",
    definition="Count once when a brand-new user account is created.",
)
SESSIONS_STARTED = CounterMetricDefinition(
    key="sessions_started",
    prometheus_name="spawnradar_sessions_started_total",
    help_text="Total number of authenticated sessions started.",
    definition="Count once when an authenticated app session is created.",
)
TRIALS_STARTED = CounterMetricDefinition(
    key="trials_started",
    prometheus_name="spawnradar_trials_started_total",
    help_text="Total number of product trials started.",
    definition="Count once when a user enters the product trial for the first time.",
)
TRIALS_EXPIRED_WITHOUT_CONVERSION = CounterMetricDefinition(
    key="trials_expired_without_conversion",
    prometheus_name="spawnradar_trials_expired_without_conversion_total",
    help_text="Total number of trials that expired without converting.",
    definition=(
        "Count once when a trial ends and the user never entered paid access "
        "before expiry."
    ),
)
PAID_SUBSCRIPTIONS_STARTED = CounterMetricDefinition(
    key="paid_subscriptions_started",
    prometheus_name="spawnradar_paid_subscriptions_started_total",
    help_text="Total number of paid subscriptions started.",
    definition="Count once when paid billing starts.",
)
PAID_ACCESS_ENDED = CounterMetricDefinition(
    key="paid_access_ended",
    prometheus_name="spawnradar_paid_access_ended_total",
    help_text="Total number of paid access periods that ended.",
    definition=(
        "Count once when paid access becomes unavailable for any reason. "
        "Uses a low-cardinality reason label."
    ),
    label_names=("reason",),
)
GAMES_CREATED = CounterMetricDefinition(
    key="games_created",
    prometheus_name="spawnradar_games_created_total",
    help_text="Total number of games created through the normal create flow.",
    definition=(
        "Count once when a game is created through the normal create flow, "
        "excluding explicit duplicates."
    ),
)
GAMES_DELETED = CounterMetricDefinition(
    key="games_deleted",
    prometheus_name="spawnradar_games_deleted_total",
    help_text="Total number of games deleted.",
    definition="Count once when a game is deleted.",
)
GAMES_DUPLICATED = CounterMetricDefinition(
    key="games_duplicated",
    prometheus_name="spawnradar_games_duplicated_total",
    help_text="Total number of game duplication actions.",
    definition="Count once when a game is created via explicit duplicate or copy.",
)
COUNTER_METRICS: tuple[CounterMetricDefinition, ...] = (
    ACCOUNTS_CREATED,
    SESSIONS_STARTED,
    TRIALS_STARTED,
    TRIALS_EXPIRED_WITHOUT_CONVERSION,
    PAID_SUBSCRIPTIONS_STARTED,
    PAID_ACCESS_ENDED,
    GAMES_CREATED,
    GAMES_DELETED,
    GAMES_DUPLICATED,
)

TIME_TO_FIRST_GAME_CREATED = TimingMetricDefinition(
    key="time_to_first_game_created",
    avg_name="spawnradar_time_to_first_game_created_hours_avg",
    p50_name="spawnradar_time_to_first_game_created_hours_p50",
    p90_name="spawnradar_time_to_first_game_created_hours_p90",
    help_text="Time from account creation to first game creation in hours.",
    definition=(
        "Derived from account creation time to the user's first games_created event."
    ),
)

TIMING_METRICS: tuple[TimingMetricDefinition, ...] = (
    TIME_TO_FIRST_GAME_CREATED,
)
